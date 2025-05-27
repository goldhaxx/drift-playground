#!/usr/bin/env python3

import argparse
import asyncio
import os
import json
from datetime import datetime

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

def format_user_stats(user_stats_data) -> dict:
    """
    Format UserStats data into a dictionary maintaining the original JSON structure
    """
    if not user_stats_data:
        return {}
    
    # Convert timestamps to readable format
    def format_timestamp(ts):
        if ts == 0:
            return 0
        try:
            return datetime.fromtimestamp(ts).isoformat()
        except:
            return ts
    
    # Helper function to safely get fee attributes
    def get_fee_value(fees_obj, attr_name, default=0):
        try:
            return getattr(fees_obj, attr_name, default) / 1e6
        except:
            return default / 1e6
    
    # Build the formatted dictionary based on the example structure
    formatted_data = {
        "authority": str(getattr(user_stats_data, 'authority', 'Unknown')),
        "referrer": str(getattr(user_stats_data, 'referrer', '11111111111111111111111111111111')),
        "fees": {},
        "nextEpochTs": getattr(user_stats_data, 'next_epoch_ts', 0),
        "maker30DVolume": getattr(user_stats_data, 'maker_volume30d', 0) / 1e9,  # Convert from base precision
        "taker30DVolume": getattr(user_stats_data, 'taker_volume30d', 0) / 1e9,
        "filler30DVolume": getattr(user_stats_data, 'filler_volume30d', 0) / 1e9,
        "lastMakerVolume30DTs": format_timestamp(getattr(user_stats_data, 'last_maker_volume30d_ts', 0)),
        "lastTakerVolume30DTs": format_timestamp(getattr(user_stats_data, 'last_taker_volume30d_ts', 0)),
        "lastFillerVolume30DTs": format_timestamp(getattr(user_stats_data, 'last_filler_volume30d_ts', 0)),
        "ifStakedQuoteAssetAmount": getattr(user_stats_data, 'if_staked_quote_asset_amount', 0) / 1e6,
        "numberOfSubAccounts": getattr(user_stats_data, 'number_of_sub_accounts', 0),
        "numberOfSubAccountsCreated": getattr(user_stats_data, 'number_of_sub_accounts_created', 0),
        "disableUpdatePerpBidAskTwap": getattr(user_stats_data, 'disable_update_perp_bid_ask_twap', False),
        "padding1": getattr(user_stats_data, 'padding1', 0),
        "fuelInsurance": getattr(user_stats_data, 'fuel_insurance', 0),
        "fuelDeposits": getattr(user_stats_data, 'fuel_deposits', 0),
        "fuelBorrows": getattr(user_stats_data, 'fuel_borrows', 0),
        "fuelPositions": getattr(user_stats_data, 'fuel_positions', 0),
        "fuelTaker": getattr(user_stats_data, 'fuel_taker', 0),
        "fuelMaker": getattr(user_stats_data, 'fuel_maker', 0),
        "ifStakedGovTokenAmount": getattr(user_stats_data, 'if_staked_gov_token_amount', 0),
        "lastFuelIfBonusUpdateTs": format_timestamp(getattr(user_stats_data, 'last_fuel_if_bonus_update_ts', 0)),
        "padding": getattr(user_stats_data, 'padding', [0] * 11)
    }
    
    # Try to populate fees object - handle different possible structures
    try:
        if hasattr(user_stats_data, 'fees'):
            fees = user_stats_data.fees
            formatted_data["fees"] = {
                "totalFeePaid": get_fee_value(fees, 'total_fee_paid'),
                "totalFeeRebate": get_fee_value(fees, 'total_fee_rebate'),
                "totalTokenDiscount": get_fee_value(fees, 'total_token_discount'),
                "totalRefereeDiscount": get_fee_value(fees, 'total_referee_discount'),
                "totalReferrerReward": get_fee_value(fees, 'total_referrer_reward'),
                "currentEpochReferrerReward": get_fee_value(fees, 'current_epoch_referrer_reward'),
            }
        else:
            # If fees is not a nested object, try direct attributes
            formatted_data["fees"] = {
                "totalFeePaid": getattr(user_stats_data, 'total_fee_paid', 0) / 1e6,
                "totalFeeRebate": getattr(user_stats_data, 'total_fee_rebate', 0) / 1e6,
                "totalTokenDiscount": getattr(user_stats_data, 'total_token_discount', 0) / 1e6,
                "totalRefereeDiscount": getattr(user_stats_data, 'total_referee_discount', 0) / 1e6,
                "totalReferrerReward": getattr(user_stats_data, 'total_referrer_reward', 0) / 1e6,
                "currentEpochReferrerReward": getattr(user_stats_data, 'current_epoch_referrer_reward', 0) / 1e6,
            }
    except Exception as e:
        print(f"Warning: Could not parse fees structure: {e}")
        formatted_data["fees"] = {
            "totalFeePaid": 0,
            "totalFeeRebate": 0,
            "totalTokenDiscount": 0,
            "totalRefereeDiscount": 0,
            "totalReferrerReward": 0,
            "currentEpochReferrerReward": 0,
        }
    
    # Check for is_referrer with different possible names
    is_referrer = False
    for attr_name in ['is_referrer', 'is_referee', 'isReferrer', 'isReferee', 'referrer_status']:
        if hasattr(user_stats_data, attr_name):
            value = getattr(user_stats_data, attr_name, False)
            # If it's referrer_status, check if it's not None or 0
            if attr_name == 'referrer_status':
                is_referrer = value is not None and value != 0
            else:
                is_referrer = bool(value)
            break
    formatted_data["isReferrer"] = is_referrer
    
    # Calculate total fuel
    total_fuel = (
        formatted_data["fuelInsurance"] + 
        formatted_data["fuelDeposits"] + 
        formatted_data["fuelBorrows"] + 
        formatted_data["fuelPositions"] + 
        formatted_data["fuelTaker"] + 
        formatted_data["fuelMaker"]
    )
    formatted_data["totalFuel"] = total_fuel
    
    return formatted_data

