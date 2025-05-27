#!/usr/bin/env python3

import csv
import argparse

def analyze_fuel_tiers(csv_filepath):
    """
    Analyzes a CSV file to count users in different FUEL point tiers.

    Args:
        csv_filepath (str): The path to the CSV file.
    """
    # Initialize counters for distinct tiers
    total_users_gte_1_fuel = 0
    users_lt_1_fuel = 0       # Tier: FUEL < 1
    users_1_to_5k = 0         # Tier: 1 <= FUEL <= 5,000
    users_5k_to_10k = 0       # Tier: 5,000 < FUEL <= 10,000
    users_10k_to_20k = 0      # Tier: 10,000 < FUEL <= 20,000
    users_gt_20k = 0          # Tier: FUEL > 20,000
    total_accounts_analyzed = 0 # New counter for total rows processed

    fuel_column_names = [
        "fuel_insurance",
        "fuel_deposits",
        "fuel_borrows",
        "fuel_positions",
        "fuel_taker",
        "fuel_maker",
    ]

    try:
        with open(csv_filepath, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Check if all required fuel columns are present in the CSV header
            if not all(col in reader.fieldnames for col in fuel_column_names):
                missing_cols = [col for col in fuel_column_names if col not in reader.fieldnames]
                print(f"Error: The CSV file '{csv_filepath}' is missing required fuel columns: {', '.join(missing_cols)}")
                print(f"Available columns in the CSV: {', '.join(reader.fieldnames or [])}")
                return

            for row_num, row in enumerate(reader):
                total_accounts_analyzed += 1 # Increment for each row processed
                current_row_total_fuel = 0
                try:
                    for col_name in fuel_column_names:
                        fuel_value_str = row.get(col_name, '0')
                        if fuel_value_str is None or fuel_value_str.strip() == '':
                            # Treat empty or None values as 0
                            fuel_value = 0
                        else:
                            # Convert to float first (to handle "0.0") then to int
                            fuel_value = int(float(fuel_value_str))
                        current_row_total_fuel += fuel_value
                except ValueError:
                    # This handles error for a specific column in the current row
                    print(f"Warning: Row {row_num + 2} (1-indexed data row) contains a non-numeric fuel value in one of the fuel columns. "
                          f"Skipping this value for this user's total fuel calculation. Problematic row data snippet for fuel columns: "
                          f"{{ {', '.join([f'{col}: {row.get(col)}' for col in fuel_column_names])} }}")
                    # The loop continues, and current_row_total_fuel will have the sum of successfully parsed values for this user.

                # Apply tiering logic based on the calculated total_fuel for the current user
                if current_row_total_fuel < 1:
                    users_lt_1_fuel += 1
                else: # current_row_total_fuel >= 1
                    total_users_gte_1_fuel += 1
                    # Assign to a distinct tier for users with >=1 FUEL
                    if current_row_total_fuel <= 5000: # Includes 1
                        users_1_to_5k += 1
                    elif current_row_total_fuel <= 10000:
                        users_5k_to_10k += 1
                    elif current_row_total_fuel <= 20000:
                        users_10k_to_20k += 1
                    else: # Implies > 20000
                        users_gt_20k += 1
                        
    except FileNotFoundError:
        print(f"Error: File not found at '{csv_filepath}'")
        return
    except Exception as e:
        print(f"An unexpected error occurred while processing the CSV file: {e}")
        import traceback
        traceback.print_exc()
        return

    # Calculate sum of distinct tier counts
    # This sum will now include all categorized users and should match total_accounts_analyzed
    sum_of_all_tier_counts = users_lt_1_fuel + users_1_to_5k + users_5k_to_10k + users_10k_to_20k + users_gt_20k

    # Print results
    print("\n--- FUEL Tier Analysis (Distinct Tiers) ---")
    print(f"Analyzed CSV File: {csv_filepath}")
    print(f"Total accounts analyzed: {total_accounts_analyzed}") 
    print("-------------------------------------------")
    print(f"Users with < 1 FUEL point:                    {users_lt_1_fuel}")
    print("-------------------------------------------")
    print(f"Breakdown for users with =>1 FUEL point (Total: {total_users_gte_1_fuel}):")
    print(f"  Users with 1 <= FUEL <= 5,000 points:       {users_1_to_5k}")
    print(f"  Users with 5,000 < FUEL <= 10,000 points:   {users_5k_to_10k}")
    print(f"  Users with 10,000 < FUEL <= 20,000 points:  {users_10k_to_20k}")
    print(f"  Users with > 20,000 FUEL points:              {users_gt_20k}")
    print("-------------------------------------------")
    print(f"Sum of accounts across all tiers:             {sum_of_all_tier_counts}") 
    print("  (This sum should equal 'Total accounts analyzed')")
    print("-------------------------------------------\n")


def main():
    """
    Main function to parse arguments and call the analysis function.
    """
    parser = argparse.ArgumentParser(
        description="Analyze FUEL point tiers from a UserStats CSV export.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "csv_filepath", 
        type=str, 
        help="Path to the CSV file to analyze (e.g., user_stats_export.csv)."
    )
    args = parser.parse_args()

    analyze_fuel_tiers(args.csv_filepath)

if __name__ == "__main__":
    main()
