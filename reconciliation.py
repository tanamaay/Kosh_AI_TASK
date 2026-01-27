import pandas as pd

# -------------------------------
# Helpers
# -------------------------------
def _norm_col_name(name: str) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace(" ", "")
        .replace(".", "")
        .replace("_", "")
        .replace("-", "")
    )


def _find_col(df: pd.DataFrame, *, any_of=None, all_of=None):
    """
    Find a column where normalized name contains:
    - any token in any_of (OR)
    - all tokens in all_of (AND)
    """
    any_of = [t for t in (any_of or []) if t]
    all_of = [t for t in (all_of or []) if t]
    norm_map = {c: _norm_col_name(c) for c in df.columns}
    for col, norm in norm_map.items():
        if all_of and not all(_norm_col_name(t) in norm for t in all_of):
            continue
        if any_of and not any(_norm_col_name(t) in norm for t in any_of):
            continue
        return col
    return None


def _to_number(series: pd.Series) -> pd.Series:
    # Handles commas/currency/etc: keep digits, dot, minus
    s = series.astype(str).str.replace(r"[^0-9\.\-]+", "", regex=True)
    s = s.replace("", pd.NA)
    return pd.to_numeric(s, errors="coerce")

# ===============================
# PROCESS STATEMENT FILE
# ===============================
def process_statement(stmt_path):
    # Step 1: Read without header
    raw = pd.read_excel(stmt_path, header=None)

    # Step 2: Delete rows 1–9 and 11 (0-based)
    raw = raw.drop(index=[0,1,2,3,4,5,6,7,8,10], errors="ignore").reset_index(drop=True)

    # Step 3: First remaining row is header
    raw.columns = raw.iloc[0]
    df = raw[1:].reset_index(drop=True)
    df.columns = df.columns.astype(str).str.strip()

    # Step 4: Extract PartnerPin from Description (11 digit number at the very end)
    desc_col = df.iloc[:,3].astype(str).str.strip()
    
    # Try multiple extraction patterns:
    # 1. Extract 11-digit number at the end
    df["PartnerPin"] = desc_col.str.extract(r"(\d{11})$")
    
    # 2. If that fails, try extracting XXP followed by 8 digits and convert to 777 + 8 digits
    missing_mask = df["PartnerPin"].isna() | (df["PartnerPin"] == "nan")
    if missing_mask.any():
        # Extract XXP + 8 digits pattern
        xxp_pattern = desc_col[missing_mask].str.extract(r"XXP(\d{8})", expand=False)
        # Convert XXP + 8 digits to 777 + 8 digits
        df.loc[missing_mask & xxp_pattern.notna(), "PartnerPin"] = "777" + xxp_pattern[missing_mask & xxp_pattern.notna()].astype(str)
    
    # 3. If still missing, try extracting any 11-digit number starting with 777
    still_missing = df["PartnerPin"].isna() | (df["PartnerPin"] == "nan")
    if still_missing.any():
        df.loc[still_missing, "PartnerPin"] = desc_col[still_missing].str.extract(r"(777\d{8})", expand=False)
    
    # 4. If still missing, try extracting any 11-digit number anywhere
    still_missing = df["PartnerPin"].isna() | (df["PartnerPin"] == "nan")
    if still_missing.any():
        df.loc[still_missing, "PartnerPin"] = desc_col[still_missing].str.extract(r"(\d{11})", expand=False)
    
    # Clean PartnerPin - remove any whitespace and ensure it's string
    df["PartnerPin"] = df["PartnerPin"].astype(str).str.strip()
    # Remove "nan" strings
    df["PartnerPin"] = df["PartnerPin"].replace("nan", pd.NA)
    
    # Check how many PartnerPins were extracted
    valid_pins = df["PartnerPin"].notna() & (df["PartnerPin"] != "nan") & (df["PartnerPin"] != "")

    # Step 5: Identify duplicate pins (only for valid PartnerPins)
    df_valid = df[valid_pins].copy()
    if len(df_valid) > 0:
        dup_pins = df_valid[df_valid["PartnerPin"].duplicated(keep=False)]["PartnerPin"].unique()
        non_dup_mask = ~df_valid["PartnerPin"].isin(dup_pins)
    else:
        dup_pins = []
        non_dup_mask = pd.Series([False] * len(df), index=df.index)

    # Step 6: Reconcile tagging
    df["ReconcileStatus"] = "Should Not Reconcile"

    # Dollar Received → Should Not Reconcile (explicitly exclude)
    dollar_received_mask = df.iloc[:,1].astype(str).str.lower().str.strip() == "dollar received"
    
    # Cancel + duplicate → Should Reconcile (but not Dollar Received)
    if len(df_valid) > 0:
        cancel_dup_mask = (
            (df.iloc[:,1].astype(str).str.lower().str.strip() == "cancel") &
            (df["PartnerPin"].isin(dup_pins)) &
            (~dollar_received_mask) &
            valid_pins
        )
        df.loc[cancel_dup_mask, "ReconcileStatus"] = "Should Reconcile"

        # Non-duplicated transactions → Should Reconcile (but exclude Dollar Received)
        non_dup_not_dollar = non_dup_mask & (~dollar_received_mask) & valid_pins
        df.loc[non_dup_not_dollar, "ReconcileStatus"] = "Should Reconcile"

    # Step 7: Amount from Col L (Settle.Amt)
    settle_col = _find_col(df, all_of=["settle", "amt"]) or _find_col(df, any_of=["settleamt"])
    if settle_col is not None:
        df["AmountUSD"] = _to_number(df[settle_col])
    else:
        # Fall back to column index 11 (Col L)
        df["AmountUSD"] = _to_number(df.iloc[:, 11])

    # Only drop rows with invalid PartnerPin AFTER all processing
    result = df[valid_pins].copy()
    return result


