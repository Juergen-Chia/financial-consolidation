# Financial Consolidation Engine — Project Guide (ICO Auto-Population Edition)

## Project Overview

A Python-based financial consolidation engine that reads subsidiary Excel files,
applies IFRS consolidation rules, and outputs a formatted consolidated Excel report.
Covers Balance Sheet, Income Statement, Cash Flow Statement, and Changes in Equity.

**This edition adds ICO auto-population:** intercompany elimination pairs are derived
automatically from a dedicated `ICO` tab in each subsidiary workbook, eliminating the
need to manually maintain the central `intercompany_matrix.xlsx` before each run.
The matrix file is retained as a manual-override layer only.

---

## Project Structure

```
financial-consolidation/
├── CLAUDE.md                    # This file
├── config/
│   ├── fx_rates.json            # FX translation rates (closing/average)
│   └── consolidation_config.json# Group structure, ownership %, reporting currency
├── data/
│   ├── coa_mapping.xlsx         # Chart of accounts mapping table
│   ├── intercompany_matrix.xlsx # Manual-override ICO entries only (not full matrix)
│   └── subsidiaries/            # One Excel file per subsidiary
│       ├── parent_co.xlsx       # Parent entity
│       ├── sub_sgd.xlsx         # Singapore subsidiary (SGD)
│       ├── sub_usd.xlsx         # US subsidiary (USD)
│       └── sub_eur.xlsx         # European subsidiary (EUR)
├── output/
│   └── consolidated_report.xlsx # Final consolidated output
├── src/
│   ├── reader.py                # Reads and validates subsidiary Excel files
│   ├── coa_mapper.py            # Maps subsidiary accounts to group COA
│   ├── fx_translator.py         # Applies FX translation per IFRS rules
│   ├── ico_detector.py          # NEW — builds and validates derived ICO matrix
│   ├── eliminations.py          # Intercompany elimination engine
│   ├── consolidator.py          # Aggregation and consolidation logic
│   └── report_writer.py         # Writes formatted Excel output
├── mock_data_generator.py       # Generates all mock data files for testing
├── main.py                      # Entry point — runs full consolidation pipeline
└── requirements.txt
```

---

## Mock Data Instructions

**Claude Code must generate all mock data by running `mock_data_generator.py`.**

### Group Structure (mock)
| Entity | Currency | Ownership | Role |
|---|---|---|---|
| Parent Co | USD | — | Group parent / reporting entity |
| Sub SGD | SGD | 100% | Singapore subsidiary |
| Sub USD | USD | 80% | US subsidiary (NCI applies) |
| Sub EUR | EUR | 100% | European subsidiary |

### Chart of Accounts (simplified IFRS-aligned)

#### Balance Sheet
```
ASSETS
  1000  Cash and Cash Equivalents
  1100  Trade Receivables
  1200  Intercompany Receivables        ← elimination account
  1300  Inventory
  1400  Prepayments
  1500  Property, Plant & Equipment
  1600  Intangible Assets
  1700  Investment in Subsidiaries      ← elimination account

LIABILITIES
  2000  Trade Payables
  2100  Intercompany Payables           ← elimination account
  2200  Short-term Borrowings
  2300  Long-term Borrowings            ← also used for intercompany loans
  2400  Deferred Tax Liability
  2500  Other Liabilities

EQUITY
  3000  Share Capital
  3100  Retained Earnings
  3200  Other Comprehensive Income (OCI)  ← FX translation differences routed here
  3300  Non-Controlling Interest (NCI)    ← calculated on consolidation
```

#### Income Statement
```
  4000  Revenue
  4100  Intercompany Revenue            ← elimination account
  5000  Cost of Goods Sold
  5100  Intercompany COGS               ← elimination account
  6000  Gross Profit                    ← calculated
  6100  Operating Expenses
  6200  Depreciation & Amortisation
  6300  Finance Income
  6400  Finance Costs
  6500  Income Tax Expense
  6600  Net Profit                      ← calculated
```

#### Cash Flow Statement (Indirect Method)
```
  7000  Net Profit (from IS)
  7100  Add: Depreciation & Amortisation
  7200  Changes in Working Capital
  7300  Cash from Operating Activities  ← calculated
  7400  Purchase of PPE
  7500  Cash from Investing Activities  ← calculated
  7600  Proceeds from Borrowings
  7700  Repayment of Borrowings
  7800  Dividends Paid
  7900  Cash from Financing Activities  ← calculated
  8000  Net Change in Cash              ← calculated
```

