# Financial Consolidation Engine

A Python-based group financial consolidation engine that reads subsidiary Excel workbooks,
applies IFRS consolidation rules automatically, and produces a formatted consolidated report
in Excel — covering Balance Sheet, Income Statement, Cash Flow Statement, and Changes in Equity.

---

## Part 1 — For Accountants and Finance Teams

### What this engine does

At period-end, each subsidiary submits a standardised Excel workbook containing their
Balance Sheet, Income Statement, Cash Flow Statement, Changes in Equity, and a new
Intercompany (ICO) tab declaring all intercompany positions. The engine reads all workbooks,
applies the full IFRS consolidation sequence automatically, and outputs a consolidated
Excel report — ready for review.

---

### Key Benefits

#### Automated Intercompany Elimination — No More Manual Matrix Maintenance

Previously, someone had to manually compile every intercompany pair into a central matrix
file before each run. This engine eliminates that step entirely.

Each subsidiary now declares its own intercompany positions directly in its ICO tab
(counterparty, relationship type, amount, currency). The engine reads all ICO tabs,
cross-references them bilaterally, and derives the elimination pairs automatically. The
central matrix file is retained only for exceptional arrangements that cannot be captured
in a subsidiary's own workbook — such as dividend approvals or three-way netting agreed
by Group Finance.

**Time saved:** Estimated 2–4 hours per consolidation cycle previously spent maintaining
and reconciling the intercompany matrix, now reduced to zero for standard bilateral positions.

---

#### Full IFRS 10 Consolidation Compliance

The engine follows the mandatory IFRS 10 consolidation sequence in the correct order:

1. Read and validate all subsidiary data
2. Map subsidiary account codes to the group Chart of Accounts
3. Translate foreign currency balances into the reporting currency (USD)
4. Detect and validate intercompany pairs from ICO tabs
5. Eliminate intercompany balances and transactions
6. Eliminate the parent's Investment in Subsidiaries against subsidiary Share Capital
7. Calculate and present Non-Controlling Interest (NCI) separately
8. Aggregate all entities line by line
9. Validate that the Consolidated Balance Sheet balances
10. Output the formatted report

**Standard:** IFRS 10 *Consolidated Financial Statements*

---

#### IAS 21 Foreign Currency Translation — Correct Rate by Account Type

Foreign currency subsidiary balances are translated using the rates prescribed by IAS 21,
applied per account type — not a single blended rate:

| Statement | Rate Applied | IAS 21 Reference |
|---|---|---|
| Balance Sheet | Closing rate | IAS 21.39(a) |
| Income Statement | Average rate | IAS 21.39(b) |
| Cash Flow Statement | Average rate | IAS 21.39(b) |
| Share Capital (historical equity items) | Historical rate | IAS 21.39(c) |
| FX translation difference | Balancing figure → OCI | IAS 21.41 |

The FX translation reserve (the difference arising from translating equity at historical
rates but assets/liabilities at closing rates) is computed automatically and posted to
Other Comprehensive Income (account 3200) — never through P&L.

**Standard:** IAS 21 *The Effects of Changes in Foreign Exchange Rates*

---

#### IAS 21.41 — Cross-Currency ICO FX Differences Routed to OCI

When two sides of an intercompany pair are denominated in different currencies, the
translated USD amounts will differ due to FX movements. The engine treats this correctly:

- Each side is eliminated at its own translated amount (never averaged)
- The residual FX difference is posted to OCI (account 3200) as a separate `ICO_FX_OCI` entry
- It never flows through P&L and never inflates or deflates the eliminated balance

This is a common error in manual consolidations. The engine enforces the correct treatment automatically.

---

#### Non-Controlling Interest (NCI) — Correct Basis

For subsidiaries not wholly owned (ownership < 100%), NCI is calculated on
**post-elimination net assets** — i.e., after intercompany balances have been removed
from the subsidiary's equity, as required by IFRS 10.22. NCI is presented separately
within consolidated equity (account 3300) and is never netted against the parent's share.

NCI in P&L is similarly calculated on the subsidiary's **post-ICO-elimination net profit**,
ensuring that intercompany revenue or costs eliminated at group level are not double-counted
in the NCI allocation.

---

#### Five-Gate ICO Validation — Problems Surfaced Before the Report Is Written

Before any elimination is processed, all intercompany pairs pass through five automated
validation gates. Results appear in the Validation tab of the output report:

