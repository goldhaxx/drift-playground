import pandas as pd
import numpy as np
from datetime import datetime

def compare_snapshots():
    """
    Compares total fuel for each authority from two different snapshots and generates a report.
    """
    # Define file paths relative to the script location
    file1_path = 'complete_snapshot.csv'
    # The excel file is in the root of the project
    file2_path = '06122025140049_user_stats_fuel_export.csv'
    
    # Generate timestamp for the output file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = f'comparison_report_{timestamp}.csv'

    # --- Load Data ---
    try:
        df1 = pd.read_csv(file1_path)
        df2 = pd.read_csv(file2_path)
    except FileNotFoundError as e:
        print(f"Error loading files: {e}")
        print("Please ensure 'complete_snapshot.csv' is in the same directory as the script,")
        print("and '06122025140049_user_stats_fuel_export.xlsx' is in the project root.")
        return

    # --- Data Preparation ---

    # Prepare DataFrame 1
    # Sanitize column headers to remove any leading/trailing whitespace
    df1.columns = df1.columns.str.strip()

    # Create new, clean boolean columns for filtering, leaving original data intact.
    bool_cols = ['isDriftUser', 'isVaultDepositor', 'isVaultManager']
    for col in bool_cols:
        new_col_name = f"{col}_bool"
        # Convert to a lowercase string, strip whitespace, and check for exact equality with 'true'.
        df1[new_col_name] = df1[col].astype(str).str.strip().str.lower() == 'true'

    # --- Identify Authorities to Exclude from Both Files ---
    # An authority should be excluded if it fails any of the required conditions.
    exclusion_mask = (df1['isDriftUser_bool'] == False) | (df1['isVaultDepositor_bool'] == True) | (df1['isVaultManager_bool'] == True)
    authorities_to_exclude = set(df1[exclusion_mask]['authority'])

    # --- Generate Exclusion Report (based on initial state of complete_snapshot.csv) ---
    total_records_initial = len(df1)
    excluded_not_drift_user = (df1['isDriftUser_bool'] == False).sum()
    excluded_is_vault_depositor = (df1['isVaultDepositor_bool'] == True).sum()
    excluded_is_vault_manager = (df1['isVaultManager_bool'] == True).sum()
    total_unique_authorities_excluded = len(authorities_to_exclude)

    print("--- Exclusion Report from 'complete_snapshot.csv' ---")
    print(f"Initial total authorities in complete_snapshot: {total_records_initial}")
    print(f"Authorities flagged for exclusion because isDriftUser is FALSE: {excluded_not_drift_user}")
    print(f"Authorities flagged for exclusion because isVaultDepositor is TRUE: {excluded_is_vault_depositor}")
    print(f"Authorities flagged for exclusion because isVaultManager is TRUE: {excluded_is_vault_manager}")
    print(f"Total unique authorities to be excluded from both files: {total_unique_authorities_excluded}")
    print("-" * 35)

    # --- Apply Exclusion to BOTH DataFrames ---
    initial_df1_count = len(df1)
    initial_df2_count = len(df2)

    df1 = df1[~df1['authority'].isin(authorities_to_exclude)]
    df2 = df2[~df2['authority'].isin(authorities_to_exclude)]

    print("--- Data Filtering Summary ---")
    print(f"Excluded {initial_df1_count - len(df1)} records from '{file1_path}'")
    print(f"Excluded {initial_df2_count - len(df2)} records from '{file2_path}'")
    print(f"Authorities remaining in '{file1_path}' for comparison: {len(df1)}")
    print(f"Authorities remaining in '{file2_path}' for comparison: {len(df2)}")
    print("-" * 35)


    # --- Data Preparation (on already filtered data) ---
    # Prepare DataFrame 1
    df1_snap = df1[['authority', 'totalFuel']].copy()
    df1_snap.rename(columns={'totalFuel': 'balance_snapshot'}, inplace=True)
    df1_snap.set_index('authority', inplace=True)


    # Prepare DataFrame 2
    # The new CSV has 'authority' and 'totalFuel' columns directly.
    df2.columns = df2.columns.str.strip() # Sanitize headers
    df2_export = df2[['authority', 'totalFuel']].copy()
    df2_export.rename(columns={'totalFuel': 'balance_export'}, inplace=True)
    df2_export.set_index('authority', inplace=True)


    # --- Merge DataFrames ---
    comparison_df = pd.merge(df1_snap, df2_export, on='authority', how='outer')
    comparison_df.fillna(0, inplace=True) # Fill missing values with 0

    # --- Calculate Difference ---
    comparison_df['difference'] = comparison_df['balance_snapshot'] - comparison_df['balance_export']

    # --- Generate Report ---
    total_auth_snap = len(df1_snap)
    total_auth_export = len(df2_export)

    in_snap_only = comparison_df['balance_export'] == 0
    in_export_only = comparison_df['balance_snapshot'] == 0
    
    in_both = (~in_snap_only) & (~in_export_only)

    num_in_snap_only = in_snap_only.sum()
    num_in_export_only = in_export_only.sum()
    num_in_both = in_both.sum()

    # Mismatched balances for authorities present in both files
    mismatched = comparison_df[in_both & (comparison_df['difference'] != 0)]
    num_mismatched = len(mismatched)

    print("--- Fuel Snapshot Comparison Report ---")
    print(f"Total authorities in final comparison from '{file1_path}': {total_auth_snap}")
    print(f"Total authorities in final comparison from '{file2_path}': {total_auth_export}")
    print("-" * 35)
    print(f"Authorities present in both files (post-filtering): {num_in_both}")
    print(f"Authorities with mismatched balances: {num_mismatched}")
    print(f"Authorities only in '{file1_path}' (post-filtering): {num_in_snap_only}")
    print(f"Authorities only in '{file2_path}' (post-filtering): {num_in_export_only}")
    print("-" * 35)

    # --- Output CSV ---
    comparison_df.reset_index(inplace=True)
    comparison_df.rename(columns={
        'balance_snapshot': 'balance_from_complete_snapshot',
        'balance_export': 'balance_from_fuel_export'
    }, inplace=True)
    
    comparison_df.to_csv(output_path, index=False)
    print(f"Comparison details saved to '{output_path}'")

if __name__ == '__main__':
    compare_snapshots()
