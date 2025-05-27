#!/usr/bin/env python3

import argparse
import asyncio
import os
import csv
from datetime import datetime

from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from anchorpy import Wallet
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
# Removed: from driftpy.user_map.userstats_map import UserStatsMap
# Removed: from driftpy.user_map.user_map_config import UserStatsMapConfig
# from driftpy.addresses import get_user_stats_account_public_key # We will define this locally
from solana.rpc.async_api import AsyncClient
from dotenv import load_dotenv

# Added helper function from get_UserStats.py
def get_user_stats_account_public_key(authority: Pubkey, program_id: Pubkey) -> Pubkey:
    """
    Derives the userStats account public key for a given authority.
    """
    user_stats_account_pk, _ = Pubkey.find_program_address(
        [b'user_stats', bytes(authority)],
        program_id
    )
    return user_stats_account_pk

def flatten_user_stats_to_row(authority_pk_str, user_stats_pk_str, user_stats_data) -> list: # Renamed authority_pk for clarity
    """
    Flatten UserStats data into a list for CSV row.
    Returns data in the exact order it appears on-chain.
    """
    if not user_stats_data:
        return [str(authority_pk_str), str(user_stats_pk_str)]
    
    # Build row with data in the order it appears in the struct
    row = [
        str(authority_pk_str),  # Authority address (from User account)
        str(user_stats_pk_str),  # UserStats account address
        str(getattr(user_stats_data, 'authority', '')), # This is authority from UserStats account, should match
        str(getattr(user_stats_data, 'referrer', '')),
    ]
    
    # Handle fees - check if it's a nested object or direct attributes
    if hasattr(user_stats_data, 'fees') and user_stats_data.fees:
        fees = user_stats_data.fees
        row.extend([
            getattr(fees, 'total_fee_paid', 0),
            getattr(fees, 'total_fee_rebate', 0),
            getattr(fees, 'total_token_discount', 0),
            getattr(fees, 'total_referee_discount', 0),
            getattr(fees, 'total_referrer_reward', 0),
            getattr(fees, 'current_epoch_referrer_reward', 0),
        ])
    else:
        # Try direct attributes
        row.extend([
            getattr(user_stats_data, 'total_fee_paid', 0),
            getattr(user_stats_data, 'total_fee_rebate', 0),
            getattr(user_stats_data, 'total_token_discount', 0),
            getattr(user_stats_data, 'total_referee_discount', 0),
            getattr(user_stats_data, 'total_referrer_reward', 0),
            getattr(user_stats_data, 'current_epoch_referrer_reward', 0),
        ])
    
    # Continue with other fields in order
    row.extend([
        getattr(user_stats_data, 'next_epoch_ts', 0),
        getattr(user_stats_data, 'maker_volume30d', 0),
        getattr(user_stats_data, 'taker_volume30d', 0),
        getattr(user_stats_data, 'filler_volume30d', 0),
        getattr(user_stats_data, 'last_maker_volume30d_ts', 0),
        getattr(user_stats_data, 'last_taker_volume30d_ts', 0),
        getattr(user_stats_data, 'last_filler_volume30d_ts', 0),
        getattr(user_stats_data, 'if_staked_quote_asset_amount', 0),
        getattr(user_stats_data, 'number_of_sub_accounts', 0),
        getattr(user_stats_data, 'number_of_sub_accounts_created', 0),
        1 if getattr(user_stats_data, 'is_referrer', False) else 0,  # Convert bool to int
        getattr(user_stats_data, 'disable_update_perp_bid_ask_twap', False),
        getattr(user_stats_data, 'padding1', 0),
        getattr(user_stats_data, 'fuel_insurance', 0),
        getattr(user_stats_data, 'fuel_deposits', 0),
        getattr(user_stats_data, 'fuel_borrows', 0),
        getattr(user_stats_data, 'fuel_positions', 0),
        getattr(user_stats_data, 'fuel_taker', 0),
        getattr(user_stats_data, 'fuel_maker', 0),
        getattr(user_stats_data, 'if_staked_gov_token_amount', 0),
        getattr(user_stats_data, 'last_fuel_if_bonus_update_ts', 0),
    ])
    
    # Handle padding array if it exists
    padding = getattr(user_stats_data, 'padding', [])
    if padding:
        row.extend(padding)
    else:
        # Add default padding values if not present
        row.extend([0] * 12)
    
    return row


