#!/usr/bin/env python3

import argparse
import asyncio
import os
import logging
import time
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from anchorpy import Wallet
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.drift_user import DriftUser
from driftpy.drift_user_stats import DriftUserStats, UserStatsSubscriptionConfig
from driftpy.constants.numeric_constants import QUOTE_PRECISION
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import MemcmpOpts
from dotenv import load_dotenv

def get_user_stats_account_public_key(authority: Pubkey, program_id: Pubkey) -> Pubkey:
    user_stats_account_pk, _ = Pubkey.find_program_address(
        [b'user_stats', bytes(authority)],
        program_id
    )
    return user_stats_account_pk

async def get_fuel_bonus_for_user(
    drift_client: DriftClient, 
    user_public_key: Pubkey, 
    user_authority: Pubkey
) -> dict:
    """
    Fetches fuel bonus data for a single DriftUser by directly fetching the 
    UserStats account, inspired by the approach in drift-v2-streamlit.

    This method avoids temporary subscriptions by fetching the UserStats data on-demand
    and providing it to the DriftUser instance via a temporary mock object.

    Args:
        drift_client: The main DriftClient instance.
        user_public_key: The public key of the user account.
        user_authority: The authority public key for the user.

    Returns:
        A dictionary containing the fuel bonus data, or None if it fails.
    """
    original_get_user_stats = drift_client.get_user_stats
    drift_user = None
    fuel_bonus_data = None

    try:
        # 1. Derive the UserStats public key for the user's authority
        user_stats_pk = get_user_stats_account_public_key(user_authority, drift_client.program_id)
        logging.info(f"Derived UserStats PK for authority {user_authority}: {user_stats_pk}")

        # 2. Fetch the UserStats account data directly, avoiding subscriptions
        logging.info("Fetching UserStats account data directly...")
        try:
            user_stats_data = await drift_client.program.account["UserStats"].fetch(user_stats_pk)
            logging.info("✅ Successfully fetched UserStats data.")
        except Exception:
            logging.error(f"❌ Failed to fetch UserStats account {user_stats_pk}. It might not exist for the given authority.", exc_info=True)
            return None

        # 3. Create a mock subscriber object to hold the fetched data.
        # This is needed to satisfy the interface expected by DriftUser.get_fuel_bonus()
        class MockUserStatsSubscriber:
            def get_account(self):
                return user_stats_data
        
        # 4. Temporarily replace the client's user_stats getter with our mock
        drift_client.get_user_stats = lambda: MockUserStatsSubscriber()
        logging.info("Temporarily patched drift_client.get_user_stats with direct-fetch data.")

        # 5. Create and subscribe a DriftUser instance to load its own account data
        drift_user = DriftUser(
            drift_client,
            user_public_key=user_public_key,
        )
        await drift_user.subscribe()
        logging.info(f"Subscribed to DriftUser for user account {user_public_key}.")

        # 6. WORKAROUND: The library's get_fuel_bonus function incorrectly looks for
        # last_fuel_bonus_update_ts on the UserStats object, but it lives on the
        # UserAccount object. We patch the fetched UserStats object in memory to include it.
        user_account_data = drift_user.get_user_account()
        if user_account_data:
            user_stats_data.last_fuel_bonus_update_ts = user_account_data.last_fuel_bonus_update_ts
            logging.info("Applied workaround: Patched UserStats data with last_fuel_bonus_update_ts from UserAccount.")
        else:
            logging.error("❌ Could not get UserAccount data to apply workaround.")
            return None

        # 7. Now, call get_fuel_bonus, which will use our patched getter.
        # This function is not async, it returns the data directly.
        fuel_bonus_data = drift_user.get_fuel_bonus(
            now=int(time.time()),
            include_settled=True,
            include_unsettled=True
        )

    finally:
        # 8. Crucial cleanup: restore the original method and unsubscribe
        drift_client.get_user_stats = original_get_user_stats
        logging.info("Restored original drift_client.get_user_stats.")
        if drift_user:
            # We must unsubscribe the DriftUser to close its websocket connection
            if drift_user.account_subscriber:
                await drift_user.account_subscriber.unsubscribe()
            logging.info(f"Unsubscribed from DriftUser for {user_public_key}")
    
    return fuel_bonus_data