#### Changes in Equity
```
  Opening Balance (Share Capital + Retained Earnings + OCI)
  Net Profit for Period
  Other Comprehensive Income
  Dividends Declared
  FX Translation Reserve Movement
  Closing Balance
```

---

## Subsidiary Excel Template (Standardized)

All subsidiaries must use the same locked template with these tabs:
- **BS** — Balance Sheet (account code | account name | amount)
- **IS** — Income Statement (account code | account name | amount)
- **CF** — Cash Flow Statement (account code | account name | amount)
- **EQ** — Changes in Equity (component | opening | movement | closing)
- **META** — Entity name, reporting currency, reporting period, ownership %
- **ICO** — Intercompany declarations (see below) ← NEW REQUIRED TAB

**Column positions are fixed. Python reads by column index, not header name.**

---

## ICO Tab Specification (NEW)

The `ICO` tab replaces the need for manual maintenance of `intercompany_matrix.xlsx`.
Each subsidiary declares its intercompany positions here. The engine cross-references
counterparty ICO tabs to auto-build bilateral elimination pairs.

**Tab name:** `ICO`
**Status:** Required in all subsidiary files. Empty content (header row only) is valid
for entities with no intercompany activity.

### Columns (fixed index — do not change order)

| Col | Field | Required | Notes |
|---|---|---|---|
| 0 | `account_no` | Yes | Local subsidiary account code (e.g. "120", "IC-REC", "1200") |
| 1 | `to_party` | Yes | Counterparty entity name — **must exactly match** the entity name in `consolidation_config.json` |
| 2 | `account_type` | Yes | Free-text relationship label (e.g. "Trade Receivable", "IC Loan", "IC Revenue") — **this is the bilateral matching key** |
| 3 | `amount` | Yes | Numeric amount in the subsidiary's local functional currency |
| 4 | `currency` | Optional | ISO 3-letter code. If blank, inherits entity functional currency from META tab |
| 5 | `description` | Optional | Audit trail note (e.g. "Invoice batch Q4 2024"). Not used for matching. |

### Example — Parent Co ICO tab

| account_no | to_party | account_type | amount | currency | description |
|---|---|---|---|---|---|
| 2100 | Sub SGD | Trade Receivable | 50000 | SGD | Q4 goods |
| 1200 | Sub SGD | IC Loan | 100000 | SGD | Facility drawdown |

### Example — Sub SGD ICO tab

| account_no | to_party | account_type | amount | currency | description |
|---|---|---|---|---|---|
| 120 | Parent Co | Trade Receivable | 50000 | SGD | Q4 goods |
| 230 | Parent Co | IC Loan | 100000 | SGD | Facility drawdown |

### Matching rule

Two ICO rows form a bilateral pair when:
```
frozenset({entity_a, entity_b}) match  AND  account_type match  AND  statement_type match
```

`account_type` is the critical key. Two distinct relationships on the **same account code**
between the same entity pair (e.g. a trade receivable AND a loan receivable, both on account
1200) must use different `account_type` labels to be matched and eliminated correctly.

### Relationship to `intercompany_matrix.xlsx`

The matrix file is now an **override layer only**. Rows in the matrix file take precedence
over auto-derived rows with the same `(from_entity, to_entity, account_type)` key. Use the
matrix file for:
- ICO relationships that cannot be captured in the ICO tab (e.g. three-way netting)
- Manual adjustments approved by the Group Finance Controller
- Off-balance-sheet intercompany arrangements

---

## Chart of Accounts Mapping Table

File: `data/coa_mapping.xlsx`

| group_code | group_account_name | sub_sgd_code | sub_usd_code | sub_eur_code | parent_co_code |
|---|---|---|---|---|---|
| 1000 | Cash and Cash Equivalents | 101 | CASH | 1000 | 1000 |
| 1100 | Trade Receivables | 110 | AR | 1100 | 1100 |
| 1200 | Intercompany Receivables | 120 | IC-REC | 1200 | 1200 |
| ... | ... | ... | ... | ... | ... |

**Rule:** If a subsidiary code is missing/blank, the account is excluded from consolidation
for that entity. Python logs all unmapped accounts as warnings.

---

## Intercompany Matrix (Override File)

File: `data/intercompany_matrix.xlsx`

Now contains **manual override entries only** — not the full ICO picture.

| from_entity | to_entity | account_type | group_account_code | amount_original_ccy | currency | side |
|---|---|---|---|---|---|---|
| Parent Co | Sub SGD | Dividend Payable | 2500 | 10000 | USD | liability |
| Sub SGD | Parent Co | Dividend Receivable | 1100 | 10000 | USD | asset |

---

## FX Translation Rules (IFRS IAS 21)

