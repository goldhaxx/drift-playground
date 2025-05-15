import asyncio
import os

from anchorpy import Wallet
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient

from driftpy.drift_client import DriftClient
from driftpy.addresses import get_high_leverage_mode_config_public_key


async def main():
    load_dotenv()
    url = os.getenv("RPC_URL")
    if url is None:
        raise ValueError("RPC_URL environment variable not set.")
    connection = AsyncClient(url)
    
    wallet = Wallet.dummy() # Using a dummy wallet as we are only reading data
    
    dc = DriftClient(
        connection,
        wallet,
        "mainnet", # Assuming mainnet, can be configured if needed
    )
    # No need to call dc.subscribe() for this specific task as we are doing a one-time fetch

    high_leverage_mode_config_pda = get_high_leverage_mode_config_public_key(
        dc.program_id # Corrected to use dc.program_id
    )
    
    print(f"Fetching HighLeverageModeConfig account for PDA: {high_leverage_mode_config_pda}")

    try:
        config_account = await dc.program.account["HighLeverageModeConfig"].fetch(
            high_leverage_mode_config_pda
        )
        # The config_account object will have attributes corresponding to the fields in the account data.
        # For example, config_account.current_users (Python uses snake_case for attributes from camelCase IDL fields)
        current_high_leverage_users = config_account.current_users 
        max_allowed_users = config_account.max_users
        is_reduce_only_mode = config_account.reduce_only # This will likely be an integer (0 or 1)
        
        print(f"Successfully fetched account data.")
        print(f"Raw config_account data: {config_account}")
        print(f"Number of current high leverage users (on-chain): {current_high_leverage_users}")
        print(f"Maximum allowed high leverage users: {max_allowed_users}")
        print(f"Reduce only mode active (0 for false, 1 for true): {is_reduce_only_mode}")
        
        # Returning the primary piece of information, but others are printed.
        return current_high_leverage_users

    except Exception as e:
        print(f"Error fetching or parsing HighLeverageModeConfig account: {e}")
        return None
    finally:
        await dc.program.close()
        await connection.close()


if __name__ == "__main__":
    print("Attempting to fetch the number of high leverage users from on-chain data...")
    num_users = asyncio.run(main())
    if num_users is not None:
        print(f"Process finished. Found {num_users} high leverage users.")
    else:
        print("Process finished with an error.")
