# the goal of this script is to show an implementation of the driftpy market map
# it will show all the markets and allow you to select one to inspect

import os
import asyncio
import inspect
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

def get_perp_market_attributes():
    """Get all available attributes for perpetual markets"""
    # Base attributes directly on PerpMarketAccount
    base_attrs = [
        "pubkey", "market_index", "name",
        "status", "contract_type", "contract_tier",
        "margin_ratio_initial", "margin_ratio_maintenance",
        "imf_factor", "unrealized_pnl_imf_factor", 
        "liquidator_fee", "if_liquidation_fee",
        "unrealized_pnl_initial_asset_weight", "unrealized_pnl_maintenance_asset_weight",
        "number_of_users", "number_of_users_with_base",
        "quote_spot_market_index", "fee_adjustment",
        "paused_operations", "expiry_ts", "expiry_price",
    ]
    
    # AMM attributes
    amm_attrs = [
        "amm.oracle", "amm.base_asset_reserve", "amm.quote_asset_reserve",
        "amm.sqrt_k", "amm.peg_multiplier", "amm.base_asset_amount_long",
        "amm.base_asset_amount_short", "amm.base_asset_amount_with_amm",
        "amm.last_funding_rate", "amm.last_funding_rate_ts", "amm.funding_period",
        "amm.order_step_size", "amm.order_tick_size", "amm.min_order_size",
        "amm.max_position_size", "amm.volume24h", "amm.oracle_source",
        "amm.last_oracle_valid", "amm.base_spread", "amm.max_spread",
    ]
    
    # Insurance claim attributes
    insurance_attrs = [
        "insurance_claim.quote_max_insurance", "insurance_claim.quote_settled_insurance",
    ]
    
    return base_attrs + amm_attrs + insurance_attrs

def get_spot_market_attributes():
    """Get all available attributes for spot markets"""
    # Base attributes directly on SpotMarketAccount
    base_attrs = [
        "pubkey", "oracle", "mint", "vault", "name", "market_index",
        "status", "asset_tier", "oracle_source", "decimals",
        "initial_asset_weight", "maintenance_asset_weight",
        "initial_liability_weight", "maintenance_liability_weight",
        "imf_factor", "liquidator_fee", "if_liquidation_fee",
        "deposit_balance", "borrow_balance", "total_spot_fee",
        "total_social_loss", "total_quote_social_loss",
        "withdraw_guard_threshold", "max_token_deposits",
        "order_step_size", "order_tick_size", "min_order_size", "max_position_size",
    ]
    
    # Interest rate attributes
    interest_attrs = [
        "optimal_utilization", "optimal_borrow_rate", "max_borrow_rate",
        "deposit_token_twap", "borrow_token_twap", "utilization_twap",
    ]
    
    # Historical oracle data attributes
    oracle_attrs = [
        "historical_oracle_data.last_oracle_price", 
        "historical_oracle_data.last_oracle_conf",
        "historical_oracle_data.last_oracle_price_twap",
    ]
    
    # Insurance fund attributes
    insurance_attrs = [
        "insurance_fund.total_shares", "insurance_fund.user_shares",
    ]
    
    return base_attrs + interest_attrs + oracle_attrs + insurance_attrs

def display_nested_attribute(obj, attr_path, indent=0):
    """Display a nested attribute value with proper formatting"""
    parts = attr_path.split('.')
    current = obj
    
    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
        else:
            return f"{' ' * indent}{attr_path}: Attribute not found"
    
    # Special handling for name attribute (regardless of how it's accessed)
    if attr_path.endswith('name') and isinstance(current, list) and len(current) > 0 and isinstance(current[0], int):
        return f"{' ' * indent}{attr_path}: {format_market_name(current)}"
    
    # Format the value based on its type
    if hasattr(current, '__class__'):
        # Special handling for Pubkey objects
        if current.__class__.__name__ == 'Pubkey':
            value = format_pubkey(str(current))
        # For other custom objects, display the class name
        elif current.__class__.__name__ not in ['int', 'str', 'float', 'bool']:
            try:
                # For enum types, display the class name
                value = current.__class__.__name__
            except:
                value = str(current)
        # For basic types, apply specific formatting based on attribute path
        elif isinstance(current, int) and 'price' in attr_path.lower():
            # For price values, format with decimals
            value = format_number(current)
        elif isinstance(current, int) and any(x in attr_path.lower() for x in ['reserve', 'balance', 'amount']):
            # For balance/reserve values, format with decimals
            value = format_number(current)
        elif isinstance(current, int) and any(x in attr_path.lower() for x in ['ratio', 'weight', 'factor']):
            # For ratio/weight values, format with fewer decimals
            value = format_number(current, 4)
        else:
            # Default string conversion for basic types
            value = str(current)
    elif isinstance(current, list) and len(current) > 0 and isinstance(current[0], int):
        # For byte arrays (like name), try to decode as UTF-8
        try:
            value = format_market_name(current)
        except:
            value = str(current)
    else:
        # Default formatting for other types
        value = str(current)
    
    return f"{' ' * indent}{attr_path}: {value}"