async def main():
    parser = argparse.ArgumentParser(description="Get full UserStats account data for a Drift authority or user account.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--authority", type=str, help="The authority public key (string).")
    group.add_argument("--account", type=str, help="The user account public key (string). If provided, the script will first derive the authority.")
    
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    load_dotenv()
    rpc_url = os.getenv("RPC_URL", DEFAULT_RPC_URL)
    parser.add_argument("--rpc-url", type=str, default=rpc_url, help=f"The Solana RPC URL (default: {rpc_url} or RPC_URL from .env).")
    parser.add_argument("--format", choices=["json", "pretty"], default="pretty", help="Output format (default: pretty)")

    args = parser.parse_args()

    connection = AsyncClient(args.rpc_url)
    # Use a dummy wallet as we are only reading data
    wallet = Wallet(Keypair()) 
    drift_client = DriftClient(
        connection,
        wallet,
        account_subscription=AccountSubscriptionConfig("cached")
    )

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
            # Fetch the user account to get the authority
            user_account_data = await drift_client.program.account['User'].fetch(account_pk)
            
            if user_account_data:
                authority_to_use = user_account_data.authority
                print(f"Derived authority: {authority_to_use} from account: {args.account}")
            else:
                print(f"Could not find user account data for account: {args.account}")
                return

        if authority_to_use:
            # Get the UserStats account public key
            user_stats_pk = get_user_stats_account_public_key(authority_to_use, drift_client.program_id)
            print(f"UserStats Account Public Key: {user_stats_pk}")
            
            # Fetch the UserStats account data
            print(f"Fetching UserStats account data...")
            user_stats_data = await drift_client.program.account['UserStats'].fetch(user_stats_pk)
            
            if user_stats_data:
                # Format the data
                formatted_data = format_user_stats(user_stats_data)
                
                if args.format == "json":
                    # Output as compact JSON
                    print(json.dumps(formatted_data))
                else:
                    # Pretty print with indentation
                    print("\n=== UserStats Account Data ===")
                    print(json.dumps(formatted_data, indent=2))
                    
                    # Add summary information
                    print("\n=== Summary ===")
                    print(f"Authority: {formatted_data['authority']}")
                    print(f"Number of Sub-Accounts: {formatted_data['numberOfSubAccounts']}")
                    print(f"Is Referrer: {formatted_data['isReferrer']}")
                    print(f"Total Fees Paid: ${formatted_data['fees']['totalFeePaid']:,.2f}")
                    print(f"30D Maker Volume: ${formatted_data['maker30DVolume']:,.0f}")
                    print(f"30D Taker Volume: ${formatted_data['taker30DVolume']:,.0f}")
                    print(f"Total FUEL Points: {formatted_data['totalFuel']:,.0f}")
                    if formatted_data['referrer'] != "11111111111111111111111111111111":
                        print(f"Referrer: {formatted_data['referrer']}")
            else:
                print(f"Could not find UserStats account data for authority: {authority_to_use}")
        else:
            print("No valid authority could be determined.")

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