File: `config/fx_rates.json`

```json
{
  "reporting_currency": "USD",
  "period": "2024-12",
  "rates": {
    "SGD": {
      "closing_rate": 0.7407,
      "average_rate": 0.7350,
      "historical_rate": 0.7200
    },
    "EUR": {
      "closing_rate": 1.0850,
      "average_rate": 1.0820,
      "historical_rate": 1.0500
    },
    "USD": {
      "closing_rate": 1.0000,
      "average_rate": 1.0000,
      "historical_rate": 1.0000
    }
  }
}
```

### Translation Method by Statement
| Statement | Rate Applied | IFRS Reference |
|---|---|---|
| Balance Sheet | Closing rate | IAS 21.39(a) |
| Income Statement | Average rate | IAS 21.39(b) |
| Cash Flow Statement | Average rate | IAS 21.39(b) |
| Equity (historical items) | Historical rate | IAS 21.39(c) |
| FX translation difference | Balancing figure → OCI (3200) | IAS 21.41 |

### IAS 21.41 — ICO Elimination FX Differences (CRITICAL)

When two sides of an ICO pair translate to different USD amounts (due to FX), the difference
**must flow to OCI (account 3200)** as a separate `ICO_FX_OCI` elimination entry.

**Never average the two sides.** Correct treatment:
1. Eliminate side A at its own translated amount
2. Eliminate side B at its own translated amount
3. Book the residual difference to OCI (account 3200) as `ICO_FX_OCI`

---

## Consolidation Rules (IFRS 10)

### Sequence Python must follow:

1. **Read** all subsidiary Excel files and validate against template structure
2. **Map** subsidiary account codes to group COA via `coa_mapping.xlsx`
3. **Translate** all non-USD amounts using rates from `fx_rates.json`
4. **Auto-detect** ICO pairs from `ICO` tabs across all entities (`ico_detector.py`)
5. **Validate** derived ICO pairs through 5 gates (halt on bilateral completeness failure)
6. **Merge** auto-derived pairs with manual matrix file rows (matrix file rows win on conflict)
7. **Eliminate** intercompany balances; route FX differences to OCI per IAS 21.41
8. **Eliminate** Investment in Subsidiaries vs. Subsidiary Share Capital
9. **Calculate** Non-Controlling Interest (NCI) where ownership < 100%
10. **Aggregate** all entities line by line
11. **Validate** BS balances (Assets = Liabilities + Equity), IS flows to retained earnings
12. **Write** formatted Excel output

### NCI Calculation
```
NCI Share = (100% - Ownership%) × Subsidiary Net Assets (post-elimination)
NCI in P&L = (100% - Ownership%) × Subsidiary Net Profit
```

---

## `src/ico_detector.py` — New Module

### `build_derived_matrix(subsidiaries, coa, config, fx) -> pd.DataFrame`

Reads `sub.ico` from each loaded `SubsidiaryData`, resolves local account codes to group
codes via COA, derives `account_type` labels and `side` values from the COA classification
column (no hardcoded account codes), and returns a DataFrame with the 7-column matrix schema:
`from_entity, to_entity, account_type, group_account_code, amount_original_ccy, currency, side`

### `validate_derived_matrix(derived_df, matrix_file_df, fx, config, validation_log) -> (merged_df, has_fatal)`

Runs 5 validation gates and returns the merged, validated DataFrame:

| Gate | Severity | Check |
|---|---|---|
| 4 (dedup — runs first) | INFO | Matrix-file row wins on `(from_entity, to_entity, account_type)` conflict |
| 1 (bilateral completeness) | **ERROR → halt** | Every row must have a counter-row (softens to WARNING if `require_bilateral_confirmation: false`) |
| 2 (FX tolerance) | WARNING | `|side_a_usd - side_b_usd| > timing_diff_threshold_usd` → `ICO_TIMING_DIFF` |
| 3 (account type consistency) | WARNING | BS pairs must be asset↔liability; IS pairs must be income↔expense |
| 5 (currency mismatch) | WARNING | Cross-currency ICO is valid; log `ICO_CURRENCY_MISMATCH` for visibility |

---

## `consolidation_config.json` — ICO Validation Block

```json
"ico_validation": {
  "auto_derive_from_subsidiaries": true,
  "timing_diff_threshold_usd": 5.0,
  "require_bilateral_confirmation": true
}
```

When `auto_derive_from_subsidiaries` is `false` (or the key is absent), the engine falls back
to reading `intercompany_matrix.xlsx` directly — identical to pre-ICO-tab behaviour.

---

## Output Report Format