| Gate | What it checks | Severity |
|---|---|---|
| Bilateral completeness | Every declared ICO position must have a matching counter-entry from the counterparty | Error — consolidation halts |
| FX tolerance | USD-translated amounts on both sides must be within a configurable threshold | Warning |
| Account type consistency | BS pairs must be asset ↔ liability; IS pairs must be income ↔ expense | Warning |
| Manual override applied | A matrix-file row supersedes an auto-derived row for the same pair | Info |
| Cross-currency ICO | ICO positions declared in different currencies — valid but flagged for awareness | Warning |

A bilateral mismatch (Gate 1) halts the run immediately rather than producing a
silently wrong report.

---

#### Full Audit Trail in the Output Report

The consolidated Excel report contains six tabs, all auto-generated:

| Tab | Contents |
|---|---|
| Consolidated BS | Balance Sheet with one column per entity plus Group Total |
| Consolidated IS | Income Statement — same structure |
| Consolidated CF | Cash Flow Statement — same structure |
| Consolidated EQ | Changes in Equity including NCI share of profit |
| Eliminations Log | Every elimination entry: reference, type, entity, account, amount, and **Source** (AUTO_DERIVED / MATRIX_FILE / CONSOLIDATION_RULE) |
| FX Translation Log | Per-entity, per-account translation detail showing local amount, rate type, rate used, and USD amount |
| Validation | All gate results, unmapped account warnings, BS balance confirmation |

The **Source** column in the Eliminations Log distinguishes:
- `AUTO_DERIVED` — derived from the subsidiary's own ICO tab declaration
- `MATRIX_FILE` — entered manually in the override matrix by Group Finance
- `CONSOLIDATION_RULE` — computed by the engine from ownership percentages
  (Investment vs Equity elimination, NCI reclassification)

---

#### Catches Common Errors Automatically

| Error type | How the engine handles it |
|---|---|
| Subsidiary account code not in group COA | Warning in Validation tab; account excluded from consolidation; run continues |
| Unknown currency in subsidiary META tab | Immediate halt with clear error message |
| Balance Sheet out of balance post-consolidation | Immediate halt — the report is not written until BS balances |
| One-sided ICO declaration (counterparty missing) | Gate 1 error — run halts before eliminations are processed |
| FX rate not configured for a currency | Immediate halt with clear error message |

---

#### Adding a New Subsidiary Requires Zero Code Changes

Drop a new subsidiary workbook into the `data/subsidiaries/` folder and run the engine.
It is discovered automatically. The only configuration steps are:

1. Add the entity to `config/consolidation_config.json` (name, currency, ownership %)
2. Add the entity's account codes to `data/coa_mapping.xlsx`
3. Add the relevant FX rates to `config/fx_rates.json` (if a new currency)

No Python code needs to change.

---

### Known Limitations (Future Development)

| Limitation | IFRS Reference | Status |
|---|---|---|
| Unrealised profit on intercompany inventory or PPE sales | IFRS 10.B86 | Not supported. The Validation tab flags a `URE_NOT_SUPPORTED` warning when IS ICO pairs are detected. |
| Goodwill arising on acquisition | IFRS 3 | Not supported. The Validation tab flags an `INVESTMENT_RESIDUAL` warning if the parent's investment cost differs from the acquired share of net assets. |
| ERP connectors (SAP, Oracle, Dynamics) | — | Not yet implemented. The ICO tab is the current data entry point. |

---

---

## Part 2 — For Developers

### Architecture Overview

The engine is a linear Python pipeline. Each module has a single responsibility and passes
typed Pydantic models to the next stage. No module calls another out of sequence.

```
main.py
  └── Consolidator.run()
        ├── reader.py          — reads + validates .xlsx files → SubsidiaryData[]
        ├── coa_mapper.py      — maps local codes to group codes → COAMapping
        ├── fx_translator.py   — translates amounts → SubsidiaryData[] (USD)
        ├── ico_detector.py    — derives + validates ICO pairs → pd.DataFrame
        ├── eliminations.py    — eliminates ICO, investment, NCI → EliminationEntry[]
        ├── consolidator.py    — aggregates rows → ConsolidatedData
        └── report_writer.py   — writes output/consolidated_report.xlsx
```

---

### Project Structure

