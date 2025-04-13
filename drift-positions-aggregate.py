#!/usr/bin/env python3
"""
Drift Protocol Position Aggregator

This script displays aggregated positions across all users in the Drift Protocol.
It leverages the drift-labs/driftpy SDK to fetch and display total notional value
of all positions in the system, grouped by market.

The script maintains only a single VAT directory for caching data. When a new VAT is created,
all previous VAT directories are automatically deleted to save disk space.

Usage:
    python drift-positions-aggregate.py [--rpc <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]

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
from collections import defaultdict

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
DEFAULT_PICKLE_DIR = "pickles"

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

class DriftPositionAggregator:
    """Class for fetching and aggregating all Drift positions"""
    
    def __init__(self, connection, pickle_dir: str = DEFAULT_PICKLE_DIR, force_refresh: bool = False):
        """Initialize with connection and pickle settings"""
        # Generate a random keypair - we're only reading data, not signing transactions
        from solders.keypair import Keypair # type: ignore
        kp = Keypair()
        self.wallet = Wallet(kp)
        self.connection = connection
        
        # Initialize DriftClient with cached subscription mode (no RPC calls yet)
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

    async def get_all_user_positions(self) -> Dict[str, Any]:
        """Get aggregated positions for all users in the system"""
        if not self.user_map:
            raise ValueError("UserMap not initialized")
        
        # Initialize aggregation containers
        perp_aggregates = defaultdict(lambda: {
            "market_name": "",
            "total_long_usd": 0.0,
            "total_short_usd": 0.0,
            "total_lp_shares": 0,
            "current_price": 0.0,
            "unique_users": set()
        })
        
        spot_aggregates = defaultdict(lambda: {
            "market_name": "",
            "total_deposits_native": 0.0,
            "total_borrows_native": 0.0,
            "total_deposits_usd": 0.0,
            "total_borrows_usd": 0.0,
            "token_price": 0.0,
            "decimals": 0,
            "unique_users": set()
        })
        
        total_users = 0
        total_sub_accounts = 0
        total_net_value = 0.0
        
        # Track unique authorities
        unique_authorities = set()
        
        # If we're using fresh data, sync first
        if not self.using_pickled_data:
            await self.user_map.sync()
        
        # Process all users
        for user in self.user_map.values():
            try:
                user_account = user.get_user_account()
                authority = str(user_account.authority)
                unique_authorities.add(authority)
                total_sub_accounts += 1
                total_net_value += user.get_net_usd_value() / 1e6
                
                # Process perpetual positions
                perp_positions = user.get_active_perp_positions()
                for position in perp_positions:
                    market = self.drift_client.get_perp_market_account(position.market_index)
                    market_name = bytes(market.name).decode('utf-8').strip('\x00')
                    oracle_price_data = user.get_oracle_data_for_perp_market(position.market_index)
                    
                    agg = perp_aggregates[position.market_index]
                    agg["market_name"] = market_name
                    agg["current_price"] = oracle_price_data.price / 1e6
                    
                    position_value = abs(user.get_perp_position_value(
                        position.market_index,
                        oracle_price_data,
                        include_open_orders=True
                    ) / 1e6)
                    
                    base_asset_amount = position.base_asset_amount / 1e9
                    if base_asset_amount > 0:
                        agg["total_long_usd"] += position_value
                    else:
                        agg["total_short_usd"] += position_value
                    
                    agg["total_lp_shares"] += position.lp_shares / 1e9
                    agg["unique_users"].add(authority)
                
                # Process spot positions
                spot_positions = user.get_active_spot_positions()
                for position in spot_positions:
                    market = self.drift_client.get_spot_market_account(position.market_index)
                    market_name = bytes(market.name).decode('utf-8').strip('\x00')
                    
                    agg = spot_aggregates[position.market_index]
                    agg["market_name"] = market_name
                    agg["decimals"] = market.decimals
                    
                    token_amount = user.get_token_amount(position.market_index)
                    formatted_amount = token_amount / (10 ** market.decimals)
                    
                    if position.market_index == QUOTE_SPOT_MARKET_INDEX:
                        token_price = 1.0
                        token_value = abs(formatted_amount)
                    else:
                        oracle_price_data = user.get_oracle_data_for_spot_market(position.market_index)
                        token_price = oracle_price_data.price / 1e6
                        if token_amount < 0:
                            token_value = abs(user.get_spot_market_liability_value(
                                market_index=position.market_index,
                                include_open_orders=True
                            ) / 1e6)
                        else:
                            token_value = abs(user.get_spot_market_asset_value(
                                market_index=position.market_index,
                                include_open_orders=True
                            ) / 1e6)
                    
                    agg["token_price"] = token_price
                    
                    if token_amount > 0:
                        agg["total_deposits_native"] += formatted_amount
                        agg["total_deposits_usd"] += token_value
                    else:
                        agg["total_borrows_native"] += abs(formatted_amount)
                        agg["total_borrows_usd"] += token_value
                    
                    agg["unique_users"].add(authority)
                    
            except Exception as e:
                print(f"Error processing user: {e}")
        
        # Convert sets to counts for JSON serialization
        for agg in perp_aggregates.values():
            agg["unique_users"] = len(agg["unique_users"])
        for agg in spot_aggregates.values():
            agg["unique_users"] = len(agg["unique_users"])
        
        return {
            "total_unique_authorities": len(unique_authorities),
            "total_sub_accounts": total_sub_accounts,
            "total_net_value": total_net_value,
            "perp_markets": dict(perp_aggregates),
            "spot_markets": dict(spot_aggregates),
            "using_cached_data": self.using_pickled_data,
            "data_timestamp": self.pickle_timestamp if self.using_pickled_data else time.time()
        }

def print_aggregated_positions(data: Dict[str, Any]):
    """
    Print formatted aggregated position information.
    
    Args:
        data: Dictionary containing aggregated position data
    """
    print("\n=== Drift Protocol Position Aggregation ===")
    if data.get("using_cached_data", False):
        data_time = datetime.datetime.fromtimestamp(data.get("data_timestamp", 0))
        print(f"(Using cached data from {data_time})")
    
    print(f"\n-- System Overview --")
    print(f"Total Unique Authorities: {data['total_unique_authorities']}")
    print(f"Total Sub-Accounts: {data['total_sub_accounts']}")
    print(f"Total Net Value: ${format_number(data['total_net_value'])}")
    
    # Print perpetual market aggregates
    print("\n-- Perpetual Markets --")
    for market_index, market_data in sorted(data['perp_markets'].items()):
        print(f"\nMarket: {market_data['market_name']} (Index: {market_index})")
        print(f"Current Price: ${format_number(market_data['current_price'])}")
        print(f"Total Long Value: ${format_number(market_data['total_long_usd'])}")
        print(f"Total Short Value: ${format_number(market_data['total_short_usd'])}")
        print(f"Total Notional: ${format_number(market_data['total_long_usd'] + market_data['total_short_usd'])}")
        if market_data['total_lp_shares'] > 0:
            print(f"Total LP Shares: {format_number(market_data['total_lp_shares'])}")
        print(f"Unique Users: {market_data['unique_users']}")
    
    # Print spot market aggregates
    print("\n-- Spot Markets --")
    for market_index, market_data in sorted(data['spot_markets'].items()):
        print(f"\nMarket: {market_data['market_name']} (Index: {market_index})")
        print(f"Token Price: ${format_number(market_data['token_price'])}")
        print(f"Total Deposits: {format_number(market_data['total_deposits_native'])} "
              f"(${format_number(market_data['total_deposits_usd'])})")
        print(f"Total Borrows: {format_number(market_data['total_borrows_native'])} "
              f"(${format_number(market_data['total_borrows_usd'])})")
        print(f"Total Volume: ${format_number(market_data['total_deposits_usd'] + market_data['total_borrows_usd'])}")
        print(f"Unique Users: {market_data['unique_users']}")

async def main():
    """
    Main function to process command line arguments and display aggregated positions.
    """
    parser = argparse.ArgumentParser(
        description="Display aggregated Drift Protocol positions across all users",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Define arguments
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
    
    # Create position aggregator with pickle settings
    aggregator = DriftPositionAggregator(
        connection, 
        pickle_dir=args.pickle_dir,
        force_refresh=args.force_refresh
    )
    
    try:
        # Initialize (will use pickles if available and fresh)
        print("Initializing...")
        await aggregator.initialize()
        
        # Get and display aggregated positions
        positions_data = await aggregator.get_all_user_positions()
        print_aggregated_positions(positions_data)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Clean up
        await aggregator.cleanup()
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 