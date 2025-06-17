import asyncio
import os
import json

from anchorpy import Wallet
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient

from driftpy.drift_client import DriftClient
from driftpy.math.user_status import is_user_protected_maker
from driftpy.types import UserAccount
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import (
    UserMapConfig,
    WebsocketConfig as UserMapWebsocketConfig,
)
from solders.pubkey import Pubkey


def to_serializable(obj):
    """
    Recursively converts an object to a JSON serializable format.
    """
    if isinstance(obj, Pubkey):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return {
            key.strip("_"): to_serializable(value) for key, value in obj.__dict__.items()
        }
    elif isinstance(obj, list):
        return [to_serializable(item) for item in obj]
    elif isinstance(obj, bytes):
        try:
            return obj.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return str(obj)
    # Add handling for other non-serializable types here if needed
    return obj


async def main():
    load_dotenv()
    url = os.getenv("RPC_URL")
    if url is None:
        raise ValueError("RPC_URL environment variable not set.")
    connection = AsyncClient(url)

    wallet = Wallet.dummy()  # Using a dummy wallet as we are only reading data

    dc = DriftClient(
        connection,
        wallet,
        "mainnet",  # Assuming mainnet, can be configured if needed
    )
    await dc.subscribe()

    user_map = UserMap(UserMapConfig(dc, UserMapWebsocketConfig(), include_idle=True))
    
    print("Subscribing to UserMap... (this may take a moment)")
    await user_map.subscribe()
    print(f"UserMap subscribed. Found {len(user_map.user_map)} total users. Filtering for PMMs...")

    try:
        pmm_users = {}
        for pubkey, user in user_map.user_map.items():
            user_account = user.get_user_account()
            if is_user_protected_maker(user_account):
                pmm_users[pubkey] = to_serializable(user_account)

        print(f"Found {len(pmm_users)} protected maker users.")

        # Output the dictionary as a JSON string to the console
        print(json.dumps(pmm_users, indent=4))

        return pmm_users

    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    finally:
        await user_map.unsubscribe()
        await dc.unsubscribe()
        await connection.close()


if __name__ == "__main__":
    print("Attempting to fetch all protected market maker accounts using UserMap...")
    pmm_accounts = asyncio.run(main())
    if pmm_accounts is not None:
        print(
            f"Process finished. Found {len(pmm_accounts)} protected market maker accounts."
        )
    else:
        print("Process finished with an error.") 