def select_attributes(all_attributes):
    """Allow the user to select which attributes to display"""
    print("\nAvailable attributes:")
    
    # Group attributes for easier selection
    groups = {}
    for i, attr in enumerate(all_attributes, 1):
        # Group by first part of the attribute path
        group_name = attr.split('.')[0] if '.' in attr else 'base'
        if group_name not in groups:
            groups[group_name] = []
        groups[group_name].append((i, attr))
    
    # Display grouped attributes
    for group_name, attrs in groups.items():
        print(f"\n{group_name.upper()} Attributes:")
        for i, attr in attrs:
            print(f"{i}. {attr}")
    
    # Provide options for selection
    print("\nSelection options:")
    print("- Enter specific numbers separated by commas (e.g., '1,3,5')")
    print("- Enter 'all' to select all attributes")
    print("- Enter 'basic' for a basic set of common attributes")
    print("- Enter 'group:[name]' to select all attributes in a group (e.g., 'group:amm')")
    
    # Get user selection
    selection = input("\nEnter your selection: ").strip().lower()
    
    if selection == 'all':
        return all_attributes
    
    if selection == 'basic':
        # Return a small set of basic attributes
        if 'market_index' in all_attributes:  # Checking if this is a spot or perp market
            basic_attrs = ["pubkey", "name", "market_index", "status"]
            if "amm.base_asset_reserve" in all_attributes:  # Perp market
                return basic_attrs + ["contract_type", "amm.base_asset_reserve", 
                                     "amm.quote_asset_reserve", "amm.oracle_source",
                                     "margin_ratio_initial", "margin_ratio_maintenance"]
            else:  # Spot market
                return basic_attrs + ["decimals", "asset_tier", "oracle_source", 
                                     "deposit_balance", "borrow_balance", 
                                     "initial_asset_weight", "maintenance_asset_weight"]
    
    if selection.startswith('group:'):
        # Select all attributes in a group
        group_name = selection.split(':')[1]
        selected_attrs = []
        for group, attrs in groups.items():
            if group.lower() == group_name:
                selected_attrs.extend([attr for _, attr in attrs])
        return selected_attrs
    
    # Parse individual numbers
    try:
        indices = [int(idx.strip()) for idx in selection.split(',')]
        return [all_attributes[i-1] for i in indices if 1 <= i <= len(all_attributes)]
    except:
        print("Invalid selection. Showing basic attributes.")
        return select_attributes('basic')

def print_market_details(market, is_perp, selected_attrs=None):
    """Print details for a market based on selected attributes"""
    market_type = "Perpetual" if is_perp else "Spot"
    print(f"\n=== {market_type} Market Details ===")
    
    # Get all available attributes
    all_attrs = get_perp_market_attributes() if is_perp else get_spot_market_attributes()
    
    # If no attributes selected, ask user to select
    if selected_attrs is None:
        selected_attrs = select_attributes(all_attrs)
    
    # Display each selected attribute
    for attr in selected_attrs:
        print(display_nested_attribute(market.data, attr))

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

    print("\nFetching Spot Markets...")
    await spot_market_map.pre_dump()

    # Pre-dump to fetch all markets
    print("\nFetching Perpetual Markets...")
    await perp_market_map.pre_dump()
    
    
    # Create a combined list of markets with their type and sort by market index
    spot_markets = list(spot_market_map.values())
    perp_markets = list(perp_market_map.values())
    
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

    # Track selected attributes for each market type
    perp_selected_attrs = None
    spot_selected_attrs = None

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
                        
                        # Ask if user wants to reuse previous attribute selection
                        reuse_attrs = False
                        current_attrs = None
                        
                        if is_perp and perp_selected_attrs:
                            reuse = input("Do you want to use the same attributes as before? (y/n): ").strip().lower()
                            reuse_attrs = reuse.startswith('y')
                            if reuse_attrs:
                                current_attrs = perp_selected_attrs
                                
                        elif not is_perp and spot_selected_attrs:
                            reuse = input("Do you want to use the same attributes as before? (y/n): ").strip().lower()
                            reuse_attrs = reuse.startswith('y')
                            if reuse_attrs:
                                current_attrs = spot_selected_attrs
                        
                        # If not reusing, select new attributes
                        if not reuse_attrs:
                            if is_perp:
                                perp_selected_attrs = select_attributes(get_perp_market_attributes())
                                current_attrs = perp_selected_attrs
                            else:
                                spot_selected_attrs = select_attributes(get_spot_market_attributes())
                                current_attrs = spot_selected_attrs
                        
                        # Print market details with selected attributes
                        print_market_details(market, is_perp, current_attrs)
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