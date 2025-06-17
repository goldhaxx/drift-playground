#!/usr/bin/env python3

import argparse
import asyncio
import os
import csv
import logging
from datetime import datetime
import base58

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

# Removed local get_user_stats_account_public_key as we are not deriving it anymore

def flatten_user_stats_to_row(authority_pk_str, user_stats_pk_str, user_stats_data) -> list:
    """
    Extract only fuel-related UserStats data into a list for CSV row.
    Returns only fuel-specific fields.
    """
    if not user_stats_data:
        return None
    
    # Extract only fuel-related fields
    row = [
        str(authority_pk_str),  # Authority address (from UserStats account)
        str(user_stats_pk_str),  # UserStats account address
        getattr(user_stats_data, 'fuel_insurance', 0),
        getattr(user_stats_data, 'fuel_deposits', 0),
        getattr(user_stats_data, 'fuel_borrows', 0),
        getattr(user_stats_data, 'fuel_positions', 0),
        getattr(user_stats_data, 'fuel_taker', 0),
        getattr(user_stats_data, 'fuel_maker', 0),
        getattr(user_stats_data, 'last_fuel_if_bonus_update_ts', 0),
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
    Get CSV column headers for fuel-specific fields only.
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
        "last_fuel_if_bonus_update_ts",
    ]
    
    return headers


async def main():
    parser = argparse.ArgumentParser(description="Export fuel-related UserStats data to CSV.")
    
    # Generate timestamp for the default filename
    timestamp = datetime.now().strftime("%m%d%Y%H%M%S")
    default_filename = f"{timestamp}_user_stats_fuel_export.csv"

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

    logging.info("🚀 Starting fuel stats export script...")
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
    
    # The size of the UserStats account struct on-chain
    USER_STATS_ACCOUNT_SIZE = 488

    try:
        logging.debug("Subscribing to Drift client...")
        await drift_client.subscribe()
        logging.info("Successfully subscribed to Drift client.")
        
        logging.info("Fetching all UserStats accounts... This may take a while.")

        # More efficient approach:
        # 1. Get all UserStats account pubkeys using getProgramAccounts with a dataSlice to be lightweight.
        # 2. Paginate through the pubkeys and fetch account data in batches using getMultipleAccounts.

        # Step 1: Get all UserStats account pubkeys
        logging.info("Fetching all UserStats account public keys...")
        
        # Get the discriminator for the UserStats account
        user_stats_discriminator = drift_client.program.account['UserStats']._coder.discriminator
        
        # Fetch accounts with matching discriminator and size, but only get their pubkeys.
        gpa_resp = await connection.get_program_accounts(
            drift_client.program_id,
            encoding="base64",
            filters=[
                {"dataSize": USER_STATS_ACCOUNT_SIZE},
                {"memcmp": {"offset": 0, "bytes": base58.b58encode(user_stats_discriminator).decode('utf-8')}}
            ],
            data_slice={"offset": 0, "length": 0}
        )
        
        user_stats_pubkeys = [acc["pubkey"] for acc in gpa_resp]
        logging.info(f"👥 Found {len(user_stats_pubkeys)} UserStats accounts. Now processing in batches.")
        
        with open(args.output, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            logging.info(f"📄 Opened output file for writing: {args.output}")
            
            headers = get_csv_headers()
            writer.writerow(headers)
            logging.debug(f"Wrote CSV headers: {headers}")
            
            count = 0
            skipped_count = 0
            
            # Step 2: Process pubkeys in batches
            batch_size = 100
            total_batches = (len(user_stats_pubkeys) + batch_size - 1) // batch_size
            logging.info(f"⚙️ Starting processing of {len(user_stats_pubkeys)} accounts in {total_batches} batches of size {batch_size}...")

            for i in range(0, len(user_stats_pubkeys), batch_size):
                batch_pubkeys = user_stats_pubkeys[i:i+batch_size]
                logging.debug(f"Processing batch {i//batch_size + 1}/{total_batches}")
                
                try:
                    # Get account data for the current batch
                    accounts_data = await connection.get_multiple_accounts(batch_pubkeys)
                    
                    for j, acc_data in enumerate(accounts_data):
                        if acc_data is None:
                            logging.debug(f"Could not fetch account data for {batch_pubkeys[j]}. Skipping.")
                            continue

                        user_stats_pk = batch_pubkeys[j]
                        
                        try:
                            # Decode the account data to get UserStats object
                            user_stats_data = drift_client.program.coder.accounts.decode(acc_data.data)
                            authority_pk = user_stats_data.authority

                            logging.debug(f"Processing UserStats account {user_stats_pk} for authority {authority_pk}")

                            # Create row data with fuel fields only
                            row = flatten_user_stats_to_row(
                                str(authority_pk), 
                                str(user_stats_pk),
                                user_stats_data
                            )
                            
                            if not row:
                                logging.debug(f"Flattening row returned None for {user_stats_pk}, skipping.")
                                continue
                            
                            # Check if this record has any non-zero fuel values
                            if not should_include_record(row):
                                skipped_count += 1
                                logging.debug(f"Record for {authority_pk} has zero fuel values. Skipping. Total skipped: {skipped_count}")
                                continue
                            
                            # Write to CSV
                            writer.writerow(row)
                            
                            count += 1
                        except Exception as e:
                            logging.warning(f"Failed to decode or process UserStats account {user_stats_pk}: {e}")
                            continue

                    if (i//batch_size + 1) % 10 == 0:
                        logging.info(f"  ...processed batch {i//batch_size + 1}/{total_batches}, exported {count} accounts so far...")

                except Exception as e:
                    logging.error(f"Error processing batch {i//batch_size + 1}: {e}")
                    continue
        
        logging.info("\n✅ Fuel data export complete!")
        logging.info(f"Total UserStats accounts with fuel data exported: {count}")
        logging.info(f"Total accounts skipped (zero fuel values): {skipped_count}")
        logging.info(f"Output saved to: {args.output}")

    except Exception as e:
        logging.exception(f"An unhandled error occurred: {e}")
    finally:
        logging.info("Cleaning up resources...")
        await drift_client.unsubscribe()
        await connection.close()
        logging.info("Cleanup complete. Script finished.")


if __name__ == "__main__":
    asyncio.run(main()) 