def get_csv_headers():
    """
    Get CSV column headers in order.
    """
    headers = [
        "authority_address",
        "user_stats_address",
        "authority",
        "referrer",
        "total_fee_paid",
        "total_fee_rebate",
        "total_token_discount",
        "total_referee_discount",
        "total_referrer_reward",
        "current_epoch_referrer_reward",
        "next_epoch_ts",
        "maker_volume30d",
        "taker_volume30d",
        "filler_volume30d",
        "last_maker_volume30d_ts",
        "last_taker_volume30d_ts",
        "last_filler_volume30d_ts",
        "if_staked_quote_asset_amount",
        "number_of_sub_accounts",
        "number_of_sub_accounts_created",
        "is_referrer",
        "disable_update_perp_bid_ask_twap",
        "padding1",
        "fuel_insurance",
        "fuel_deposits",
        "fuel_borrows",
        "fuel_positions",
        "fuel_taker",
        "fuel_maker",
        "if_staked_gov_token_amount",
        "last_fuel_if_bonus_update_ts",
    ]
    
    # Add padding columns
    for i in range(12):
        headers.append(f"padding_{i}")
    
    return headers


async def main():
    parser = argparse.ArgumentParser(description="Export all UserStats accounts data to CSV using UserStatsMap.")
    
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL (default: {rpc_url} or RPC_URL from .env).")
    parser.add_argument("--output", type=str, default="user_stats_export.csv", help="Output CSV filename (default: user_stats_export.csv)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    connection = AsyncClient(args.rpc_url)
    # Use a dummy wallet as we are only reading data
    wallet = Wallet(Keypair()) 
    drift_client = DriftClient(
        connection,
        wallet,
        "mainnet", # Ensure this is the desired environment or make it configurable
        account_subscription=AccountSubscriptionConfig("cached")
    )

    try:
        # Subscribe to drift client first
        if args.verbose:
            print("Subscribing to Drift client...")
        await drift_client.subscribe()
        
        if args.verbose:
            print("Fetching all User accounts... This may take a while.")
        
        # Fetch all User accounts
        # The .all() method returns a list of objects, each with an 'account' attribute
        # and a 'publicKey' attribute.
        all_user_account_wrappers = await drift_client.program.account["User"].all()
        
        if args.verbose:
            print(f"Found {len(all_user_account_wrappers)} User accounts. Now processing UserStats for each.")
        
        # Open CSV file for writing
        with open(args.output, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write headers
            writer.writerow(get_csv_headers())
            
            # Counter for progress
            count = 0
            processed_authorities = set() # To avoid processing duplicate authorities if User accounts share one
            
            for user_account_wrapper in all_user_account_wrappers:
                user_data = user_account_wrapper.account
                authority_pk = user_data.authority

                if str(authority_pk) in processed_authorities:
                    if args.verbose:
                        print(f"Authority {authority_pk} already processed (from another User subaccount). Skipping UserStats derivation.")
                    continue
                
                processed_authorities.add(str(authority_pk))

                try:
                    # Derive UserStats account public key
                    user_stats_account_pk = get_user_stats_account_public_key(authority_pk, drift_client.program_id)
                    
                    if args.verbose:
                        print(f"Fetching UserStats for authority {authority_pk} (UserStats PK: {user_stats_account_pk})...")
                        
                    # Fetch the UserStats account data directly
                    user_stats_data = await drift_client.program.account['UserStats'].fetch(user_stats_account_pk)
                    
                    if not user_stats_data:
                        if args.verbose:
                            print(f"No UserStats data found for UserStats account {user_stats_account_pk} (Authority: {authority_pk}). Skipping.")
                        continue

                    # Create row data
                    # Pass the authority_pk from the User account as the primary authority identifier
                    row = flatten_user_stats_to_row(
                        str(authority_pk), 
                        str(user_stats_account_pk),
                        user_stats_data
                    )
                    
                    # Write to CSV
                    writer.writerow(row)
                    
                    count += 1
                    if args.verbose and count % 100 == 0:
                        print(f"Processed {count} UserStats accounts...")
                        
                except Exception as e: # Broad catch, specific errors like AccountDoesNotExistError could be handled
                    if args.verbose:
                        # Example of how to check for specific errors if needed:
                        # from anchorpy.error import AccountDoesNotExistError
                        # if isinstance(e, AccountDoesNotExistError):
                        #    print(f"UserStats account {user_stats_account_pk} not found for authority {authority_pk}. Skipping.")
                        # else:
                        print(f"Error processing UserStats for authority {authority_pk} (UserStats PK: {user_stats_account_pk if 'user_stats_account_pk' in locals() else 'unknown'}): {e}")
                    continue
        
        print(f"\nExport complete!")
        print(f"Total UserStats accounts exported: {count}")
        print(f"Output saved to: {args.output}")
        
        # No UserStatsMap to unsubscribe from

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await drift_client.unsubscribe()
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main()) 