# ===============================
# PROCESS SETTLEMENT FILE
# ===============================
def process_settlement(file_path):
    raw = pd.read_excel(file_path, header=None)

    # Delete rows 1 & 2
    raw = raw.drop(index=[0,1], errors="ignore").reset_index(drop=True)

    # Header
    raw.columns = raw.iloc[0]
    df = raw[1:].reset_index(drop=True)
    df.columns = df.columns.astype(str).str.strip()

    # PartnerPin from Col D - extract 11 digit number
    # Col D might already be PartnerPin directly, or might contain it in text
    partner_pin_col = df.iloc[:,3]
    
    # First, try to convert directly if it's numeric
    if partner_pin_col.dtype in ['int64', 'float64']:
        # Convert numeric to string, removing decimals
        partner_pin_str = partner_pin_col.astype('Int64').astype(str).str.replace(r"\.0+$", "", regex=True)
    else:
        partner_pin_str = partner_pin_col.astype(str).str.strip()
    
    # Try direct 11-digit match first
    direct_match = partner_pin_str.str.match(r"^\d{11}$", na=False)
    df.loc[direct_match, "PartnerPin"] = partner_pin_str[direct_match]
    
    # For non-matching rows, try to extract 11-digit number
    not_matched = ~direct_match & partner_pin_str.notna()
    if not_matched.any():
        # Try extracting from end first (most common case)
        extracted = partner_pin_str[not_matched].str.extract(r"(\d{11})$", expand=False)
        # If that fails, extract from anywhere
        still_missing = extracted.isna()
        if still_missing.any():
            extracted[still_missing] = partner_pin_str[not_matched][still_missing].str.extract(r"(\d{11})", expand=False)
        df.loc[not_matched, "PartnerPin"] = extracted
    
    # Clean PartnerPin - remove any whitespace and ensure it's string
    df["PartnerPin"] = df["PartnerPin"].astype(str).str.strip()
    # Remove "nan" strings
    df["PartnerPin"] = df["PartnerPin"].replace("nan", pd.NA)

    # Amount calculation: estimate amount (usd) = PayoutRoundAmt ÷ APIRate
    payout_col = _find_col(df, all_of=["payout", "round", "amt"]) or _find_col(df, all_of=["payout", "amt"])
    rate_col = _find_col(df, all_of=["api", "rate"]) or _find_col(df, any_of=["apirate"])

    payout = _to_number(df[payout_col]) if payout_col is not None else _to_number(df.iloc[:, 10])  # Col K
    rate = _to_number(df[rate_col]) if rate_col is not None else _to_number(df.iloc[:, 12])  # Col M
    rate = rate.replace(0, pd.NA)
    df["AmountUSD"] = (payout / rate).astype(float)

    # Duplicate pins
    dup_pins = df[df["PartnerPin"].duplicated(keep=False)]["PartnerPin"].unique()
    non_dup_mask = ~df["PartnerPin"].isin(dup_pins)

    # Reconcile tagging
    df["ReconcileStatus"] = "Should Not Reconcile"

    # Cancel + duplicate → Should Reconcile
    df.loc[
        (df.iloc[:,5].astype(str).str.lower() == "cancel") &
        (df["PartnerPin"].isin(dup_pins)),
        "ReconcileStatus"
    ] = "Should Reconcile"

    # Non-duplicated transactions → Should Reconcile
    df.loc[non_dup_mask, "ReconcileStatus"] = "Should Reconcile"

    return df.dropna(subset=["PartnerPin"])