File: `output/consolidated_report.xlsx`

Tabs:
- **Consolidated BS** — group total with entity columns for transparency
- **Consolidated IS** — same structure
- **Consolidated CF** — same structure
- **Consolidated EQ** — same structure
- **Eliminations Log** — every elimination entry including `Source` column (AUTO_DERIVED / MATRIX_FILE) and `ICO_FX_OCI` entries for OCI-routed FX differences
- **FX Translation Log** — translated amounts per entity per statement
- **Validation** — balance checks, ICO gate warnings/errors, unmapped accounts

---

## Python Libraries Required

```
pandas>=2.0
openpyxl>=3.1
pydantic>=2.0
json (stdlib)
logging (stdlib)
```

Install: `pip install pandas openpyxl pydantic`

---

## Running the Project

```bash
# Step 1: Generate all mock data (includes ICO tabs in subsidiary files)
python mock_data_generator.py

# Step 2: Run full consolidation
python main.py

# Output will be at: output/consolidated_report.xlsx
# Check Eliminations Log: Source column shows AUTO_DERIVED vs MATRIX_FILE
# Check Validation tab: ICO gate results, any ICO_BILATERAL_MISSING errors
```

---

## Template Flexibility & Extensibility

The consolidation engine must be **data-driven, not hardcoded**.

### Rules Python must follow:

**1. Dynamic COA reading**
- Never hardcode account codes or account names in any `.py` file
- Read all valid group accounts from `coa_mapping.xlsx` at runtime

**2. Dynamic subsidiary discovery**
- Scan `data/subsidiaries/` folder at runtime for all `.xlsx` files
- New subsidiary file dropped in = automatically consolidated

**3. Dynamic account mapping**
- Unmapped accounts → WARNING in Validation tab; excluded from consolidation; no crash

**4. Dynamic ICO detection**
- ICO pairs are derived from `ICO` tabs at runtime
- New ICO relationship = add rows to both counterparty `ICO` tabs; no code change
- Manual overrides = add rows to `intercompany_matrix.xlsx`; no code change

**5. Dynamic FX currencies**
- Adding a new currency = add it to `fx_rates.json` only

**6. Dynamic output columns**
- Report entity columns generated from whatever subsidiaries are discovered at runtime

### What still requires a code change (acceptable exceptions):
| Change | Why code change needed |
|---|---|
| New financial statement type (e.g., add a 5th statement) | New reader + writer tab logic required |
| Change in IFRS translation method | Accounting rule change, intentional |
| Structural change to subsidiary template tabs | Reader column-index mapping must update |

### Validation Claude Code must implement:
```python
# On every run, report:
# - ICO_BILATERAL_MISSING: auto-derived row has no counter-entry     → ERROR (halt)
# - ICO_TIMING_DIFF: FX-adjusted mismatch > timing_diff_threshold    → WARNING
# - ICO_ACCOUNT_TYPE_INCONSISTENCY: unexpected BS/IS pairing         → WARNING
# - ICO_CURRENCY_MISMATCH: cross-currency ICO pair detected          → WARNING (INFO)
# - ICO_MANUAL_OVERRIDE_APPLIED: matrix file row overrides derived   → INFO
# - New accounts found in subsidiaries not in coa_mapping.xlsx       → WARNING
# - Currencies in subsidiary META tab not in fx_rates.json           → ERROR (halt)
```

---

## Known Gaps (Future Development)

| Gap | IFRS Reference | Notes |
|---|---|---|
| Unrealised profit on intercompany inventory/PPE | IFRS 10.B86 | Requires `unrealised_profit` column in ICO tab or separate URE mechanism. Flag as `URE_NOT_SUPPORTED` in Validation tab when IS ICO pairs are detected. |
| ERP connectors (SAP BAPI, Oracle REST, Dynamics OData) | — | Optional future layer; slots into `ico_detector.py` as an additional data source feeding the same derived DataFrame |

---

## Development Notes for Claude Code

- Always run `mock_data_generator.py` first to recreate clean test data
- Log all warnings (unmapped accounts, ICO gate results) — do not silently skip
- `consolidator.py` must halt and report if BS does not balance
- Keep ICO detection logic in `ico_detector.py`, elimination logic in `eliminations.py`
- FX translation differences on ICO elimination must go to OCI (account 3200) — never averaged into the elimination amount, never flow through P&L
- NCI is always presented as a separate equity component, never netted off
- `EliminationEntry.source` must be set on every entry: `"AUTO_DERIVED"` or `"MATRIX_FILE"`
- `classify_account_statement()` must live in `models.py` (shared utility) — not duplicated across modules
