#!/usr/bin/env python3
"""
Drift Protocol User Positions Viewer

This script displays all positions for a given Drift Protocol authority address.
It leverages the drift-labs/driftpy SDK to fetch and display positions with minimal RPC calls.
Uses VAT (vat of pickles) to cache on-chain data and reduce RPC calls.

The script maintains only a single VAT directory for caching data. When a new VAT is created,
all previous VAT directories are automatically deleted to save disk space.

Usage:
    python drift-positions.py <AUTHORITY_ADDRESS> [--rpc <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]

Requirements:
    - Python 3.7+
    - driftpy
    - anchorpy
    - solders
    - solana
    - dotenv

Environment Variables:
    RPC_URL: Solana RPC endpoint URL
"""

import os
import sys
import asyncio
import argparse
import time
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from anchorpy import Wallet
from dotenv import load_dotenv
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.async_api import AsyncClient

from driftpy.drift_client import DriftClient
from driftpy.drift_user import DriftUser
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import UserMapConfig, PollingConfig
from driftpy.user_map.user_map_config import WebsocketConfig as UserMapWebsocketConfig
from driftpy.constants.numeric_constants import QUOTE_SPOT_MARKET_INDEX
from driftpy.types import SpotPosition, PerpPosition, MarketType
from driftpy.market_map.market_map import MarketMap
from driftpy.market_map.market_map_config import MarketMapConfig
from driftpy.market_map.market_map_config import WebsocketConfig as MarketMapWebsocketConfig
from driftpy.pickle.vat import Vat
from driftpy.user_map.userstats_map import UserStatsMap
from driftpy.user_map.user_map_config import UserStatsMapConfig
from driftpy.account_subscription_config import AccountSubscriptionConfig

# Load environment variables
load_dotenv()

# Default pickle directory
DEFAULT_PICKLE_DIR = "../pickles"

def format_number(number: float, decimals: int = 4, use_commas: bool = True) -> str:
    """Format a number with proper decimal places and optional comma separators"""
    if abs(number) >= 1e6:
        # For large numbers, use millions format
        return f"{number/1e6:,.{decimals}f}M"
    elif abs(number) >= 1e3 and use_commas:
        return f"{number:,.{decimals}f}"
    else:
        return f"{number:.{decimals}f}"

def get_newest_pickle_set(directory: str) -> Tuple[Optional[Dict[str, str]], Optional[float]]:
    """
    Find the newest set of pickle files in the given directory.
    Returns a tuple of (file_dict, timestamp_in_seconds) or (None, None) if no valid files found.
    """
    if not os.path.exists(directory):
        return None, None
    
    # Look for pickle files that start with vat- prefix
    subdirs = [d for d in os.listdir(directory) if d.startswith("vat-") and os.path.isdir(os.path.join(directory, d))]
    if not subdirs:
        return None, None
    
    # Since we now maintain only one VAT directory, just take the first one
    # (but still sort by timestamp to be safe)
    subdirs.sort(reverse=True)
    subdir = subdirs[0]
    path = os.path.join(directory, subdir)
    
    # Check if this is a complete pickle set with all required files
    required_prefixes = ["perp_", "spot_", "usermap_", "userstats_", "perporacles_", "spotoracles_"]
    files_present = []
    
    for f in os.listdir(path):
        if f.endswith(".pkl") and any(f.startswith(prefix) for prefix in required_prefixes):
            files_present.append(f)
            
    # Check if all required file types are present
    if all(any(f.startswith(prefix) for f in files_present) for prefix in required_prefixes):
        # Extract datetime from directory name
        try:
            # Format is vat-%Y-%m-%d-%H-%M-%S
            date_part = subdir[4:]  # Remove 'vat-' prefix
            dt = datetime.datetime.strptime(date_part, "%Y-%m-%d-%H-%M-%S")
            timestamp = dt.timestamp()
            
            # Create a map of file types to full paths
            file_map = {}
            for prefix in required_prefixes:
                prefix_base = prefix.rstrip("_")
                matching_files = [f for f in files_present if f.startswith(prefix)]
                if matching_files:
                    # Sort by slot number to get the newest file
                    matching_files.sort(key=lambda x: int(x.split("_")[-1].split(".")[0]), reverse=True)
                    file_map[prefix_base] = os.path.join(path, matching_files[0])
            
            return file_map, timestamp
        except Exception as e:
            print(f"Error parsing timestamp from directory {subdir}: {e}")
    
    return None, None

