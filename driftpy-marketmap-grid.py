# the goal of this script is to show an implementation of the driftpy market map
# it will show all the markets in tabular format

import os
import asyncio
from anchorpy import Wallet
from dotenv import load_dotenv
from driftpy.keypair import load_keypair
from driftpy.drift_client import DriftClient
from driftpy.market_map.market_map import MarketMap
from driftpy.market_map.market_map_config import MarketMapConfig, WebsocketConfig
from driftpy.types import MarketType, ContractType, ContractTier, MarketStatus, OracleSource, AssetTier
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair # type: ignore
import base58
from tabulate import tabulate  # Added for table formatting

load_dotenv()  # load environment variables from .env file

# Generate a random Solana keypair (wallet) for interaction with Drift
kp = Keypair()

# create a wallet from the keypair
wallet = Wallet(kp)

# get the rpc url from the environment variable
connection = AsyncClient(os.environ.get('RPC_URL'))

# create a drift client
drift_client = DriftClient(connection, wallet)

def format_market_name(name_bytes):
    """Convert market name bytes to string"""
    return bytes(name_bytes).decode('utf-8').strip()

def format_pubkey(pubkey):
    """Format pubkey for display"""
    return str(pubkey)[:20] + "..."

def format_number(number, decimals=6):
    """Format large numbers for better readability"""
    return f"{number / (10 ** decimals):,.6f}"

def get_perp_market_data(market):
    """Extract relevant data from perpetual market for tabular display"""
    return {
        'Market Index': f"P{market.data.market_index}",
        'Name': format_market_name(market.data.name),
        'Status': market.data.status.__class__.__name__,
        'Contract Type': market.data.contract_type.__class__.__name__,
        'Contract Tier': market.data.contract_tier.__class__.__name__,
        'Base Asset Reserve': format_number(market.data.amm.base_asset_reserve),
        'Quote Asset Reserve': format_number(market.data.amm.quote_asset_reserve),
        'Sqrt K': format_number(market.data.amm.sqrt_k),
        'Peg Multiplier': format_number(market.data.amm.peg_multiplier),
        'Oracle Source': market.data.amm.oracle_source.__class__.__name__,
        'Initial Margin Ratio': format_number(market.data.margin_ratio_initial, 4),
        'Maintenance Margin Ratio': format_number(market.data.margin_ratio_maintenance, 4),
        'IMF Factor': format_number(market.data.imf_factor, 4),
        'Number of Users': market.data.number_of_users,
        'Users with Base Asset': market.data.number_of_users_with_base,
        'Quote Spot Market Index': market.data.quote_spot_market_index,
        'Public Key': format_pubkey(market.data.pubkey),
    }

def get_spot_market_data(market):
    """Extract relevant data from spot market for tabular display"""
    return {
        'Market Index': f"S{market.data.market_index}",
        'Name': format_market_name(market.data.name),
        'Status': market.data.status.__class__.__name__,
        'Asset Tier': market.data.asset_tier.__class__.__name__,
        'Oracle Source': market.data.oracle_source.__class__.__name__,
        'Decimals': market.data.decimals,
        'Initial Asset Weight': format_number(market.data.initial_asset_weight, 4),
        'Maintenance Asset Weight': format_number(market.data.maintenance_asset_weight, 4),
        'Initial Liability Weight': format_number(market.data.initial_liability_weight, 4),
        'Maintenance Liability Weight': format_number(market.data.maintenance_liability_weight, 4),
        'Deposit Balance': format_number(market.data.deposit_balance),
        'Borrow Balance': format_number(market.data.borrow_balance),
        'Total Spot Fee': format_number(market.data.total_spot_fee),
        'Optimal Utilization': format_number(market.data.optimal_utilization, 4),
        'Optimal Borrow Rate': format_number(market.data.optimal_borrow_rate, 4),
        'Max Borrow Rate': format_number(market.data.max_borrow_rate, 4),
        'Public Key': format_pubkey(market.data.pubkey),
    }

async def main():
    print("Loading market data...")
    
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

    # Fetch all markets
    print("Fetching Spot Markets...")
    await spot_market_map.pre_dump()

    print("Fetching Perpetual Markets...")
    await perp_market_map.pre_dump()
    
    # Get spot market data
    spot_markets = list(spot_market_map.values())
    spot_markets.sort(key=lambda m: m.data.market_index)
    spot_market_data = [get_spot_market_data(market) for market in spot_markets]
    
    # Get perpetual market data
    perp_markets = list(perp_market_map.values())
    perp_markets.sort(key=lambda m: m.data.market_index)
    perp_market_data = [get_perp_market_data(market) for market in perp_markets]
    
    # Display spot markets table
    if spot_market_data:
        print("\n=== SPOT MARKETS ===")
        # Get all keys from the first entry to use as headers
        headers = list(spot_market_data[0].keys())
        # Create a list of lists for the table data
        table_data = [[market_data[key] for key in headers] for market_data in spot_market_data]
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        print("\nNo spot markets found.")
    
    # Display perpetual markets table
    if perp_market_data:
        print("\n=== PERPETUAL MARKETS ===")
        # Get all keys from the first entry to use as headers
        headers = list(perp_market_data[0].keys())
        # Create a list of lists for the table data
        table_data = [[market_data[key] for key in headers] for market_data in perp_market_data]
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        print("\nNo perpetual markets found.")

# This is the entry point of the script. It ensures that the main() coroutine
# is only executed when the script is run directly (not when imported as a module).
if __name__ == "__main__":
    # asyncio.run() creates a new event loop, runs the main() coroutine until it completes,
    # and then closes the event loop.
    asyncio.run(main())