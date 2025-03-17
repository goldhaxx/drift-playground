# the goal of this script is to connect to driftpy using driftpy-sdk and DriftClient

import os
import asyncio
from anchorpy import Wallet
from dotenv import load_dotenv
from driftpy.keypair import load_keypair
from driftpy.drift_client import DriftClient
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import UserMapConfig, PollingConfig
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair # type: ignore
import base58

load_dotenv()  # load environment variables from .env file

# Generate a random Solana keypair (wallet) for interaction with Drift
kp = Keypair()

public_key = kp.pubkey()

private_key = kp.secret()

print(f"Public Key: {public_key}")
print(f"Private Key: {private_key}")

# create a wallet from the keypair
wallet = Wallet(kp)

# get the rpc url from the environment variable
connection = AsyncClient(os.environ.get('RPC_URL'))

# create a drift client
drift_client = DriftClient(connection, wallet)

async def main():
    # Create a UserMap to fetch all user accounts
    user_map = UserMap(
        UserMapConfig(
            drift_client,
            PollingConfig(frequency=10000),  # Polling frequency in ms
            connection,
            include_idle=True,  # Include idle accounts
        )
    )

    # Sync the user map to fetch all accounts
    await user_map.sync()
    
    # Print the tail of user_map to terminal
    print("User Map Tail:")
    user_accounts = list(user_map.values())
    # Display the last 5 accounts or all if fewer than 5
    tail_count = min(5, len(user_accounts))
    for i in range(len(user_accounts) - tail_count, len(user_accounts)):
        print(f"Account {i+1}: {user_accounts[i]}")

# This is the entry point of the script. It ensures that the main() coroutine
# is only executed when the script is run directly (not when imported as a module).
if __name__ == "__main__":
    # asyncio.run() creates a new event loop, runs the main() coroutine until it completes,
    # and then closes the event loop.
    asyncio.run(main())