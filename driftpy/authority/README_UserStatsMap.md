# UserStats Export Script

## Overview

`get_all_UserStats.py` is a script that uses the driftpy `UserStatsMap` to efficiently fetch and export all UserStats accounts from the Drift protocol to a CSV file.

## Key Differences from `get_UserStats.py`

- **Batch Processing**: Uses `UserStatsMap` to fetch all UserStats accounts in a single batch operation, rather than fetching individual accounts
- **Complete Export**: Exports data for ALL users on the protocol, not just a single user
- **CSV Output**: Data is exported in CSV format for easy analysis and processing
- **Raw Data Format**: Preserves data in its raw on-chain format (no precision adjustments for fuel points as requested)

## Usage

```bash
# Basic usage (exports to user_stats_export.csv)
python get_all_UserStats.py

# With custom RPC endpoint
python get_all_UserStats.py --rpc-url "https://your-rpc-endpoint.com"

# With custom output file
python get_all_UserStats.py --output my_export.csv

# With verbose output to see progress
python get_all_UserStats.py --verbose
```

## Command Line Arguments

- `--rpc-url`: Solana RPC URL (defaults to mainnet-beta or RPC_URL from .env file)
- `--output`: Output CSV filename (default: user_stats_export.csv)
- `--verbose`: Enable verbose output to see progress during export

## CSV Output Format

The CSV file contains the following columns in order:

1. **authority_address** - The authority wallet address
2. **user_stats_address** - The UserStats account public key
3. **authority** - Authority from the account data
4. **referrer** - Referrer address
5. **Fee data** (6 columns):
   - total_fee_paid
   - total_fee_rebate
   - total_token_discount
   - total_referee_discount
   - total_referrer_reward
   - current_epoch_referrer_reward
6. **Timestamps and volumes**:
   - next_epoch_ts
   - maker_volume30d
   - taker_volume30d
   - filler_volume30d
   - last_maker_volume30d_ts
   - last_taker_volume30d_ts
   - last_filler_volume30d_ts
7. **Account data**:
   - if_staked_quote_asset_amount
   - number_of_sub_accounts
   - number_of_sub_accounts_created
   - is_referrer (0 or 1)
   - disable_update_perp_bid_ask_twap
8. **Fuel points** (raw values, no precision adjustment):
   - fuel_insurance
   - fuel_deposits
   - fuel_borrows
   - fuel_positions
   - fuel_taker
   - fuel_maker
9. **Additional fields**:
   - if_staked_gov_token_amount
   - last_fuel_if_bonus_update_ts
10. **Padding fields** (padding_0 through padding_10)

## Example

```bash
# Export all UserStats with verbose output
python get_all_UserStats.py --verbose --output drift_users_2024.csv

# Output:
# Subscribing to Drift client...
# Creating UserStatsMap...
# Fetching all UserStats accounts... This may take a moment.
# Found 12345 UserStats accounts
# Processed 100 accounts...
# Processed 200 accounts...
# ...
# Export complete!
# Total UserStats accounts exported: 12345
# Output saved to: drift_users_2024.csv
```

## Performance Notes

- The script uses `UserStatsMap` which fetches all accounts in batches for efficiency
- Initial sync may take 30-60 seconds depending on the number of users and RPC performance
- Progress is shown every 100 accounts when using `--verbose` flag

## Error Handling

- Individual account processing errors are caught and logged without stopping the export
- Failed accounts will show an error message but the export will continue
- Network errors during the initial sync will cause the script to fail with a full error trace 