```
fin-consol-auto-populate/
├── config/
│   ├── fx_rates.json               # FX rates: closing, average, historical per currency
│   └── consolidation_config.json   # Group entities, ownership %, ICO validation thresholds
├── data/
│   ├── coa_mapping.xlsx            # group_code → local codes per entity, classification
│   ├── intercompany_matrix.xlsx    # Manual override ICO rows only
│   └── subsidiaries/               # Auto-discovered *.xlsx — one per entity
├── output/
│   └── consolidated_report.xlsx    # Generated report
├── src/
│   ├── models.py                   # Pydantic models shared across all modules
│   ├── reader.py                   # openpyxl-based workbook reader
│   ├── coa_mapper.py               # COA lookup and classification
│   ├── fx_translator.py            # IAS 21 rate selection and translation
│   ├── ico_detector.py             # ICO auto-detection and 5-gate validation
│   ├── eliminations.py             # EliminationEngine: ICO, investment, NCI
│   ├── consolidator.py             # Orchestration and aggregation
│   └── report_writer.py            # openpyxl-based report writer
├── mock_data_generator.py          # Generates all test data from scratch
├── main.py                         # Entry point
├── requirements.txt
└── CLAUDE.md                       # Detailed developer guide (AI-assisted development)
```

---

### Core Data Models (`src/models.py`)

```python
EntityMeta          # Entity name, currency, reporting period, ownership %
AccountLine         # One BS/IS/CF row: group_code, amount_local, amount_usd, entity
EquityLine          # One EQ row: component, opening/movement/closing in local + USD
IntercompanyLine    # One ICO tab row: entity, counterparty, account_type, amount
SubsidiaryData      # Full entity: bs[], is_[], cf[], eq[], ico[], unmapped_accounts[]
EliminationEntry    # One elimination journal line: reference, type, source, amount_usd
FxTranslationEntry  # One FX log row: entity, account, rate_type, rate_used, amount_usd
ValidationMessage   # Severity (INFO/WARNING/ERROR), category code, message, detail
ConsolidatedData    # Final aggregated output passed to report_writer
```

`EliminationEntry.source` is a three-value literal:
- `AUTO_DERIVED` — derived from ICO tabs
- `MATRIX_FILE` — manually entered in `intercompany_matrix.xlsx`
- `CONSOLIDATION_RULE` — computed by the engine (investment elimination, NCI)

---

### ICO Auto-Population Flow (`src/ico_detector.py`)

```
SubsidiaryData[].ico  →  build_derived_matrix()  →  derived_df (AUTO_DERIVED rows)
                                                          │
intercompany_matrix.xlsx  ──────────────────────────────►│
                                                          ▼
                                               validate_derived_matrix()
                                                    │
                              ┌─────────────────────┼──────────────────────┐
                          Gate 4               Gate 1                 Gate 2/3/5
                         (dedup —           (bilateral —            (warnings:
                        matrix wins)       halt on ERROR)         FX diff, type,
                              │                   │                  currency)
                              └─────────────────────┘
                                                  │
                                             merged_df  →  EliminationEngine
```

Gate order: **4 → 1 → 2 → 3 → 5**. Gate 4 (dedup/merge) runs first so that bilateral
checking in Gate 1 operates on the already-merged set.

**Bilateral matching key:**
```python
frozenset({entity_a, entity_b})  +  account_type  +  statement_type
```

`account_type` is the critical matching field. Two distinct relationships between the
same entity pair (e.g. a trade receivable AND a loan, both on account 1200) must use
different `account_type` labels to be matched and eliminated separately.

---

### FX Translation (`src/fx_translator.py`)

Rate selection is driven by account classification — not hardcoded ranges:

| COA classification | Rate used |
|---|---|
| Asset, Liability | closing |
| Income, Expense | average |
| Equity (Share Capital — historical) | historical |
| Equity (Retained Earnings, OCI — current period) | average |

The FX translation reserve (IAS 21.41) is the balancing figure:
```
FX Reserve = sum(assets at closing) − sum(liabilities at closing) − sum(equity at historical/average)
```
Posted as a synthetic `AccountLine(group_code="3200")` in memory — never written to the workbook.

---

### Elimination Engine (`src/eliminations.py`)

**`eliminate_intercompany()`** — ICO balance/P&L eliminations per IAS 21.41:
- Each side eliminated at its own translated amount (never averaged)
- FX difference between sides posted to account 3200 as `ICO_FX_OCI` if `abs(diff) > 0.005`
- OCI entries only generated for BS-side pairs (IS-only pairs have no BS impact)
- Rate type derived independently per side: `"closing"` for BS accounts, `"average"` for IS

**`eliminate_investment_vs_equity()`** — IFRS 10 investment elimination:
- Eliminates parent's full 1700 balance against each subsidiary's Share Capital (3000)
- Only the parent's ownership % of each subsidiary's SC is eliminated here
- NCI's remaining share is left in 3000 and reclassified by `calculate_nci()`
- Residual (potential goodwill) flagged as `INVESTMENT_RESIDUAL` warning if > 1 USD