def is_pickle_fresh(timestamp: float, max_age_seconds: int = 3600) -> bool:
    """Check if a pickle is fresh enough (less than max_age_seconds old)"""
    current_time = time.time()
    age = current_time - timestamp
    return age < max_age_seconds

class DriftPositionViewer:
    """Class for fetching and displaying Drift positions"""
    
    def __init__(self, connection, pickle_dir: str = DEFAULT_PICKLE_DIR, force_refresh: bool = False):
        """Initialize with connection and pickle settings"""
        # Generate a random keypair - we're only reading data, not signing transactions
        from solders.keypair import Keypair # type: ignore
        kp = Keypair()
        self.wallet = Wallet(kp)
        self.connection = connection
        
        # Initialize DriftClient with cached subscription mode (no RPC calls yet)
        # The DriftClient is initialized but not subscribed until needed
        self.drift_client = DriftClient(
            connection, 
            self.wallet, 
            account_subscription=AccountSubscriptionConfig("cached")
        )
        
        self.user_map = None
        self.stats_map = None
        self.spot_map = None
        self.perp_map = None
        self.vat = None
        self.pickle_dir = pickle_dir
        self.force_refresh = force_refresh
        self.using_pickled_data = False
        self.pickle_timestamp = None
        
        # Create pickle directory if it doesn't exist
        if not os.path.exists(self.pickle_dir):
            os.makedirs(self.pickle_dir)
    
    async def initialize(self):
        """Initialize the drift client and maps, using pickled data if available and fresh"""
        # First check if we have fresh pickle data available
        if not self.force_refresh:
            pickle_files, timestamp = get_newest_pickle_set(self.pickle_dir)
            if pickle_files and timestamp and is_pickle_fresh(timestamp):
                print(f"Using pickled data from {datetime.datetime.fromtimestamp(timestamp)}")
                self.pickle_timestamp = timestamp
                self.using_pickled_data = True
                success = await self.load_from_pickle(pickle_files)
                if success:
                    return
                else:
                    print("Failed to load from pickle, fetching fresh data instead")
        
        # Only connect to RPC if we couldn't use pickled data
        print("Fetching fresh data from RPC...")
        # Subscribe to the drift client
        await self.drift_client.subscribe()
        await self.initialize_fresh()
        await self.save_to_pickle()
    
    async def initialize_fresh(self):
        """Initialize with fresh data from RPC"""
        # Initialize all the maps we need
        self.spot_map = MarketMap(
            MarketMapConfig(
                self.drift_client.program,
                MarketType.Spot(),
                MarketMapWebsocketConfig(),
                self.drift_client.connection,
            )
        )
        self.perp_map = MarketMap(
            MarketMapConfig(
                self.drift_client.program,
                MarketType.Perp(),
                MarketMapWebsocketConfig(),
                self.drift_client.connection,
            )
        )
        self.user_map = UserMap(
            UserMapConfig(
                self.drift_client,
                UserMapWebsocketConfig(),
            )
        )
        self.stats_map = UserStatsMap(UserStatsMapConfig(self.drift_client))
        
        # Initialize VAT
        self.vat = Vat(
            self.drift_client,
            self.user_map,
            self.stats_map,
            self.spot_map,
            self.perp_map,
        )
        
        # Subscribe to all maps
        await asyncio.gather(
            self.spot_map.subscribe(),
            self.perp_map.subscribe(),
            self.user_map.subscribe(),
            self.stats_map.subscribe(),
        )
    
    async def load_from_pickle(self, pickle_files: Dict[str, str]) -> bool:
        """Load data from pickle files, returns True if successful, False otherwise"""
        try:
            # Note: When using pickle data, we don't need to subscribe to the drift client or any maps
            # Create the maps but don't subscribe to them
            self.spot_map = MarketMap(
                MarketMapConfig(
                    self.drift_client.program,
                    MarketType.Spot(),
                    MarketMapWebsocketConfig(),
                    self.drift_client.connection,
                )
            )
            self.perp_map = MarketMap(
                MarketMapConfig(
                    self.drift_client.program,
                    MarketType.Perp(),
                    MarketMapWebsocketConfig(),
                    self.drift_client.connection,
                )
            )
            self.user_map = UserMap(
                UserMapConfig(
                    self.drift_client,
                    UserMapWebsocketConfig(),
                )
            )
            self.stats_map = UserStatsMap(UserStatsMapConfig(self.drift_client))
            
            # Initialize VAT
            self.vat = Vat(
                self.drift_client,
                self.user_map,
                self.stats_map,
                self.spot_map,
                self.perp_map,
            )
            
            # Load from pickle - this deserializes the data without requiring RPC calls
            print("Loading data from pickle without contacting RPC...")
            await self.vat.unpickle(
                users_filename=pickle_files.get('usermap'),
                user_stats_filename=pickle_files.get('userstats'),
                spot_markets_filename=pickle_files.get('spot'),
                perp_markets_filename=pickle_files.get('perp'),
                spot_oracles_filename=pickle_files.get('spotoracles'),
                perp_oracles_filename=pickle_files.get('perporacles'),
            )
            return True
        except Exception as e:
            print(f"Error loading from pickle: {str(e)}")
            return False
    
    async def save_to_pickle(self):
        """Save current state to pickle files"""
        if not self.vat:
            return
        
        # Create timestamped directory for the new pickle set
        now = datetime.datetime.now()
        folder_name = now.strftime("vat-%Y-%m-%d-%H-%M-%S")
        path = os.path.join(self.pickle_dir, folder_name, "")
        
        os.makedirs(path, exist_ok=True)
        pickle_files = await self.vat.pickle(path)
        self.pickle_timestamp = now.timestamp()
        print(f"Saved fresh data to {path}")
        
        # Delete all previous VAT directories
        self._delete_old_vat_dirs(except_dir=folder_name)
        
        return pickle_files
    
    def _delete_old_vat_dirs(self, except_dir=None):
        """Delete all VAT directories except the one specified"""
        if not os.path.exists(self.pickle_dir):
            return
            
        for item in os.listdir(self.pickle_dir):
            item_path = os.path.join(self.pickle_dir, item)
            if os.path.isdir(item_path) and item.startswith("vat-") and item != except_dir:
                try:
                    import shutil
                    shutil.rmtree(item_path)
                    print(f"Deleted old VAT directory: {item}")
                except Exception as e:
                    print(f"Warning: Failed to delete old VAT directory {item}: {e}")
    
    async def cleanup(self):
        """Clean up connections"""
        try:
            # Only cleanup subscriptions if we weren't using pickled data
            # (if using pickled data, we never subscribed)
            if not self.using_pickled_data:
                if hasattr(self, 'spot_map') and self.spot_map:
                    try:
                        await self.spot_map.unsubscribe()
                    except Exception as e:
                        print(f"Warning: Error unsubscribing from spot_map: {e}")
                
                if hasattr(self, 'perp_map') and self.perp_map:
                    try:
                        await self.perp_map.unsubscribe()
                    except Exception as e:
                        print(f"Warning: Error unsubscribing from perp_map: {e}")
                    
                if self.user_map:
                    try:
                        await self.user_map.unsubscribe()
                    except Exception as e:
                        print(f"Warning: Error unsubscribing from user_map: {e}")
                    
                if hasattr(self, 'stats_map') and self.stats_map:
                    try:
                        if hasattr(self.stats_map, 'account_subscriber') and self.stats_map.account_subscriber:
                            if hasattr(self.stats_map.account_subscriber, 'unsubscribe'):
                                await self.stats_map.account_subscriber.unsubscribe()
                    except Exception as e:
                        print(f"Warning: Error unsubscribing from stats_map: {e}")
                    
                await self.drift_client.unsubscribe()
        except Exception as e:
            print(f"Warning: Error during cleanup: {e}")
    
    async def get_user_accounts_by_authority(self, authority_pubkey: Pubkey) -> List[DriftUser]:
        """Get all user accounts associated with an authority"""
        if not self.user_map:
            raise ValueError("UserMap not initialized")
        
        users = []
        
        # If we're using fresh data, sync first
        if not self.using_pickled_data:
            await self.user_map.sync()
        
        # Find all accounts with matching authority
        for user in self.user_map.values():
            try:
                user_authority = user.get_user_account().authority
                if str(user_authority) == str(authority_pubkey):
                    users.append(user)
            except Exception as e:
                print(f"Error checking user authority: {e}")
        
        return users
    
    def get_perp_position_details(self, user: DriftUser, position: PerpPosition) -> Dict[str, Any]:
        """Get detailed information about a perpetual position"""
        # Get market information
        market = self.drift_client.get_perp_market_account(position.market_index)
        oracle_price_data = user.get_oracle_data_for_perp_market(position.market_index)
        
        # Decode market name from bytes
        market_name = bytes(market.name).decode('utf-8').strip('\x00')
        
        # Calculate base asset amount (position size) with precision adjustment
        base_asset_amount = position.base_asset_amount / 1e9  # BASE_PRECISION
        
        # Get position value in USD
        position_value = user.get_perp_position_value(
            position.market_index, 
            oracle_price_data,
            include_open_orders=True
        ) / 1e6  # QUOTE_PRECISION
        
        # Get current oracle price
        current_price = oracle_price_data.price / 1e6  # Convert to USD
        
        # Calculate entry price if possible
        entry_price = None
        if position.base_asset_amount != 0:
            entry_price = abs(position.quote_entry_amount / position.base_asset_amount * 1e9) / 1e6
        
        # Calculate unrealized PnL
        unrealized_pnl = user.get_unrealized_pnl(
            with_funding=False,
            market_index=position.market_index
        ) / 1e6  # QUOTE_PRECISION
        
        # Calculate funding PnL
        funding_pnl = user.get_unrealized_funding_pnl(
            market_index=position.market_index
        ) / 1e6  # QUOTE_PRECISION
        
        # Get LP information
        lp_shares = position.lp_shares / 1e9 if position.lp_shares != 0 else 0
        
        return {
            "market_index": position.market_index,
            "market_name": market_name,
            "position_type": "Long" if base_asset_amount > 0 else "Short",
            "position_size": base_asset_amount,
            "position_value": position_value,
            "current_price": current_price,
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "funding_pnl": funding_pnl,
            "lp_shares": lp_shares
        }
    
    def get_spot_position_details(self, user: DriftUser, position: SpotPosition) -> Dict[str, Any]:
        """Get detailed information about a spot market position"""
        # Get market information
        market = self.drift_client.get_spot_market_account(position.market_index)
        oracle_price_data = user.get_oracle_data_for_spot_market(position.market_index)
        
        # Decode market name from bytes
        market_name = bytes(market.name).decode('utf-8').strip('\x00')
        
        # Get token amount with proper sign (positive for deposits, negative for borrows)
        token_amount = user.get_token_amount(position.market_index)
        
        # Convert to human readable format based on decimals
        decimals = market.decimals
        formatted_token_amount = token_amount / (10 ** decimals)
        
        # Get position type (deposit or borrow)
        position_type = "Deposit" if token_amount > 0 else "Borrow"
        
        # Calculate token value in USD
        token_value = 0
        if position.market_index == QUOTE_SPOT_MARKET_INDEX:
            # For USDC, the value is just the token amount
            token_value = abs(formatted_token_amount)
            token_price = 1.0  # USDC price is 1:1 with USD
        else:
            # For other tokens, calculate USD value and get token price
            token_price = oracle_price_data.price / 1e6  # Convert to USD
            
            if token_amount < 0:
                liability_value = user.get_spot_market_liability_value(
                    market_index=position.market_index,
                    include_open_orders=True
                ) / 1e6  # QUOTE_PRECISION
                token_value = liability_value
            else:
                asset_value = user.get_spot_market_asset_value(
                    market_index=position.market_index,
                    include_open_orders=True
                ) / 1e6  # QUOTE_PRECISION
                token_value = asset_value
        
        return {
            "market_index": position.market_index,
            "market_name": market_name,
            "position_type": position_type,
            "token_amount": formatted_token_amount,
            "token_price": token_price,
            "token_value": token_value,
            "decimals": decimals
        }
    
    async def get_user_positions(self, authority_pubkey: str) -> Dict[str, Any]:
        """Get all positions for the given authority address"""
        pubkey = Pubkey.from_string(authority_pubkey)
        users = await self.get_user_accounts_by_authority(pubkey)
        
        if not users:
            return {"error": f"No accounts found for authority: {authority_pubkey}"}
        
        result = []
        
        for user in users:
            user_account = user.get_user_account()
            sub_account = {
                "sub_account_id": user_account.sub_account_id,
                "account_health": user.get_health(),
                "total_collateral": user.get_total_collateral() / 1e6,
                "free_collateral": user.get_free_collateral() / 1e6,
                "leverage": user.get_leverage() / 10000,  # Convert from basis points to x format
                "net_value": user.get_net_usd_value() / 1e6,
                "perp_positions": [],
                "spot_positions": []
            }
            
            # Get active perpetual positions
            perp_positions = user.get_active_perp_positions()
            for position in perp_positions:
                position_details = self.get_perp_position_details(user, position)
                sub_account["perp_positions"].append(position_details)
            
            # Get active spot positions
            spot_positions = user.get_active_spot_positions()
            for position in spot_positions:
                position_details = self.get_spot_position_details(user, position)
                sub_account["spot_positions"].append(position_details)
            
            result.append(sub_account)
        
        return {
            "authority": authority_pubkey, 
            "sub_accounts": result, 
            "using_cached_data": self.using_pickled_data,
            "data_timestamp": self.pickle_timestamp if self.using_pickled_data else time.time()
        }

