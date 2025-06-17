#!/usr/bin/env python3

import argparse
import asyncio
import os
import csv
import logging
import time
from datetime import datetime

from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from anchorpy import Wallet
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.drift_user import DriftUser
from driftpy.constants.numeric_constants import QUOTE_PRECISION
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


def flatten_fuel_bonus_to_row(authority_pk_str, user_stats_pk_str, fuel_bonus_data, last_update_ts) -> list:
    """
    Extract fuel bonus data into a list for CSV row.
    The fuel_bonus_data is a dictionary returned by get_fuel_bonus() method.
    """
    if not fuel_bonus_data:
        return None
    
    # Convert raw fuel values to decimal by dividing by QUOTE_PRECISION
    row = [
        str(authority_pk_str),  # Authority address (from User account)
        str(user_stats_pk_str),  # UserStats account address
        fuel_bonus_data.get('insurance_fuel', 0) / QUOTE_PRECISION,
        fuel_bonus_data.get('deposit_fuel', 0) / QUOTE_PRECISION,
        fuel_bonus_data.get('borrow_fuel', 0) / QUOTE_PRECISION,
        fuel_bonus_data.get('position_fuel', 0) / QUOTE_PRECISION,
        fuel_bonus_data.get('taker_fuel', 0) / QUOTE_PRECISION,
        fuel_bonus_data.get('maker_fuel', 0) / QUOTE_PRECISION,
        last_update_ts,  # Last fuel update timestamp
    ]
    
    return row


def should_include_record(row):
    """
    Check if a record should be included based on fuel values.
    Returns True if at least one fuel metric (excluding timestamp) is non-zero.
    """
    # Check fuel values (indices 2-7, excluding the timestamp at index 8)
    fuel_values = row[2:8]  # fuel_insurance through fuel_maker
    return any(value != 0 for value in fuel_values)


def get_csv_headers():
    """
    Get CSV column headers for fuel fields.
    """
    headers = [
        "authority_address",
        "user_stats_address",
        "fuel_insurance",
        "fuel_deposits",
        "fuel_borrows",
        "fuel_positions",
        "fuel_taker",
        "fuel_maker",
        "last_fuel_update_ts",
    ]
    
    return headers


