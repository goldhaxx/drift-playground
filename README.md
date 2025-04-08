# Drift Protocol Position Viewer

This script allows you to view all positions for a given authority account on the Drift Protocol. It displays both perpetual and spot positions with detailed information including position sizes, values, entry prices, and PnL.

## Features

- Display positions for any Drift authority address
- Show multiple sub-accounts for the same authority
- View detailed account health, collateral, and leverage information
- Display perpetual positions with market details, entry price, current price, and PnL
- Display spot positions with deposit/borrow details and USD values
- Show LP (Liquidity Provider) shares if available
- **Cache on-chain data locally with VAT (vat of pickles)** to reduce RPC calls
- **Automatically use cached data if less than one hour old**

## Requirements

- Python 3.7 or higher
- Required Python packages (install using `pip install -r requirements.txt`):
  - driftpy
  - anchorpy
  - solders
  - solana
  - python-dotenv
  - base58
  - asyncio

## Installation

1. Clone or download this repository
2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your RPC URL (or use the command line argument):
   ```
   RPC_URL=https://your-rpc-endpoint.com
   ```

## Usage

```bash
python drift-positions.py <AUTHORITY_ADDRESS> [--rpc <RPC_URL>] [--force-refresh] [--pickle-dir <DIRECTORY>]
```

### Arguments

- `AUTHORITY_ADDRESS`: The Solana public key of the authority to query (required)
- `--rpc`: RPC URL to use (optional, will use RPC_URL from .env file if not provided)
- `--force-refresh`: Force fetch fresh data from RPC even if cached data is available (optional)
- `--pickle-dir`: Directory to store/load pickle files (default: "pickles")

### Example

```bash
# Basic usage (will use cached data if available and less than 1 hour old)
python drift-positions.py FULqR3GHUtHBxjhVHRSg7u1JXvBxQNPZGS9fnhqt8YEk

# Force fresh data from RPC
python drift-positions.py FULqR3GHUtHBxjhVHRSg7u1JXvBxQNPZGS9fnhqt8YEk --force-refresh

# Use a custom pickle directory
python drift-positions.py FULqR3GHUtHBxjhVHRSg7u1JXvBxQNPZGS9fnhqt8YEk --pickle-dir my_pickles
```

## How Caching Works

The script uses a "vat of pickles" (VAT) to store and load cached on-chain data:

1. On first run or when cached data is older than one hour, it:
   - Fetches fresh data from the RPC provider
   - Saves this data to timestamped pickle files in the pickle directory
   - Displays the positions based on this fresh data

2. On subsequent runs, it:
   - Checks for existing pickle files in the pickle directory
   - If valid pickle files are found that are less than one hour old, it loads them
   - Displays positions using the cached data instead of making RPC calls
   - Indicates in the output that cached data is being used

3. You can force a refresh of the data with the `--force-refresh` flag, which will:
   - Skip checking for cached data
   - Always fetch fresh data from the RPC provider
   - Create new pickle files with the fresh data

This approach significantly reduces the number of RPC calls made to the Solana network.

## Example Output

```
=== Positions for Authority: FULqR3GHUtHBxjhVHRSg7u1JXvBxQNPZGS9fnhqt8YEk ===
(Using cached data)
Number of Sub-Accounts: 2

=== Sub-Account 0 (ID: 0) ===

-- Account Summary --
Health: 100%
Total Collateral: $25,000.0000
Free Collateral: $23,450.2345
Leverage: 1.50x
Net Account Value: $24,987.1234

-- Perpetual Positions --

Market: SOL-PERP (Index: 1)
Type: Long
Size: 10.000000
Entry Price: $30.5000
Current Price: $32.6500
Value: $326.5000
Unrealized PnL: $21.5000
Funding PnL: $1.2500

Market: ETH-PERP (Index: 2)
Type: Short
Size: 1.500000
Entry Price: $2,505.0000
Current Price: $2,498.7500
Value: $3,748.1250
Unrealized PnL: $9.3750
Funding PnL: -$2.2500

-- Spot Positions --

Market: USDC (Index: 0)
Type: Deposit
Amount: 20,000.000000
Price: $1.0000
Value: $20,000.0000

Market: SOL (Index: 1)
Type: Deposit
Amount: 150.000000
Price: $32.6500
Value: $4,897.5000
```

## Notes

- Cached data is stored in the `pickles` directory by default (configurable via `--pickle-dir`)
- Each cache set is stored in a timestamp-named subdirectory (format: `vat-YYYY-MM-DD-HH-MM-SS`)
- If you have issues with the cached data, try running with `--force-refresh` to get fresh data
- The script uses a dummy wallet for reading data and doesn't require any signing capabilities

## License

MIT 