def print_positions(positions_data: Dict[str, Any]):
    """
    Print formatted position information for a user.
    
    Args:
        positions_data: Dictionary containing user positions and account data
    """
    if "error" in positions_data:
        print(positions_data["error"])
        return
    
    print(f"\n=== Positions for Authority: {positions_data['authority']} ===")
    if positions_data.get("using_cached_data", False):
        data_time = datetime.datetime.fromtimestamp(positions_data.get("data_timestamp", 0))
        print(f"(Using cached data from {data_time})")
    print(f"Number of Sub-Accounts: {len(positions_data['sub_accounts'])}")
    
    for i, sub_account in enumerate(positions_data['sub_accounts']):
        print(f"\n=== Sub-Account {i} (ID: {sub_account['sub_account_id']}) ===")
        
        # Print account summary
        print("\n-- Account Summary --")
        print(f"Health: {sub_account['account_health']}%")
        print(f"Total Collateral: ${format_number(sub_account['total_collateral'])}")
        print(f"Free Collateral: ${format_number(sub_account['free_collateral'])}")
        print(f"Leverage: {format_number(sub_account['leverage'], 2)}x")
        print(f"Net Account Value: ${format_number(sub_account['net_value'])}")
        
        # Print perpetual positions
        if sub_account['perp_positions']:
            print("\n-- Perpetual Positions --")
            for pos in sub_account['perp_positions']:
                print(f"\nMarket: {pos['market_name']} (Index: {pos['market_index']})")
                print(f"Type: {pos['position_type']}")
                print(f"Size: {format_number(abs(pos['position_size']), 6)}")
                if pos['entry_price']:
                    print(f"Entry Price: ${format_number(pos['entry_price'])}")
                print(f"Current Price: ${format_number(pos['current_price'])}")
                print(f"Value: ${format_number(abs(pos['position_value']))}")
                print(f"Unrealized PnL: ${format_number(pos['unrealized_pnl'])}")
                print(f"Funding PnL: ${format_number(pos['funding_pnl'])}")
                if pos['lp_shares'] > 0:
                    print(f"LP Shares: {format_number(pos['lp_shares'])}")
        else:
            print("\nNo perpetual positions")
        
        # Print spot positions
        if sub_account['spot_positions']:
            print("\n-- Spot Positions --")
            for pos in sub_account['spot_positions']:
                print(f"\nMarket: {pos['market_name']} (Index: {pos['market_index']})")
                print(f"Type: {pos['position_type']}")
                print(f"Amount: {format_number(abs(pos['token_amount']), 6)}")
                print(f"Price: ${format_number(pos['token_price'])}")
                print(f"Value: ${format_number(abs(pos['token_value']))}")
        else:
            print("\nNo spot positions")

