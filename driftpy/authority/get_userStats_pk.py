#!/usr/bin/env python3

import argparse
import asyncio
import os

from solders.pubkey import Pubkey  # type: ignore
from solders.keypair import Keypair # type: ignore
from anchorpy import Wallet
from driftpy.drift_client import DriftClient
from driftpy.account_subscription_config import AccountSubscriptionConfig
from solana.rpc.async_api import AsyncClient
from dotenv import load_dotenv

def get_user_stats_account_public_key(authority: Pubkey, program_id: Pubkey) -> Pubkey:
    """
    Derives the userStats account public key for a given authority.
    """
    user_stats_account_pk, _ = Pubkey.find_program_address(
        [b'user_stats', bytes(authority)],
        program_id
    )
    return user_stats_account_pk

async def main():
    parser = argparse.ArgumentParser(description="Get userStats account public key for a Drift authority or user account.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--authority", type=str, help="The authority public key (string).")
    group.add_argument("--account", type=str, help="The user account public key (string). If provided, the script will first derive the authority.")
    
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL (default: {rpc_url} or RPC_URL from .env).")

    args = parser.parse_args()

    connection = AsyncClient(args.rpc_url)
    # Use a dummy wallet as we are only reading data
    wallet = Wallet(Keypair()) 
    drift_client = DriftClient(
        connection,
        wallet,
        account_subscription=AccountSubscriptionConfig("cached") # or "polling" if updates are needed
    )
    # No need to subscribe the main client if only fetching specific accounts directly, 
    # but good practice if using other parts of DriftClient that expect it.
    # await drift_client.subscribe() 

    user_stats_pk = None
    authority_to_use = None

    try:
        if args.authority:
            print(f"Authority provided: {args.authority}")
            authority_to_use = Pubkey.from_string(args.authority)
        elif args.account:
            print(f"Account provided: {args.account}")
            account_pk = Pubkey.from_string(args.account)
            
            print(f"Fetching user account data for: {account_pk}...")
            # To fetch a specific user account, we might need to use the program directly
            # or ensure DriftUser is setup if get_user_account is on DriftUser.
            # The DriftClient itself doesn't have a direct get_user_account(pubkey) method.
            # Let's assume we need to fetch it via program.account['User'].fetch(account_pk)
            # or use a method that resolves a user account to its authority.

            # Based on documentation: "Viewing Other Users' Accounts"
            # You can also view account information for other users by creating a DriftUser instance with their public key
            # However, this requires knowing the sub_account_id if it's not the default.
            # A more direct way to get UserAccount data is:
            user_account_data = await drift_client.program.account['User'].fetch(account_pk)
            
            if user_account_data:
                authority_to_use = user_account_data.authority
                print(f"Derived authority: {authority_to_use} from account: {args.account}")
            else:
                print(f"Could not find user account data for account: {args.account}")
                return

        if authority_to_use:
            user_stats_pk = get_user_stats_account_public_key(authority_to_use, drift_client.program_id)
            print(f"UserStats Account Public Key for authority {authority_to_use}: {user_stats_pk}")
        else:
            if not args.authority and not args.account: # Should not happen due to mutually_exclusive_group
                 print("Please provide either --authority or --account.")
            # If authority_to_use is None and one of the args was provided, means an issue occurred.
            # Error messages would have been printed above.

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # if drift_client.is_subscribed: # Check before unsubscribing
        #     await drift_client.unsubscribe()
        await connection.close()
        # For DriftClient initialized with "cached", explicit unsubscribe might not be needed
        # or might throw error if not fully subscribed. 
        # Closing the connection is generally sufficient for simple scripts.


if __name__ == "__main__":
    asyncio.run(main())
