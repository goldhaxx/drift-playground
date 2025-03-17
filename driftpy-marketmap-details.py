# the goal of this script is to connect to driftpy using driftpy-sdk and DriftClient

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

def print_perp_market_details(market):
    """Print detailed information about a perpetual market"""
    print("\n=== Perpetual Market Details ===")
    print(f"Name: {format_market_name(market.data.name)}")
    print(f"Market Index: {market.data.market_index}")
    print(f"Public Key: {format_pubkey(market.data.pubkey)}")
    
    # Market Status and Type
    print(f"\nStatus: {market.data.status.__class__.__name__}")
    print(f"Contract Type: {market.data.contract_type.__class__.__name__}")
    print(f"Contract Tier: {market.data.contract_tier.__class__.__name__}")
    
    # AMM Details
    print("\nAMM Configuration:")
    print(f"Base Asset Reserve: {format_number(market.data.amm.base_asset_reserve)}")
    print(f"Quote Asset Reserve: {format_number(market.data.amm.quote_asset_reserve)}")
    print(f"Sqrt K: {format_number(market.data.amm.sqrt_k)}")
    print(f"Peg Multiplier: {format_number(market.data.amm.peg_multiplier)}")
    print(f"Oracle Source: {market.data.amm.oracle_source.__class__.__name__}")
    
    # Risk Parameters
    print("\nRisk Parameters:")
    print(f"Initial Margin Ratio: {format_number(market.data.margin_ratio_initial, 4)}")
    print(f"Maintenance Margin Ratio: {format_number(market.data.margin_ratio_maintenance, 4)}")
    print(f"IMF Factor: {format_number(market.data.imf_factor, 4)}")
    
    # Market Stats
    print("\nMarket Statistics:")
    print(f"Number of Users: {market.data.number_of_users}")
    print(f"Number of Users with Base Asset: {market.data.number_of_users_with_base}")
    print(f"Quote Spot Market Index: {market.data.quote_spot_market_index}")

def print_spot_market_details(market):
    """Print detailed information about a spot market"""
    print("\n=== Spot Market Details ===")
    print(f"Name: {format_market_name(market.data.name)}")
    print(f"Market Index: {market.data.market_index}")
    print(f"Public Key: {format_pubkey(market.data.pubkey)}")
    
    # Market Status and Configuration
    print(f"\nStatus: {market.data.status.__class__.__name__}")
    print(f"Asset Tier: {market.data.asset_tier.__class__.__name__}")
    print(f"Oracle Source: {market.data.oracle_source.__class__.__name__}")
    print(f"Decimals: {market.data.decimals}")
    
    # Market Parameters
    print("\nMarket Parameters:")
    print(f"Initial Asset Weight: {format_number(market.data.initial_asset_weight, 4)}")
    print(f"Maintenance Asset Weight: {format_number(market.data.maintenance_asset_weight, 4)}")
    print(f"Initial Liability Weight: {format_number(market.data.initial_liability_weight, 4)}")
    print(f"Maintenance Liability Weight: {format_number(market.data.maintenance_liability_weight, 4)}")
    
    # Market Stats
    print("\nMarket Statistics:")
    print(f"Deposit Balance: {format_number(market.data.deposit_balance)}")
    print(f"Borrow Balance: {format_number(market.data.borrow_balance)}")
    print(f"Total Spot Fee: {format_number(market.data.total_spot_fee)}")
    
    # Interest Rates
    print("\nInterest Rate Configuration:")
    print(f"Optimal Utilization: {format_number(market.data.optimal_utilization, 4)}")
    print(f"Optimal Borrow Rate: {format_number(market.data.optimal_borrow_rate, 4)}")
    print(f"Max Borrow Rate: {format_number(market.data.max_borrow_rate, 4)}")

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
    
    # Create a combined list of markets with their type and sort by market index
    perp_markets = list(perp_market_map.values())
    spot_markets = list(spot_market_map.values())
    
    # Create separate lists for spot and perp markets
    spot_market_list = [(m.data.market_index, "S", m, False) for m in spot_markets]
    perp_market_list = [(m.data.market_index, "P", m, True) for m in perp_markets]
    
    # Sort each list by market index
    spot_market_list.sort(key=lambda x: x[0])
    perp_market_list.sort(key=lambda x: x[0])
    
    # Store combined list for selection logic
    all_markets = spot_market_list + perp_market_list
    
    # Print available markets
    print("\nAvailable Markets:")
    print("\nSpot Markets:")
    for market_index, prefix, market, _ in spot_market_list:
        print(f"{prefix}{market_index}. Name: {format_market_name(market.data.name)}")

    print("\nPerpetual Markets:")
    for market_index, prefix, market, _ in perp_market_list:
        print(f"{prefix}{market_index}. Name: {format_market_name(market.data.name)}")

    # Get user input for market selection
    while True:
        try:
            selection = input("\nEnter market ID (e.g., 'P0' or 'S1') to inspect (or 'exit' to quit): ").strip().upper()
            if selection == 'EXIT':
                break
                
            if not (selection.startswith('P') or selection.startswith('S')):
                print("Invalid input. Please use format 'P0' for perp markets or 'S1' for spot markets.")
                continue
                
            try:
                market_index = int(selection[1:])
                market_type = selection[0]
                
                # Find the market in our sorted list
                selected_market = None
                for _, prefix, market, is_perp in all_markets:
                    if prefix == market_type and market.data.market_index == market_index:
                        selected_market = market
                        if is_perp:
                            print_perp_market_details(market)
                        else:
                            print_spot_market_details(market)
                        break
                
                if selected_market is None:
                    print(f"Market {selection} not found.")
            except ValueError:
                print("Invalid market index. Please enter a valid number after P/S.")
                
        except Exception as e:
            print(f"Error: {str(e)}")
            break

# This is the entry point of the script. It ensures that the main() coroutine
# is only executed when the script is run directly (not when imported as a module).
if __name__ == "__main__":
    # asyncio.run() creates a new event loop, runs the main() coroutine until it completes,
    # and then closes the event loop.
    asyncio.run(main())