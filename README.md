# Kosh AI Project — Statement vs Settlement Reconciliation (5 / 6 / 7)

This project provides:
- **An interface to upload** the Statement and Settlement Excel files
- **A results page** showing only the reconciliation classifications **5 / 6 / 7**

## What the app does

### Statement file (per test steps)
- Deletes rows **1 to 9 and 11**
- From **Column D (Description)** extracts **PartnerPin** (an **11-digit number at the very end**)
- Finds duplicates by PartnerPin
- Tags:
  - **Cancel** (Column B) **of duplicated transactions** → **Should Reconcile**
  - **Dollar Received** (Column B) → **Should Not Reconcile**
  - **Non-duplicated** PartnerPins → **Should Reconcile**
- Uses **Column L (Settle.Amt)** as the Statement amount for comparison

### Settlement file (per test steps)
- Deletes rows **1 and 2**
- Uses **Column D** as PartnerPin (keeps only 11 digits)
- Adds/estimates USD amount:
  - **AmountUSD = PayoutRoundAmt (Column K) ÷ APIRate (Column M)**
- Finds duplicates by PartnerPin
- Tags:
  - **Cancel** (Column F) **of duplicated transactions** → **Should Reconcile**
  - **Non-duplicated** PartnerPins → **Should Reconcile**

### Matching + output (Classifications 5 / 6 / 7)
Matches only PartnerPins that are tagged **“Should Reconcile”** in both files, then labels:
- **Present in Both**
- **Present in the Settlement File but not in the Partner Statement File**
- **Not Present in the Settlement File but are present in the Statement File**

For **Present in Both**:
- **AmountVariance = Settlement AmountUSD − Statement Settle.Amt**
- Display is **2 decimals (USD cents)**.

## Project structure
- `app.py`: Flask web app (upload + results)
- `reconciliation.py`: statement/settlement parsing + reconciliation logic
- `templates/upload.html`: upload form
- `templates/results.html`: results page
- `uploads/`: uploaded files saved here

## System design / architecture

### High-level flow (graph)

```mermaid
┌────────────────────┐
│   Input Layer      │
│────────────────────│
│ statement.xlsx     │
│ settlement.xlsx    │
└─────────┬──────────┘
          │
          ▼
┌──────────────────────────┐
│   File Processing Layer  │
│──────────────────────────│
│ process_statement()      │
│ process_settlement()     │
└─────────┬────────────────┘
          │
          ▼
┌──────────────────────────┐
│   Data Cleaning Layer    │
│──────────────────────────│
│ • Column normalization  │
│ • PartnerPin extraction │
│ • Amount normalization  │
│ • Duplicate detection   │
└─────────┬────────────────┘
          │
          ▼
┌──────────────────────────┐
│ Business Rules Layer     │
│──────────────────────────│
│ • Reconcile tagging     │
│ • Cancel logic          │
│ • Duplicate handling    │
└─────────┬────────────────┘
          │
          ▼
┌──────────────────────────┐
│ Reconciliation Engine    │
│──────────────────────────│
│ • Merge on PartnerPin   │
│ • Variance calculation  │
│ • Tolerance matching    │
└─────────┬────────────────┘
          │
          ▼
┌──────────────────────────┐
│ Output Layer             │
│──────────────────────────│
│ reconciliation_result.xlsx│
└──────────────────────────┘

```

## Setup (Windows / PowerShell)

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the web app:

```bash
python app.py
```

Then open the local URL shown in the console (Flask default is `http://127.0.0.1:5000`).

## Deploy (Render - recommended)

1) Push your code to GitHub (already done).

2) On Render:
- Create **New → Web Service**
- Connect your GitHub repo: `tanamaay/Kosh_AI_TASK`

3) Configure:
- **Runtime**: Python
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`

4) Deploy → open the public URL.

## Deploy (Railway - alternative)
- Create New Project → Deploy from GitHub repo
- Set start command to: `gunicorn app:app --bind 0.0.0.0:$PORT`

## Notes
- The code follows the prompt’s **fixed column positions** (B/D/L for Statement, D/F/K/M for Settlement).
- If your file layout changes, the column indexes in `reconciliation.py` must be updated.
