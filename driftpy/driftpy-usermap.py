# the goal of this script is to connect to driftpy using driftpy-sdk and DriftClient

import os
import asyncio
import inspect
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

# create a wallet from the keypair
wallet = Wallet(kp)

# get the rpc url from the environment variable
connection = AsyncClient(os.environ.get('RPC_URL'))

# create a drift client
drift_client = DriftClient(connection, wallet)

def get_object_attributes(obj, prefix=''):
    """Get all attributes of an object recursively"""
    attributes = []
    
    if obj is None:
        return attributes

    # Get all attributes of the object
    for attr_name in dir(obj):
        # Skip truly private attributes (double underscore) and special methods
        if attr_name.startswith('__'):
            continue
            
        try:
            attr_value = getattr(obj, attr_name)
            
            # Skip methods and built-in attributes
            if inspect.ismethod(attr_value) or inspect.isfunction(attr_value):
                continue
                
            # Create the full attribute path
            attr_path = f"{prefix}{attr_name}" if prefix else attr_name
            
            # Add the current attribute
            attributes.append(attr_path)
            
            # If this is a list and not empty, check the first item for nested attributes
            if isinstance(attr_value, list) and len(attr_value) > 0:
                first_item = attr_value[0]
                nested_attrs = get_object_attributes(first_item, f"{attr_path}.")
                attributes.extend(nested_attrs)
            
            # If this is an object with a 'data' attribute, inspect it
            elif hasattr(attr_value, 'data') and not isinstance(attr_value, (str, int, float, bool)):
                try:
                    data_attrs = get_object_attributes(attr_value.data, f"{attr_path}.")
                    attributes.extend(data_attrs)
                except:
                    pass
                    
        except Exception:
            # Skip attributes that can't be accessed
            continue
    
    return attributes

def get_user_attributes(user_account):
    """Get all available attributes for user accounts by inspecting the object"""
    all_attrs = get_object_attributes(user_account)
    
    # Try to get attributes from user data if available
    try:
        if hasattr(user_account, 'data'):
            all_attrs.extend(get_object_attributes(user_account.data))
    except:
        pass
    
    # Group attributes by their prefix
    grouped_attrs = {}
    for attr in all_attrs:
        # Determine the group based on the attribute name
        if '.' in attr:
            group = attr.split('.')[0]
        else:
            group = 'base'
            
        if group not in grouped_attrs:
            grouped_attrs[group] = []
        grouped_attrs[group].append(attr)
    
    # Sort attributes within each group
    for group in grouped_attrs:
        grouped_attrs[group].sort()
    
    return grouped_attrs

def format_attribute_value(obj, attr_path):
    """Format an attribute value for display"""
    parts = attr_path.split('.')
    current = obj
    
    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
        else:
            return f"{attr_path}: Attribute not found"
    
    # Handle different types of values
    if isinstance(current, list):
        if any(p in attr_path for p in ['positions', 'orders']):
            return f"{attr_path}: {len(current)} items"
        else:
            return f"{attr_path}: {current}"
    elif hasattr(current, '__class__'):
        if current.__class__.__name__ == 'Pubkey':
            return f"{attr_path}: {str(current)[:20]}..."
        else:
            return f"{attr_path}: {str(current)}"
    else:
        return f"{attr_path}: {str(current)}"

def select_attributes(all_attributes):
    """Allow the user to select which attributes to display"""
    print("\nAvailable attribute groups:")
    
    # Display grouped attributes
    for group_name, attrs in all_attributes.items():
        print(f"\n{group_name.upper()} Attributes:")
        for i, attr in enumerate(attrs, 1):
            print(f"{i}. {attr}")
    
    # Provide options for selection
    print("\nSelection options:")
    print("- Enter specific numbers separated by commas (e.g., '1,3,5')")
    print("- Enter 'all' to select all attributes")
    print("- Enter 'basic' for a basic set of common attributes")
    print("- Enter 'group:[name]' to select all attributes in a group (e.g., 'group:base')")
    
    # Get user selection
    selection = input("\nEnter your selection: ").strip().lower()
    
    selected_attrs = []
    if selection == 'all':
        for group in all_attributes.values():
            selected_attrs.extend(group)
    elif selection == 'basic':
        # Get a subset of common attributes from the available ones
        basic_attrs = []
        for group, attrs in all_attributes.items():
            if group == 'base':
                # Add important base attributes
                basic_attrs.extend([a for a in attrs if a in [
                    'authority', 'name', 'status', 'margin_mode',
                    'settled_perp_pnl', 'total_deposits', 'total_withdraws'
                ]])
            elif group in ['spot_positions', 'perp_positions', 'orders']:
                # Add the main collection attributes
                basic_attrs.append(group)
        selected_attrs = basic_attrs
    elif selection.startswith('group:'):
        # Select all attributes in a group
        group_name = selection.split(':')[1]
        if group_name in all_attributes:
            selected_attrs.extend(all_attributes[group_name])
    else:
        try:
            # Parse individual numbers for each group
            for group_attrs in all_attributes.values():
                for i, attr in enumerate(group_attrs, 1):
                    if str(i) in selection.split(','):
                        selected_attrs.append(attr)
        except:
            print("Invalid selection. Showing basic attributes.")
            return select_attributes('basic')
    
    return selected_attrs

def print_user_details(user, selected_attrs=None, all_attrs=None):
    """Print details for a user based on selected attributes"""
    print(f"\n=== User Account Details ===")
    
    # Get all available attributes by inspecting the user object if not provided
    if all_attrs is None:
        all_attrs = get_user_attributes(user)
    
    # If no attributes selected and no all_attrs provided, return without printing
    if selected_attrs is None:
        return
    
    # Display each selected attribute
    for attr in selected_attrs:
        print(format_attribute_value(user, attr))

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
    print("\nFetching User Accounts...")
    await user_map.sync()
    
    # Print the tail of user_map to terminal
    print("\nUser Map Tail:")
    user_accounts = list(user_map.values())
    # Display the last 5 accounts or all if fewer than 5
    tail_count = min(5, len(user_accounts))
    
    # Store selected attributes and all attributes for reuse
    selected_attrs = None
    all_attrs = None
    
    for i in range(len(user_accounts) - tail_count, len(user_accounts)):
        print(f"\nAccount {i+1}:")
        
        # Get all attributes from the first account if not already done
        if all_attrs is None:
            all_attrs = get_user_attributes(user_accounts[i])
        
        # Ask if user wants to reuse previous attribute selection
        if selected_attrs is not None:
            reuse = input("Do you want to use the same attributes as before? (y/n): ").strip().lower()
            if not reuse.startswith('y'):
                selected_attrs = None
        
        # Get attribute selection if needed
        if selected_attrs is None:
            selected_attrs = select_attributes(all_attrs)
        
        print_user_details(user_accounts[i], selected_attrs, all_attrs)

# This is the entry point of the script. It ensures that the main() coroutine
# is only executed when the script is run directly (not when imported as a module).
if __name__ == "__main__":
    # asyncio.run() creates a new event loop, runs the main() coroutine until it completes,
    # and then closes the event loop.
    asyncio.run(main())