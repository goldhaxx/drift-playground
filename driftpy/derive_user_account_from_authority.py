#!/usr/bin/env python3
"""
Drift User Account Derivation Script

This script derives Drift user account public keys from a given authority address.
It demonstrates how to use the `get_user_account_public_key` function from the
driftpy SDK to generate sub-account addresses.

The script accepts an authority's public key and the number of user accounts
to derive as command-line arguments.

Usage:
    python derive_user_account_from_authority.py <AUTHORITY_PUBKEY> <NUM_ACCOUNTS> [--rpc <RPC_URL>]

Example:
    python derive_user_account_from_authority.py Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS 5

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
from driftpy.addresses import get_user_account_public_key

# Load environment variables from a .env file if present
load_dotenv()

def derive_user_accounts(program_id: Pubkey, authority: Pubkey, num_accounts: int) -> list[Pubkey]:
    """
    Derives a specified number of user account public keys for a given authority.

    Args:
        program_id: The public key of the Drift program.
        authority: The public key of the user's main wallet.
        num_accounts: The number of sub-accounts to derive.

    Returns:
        A list of derived user account public keys.
    """
    accounts = []
    for i in range(num_accounts):
        user_account_pubkey = get_user_account_public_key(
            program_id=program_id,
            authority=authority,
            sub_account_id=i
        )
        accounts.append(user_account_pubkey)
    return accounts

async def main():
    """
    Main function to parse arguments, set up the Drift client, and derive accounts.
    """
    parser = argparse.ArgumentParser(
        description="Derive Drift user account addresses from an authority public key.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Example usage:
  python derive_user_account_from_authority.py Bx11bA9p9q54cWg2F2P33n2123f11a4A1F9d11Ea1b 10
  python derive_user_account_from_authority.py Bx11bA9p9q54cWg2F2P33n2123f11a4A1F9d11Ea1b 5 --rpc https://api.mainnet-beta.solana.com
"""
    )
    parser.add_argument(
        "authority",
        type=str,
        help="The public key of the authority wallet."
    )
    parser.add_argument(
        "num_accounts",
        type=int,
        help="The number of user sub-accounts to derive (e.g., 5)."
    )
    parser.add_argument(
        "--rpc",
        help="RPC URL for the Solana cluster (defaults to RPC_URL env var)."
    )

    args = parser.parse_args()

    # --- Client Setup ---
    # Get RPC URL from arguments or environment variable
    rpc_url = args.rpc or os.environ.get("RPC_URL")
    if not rpc_url:
        print("Error: RPC URL is required. Set the RPC_URL environment variable or use the --rpc argument.", file=sys.stderr)
        return 1
    
    # We use a dummy keypair since we're only deriving addresses and not sending transactions.
    # The DriftClient requires a wallet for initialization.
    dummy_keypair = Keypair()
    wallet = Wallet(dummy_keypair)
    
    # Set up the connection to the Solana RPC node
    connection = AsyncClient(rpc_url)
    
    # Initialize the DriftClient. This is needed to get the program ID.
    # We don't need to subscribe to any accounts since address derivation is a local, offline operation.
    drift_client = DriftClient(connection, wallet)
    
    # --- Address Derivation ---
    try:
        authority_pubkey = Pubkey.from_string(args.authority)
    except Exception:
        print(f"Error: Invalid authority public key provided: '{args.authority}'", file=sys.stderr)
        await connection.close()
        return 1

    if args.num_accounts <= 0:
        print("Error: Number of accounts must be a positive integer.", file=sys.stderr)
        await connection.close()
        return 1
    
    print(f"Deriving {args.num_accounts} user account(s) for authority: {args.authority}\n")
    
    # The program ID is required for PDA derivation. We get it from the client instance.
    program_id = drift_client.program.program_id
    
    user_accounts = derive_user_accounts(program_id, authority_pubkey, args.num_accounts)
    
    for i, account_pubkey in enumerate(user_accounts):
        print(f"Sub-account ID {i}: {account_pubkey}")

    # --- Cleanup ---
    await connection.close()
    
    return 0

if __name__ == "__main__":
    # asyncio.run is used to execute the async main function
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(1)