# ===============================
# RECONCILIATION LOGIC
# ===============================
def reconcile(stmt_df, sett_df):
    stmt = stmt_df[stmt_df["ReconcileStatus"] == "Should Reconcile"].copy()
    sett = sett_df[sett_df["ReconcileStatus"] == "Should Reconcile"].copy()

    # Ensure PartnerPin is string and clean
    stmt["PartnerPin"] = stmt["PartnerPin"].astype(str).str.strip()
    sett["PartnerPin"] = sett["PartnerPin"].astype(str).str.strip()
    
    # Remove any rows with invalid PartnerPin (nan, empty, or not 11 digits)
    # Also remove "nan" strings that might come from NaN values
    stmt = stmt[
        (stmt["PartnerPin"] != "nan") & 
        (stmt["PartnerPin"] != "") & 
        (stmt["PartnerPin"].str.match(r"^\d{11}$", na=False))
    ]
    sett = sett[
        (sett["PartnerPin"] != "nan") & 
        (sett["PartnerPin"] != "") & 
        (sett["PartnerPin"].str.match(r"^\d{11}$", na=False))
    ]

    stmt = stmt.drop_duplicates("PartnerPin", keep="first")
    sett = sett.drop_duplicates("PartnerPin", keep="first")

    merged = pd.merge(
        sett[["PartnerPin", "AmountUSD"]],
        stmt[["PartnerPin", "AmountUSD"]],
        on="PartnerPin",
        how="outer",
        suffixes=("_settlement", "_statement"),
        indicator=True,
    )

    # Classify by presence in each file (NOT by whether AmountUSD is non-null)
    merged["Classification"] = merged["_merge"].map(
        {
            "both": "Present in Both",
            "left_only": "Present in the Settlement File but not in the Partner Statement File",
            "right_only": "Not Present in the Settlement File but are present in the Statement File",
        }
    )

    # Variance is required only for "Present in Both"
    merged["AmountVariance"] = pd.NA
    both_mask = merged["_merge"] == "both"
    raw_var = (
        merged.loc[both_mask, "AmountUSD_settlement"].astype(float)
        - merged.loc[both_mask, "AmountUSD_statement"].astype(float)
    )
    merged.loc[both_mask, "AmountVariance"] = raw_var

    # -------------------------------
    # Final reconcile decisioning
    # -------------------------------
    # Treat values within a cent as reconciled (currency tolerance)
    tolerance = 0.01

    # Display variance to 6 decimals (so you can see tiny differences)
    _var_display = pd.to_numeric(merged.loc[both_mask, "AmountVariance"], errors="coerce").round(6)
    # Avoid displaying "-0.000000"
    _var_display = _var_display.mask(_var_display.abs() < 0.0000005, 0.0)
    merged.loc[both_mask, "AmountVariance"] = _var_display

    merged["FinalReconcileStatus"] = pd.NA
    merged.loc[both_mask, "FinalReconcileStatus"] = "Amount Mismatch"
    merged.loc[
        both_mask
        & (
            pd.to_numeric(raw_var, errors="coerce").abs().le(tolerance)
        ),
        "FinalReconcileStatus",
    ] = "Reconciled"

    merged.loc[merged["_merge"] == "left_only", "FinalReconcileStatus"] = "Missing in Statement"
    merged.loc[merged["_merge"] == "right_only", "FinalReconcileStatus"] = "Missing in Settlement"

    # Filter only classifications 5, 6, & 7:
    # 5 = "Present in Both"
    # 6 = "Present in the Settlement File but not in the Partner Statement File"
    # 7 = "Not Present in the Settlement File but are present in the Statement File"
    valid_classifications = [
        "Present in Both",
        "Present in the Settlement File but not in the Partner Statement File",
        "Not Present in the Settlement File but are present in the Statement File"
    ]
    merged = merged[merged["Classification"].isin(valid_classifications)]

    return merged[
        ["PartnerPin","Classification","FinalReconcileStatus","AmountVariance"]
    ]


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    statement_df = process_statement("statement.xlsx")
    settlement_df = process_settlement("settlement.xlsx")

    result = reconcile(statement_df, settlement_df)

    result.to_excel("reconciliation_result.xlsx", index=False)
    print(" Reconciliation completed successfully")