**`calculate_nci()`** — IFRS 10.22 NCI reclassification:
- Builds `eq_post` from subsidiary equity lines after ICO eliminations only
  (`INVESTMENT_EQUITY` entries explicitly excluded — they represent the parent's side)
- NCI P&L adjusted for ICO IS eliminations (`ICO_PL` type) before applying NCI %
- Two entries per equity line: debit source account (3000/3100/3200), credit 3300

---

### Adding a New Subsidiary — Zero Code Changes

1. Add the subsidiary's Excel file to `data/subsidiaries/` following the tab template:
   `BS | IS | CF | EQ | META | ICO`
2. Add the entity to `config/consolidation_config.json`
3. Add account mappings to `data/coa_mapping.xlsx` (new column for the entity)
4. Add FX rates to `config/fx_rates.json` if a new currency is involved

The engine discovers and processes the new file automatically on the next run.

---

### Configuration Files

**`config/consolidation_config.json`**
```json
{
  "group_name": "Parent Co Group",
  "reporting_currency": "USD",
  "reporting_period": "2024-12",
  "parent_entity": "Parent Co",
  "entities": [
    { "name": "Parent Co", "currency": "USD", "ownership_pct": 100, "role": "parent" },
    { "name": "Sub SGD",   "currency": "SGD", "ownership_pct": 100, "role": "subsidiary" }
  ],
  "tolerance": {
    "bs_balance_threshold_usd": 1.0,
    "ico_mismatch_threshold_usd": 1.0
  },
  "ico_validation": {
    "auto_derive_from_subsidiaries": true,
    "timing_diff_threshold_usd": 5.0,
    "require_bilateral_confirmation": true
  }
}
```

Set `auto_derive_from_subsidiaries: false` to fall back to reading `intercompany_matrix.xlsx`
directly — identical behaviour to a pre-ICO-tab deployment.

---

### Subsidiary Excel Template

All tabs use fixed column positions — the reader uses column index, not header name.

**BS / IS / CF tabs:**
| Col 0 | Col 1 | Col 2 |
|---|---|---|
| account_code | account_name | amount |

**EQ tab:**
| Col 0 | Col 1 | Col 2 | Col 3 |
|---|---|---|---|
| component | opening | movement | closing |

**META tab:**
| Col 0 | Col 1 |
|---|---|
| key | value |

Keys: `entity_name`, `currency`, `reporting_period`, `ownership_pct`

**ICO tab:**
| Col 0 | Col 1 | Col 2 | Col 3 | Col 4 | Col 5 |
|---|---|---|---|---|---|
| account_no | to_party | account_type | amount | currency (opt) | description (opt) |

`to_party` must exactly match the entity name in `consolidation_config.json`.
`account_type` is the bilateral matching key — use a consistent label on both sides of each pair.

---

### Running the Engine

```bash
# Install dependencies
pip install pandas openpyxl pydantic

# Generate mock test data (creates all subsidiary workbooks and config files)
python mock_data_generator.py

# Run consolidation
python main.py

# Output: output/consolidated_report.xlsx
```

**On Windows with Anaconda:**
```powershell
$python = "D:\Anaconda3_10_24\envs\fin-consol\python.exe"
& $python mock_data_generator.py
& $python main.py
```

---

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| pandas | >= 2.0 | ICO matrix manipulation and bilateral matching |
| openpyxl | >= 3.1 | Reading subsidiary workbooks and writing the output report |
| pydantic | >= 2.0 | Typed, validated data models throughout the pipeline |

All other dependencies (`json`, `logging`, `pathlib`, `collections`) are Python stdlib.

---

### Design Constraints (from `CLAUDE.md`)

- **No hardcoded account codes** anywhere in `.py` files. All account classification is read from `coa_mapping.xlsx` at runtime via `coa.get_classification(group_code)`.
- **No hardcoded entity names.** Entity list, ownership percentages, and reporting currency are read from `consolidation_config.json`.
- **No hardcoded currencies.** Any ISO currency code supported as long as rates are in `fx_rates.json`.
- **`classify_account_statement()`** lives in `models.py` only — not duplicated across modules.
- **ICO detection logic** stays in `ico_detector.py`; elimination logic stays in `eliminations.py`.
- **FX differences on ICO eliminations** must go to OCI (account 3200) — never averaged into the elimination amount, never through P&L.
