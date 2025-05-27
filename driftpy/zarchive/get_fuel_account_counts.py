#!/usr/bin/env python3

import asyncio
import os
import time
from solders.pubkey import Pubkey # type: ignore
from solders.keypair import Keypair # type: ignore

from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.user_map.user_map import UserMap, UserMapConfig
from driftpy.user_map.user_map_config import PollingConfig 
from driftpy.constants.numeric_constants import QUOTE_PRECISION, FUEL_START_TS # Added FUEL_START_TS
from driftpy.types import UserAccount # For type hint
from driftpy.drift_user_stats import DriftUserStats, UserStatsSubscriptionConfig # Corrected: UserStatsSubscriptionConfig added here
# from driftpy.addresses import get_user_stats_account_public_key # This function might not exist with this name/path

from solana.rpc.async_api import AsyncClient
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
RPC_ENDPOINT = os.environ.get('RPC_URL')
# DRIFT_PROGRAM_ID is defined globally; ensure drift_client.program_id is correctly accessed if needed for PDA
PROGRAM_ID = Pubkey.from_string("dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH") 

async def get_fuel_data_breakdown():
    logger.info("Starting FUEL data acquisition...")

    if not RPC_ENDPOINT:
        logger.error("RPC_URL environment variable is not set. Please set it in your .env file or environment.")
        print("Error: RPC_URL environment variable is not set. Update your .env file or environment.")
        return None

    wallet = Keypair() 
    connection = AsyncClient(RPC_ENDPOINT)

    # Pass program_id explicitly if required by the constructor version, otherwise it uses a default
    # For the version that caused 'unexpected keyword argument program_id', we omit it.
    # If program_id is needed for Pubkey.find_program_address, ensure drift_client.program_id is valid.
    drift_client = DriftClient(
        connection,
        wallet,
        account_subscription=AccountSubscriptionConfig("websocket", commitment="confirmed"),
        active_sub_account_id=0
        # program_id = PROGRAM_ID, # Add back if constructor accepts it and it's not defaulting correctly
    )
    logger.info("Initializing DriftClient...")
    await drift_client.subscribe()
    logger.info(f"DriftClient subscribed. Program ID used by client: {drift_client.program_id}")


    user_map_config = UserMapConfig(
        drift_client=drift_client,
        subscription_config=PollingConfig(frequency=60000), # Polling for UserMap
        connection=connection,
        skip_initial_load=False, 
        include_idle=True 
    )
    user_map = UserMap(user_map_config)
    
    logger.info("Subscribing to UserMap and loading initial user data... This may take a while.")
    await user_map.subscribe()
    logger.info(f"UserMap subscribed. Initial user count from UserMap's internal map: {len(user_map.user_map)}")

    fuel_counts = {
        "gt_1_fuel": 0, "lt_20k_fuel": 0, "lt_10k_fuel": 0, "lt_5k_fuel": 0,
        "total_users_with_fuel_data": 0, "total_users_processed_from_usermap": 0,
        "users_with_zero_total_fuel": 0, "user_stats_fetch_errors": 0,
        "last_fuel_ts_errors": 0
    }

    authorities_in_usermap = list(user_map.user_map.keys())
    total_authorities_to_process = len(authorities_in_usermap)
    logger.info(f"Attempting to process {total_authorities_to_process} users from UserMap.")

    if total_authorities_to_process == 0:
        logger.warning("No users found in UserMap. Exiting processing.")
        await connection.close()
        await drift_client.unsubscribe()
        await user_map.unsubscribe()
        return fuel_counts

    original_get_user_stats = drift_client.get_user_stats # Store original method

    for i, authority_pk_str in enumerate(authorities_in_usermap):
        fuel_counts["total_users_processed_from_usermap"] += 1
        
        if (i + 1) % 100 == 0: # Log progress more frequently due to potential slowness
            logger.info(f"Processing user {i+1}/{total_authorities_to_process} (Authority: {authority_pk_str}). Success: {fuel_counts['total_users_with_fuel_data']}, StatsErrors: {fuel_counts['user_stats_fetch_errors']}, TS_Errors: {fuel_counts['last_fuel_ts_errors']}")

        temp_user_stats_instance = None # For finally block
        try:
            map_user_object = user_map.get(authority_pk_str) 

            if not map_user_object:
                logger.debug(f"User {authority_pk_str} not found in UserMap. Skipping.")
                continue
            
            if hasattr(map_user_object, 'is_loaded') and not map_user_object.is_loaded():
                logger.debug(f"User object for {authority_pk_str} exists but is not loaded. Skipping.")
                continue
            
            # map_user_object is a DriftUser instance
            user_account = map_user_object.get_user_account() # This is DriftUser.get_user_account()
            if not user_account:
                logger.warning(f"Could not get UserAccount for {authority_pk_str}. Skipping.")
                continue
            
            authority_pubkey = user_account.authority

            # Derive UserStatsAccount public key
            user_stats_account_pk, _ = Pubkey.find_program_address(
                [b'user_stats', bytes(authority_pubkey)],
                drift_client.program_id # Use the client's actual program_id
            )

            # Create and subscribe to a temporary, user-specific DriftUserStats
            # Using "polling" to ensure it attempts to fetch if not cached by this specific instance
            temp_user_stats_instance = DriftUserStats(
                drift_client, 
                user_stats_account_pk, 
                UserStatsSubscriptionConfig(type="polling", commitment="confirmed") # Corrected: type="polling"
            )
            await temp_user_stats_instance.subscribe() # This should also fetch the data

            # Monkey-patch drift_client.get_user_stats
            def patched_get_user_stats_method():
                return temp_user_stats_instance
            
            drift_client.get_user_stats = patched_get_user_stats_method
            
            current_timestamp = int(time.time())
            # Now call get_fuel_bonus with both settled and unsettled true
            fuel_bonus_update = await map_user_object.get_fuel_bonus(
                current_timestamp, 
                include_settled=True, 
                include_unsettled=True
            )
            
            if fuel_bonus_update is None:
                logger.debug(f"No FUEL bonus data for user {authority_pk_str} even with patch. Skipping.")
                continue
            
            fuel_counts["total_users_with_fuel_data"] += 1

            total_fuel_raw = sum(fuel_bonus_update.get(k, 0) for k in [
                "insurance_fuel", "taker_fuel", "maker_fuel", 
                "deposit_fuel", "borrow_fuel", "position_fuel"
            ])
            
            total_fuel = total_fuel_raw / QUOTE_PRECISION 

            if total_fuel == 0:
                fuel_counts["users_with_zero_total_fuel"] += 1
            if total_fuel > 1:
                fuel_counts["gt_1_fuel"] += 1
            if total_fuel < 5000:
                fuel_counts["lt_5k_fuel"] += 1
            if total_fuel < 10000:
                fuel_counts["lt_10k_fuel"] += 1
            if total_fuel < 20000:
                fuel_counts["lt_20k_fuel"] += 1

        except AttributeError as ae:
            if 'last_fuel_bonus_update_ts' in str(ae):
                logger.warning(f"AttributeError (likely missing 'last_fuel_bonus_update_ts' on UserAccount) for user {authority_pk_str}: {ae}")
                fuel_counts["last_fuel_ts_errors"] += 1
            elif "'NoneType' object has no attribute 'data'" in str(ae) or \
                 "'NoneType' object has no attribute 'fuel_taker'" in str(ae): # More specific to user_stats issues
                logger.warning(f"AttributeError (likely UserStats not found/loaded) for user {authority_pk_str}: {ae}")
                fuel_counts["user_stats_fetch_errors"] += 1
            else:
                logger.error(f"Unhandled AttributeError for user {authority_pk_str}: {ae}", exc_info=True)
        except Exception as e:
            logger.error(f"Generic error processing user {authority_pk_str}: {e}", exc_info=True)
        finally:
            drift_client.get_user_stats = original_get_user_stats # CRITICAL: Restore original method
            if temp_user_stats_instance:
                try:
                    await temp_user_stats_instance.unsubscribe()
                except Exception as unsub_e:
                    logger.debug(f"Error unsubscribing temp_user_stats for {authority_pk_str}: {unsub_e}")


    logger.info("Cleaning up resources...")
    await connection.close()
    await drift_client.unsubscribe() 
    await user_map.unsubscribe()
    logger.info("Cleanup complete.")

    return fuel_counts

