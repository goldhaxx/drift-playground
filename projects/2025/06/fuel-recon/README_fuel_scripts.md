# Drift Fuel Export Scripts

This directory contains two versions of scripts for exporting fuel data from Drift Protocol:

1. `get_all_UserStats_fuelOnly.py` - Original version that reads directly from UserStats accounts
2. `get_all_UserStats_fuelOnly_v2.py` - Enhanced version using `get_fuel_bonus()` method

## Key Differences

### Version 1 (Original)
- Reads fuel data directly from UserStats account fields
- Only captures **settled fuel** that's stored in the main UserStats account
- May miss overflow fuel data when fuel amounts exceed field capacity
- Faster but potentially incomplete

### Version 2 (Enhanced with Overflow Support)
- Uses the built-in `get_fuel_bonus()` method from DriftPy
- Captures **both settled and overflow fuel** automatically
- Handles edge cases where fuel amounts exceed UserStats field limits
- More comprehensive but may be slower due to additional computations

## Fuel Data Sources in Drift

The fuel system in Drift has two main components:

1. **Settled Fuel** - Stored directly in UserStats account fields
   - `fuel_insurance`
   - `fuel_deposits` 
   - `fuel_borrows`
   - `fuel_positions`
   - `fuel_taker`
   - `fuel_maker`

2. **Overflow Fuel** - Handled through a separate FuelOverflow account when values exceed limits

## Usage

Both scripts support the same command-line arguments:

```bash
# Using default RPC and output file
python get_all_UserStats_fuelOnly_v2.py

# Using custom RPC URL
python get_all_UserStats_fuelOnly_v2.py --rpc-url https://your-rpc-endpoint.com

# Specifying output filename
python get_all_UserStats_fuelOnly_v2.py --output my_fuel_export.csv

# Enable verbose logging
python get_all_UserStats_fuelOnly_v2.py --verbose
```

## Output Format

Both scripts produce CSV files with the following columns:

- `authority_address` - The wallet address that owns the account
- `user_stats_address` - The derived UserStats account address
- `fuel_insurance` - Insurance fuel points (decimal)
- `fuel_deposits` - Deposit fuel points (decimal) 
- `fuel_borrows` - Borrow fuel points (decimal)
- `fuel_positions` - Position fuel points (decimal)
- `fuel_taker` - Taker fuel points (decimal)
- `fuel_maker` - Maker fuel points (decimal)
- `last_fuel_update_ts` - Timestamp of last fuel update

**Note**: Version 2 automatically converts raw fuel values to decimal by dividing by QUOTE_PRECISION.

## Performance Considerations

- Version 1 is faster as it only reads UserStats accounts
- Version 2 may be slower as it:
  - Creates DriftUser instances for each account
  - Calculates unsettled fuel bonuses
  - Checks for overflow accounts
  
## Recommendations

- Use **Version 2** (`get_all_UserStats_fuelOnly_v2.py`) for:
  - Complete fuel data including overflow
  - Accuracy over speed
  - Production reporting
  
- Use **Version 1** (`get_all_UserStats_fuelOnly.py`) for:
  - Quick approximations
  - When overflow fuel is not a concern
  - Development/testing

## Environment Setup

Create a `.env` file with your RPC URL:

```
RPC_URL=https://your-solana-rpc-endpoint.com
```

Or pass it via command line:

```bash
python get_all_UserStats_fuelOnly_v2.py --rpc-url https://your-rpc-endpoint.com
```

## Dependencies

Both scripts require:
- driftpy
- solders
- anchorpy
- python-dotenv

Install with:
```bash
pip install driftpy solders anchorpy python-dotenv
``` 