#!/usr/bin/env python3
"""
Drift Protocol Fuel Balance Checker with VAT Caching

This script displays the fuel balance for a given Drift Protocol authority address.
It leverages the drift-labs/driftpy SDK and uses VAT (vat of pickles) to cache
on-chain data and reduce RPC calls.

The script maintains only a single VAT directory for caching data. When a new VAT is created,
all previous VAT directories are automatically deleted to save disk space.

Usage:
    python get_fuel.py --authority <AUTHORITY_ADDRESS> [--rpc-url <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]
    python get_fuel.py --account <USER_ACCOUNT_ADDRESS> [--rpc-url <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]

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

import argparse
import asyncio
import os
import time
import datetime
import shutil
from typing import Optional, Dict, Tuple
from pathlib import Path

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from anchorpy import Wallet
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.constants.numeric_constants import QUOTE_PRECISION
from driftpy.types import UserStatsAccount, MarketType
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import UserMapConfig
from driftpy.user_map.user_map_config import WebsocketConfig as UserMapWebsocketConfig
from driftpy.market_map.market_map import MarketMap
from driftpy.market_map.market_map_config import MarketMapConfig
from driftpy.market_map.market_map_config import WebsocketConfig as MarketMapWebsocketConfig
from driftpy.pickle.vat import Vat
from driftpy.user_map.userstats_map import UserStatsMap
from driftpy.user_map.user_map_config import UserStatsMapConfig
from solana.rpc.async_api import AsyncClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Default settings
DEFAULT_PICKLE_DIR = "../fuel_pickles"
DEFAULT_MAX_PICKLE_AGE = 3600  # 1 hour

def get_user_stats_account_public_key(authority: Pubkey, program_id: Pubkey) -> Pubkey:
    """
    Derives the userStats account public key for a given authority.
    """
    user_stats_account_pk, _ = Pubkey.find_program_address(
        [b'user_stats', bytes(authority)],
        program_id
    )
    return user_stats_account_pk

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
                    # Sort by slot number to get the newest file - more robust parsing
                    def get_slot_number(filename):
                        try:
                            # Remove .pkl extension first
                            name_without_ext = filename.rsplit('.', 1)[0]
                            # Split by underscore and get the last part
                            parts = name_without_ext.split('_')
                            if len(parts) > 1:
                                return int(parts[-1])
                            return 0
                        except (ValueError, IndexError):
                            return 0
                    
                    matching_files.sort(key=get_slot_number, reverse=True)
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

class FuelBalanceChecker:
    """Class for checking fuel balances using VAT caching"""
    
    def __init__(self, connection, pickle_dir: str = DEFAULT_PICKLE_DIR, force_refresh: bool = False, max_pickle_age: int = DEFAULT_MAX_PICKLE_AGE):
        """Initialize with connection and pickle settings"""
        # Generate a random keypair - we're only reading data, not signing transactions
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
        self.max_pickle_age = max_pickle_age
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
            if pickle_files and timestamp and is_pickle_fresh(timestamp, self.max_pickle_age):
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
            
            # Debug: Print the pickle files being loaded
            print("Pickle files to load:")
            for key, value in pickle_files.items():
                print(f"  {key}: {value}")
            
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
            import traceback
            print("Full traceback:")
            traceback.print_exc()
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

    async def get_fuel_balance(self, authority: Pubkey) -> Optional[float]:
        """Get fuel balance for the given authority"""
        if not self.stats_map:
            raise ValueError("UserStatsMap not initialized")
        
        # If we're using fresh data, sync first
        if not self.using_pickled_data:
            await self.stats_map.sync()
        
        # Get the user stats account public key
        user_stats_pk = get_user_stats_account_public_key(authority, self.drift_client.program_id)
        
        # Get the user stats data
        user_stats_data = self.stats_map.get(str(user_stats_pk))
        
        if not user_stats_data:
            print(f"No UserStats account found for authority: {authority}")
            return None
        
        # Calculate total fuel balance
        raw_fuel_balance = 0
        raw_fuel_balance += getattr(user_stats_data, 'fuel_insurance', 0)
        raw_fuel_balance += getattr(user_stats_data, 'fuel_taker', 0)
        raw_fuel_balance += getattr(user_stats_data, 'fuel_maker', 0)
        raw_fuel_balance += getattr(user_stats_data, 'fuel_deposits', 0)
        raw_fuel_balance += getattr(user_stats_data, 'fuel_borrows', 0)
        raw_fuel_balance += getattr(user_stats_data, 'fuel_positions', 0)
        
        fuel_balance = raw_fuel_balance / QUOTE_PRECISION
        return fuel_balance

async def main():
    parser = argparse.ArgumentParser(
        description="Get fuel balance for a Drift authority or user account, with VAT caching.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--authority", type=str, help="The authority public key (string).")
    group.add_argument("--account", type=str, help="The user account public key (string). If provided, the script will first derive the authority.")
    
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL (default: {rpc_url} or RPC_URL from .env).")
    parser.add_argument("--pickle-dir", type=str, default=DEFAULT_PICKLE_DIR, help=f"Directory for caching VAT data (default: {DEFAULT_PICKLE_DIR}).")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cache and fetch fresh data from the network.")
    parser.add_argument("--max-pickle-age", type=int, default=DEFAULT_MAX_PICKLE_AGE, help=f"Maximum age of a pickle file in seconds to be considered fresh (default: {DEFAULT_MAX_PICKLE_AGE}).")

    args = parser.parse_args()

    print(f"Using RPC URL: {args.rpc_url}")
    connection = AsyncClient(args.rpc_url)
    
    # Create fuel balance checker
    checker = FuelBalanceChecker(
        connection,
        pickle_dir=args.pickle_dir,
        force_refresh=args.force_refresh,
        max_pickle_age=args.max_pickle_age
    )

    authority_to_use = None

    try:
        if args.authority:
            print(f"Authority provided: {args.authority}")
            authority_to_use = Pubkey.from_string(args.authority)
        elif args.account:
            print(f"Account provided: {args.account}")
            account_pk = Pubkey.from_string(args.account)
            
            # We need to fetch the account data to get the authority
            # This requires at least a minimal connection
            print(f"Fetching user account data for: {account_pk} to derive authority...")
            start_fetch_user_time = time.time()
            
            # Use a temporary drift client just to fetch the account
            temp_wallet = Wallet(Keypair())
            temp_drift_client = DriftClient(
                connection,
                temp_wallet,
                account_subscription=AccountSubscriptionConfig("cached")
            )
            
            user_account_info = await temp_drift_client.program.account['User'].fetch(account_pk)
            end_fetch_user_time = time.time()
            print(f"Fetched User account data. Took {end_fetch_user_time - start_fetch_user_time:.2f} seconds.")
            
            if user_account_info:
                authority_to_use = user_account_info.authority
                print(f"Derived authority: {authority_to_use} from account: {args.account}")
            else:
                print(f"Could not find user account data for account: {args.account}")
                return

        if not authority_to_use:
            print("Authority could not be determined.")
            return

        # Initialize with VAT
        print("Initializing...")
        await checker.initialize()
        
        # Get fuel balance
        fuel_balance = await checker.get_fuel_balance(authority_to_use)
        
        if fuel_balance is not None:
            print(f"\nCalculated Total Fuel Balance for authority {authority_to_use}: {fuel_balance}")
            
            if fuel_balance == 0:
                print("\nNote: Fuel balance is zero. This could be because:")
                print("1. The account has no fuel-generating activity")
                print("2. The field names used for fuel (fuel_insurance, fuel_taker, etc.) might be incorrect")
                print("3. Check the actual UserStatsAccount structure in driftpy.types")
        else:
            print(f"No fuel balance data available for authority {authority_to_use}")

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up...")
        await checker.cleanup()
        await connection.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