async def main():
    logger.info("--- Drift FUEL Data Analysis Script ---")
    results = await get_fuel_data_breakdown()
    if results:
        print("\\n--- FUEL Data Breakdown ---")
        print(f"Total unique authorities processed from UserMap: {results['total_users_processed_from_usermap']}")
        print(f"Total users for whom FUEL data was successfully calculated: {results['total_users_with_fuel_data']}")
        print(f"Users with UserStats fetch/load issues: {results['user_stats_fetch_errors']}")
        print(f"Users with missing 'last_fuel_bonus_update_ts' on UserAccount: {results['last_fuel_ts_errors']}")
        print(f"Number of users with exactly 0 total FUEL points (among successfully calculated): {results['users_with_zero_total_fuel']}")
        print("---------------------------")
        print(f"Total number of users with >1 FUEL point: {results['gt_1_fuel']}")
        print(f"Number of users with <20K FUEL: {results['lt_20k_fuel']}")
        print(f"Number of users with <10K FUEL: {results['lt_10k_fuel']}")
        print(f"Number of users with <5K FUEL: {results['lt_5k_fuel']}")
        print("---------------------------\\n")
    else:
        print("Could not retrieve FUEL data. Check logs and RPC_URL configuration.")

if __name__ == '__main__':
    asyncio.run(main())
