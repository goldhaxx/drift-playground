#!/usr/bin/env python3
"""
Drift Authority Derivation Script

This script retrieves the authority public key for a given Drift user account address.
Unlike deriving a user account from an authority (a one-way process), this script
works by fetching the user account's on-chain data, where the authority is
stored as a field.

This approach is best for single, ad-hoc lookups. For applications requiring
bulk lookups or real-time monitoring, using the UserMap would be more efficient.

Usage:
    python derive_authority_from_user_account.py <USER_ACCOUNT_PUBKEY> [--rpc <RPC_URL>]

Example:
    python derive_authority_from_user_account.py 5wDD59a3iRd2aP2e3n4r5s6t7u8v9w0x1y2z3a4b5c6d7e8f9g0h1i2j3k4l5m6n7o8p

Requirements:
    - Python 3.7+
    - driftpy
    - anchorpy
    - solders
    - solana
    - python-dotenv
"""

import os
import sys
import asyncio
import argparse
from dotenv import load_dotenv

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from anchorpy import Wallet
from solana.rpc.async_api import AsyncClient
from driftpy.drift_client import DriftClient
from driftpy.accounts.get_accounts import get_user_account
from driftpy.types import UserAccount

# Load environment variables from a .env file if present
load_dotenv()

async def get_authority_from_user_account(client: DriftClient, user_account_pubkey: Pubkey) -> Pubkey | None:
    """
    Fetches the user account data from the blockchain and returns its authority.

    Args:
        client: An initialized DriftClient instance.
        user_account_pubkey: The public key of the user account to look up.

    Returns:
        The authority public key, or None if the account is not found or an error occurs.
    """
    try:
        user_account: UserAccount = await get_user_account(client.program, user_account_pubkey)
        return user_account.authority
    except Exception as e:
        print(f"Error fetching account data for {user_account_pubkey}: {e}", file=sys.stderr)
        return None

async def main():
    """
    Main function to parse arguments, set up the Drift client, and find the authority.
    """
    parser = argparse.ArgumentParser(
        description="Retrieve the authority for a given Drift user account address.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example usage:
  python derive_authority_from_user_account.py HnxVcr2tftdZfSgZqAnr5sV1d1d8Z4wX9Y3Z5d6c8b2a
  python derive_authority_from_user_account.py HnxVcr2tftdZfSgZqAnr5sV1d1d8Z4wX9Y3Z5d6c8b2a --rpc https://api.mainnet-beta.solana.com
"""
    )
    parser.add_argument(
        "user_account",
        type=str,
        help="The public key of the user account."
    )
    parser.add_argument(
        "--rpc",
        help="RPC URL for the Solana cluster (defaults to RPC_URL env var)."
    )

    args = parser.parse_args()

    # --- Client Setup ---
    rpc_url = args.rpc or os.environ.get("RPC_URL")
    if not rpc_url:
        print("Error: RPC URL is required. Set the RPC_URL environment variable or use the --rpc argument.", file=sys.stderr)
        return 1

    dummy_keypair = Keypair()
    wallet = Wallet(dummy_keypair)
    connection = AsyncClient(rpc_url)
    drift_client = DriftClient(connection, wallet)

    # --- Authority Lookup ---
    try:
        user_account_pubkey = Pubkey.from_string(args.user_account)
    except Exception:
        print(f"Error: Invalid user account public key provided: '{args.user_account}'", file=sys.stderr)
        await connection.close()
        return 1

    print(f"Attempting to find authority for user account: {user_account_pubkey}\n")

    authority_pubkey = await get_authority_from_user_account(drift_client, user_account_pubkey)

    if authority_pubkey:
        print(f"Successfully found authority:")
        print(f"  -> {authority_pubkey}")
    else:
        print("Could not determine the authority. The user account may not exist or there was a network issue.")
        await connection.close()
        return 1
        
    # --- Cleanup ---
    await connection.close()
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(1)
