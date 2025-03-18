# the goal of this script is to connect to driftpy using driftpy-sdk and DriftClient

import os
import asyncio
from anchorpy import Wallet
from dotenv import load_dotenv
from driftpy.keypair import load_keypair
from driftpy.drift_client import DriftClient
from driftpy.market_map.market_map import MarketMap
from driftpy.market_map.market_map_config import MarketMapConfig, WebsocketConfig
from driftpy.types import MarketType
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair # type: ignore
import base58

load_dotenv()  # load environment variables from .env file

# Generate a random Solana keypair (wallet) for interaction with Drift
kp = Keypair()

# create a wallet from the keypair
wallet = Wallet(kp)

# get the rpc url from the environment variable
connection = AsyncClient(os.environ.get('RPC_URL'))

# create a drift client
drift_client = DriftClient(connection, wallet)

async def main():
    # Create MarketMaps for both perpetual and spot markets
    perp_market_map = MarketMap(
        MarketMapConfig(
            drift_client.program,
            MarketType.Perp(),
            WebsocketConfig(resub_timeout_ms=10000),
            connection,
        )
    )

    spot_market_map = MarketMap(
        MarketMapConfig(
            drift_client.program,
            MarketType.Spot(),
            WebsocketConfig(resub_timeout_ms=10000),
            connection,
        )
    )

    # Pre-dump to fetch all markets
    print("\nFetching Perpetual Markets...")
    await perp_market_map.pre_dump()
    
    print("\nFetching Spot Markets...")
    await spot_market_map.pre_dump()
    
    # Print market information
    print("\nPerpetual Markets:")
    perp_markets = list(perp_market_map.values())
    for market in perp_markets:
        print(f"Market Index: {market.data.market_index}, Name: {bytes(market.data.name).decode('utf-8').strip()}")

    print("\nSpot Markets:")
    spot_markets = list(spot_market_map.values())
    for market in spot_markets:
        print(f"Market Index: {market.data.market_index}, Name: {bytes(market.data.name).decode('utf-8').strip()}")

# This is the entry point of the script. It ensures that the main() coroutine
# is only executed when the script is run directly (not when imported as a module).
if __name__ == "__main__":
    # asyncio.run() creates a new event loop, runs the main() coroutine until it completes,
    # and then closes the event loop.
    asyncio.run(main())