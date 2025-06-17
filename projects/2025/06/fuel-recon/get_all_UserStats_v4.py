#!/usr/bin/env python3
"""
Production script to export all Drift Protocol UserStats accounts to CSV.
"""

import argparse
import asyncio
import csv
import logging
import os
from datetime import datetime

from anchorpy import Wallet
from driftpy.account_subscription_config import AccountSubscriptionConfig
from driftpy.drift_client import DriftClient
from driftpy.user_map.user_map_config import UserStatsMapConfig, SyncConfig
from driftpy.user_map.userstats_map import UserStatsMap
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair

# Configure logging
logger = logging.getLogger(__name__)


class UserStatsExporter:
    def __init__(self, rpc_url: str, output_file: str):
        self.rpc_url = rpc_url
        self.output_file = output_file
        self.connection = AsyncClient(rpc_url)
        self.drift_client = None
        self.user_stats_map = None

    async def initialize_drift_client(self):
        """Initialize DriftClient with minimal configuration for read-only operations."""
        dummy_keypair = Keypair()
        wallet = Wallet(dummy_keypair)

        self.drift_client = DriftClient(
            self.connection,
            wallet,
            "mainnet",
            account_subscription=AccountSubscriptionConfig("cached"),
        )

        await self.drift_client.subscribe()
        logger.info("DriftClient initialized successfully")

    async def initialize_user_stats_map(self, use_paginated: bool = True):
        """Initialize UserStatsMap with optimal configuration."""
        sync_config = SyncConfig(
            type="paginated" if use_paginated else "default",
            chunk_size=100,
            concurrency_limit=10,
        )

        config = UserStatsMapConfig(
            drift_client=self.drift_client,
            connection=self.connection,
            sync_config=sync_config,
        )

        self.user_stats_map = UserStatsMap(config)
        logger.info(
            f"UserStatsMap initialized with {'paginated' if use_paginated else 'default'} sync"
        )

    async def fetch_all_user_stats(self):
        """Fetch all UserStats accounts from the protocol."""
        logger.info("Starting to fetch all UserStats accounts...")

        try:
            await self.user_stats_map.subscribe()
            total_accounts = self.user_stats_map.size()
            logger.info(f"Successfully fetched {total_accounts} UserStats accounts")
            return total_accounts
        except Exception as e:
            logger.error(f"Error fetching UserStats accounts: {e}")
            raise

    def get_csv_headers(self):
        """Define CSV headers based on UserStatsAccount structure."""
        return [
            "authority",
            "user_stats_account_key",
            "referrer",
            "total_fee_paid",
            "total_fee_rebate",
            "total_token_discount",
            "total_referee_discount",
            "total_referrer_reward",
            "current_epoch_referrer_reward",
            "next_epoch_ts",
            "maker_volume_30d",
            "taker_volume_30d",
            "filler_volume_30d",
            "last_maker_volume_30d_ts",
            "last_taker_volume_30d_ts",
            "last_filler_volume_30d_ts",
            "if_staked_quote_asset_amount",
            "number_of_sub_accounts",
            "number_of_sub_accounts_created",
            "is_referrer",
            "disable_update_perp_bid_ask_twap",
            "fuel_overflow_status",
            "fuel_insurance",
            "fuel_deposits",
            "fuel_borrows",
            "fuel_positions",
            "fuel_taker",
            "fuel_maker",
            "if_staked_gov_token_amount",
            "last_fuel_if_bonus_update_ts",
        ]

    def extract_user_stats_data(self, user_stats_account, user_stats_pk):
        """Extract data from UserStatsAccount for CSV export."""
        fees = getattr(user_stats_account, "fees", None)

        return [
            str(getattr(user_stats_account, "authority", "")),
            str(user_stats_pk),
            str(getattr(user_stats_account, "referrer", "")),
            getattr(fees, "total_fee_paid", 0) if fees else 0,
            getattr(fees, "total_fee_rebate", 0) if fees else 0,
            getattr(fees, "total_token_discount", 0) if fees else 0,
            getattr(fees, "total_referee_discount", 0) if fees else 0,
            getattr(fees, "total_referrer_reward", 0) if fees else 0,
            getattr(fees, "current_epoch_referrer_reward", 0) if fees else 0,
            getattr(user_stats_account, "next_epoch_ts", 0),
            getattr(user_stats_account, "maker_volume_30d", 0),
            getattr(user_stats_account, "taker_volume_30d", 0),
            getattr(user_stats_account, "filler_volume_30d", 0),
            getattr(user_stats_account, "last_maker_volume_30d_ts", 0),
            getattr(user_stats_account, "last_taker_volume_30d_ts", 0),
            getattr(user_stats_account, "last_filler_volume_30d_ts", 0),
            getattr(user_stats_account, "if_staked_quote_asset_amount", 0),
            getattr(user_stats_account, "number_of_sub_accounts", 0),
            getattr(user_stats_account, "number_of_sub_accounts_created", 0),
            getattr(user_stats_account, "is_referrer", False),
            getattr(user_stats_account, "disable_update_perp_bid_ask_twap", False),
            getattr(user_stats_account, "fuel_overflow_status", 0),
            getattr(user_stats_account, "fuel_insurance", 0),
            getattr(user_stats_account, "fuel_deposits", 0),
            getattr(user_stats_account, "fuel_borrows", 0),
            getattr(user_stats_account, "fuel_positions", 0),
            getattr(user_stats_account, "fuel_taker", 0),
            getattr(user_stats_account, "fuel_maker", 0),
            getattr(user_stats_account, "if_staked_gov_token_amount", 0),
            getattr(user_stats_account, "last_fuel_if_bonus_update_ts", 0),
        ]

    async def export_to_csv(self):
        """Export all UserStats data to CSV file."""
        logger.info(f"Exporting data to {self.output_file}")

        try:
            with open(self.output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)

                headers = self.get_csv_headers()
                writer.writerow(headers)

                exported_count = 0
                for drift_user_stats in self.user_stats_map.values():
                    try:
                        user_stats_account = drift_user_stats.get_account()
                        user_stats_pk = drift_user_stats.user_stats_account_pubkey
                        row_data = self.extract_user_stats_data(
                            user_stats_account, user_stats_pk
                        )
                        writer.writerow(row_data)
                        exported_count += 1

                        if exported_count % 1000 == 0:
                            logger.info(f"Exported {exported_count} records...")

                    except Exception as e:
                        logger.warning(
                            f"Error processing user stats for {drift_user_stats.user_stats_account_pubkey}: {e}"
                        )
                        continue

                logger.info(
                    f"Successfully exported {exported_count} UserStats accounts to {self.output_file}"
                )
                return exported_count

        except Exception as e:
            logger.error(f"Error writing to CSV file: {e}")
            raise

    async def cleanup(self):
        """Clean up resources."""
        if self.user_stats_map:
            self.user_stats_map.unsubscribe()
        if self.drift_client:
            await self.drift_client.unsubscribe()
        await self.connection.close()
        logger.info("Cleanup completed")

    async def run(self):
        """Main execution method."""
        try:
            logger.info("🚀 Starting Drift UserStats export process...")

            await self.initialize_drift_client()
            await self.initialize_user_stats_map(use_paginated=True)

            total_accounts = await self.fetch_all_user_stats()

            exported_count = await self.export_to_csv()

            logger.info("✅ Export completed successfully!")
            logger.info(f"Total accounts found: {total_accounts}")
            logger.info(f"Records exported: {exported_count}")
            logger.info(f"Output file: {self.output_file}")

        except Exception as e:
            logger.error(f"Export failed: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export all Drift Protocol UserStats accounts to CSV."
    )

    timestamp = datetime.now().strftime("%m%d%Y%H%M%S")
    default_filename = f"{timestamp}_user_stats_full_export.csv"

    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)

    parser.add_argument(
        "--rpc-url",
        type=str,
        default=rpc_url,
        help=f"The Solana RPC URL (default: loaded from .env or {DEFAULT_RPC_URL}).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=default_filename,
        help=f"Output CSV filename (default: {default_filename})",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose (DEBUG level) logging."
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(f"Using RPC URL: {args.rpc_url}")
    logger.info(f"Output file: {args.output}")

    exporter = UserStatsExporter(rpc_url=args.rpc_url, output_file=args.output)
    await exporter.run()


if __name__ == "__main__":
    asyncio.run(main()) 