async def main():
    parser = argparse.ArgumentParser(description="Fetches and displays the fuel bonus for a specific user subaccount.")
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL. Defaults to {DEFAULT_RPC_URL} or RPC_URL env var.")
    parser.add_argument("--authority", type=str, required=True, help="The authority public key of the user to test.")
    
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    logging.info("🚀 Starting single user fuel test script...")
    
    connection = None
    drift_client = None
    is_initialized = False
    try:
        connection = AsyncClient(args.rpc_url)
        logging.info(f"🔌 Connecting to RPC endpoint: {args.rpc_url}")
        
        # Use a dummy wallet, as we only need to read data
        wallet = Wallet(Keypair()) 
        
        drift_client = DriftClient(
            connection,
            wallet,
            "mainnet",
            account_subscription=AccountSubscriptionConfig("cached")
        )
        await drift_client.subscribe()
        is_initialized = True
        logging.info("✅ Successfully subscribed to Drift client.")

        authority_pk_arg = Pubkey.from_string(args.authority)
        logging.info(f"⏳ Fetching user account(s) for authority: {authority_pk_arg}")
        
        # This method of fetching user accounts by authority is consistent with
        # the approach used in the drift-v2-streamlit repository.
        user_accounts = await drift_client.program.account["User"].all(
            filters=[
                # MemcmpOpts for the User account discriminator
                MemcmpOpts(offset=0, bytes="TfwwBiNJtao"), 
                # MemcmpOpts for the authority pubkey
                MemcmpOpts(offset=8, bytes=bytes(authority_pk_arg))
            ]
        )
        
        if not user_accounts:
             logging.error(f"❌ Could not find any user accounts for authority {args.authority}")
             return
        
        logging.info(f"Found {len(user_accounts)} sub-account(s). Processing all of them.")
        
        total_fuel = {
            'insurance_fuel': 0, 
            'taker_fuel': 0, 
            'maker_fuel': 0, 
            'deposit_fuel': 0, 
            'borrow_fuel': 0, 
            'position_fuel': 0
        }

        for user_account_wrapper in user_accounts:
            user_data = user_account_wrapper.account
            
            logging.info(f"⚙️  Processing User Account PK: {user_account_wrapper.public_key} (Sub-ID: {user_data.sub_account_id})")

            try:
                # The get_fuel_bonus_for_user function is async and should be awaited.
                fuel_bonus = await get_fuel_bonus_for_user(
                    drift_client, 
                    user_account_wrapper.public_key, 
                    user_data.authority
                )

                if fuel_bonus:
                    logging.info(f"    ✅ Fuel bonus data: {fuel_bonus}")
                    for key, value in fuel_bonus.items():
                        if key in total_fuel:
                            total_fuel[key] += value
                else:
                    logging.warning(f"    ⚠️ Received no fuel bonus data for sub-account {user_data.sub_account_id}.")

            except Exception as e:
                logging.error(f"❌ An error occurred while processing sub-account {user_data.sub_account_id}: {e}", exc_info=True)

        logging.info("--------------------------------------------------")
        logging.info(f"✅ Finished processing all {len(user_accounts)} sub-accounts.")
        logging.info(f"Total Fuel for authority {authority_pk_arg}:")
        logging.info(f"{total_fuel}")
        logging.info("--------------------------------------------------")

    except Exception as e:
        logging.error(f"An unhandled error occurred: {e}", exc_info=True)
    finally:
        if is_initialized:
            await drift_client.unsubscribe()
            logging.info("✔️ Drift client unsubscribed.")
        if connection:
            await connection.close()
            logging.info("🔌 RPC connection closed.")
        logging.info("✨ Script finished.")

if __name__ == "__main__":
    asyncio.run(main()) 