async def main():
    """
    Main function to process command line arguments and display user positions.
    """
    parser = argparse.ArgumentParser(
        description="Display Drift Protocol positions for a given authority address",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Define arguments
    parser.add_argument("authority", help="Authority public key to query")
    parser.add_argument("--rpc", help="RPC URL (will use RPC_URL env var if not provided)")
    parser.add_argument("--force-refresh", action="store_true", help="Force fetch fresh data from RPC")
    parser.add_argument("--pickle-dir", default=DEFAULT_PICKLE_DIR, help=f"Directory for pickle files (default: {DEFAULT_PICKLE_DIR})")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Get RPC URL
    rpc_url = args.rpc or os.environ.get("RPC_URL")
    if not rpc_url:
        print("Error: RPC URL is required. Either set the RPC_URL environment variable or use --rpc")
        return 1
    
    # Setup connection
    connection = AsyncClient(rpc_url)
    
    # Create position viewer with pickle settings
    viewer = DriftPositionViewer(
        connection, 
        pickle_dir=args.pickle_dir,
        force_refresh=args.force_refresh
    )
    
    try:
        # Initialize (will use pickles if available and fresh)
        print("Initializing...")
        await viewer.initialize()
        
        # Get and display positions
        positions_data = await viewer.get_user_positions(args.authority)
        print_positions(positions_data)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Clean up
        await viewer.cleanup()
    
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python drift-positions.py <AUTHORITY_ADDRESS> [--rpc <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]")
        sys.exit(1)
    
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 