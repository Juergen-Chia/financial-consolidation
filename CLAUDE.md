# Financial Consolidation Engine — Project Guide

## Project Overview

A Python-based financial consolidation engine that reads subsidiary Excel files,
applies IFRS consolidation rules, and outputs a formatted consolidated Excel report.
Covers Balance Sheet, Income Statement, Cash Flow Statement, and Changes in Equity.

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
│   ├── intercompany_matrix.xlsx # Intercompany balances tracker
│   └── subsidiaries/            # One Excel file per subsidiary
│       ├── sub_sgd.xlsx         # Singapore subsidiary (SGD)
│       ├── sub_usd.xlsx         # US subsidiary (USD)
│       └── sub_eur.xlsx         # European subsidiary (EUR)
├── output/
│   └── consolidated_report.xlsx # Final consolidated output
├── src/
│   ├── reader.py                # Reads and validates subsidiary Excel files
│   ├── coa_mapper.py            # Maps subsidiary accounts to group COA
│   ├── fx_translator.py         # Applies FX translation per IFRS rules
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
  2300  Long-term Borrowings
  2400  Deferred Tax Liability
  2500  Other Liabilities

EQUITY
  3000  Share Capital
  3100  Retained Earnings
  3200  Other Comprehensive Income (OCI)
  3300  Non-Controlling Interest (NCI)  ← calculated on consolidation
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

**Column positions are fixed. Python reads by column index, not header name.**

---

## Chart of Accounts Mapping Table

File: `data/coa_mapping.xlsx`

| group_code | group_account_name | sub_sgd_code | sub_usd_code | sub_eur_code |
|---|---|---|---|---|
| 1000 | Cash and Cash Equivalents | 101 | CASH | 1000 |
| 1100 | Trade Receivables | 110 | AR | 1100 |
| ... | ... | ... | ... | ... |

**Rule:** If a subsidiary code is missing/blank, the account is excluded from consolidation for that entity. Python logs all unmapped accounts as warnings.

---

## Intercompany Matrix

File: `data/intercompany_matrix.xlsx`

Tracks all intercompany balances for elimination.

| from_entity | to_entity | account_type | group_account_code | amount_original_ccy | currency |
|---|---|---|---|---|---|
| Sub SGD | Parent Co | Receivable/Payable | 1200/2100 | 50,000 | SGD |
| Sub USD | Sub EUR | Revenue/COGS | 4100/5100 | 30,000 | USD |
| Parent Co | Sub SGD | Loan | 2300/2300 | 100,000 | USD |

**Elimination rule:** Both sides must be present and match after FX translation. Python flags unmatched intercompany balances as reconciliation errors before consolidation proceeds.

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
      "average_rate": 0.7350
    },
    "EUR": {
      "closing_rate": 1.0850,
      "average_rate": 1.0820
    },
    "USD": {
      "closing_rate": 1.0000,
      "average_rate": 1.0000
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
| FX translation difference | Balancing figure → OCI | IAS 21.41 |

---

## Consolidation Rules (IFRS 10)

### Sequence Python must follow:
1. **Read** all subsidiary Excel files and validate against template structure
2. **Map** subsidiary account codes to group COA via `coa_mapping.xlsx`
3. **Translate** all non-USD amounts using rates from `fx_rates.json`
4. **Eliminate** intercompany balances using `intercompany_matrix.xlsx`
5. **Eliminate** Investment in Subsidiaries vs. Subsidiary Share Capital
6. **Calculate** Non-Controlling Interest (NCI) where ownership < 100%
7. **Aggregate** all entities line by line
8. **Validate** BS balances (Assets = Liabilities + Equity), IS flows to retained earnings
9. **Write** formatted Excel output

### NCI Calculation
```
NCI Share = (100% - Ownership%) × Subsidiary Net Assets (post-elimination)
NCI in P&L = (100% - Ownership%) × Subsidiary Net Profit
```

---

## Output Report Format

File: `output/consolidated_report.xlsx`

Tabs:
- **Consolidated BS** — group total with entity columns for transparency
- **Consolidated IS** — same structure
- **Consolidated CF** — same structure
- **Consolidated EQ** — same structure
- **Eliminations Log** — every elimination entry with reference
- **FX Translation Log** — translated amounts per entity per statement
- **Validation** — balance checks, unmatched ICO warnings, unmapped accounts

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
# Step 1: Generate all mock data
python mock_data_generator.py

# Step 2: Run full consolidation
python main.py

# Output will be at: output/consolidated_report.xlsx
```

---

## Template Flexibility & Extensibility

The consolidation engine must be **data-driven, not hardcoded**. Adding a new account
number, new subsidiary, or new currency must require zero changes to Python source code.

### Rules Python must follow:

**1. Dynamic COA reading**
- Never hardcode account codes or account names in any `.py` file
- Read all valid group accounts from `coa_mapping.xlsx` at runtime
- New row added to `coa_mapping.xlsx` = automatically included in consolidation

**2. Dynamic subsidiary discovery**
- Scan the `data/subsidiaries/` folder at runtime for all `.xlsx` files
- Each file found is treated as a subsidiary — no registration needed
- New subsidiary file dropped into the folder = automatically consolidated

**3. Dynamic account mapping**
- If a subsidiary has a new account code not yet in `coa_mapping.xlsx`:
  - Log it as an **unmapped account warning** in the Validation tab
  - Exclude it from consolidation (do not silently drop or crash)
  - Never raise an unhandled exception for missing mappings

**4. Dynamic intercompany elimination**
- Elimination pairs are driven entirely by `intercompany_matrix.xlsx`
- New intercompany relationship = add a row to the matrix, no code change needed

**5. Dynamic FX currencies**
- Adding a new currency (e.g., GBP) = add it to `fx_rates.json` only
- Python must read all currencies from the config file, not from a hardcoded list

**6. Dynamic output columns**
- Consolidated report entity columns are generated from whatever subsidiaries
  are discovered at runtime — not from a fixed list

### What still requires a code change (acceptable exceptions):
| Change | Why code change needed |
|---|---|
| New financial statement type (e.g., add a 5th statement) | New reader + writer tab logic required |
| Change in IFRS translation method | Accounting rule change, intentional |
| Structural change to subsidiary template tabs | Reader column-index mapping must update |

### Validation Claude Code must implement:
```python
# On every run, report:
# - New accounts found in subsidiaries not in coa_mapping.xlsx  → WARNING
# - Accounts in coa_mapping.xlsx with no data in any subsidiary → INFO
# - New subsidiary files detected since last run               → INFO
# - Currencies in subsidiary META tab not in fx_rates.json     → ERROR (halt)
```

---

## Development Notes for Claude Code

- Always run `mock_data_generator.py` first to recreate clean test data
- Log all warnings (unmapped accounts, ICO mismatches) — do not silently skip
- Validation step in `consolidator.py` must halt and report if BS does not balance
- Keep elimination logic in `eliminations.py` separate from aggregation logic
- FX translation differences must be isolated to OCI — never flow through P&L
- NCI is always presented as a separate equity component, never netted off