async def main():
    parser = argparse.ArgumentParser(description="Export fuel data (including overflow) to CSV using get_fuel_bonus().")
    
    # Generate timestamp for the default filename
    timestamp = datetime.now().strftime("%m%d%Y%H%M%S")
    default_filename = f"{timestamp}_user_stats_fuel_v2_export.csv"

    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL (default: {rpc_url} or RPC_URL from .env).")
    parser.add_argument("--output", type=str, default=default_filename, help=f"Output CSV filename (default: {default_filename})")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logging.info("🚀 Starting fuel stats export script (v2 with overflow support)...")
    logging.debug(f"Script arguments: {args}")

    connection = AsyncClient(args.rpc_url)
    logging.info(f"🔌 Connecting to RPC endpoint: {args.rpc_url}")
    # Use a dummy wallet as we are only reading data
    wallet = Wallet(Keypair()) 
    drift_client = DriftClient(
        connection,
        wallet,
        "mainnet", # Ensure this is the desired environment or make it configurable
        account_subscription=AccountSubscriptionConfig("cached")
    )

    try:
        logging.debug("Subscribing to Drift client...")
        await drift_client.subscribe()
        logging.info("✅ Successfully subscribed to Drift client.")
        
        logging.info("⏳ Fetching all User accounts to extract fuel statistics... This may take a while.")
        
        all_user_account_wrappers = await drift_client.program.account["User"].all()
        
        logging.info(f"👥 Found {len(all_user_account_wrappers)} User accounts. Now processing fuel data with overflow support.")
        
        with open(args.output, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            logging.info(f"📄 Opened output file for writing: {args.output}")
            
            headers = get_csv_headers()
            writer.writerow(headers)
            logging.debug(f"Wrote CSV headers: {headers}")
            
            # Counters for progress
            count = 0
            skipped_count = 0
            error_count = 0
            processed_authorities = set() # To avoid processing duplicate authorities if User accounts share one
            
            # Get current timestamp for fuel bonus calculation
            current_timestamp = int(time.time())
            
            total_wrappers = len(all_user_account_wrappers)
            logging.info(f"⚙️ Starting processing of {total_wrappers} user account wrappers...")
            
            for i, user_account_wrapper in enumerate(all_user_account_wrappers):
                user_data = user_account_wrapper.account
                authority_pk = user_data.authority

                logging.debug(f"Processing wrapper {i+1}/{total_wrappers}: authority={authority_pk}")

                if str(authority_pk) in processed_authorities:
                    logging.debug(f"Authority {authority_pk} already processed. Skipping.")
                    continue
                
                processed_authorities.add(str(authority_pk))

                try:
                    # Derive UserStats account public key
                    user_stats_account_pk = get_user_stats_account_public_key(authority_pk, drift_client.program_id)
                    logging.debug(f"Derived UserStats PK for authority {authority_pk}: {user_stats_account_pk}")
                    
                    # Create a DriftUser instance for this user
                    # We pass the sub_account_id from the user data
                    drift_user = DriftUser(
                        drift_client,
                        user_public_key=authority_pk,
                        sub_account_id=user_data.sub_account_id,
                        use_cache=False  # Don't cache since we're processing many users
                    )
                    
                    # The DriftUser might need to load the user account data
                    # Call get_fuel_bonus which handles both settled and overflow fuel
                    try:
                        fuel_bonus_data = await drift_user.get_fuel_bonus(
                            now=current_timestamp,
                            include_settled=True,    # Include fuel from user_stats
                            include_unsettled=True   # Include calculated overflow fuel
                        )
                    except Exception as fuel_error:
                        logging.debug(f"Could not get fuel bonus for authority {authority_pk}: {fuel_error}")
                        error_count += 1
                        continue
                    
                    if not fuel_bonus_data:
                        logging.debug(f"No fuel bonus data returned for authority {authority_pk}. Skipping.")
                        continue
                    
                    logging.debug(f"Successfully fetched fuel bonus data for {authority_pk}: {fuel_bonus_data}")
                    
                    # Get the last fuel update timestamp from user account
                    last_fuel_update_ts = getattr(user_data, 'last_fuel_bonus_update_ts', 0)

                    # Create row data with all fuel types
                    row = flatten_fuel_bonus_to_row(
                        str(authority_pk), 
                        str(user_stats_account_pk),
                        fuel_bonus_data,
                        last_fuel_update_ts
                    )
                    
                    if not row:
                        logging.debug(f"Flattening row returned None for {user_stats_account_pk}, skipping.")
                        continue
                    
                    # Check if this record has any non-zero fuel values
                    if not should_include_record(row):
                        skipped_count += 1
                        logging.debug(f"Record for {authority_pk} has zero fuel values. Skipping. Total skipped: {skipped_count}")
                        continue
                    
                    # Write to CSV
                    writer.writerow(row)
                    logging.debug(f"Wrote record for authority {authority_pk} to CSV.")
                    
                    count += 1
                    if count > 0 and count % 100 == 0:
                        logging.info(f"  ...exported {count} accounts with fuel data so far...")
                        
                except Exception as e:
                    # Log the error but continue processing
                    logging.debug(f"Could not process authority {authority_pk}: {e}")
                    error_count += 1
                    continue
        
        logging.info("\n✅ Fuel data export complete!")
        logging.info(f"📊 Total accounts with fuel data exported: {count}")
        logging.info(f"⏭️  Total accounts skipped (zero fuel values): {skipped_count}")
        logging.info(f"❌ Total accounts with errors: {error_count}")
        logging.info(f"💾 Output saved to: {args.output}")
        logging.info("📝 Note: This version includes both settled fuel and overflow fuel automatically.")

    except Exception as e:
        logging.exception(f"An unhandled error occurred: {e}")
    finally:
        logging.info("🧹 Cleaning up resources...")
        await drift_client.unsubscribe()
        await connection.close()
        logging.info("✨ Cleanup complete. Script finished.")


if __name__ == "__main__":
    asyncio.run(main()) 