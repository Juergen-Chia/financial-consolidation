Ready for review
Select text to add comments on the plan
Financial Consolidation Engine — Implementation Plan
Context
This is a greenfield Python project. Only CLAUDE.md exists; all code, config, data, and output files need to be created. The goal is a fully data-driven IFRS consolidation engine (IFRS 10 / IAS 21) that reads subsidiary Excel files, applies FX translation, eliminates intercompany balances, calculates NCI, and writes a formatted consolidated Excel report.

Files to Create (in dependency order)
Phase 1 — Static config (no Python deps)
File	Purpose
requirements.txt	pandas>=2.0, openpyxl>=3.1, pydantic>=2.0
config/fx_rates.json	FX rates SGD/EUR/USD + historical_rate for IAS 21.39(c)
config/consolidation_config.json	Entities, ownership %, reporting currency, balance tolerance
Note: fx_rates.json must include a historical_rate field per currency (used for equity translation of share capital). If absent, engine falls back to closing rate and logs WARNING.

Note: consolidation_config.json must include a tolerance section: bs_balance_threshold_usd: 1.0 and ico_mismatch_threshold_usd: 1.0 (1 USD tolerance handles FX rounding on cross-currency ICO).

Phase 2 — Mock data generator
File	Purpose
mock_data_generator.py	Generates all xlsx files in data/ — run this before main.py
Generates:

data/coa_mapping.xlsx — deliberately varied local codes per subsidiary to exercise reverse-lookup; adds classification column (Asset/Liability/Equity/Income/Expense) for data-driven BS validation
data/intercompany_matrix.xlsx — 6 rows (3 ICO pairs × 2 sides), includes side column (asset/liability) to disambiguate same-account-code loan elimination
data/subsidiaries/sub_sgd.xlsx, sub_usd.xlsx, sub_eur.xlsx, parent_co.xlsx
Mock data is designed to exercise every code path:

Code path exercised	How
FX closing-rate BS	Sub SGD and Sub EUR BS accounts
FX average-rate IS/CF	Sub SGD, Sub EUR income statement
FX historical-rate equity	Sub SGD share capital at historical_rate
FX translation reserve → OCI	Computed difference posted to account 3200
ICO BS elimination (cross-currency)	Sub SGD 1200 IC Receivable 50,000 SGD ↔ Parent Co 2100 IC Payable
ICO P&L elimination	Sub USD 4100 IC Revenue 30,000 USD ↔ Sub EUR 5100 IC COGS (27,726 EUR × average ≈ 30,000 USD)
Loan elimination (same account both sides)	Parent → Sub SGD 2300/2300 100,000 USD
Investment vs equity elimination	Parent 1700 Investment ↔ Sub share capitals at historical rate
NCI BS (20%)	Sub USD 80% owned → NCI = 20% × net assets post-elimination
NCI P&L (20%)	20% × Sub USD net profit
Unmapped account WARNING	Sub SGD local code "999" Miscellaneous — not in coa_mapping.xlsx
ICO near-mismatch (FX rounding)	27,726 EUR × 1.0820 = 29,999.8 vs 30,000 → within 1 USD tolerance
Phase 3 — Shared data models
File	Purpose
src/models.py	Pydantic v2 models shared by all pipeline modules
Key models:

EntityMeta — entity_name, currency, reporting_period, ownership_pct
AccountLine — group_code, amount_local, amount_usd (=0 before translation), entity_name, statement
EquityLine — component, opening/movement/closing in local + usd
SubsidiaryData — meta, bs, is_, cf, eq, unmapped_accounts
EliminationEntry — reference, from/to entity, account_code, amount_usd, elimination_type
FxTranslationEntry — entity, statement, group_code, rate_type, rate_used, amounts
ValidationMessage — severity (INFO/WARNING/ERROR), category, message
ConsolidatedData — entities list, bs/is_/cf/eq DataFrames, eliminations, fx_log, validation_messages, nci figures
Phase 4 — Pipeline modules (bottom-up)
src/reader.py
discover_subsidiaries(dir) -> list[Path] — scans for *.xlsx, dynamic discovery
read_subsidiary(path, coa) -> SubsidiaryData — reads by column index (not header name)
Reads META tab: col 0 = key label, col 1 = value
Reads BS/IS/CF tabs: col 0 = code, col 1 = name, col 2 = amount; skips blank rows (stops at 3 consecutive blanks)
Reads EQ tab: col 0 = component, col 1 = opening, col 2 = movement, col 3 = closing
Unmapped local codes → collected in SubsidiaryData.unmapped_accounts, not raised as exceptions
SubsidiaryReadError raised (halts) only for structural problems (missing tabs, non-numeric amounts)
src/coa_mapper.py
COAMapping class — loads coa_mapping.xlsx at construction, builds reverse lookup dict
Entity column names derived dynamically: "Sub SGD" → "sub_sgd_code" (lowercase + underscores + _code)
get_group_code(entity_col, local_code) -> str | None
all_group_codes() -> list[str] — drives output row order
classification(group_code) -> str — reads from classification column in coa_mapping.xlsx for BS balance validation
src/fx_translator.py
FXTranslator class — loads fx_rates.json at construction; reads all currencies dynamically
validate_currency(currency) — raises FXConfigError (ERROR+halt) if currency absent from config
translate_subsidiary(sub_data, STATEMENT_RATE_MAP) -> (SubsidiaryData, list[FxTranslationEntry])
STATEMENT_RATE_MAP = {"BS": "closing", "IS": "average", "CF": "average"}
EQ components translated using historical for share capital, average for P&L movement, closing for closing balance
compute_fx_translation_difference(sub_data) -> float — IAS 21.41 balancing figure posted to account 3200 (OCI)
All amounts rounded to 2 decimal places at translation (prevents cascade rounding errors)
src/eliminations.py
EliminationEngine class — loads intercompany_matrix.xlsx at construction
eliminate_intercompany(translated_data, validation_log) -> list[EliminationEntry]
Groups matrix rows by ICO pair using (from_entity, to_entity, account_type)
Translates both sides to USD (using the currency column in matrix)
If abs(side_a - side_b) > ico_mismatch_threshold: logs WARNING, eliminates at average of two sides
Uses side column in matrix to correctly handle same-account-code loan (2300/2300)
eliminate_investment_vs_equity(translated_data, config, validation_log) -> list[EliminationEntry]
Matches parent 1700 vs each sub's 3000 at historical rate
Non-zero residual → logs WARNING "Goodwill/Bargain purchase not handled — consult IFRS 3"
calculate_nci(translated_data, config, eliminations) -> (nci_bs_usd, nci_pl_usd, list[EliminationEntry])
NCI only for entities with ownership_pct < 100
NCI in BS posted to account 3300 (separate equity component — never netted)
NCI in P&L disclosed in EQ statement only — NOT deducted from consolidated IS
src/consolidator.py
Orchestration sequence (order is a hard constraint):

Load config, COA, FX rates, read all subsidiaries
validate_currency() for each sub → halt on ERROR
Translate all subs to USD (FX log populated)
Eliminate ICO balances (warnings logged for mismatches)
Eliminate Investment vs Equity
Calculate NCI
Aggregate: _aggregate(statement, translated_data, all_eliminations, coa) — builds DataFrame with entity columns + Group Total
Validate BS balance → halt if imbalance > threshold
Validate unmapped accounts, COA coverage
Return ConsolidatedData
_aggregate() logic: for each group_code, sum amount_usd per entity, then subtract elimination entries from the correct entity columns. Source SubsidiaryData objects are NOT mutated (eliminations applied at aggregation stage so FX log shows pre-elimination amounts).

_validate_bs_balance(): reads classification from COA to determine which rows are Assets vs Liabilities+Equity — no hardcoded account ranges.

src/report_writer.py
ReportWriter(output_path) + write(data: ConsolidatedData)
7 tabs: Consolidated BS, IS, CF, EQ, Eliminations Log, FX Translation Log, Validation
Entity columns generated from data.entities (dynamic — not hardcoded)
Uses openpyxl directly (not pandas ExcelWriter) for formatting control
Formatting: header bold, number format #,##0.00, calculated rows in bold
Phase 5 — Entry point
File	Purpose
main.py	Initialises logging, calls Consolidator.run() → ReportWriter.write(), exits 1 on ConsolidationError
output/	Directory created if absent
Key Design Decisions
Decision	Rationale
Add src/models.py (not in spec)	Shared Pydantic models prevent ad-hoc dicts between modules; single source of truth for inter-module contracts
Add classification column to coa_mapping.xlsx	Enables data-driven BS balance validation without hardcoded account code ranges
Add historical_rate to fx_rates.json	Required for IAS 21.39(c) equity translation of share capital
Add side column to intercompany_matrix.xlsx	Disambiguates same-account-code loan elimination (2300/2300)
ICO tolerance = 1.00 USD (not 0.01)	Cross-currency ICO (EUR ↔ USD) produces ~0.20 USD FX rounding difference; 1 USD avoids false mismatches
Eliminations applied at aggregation (not to source data)	Keeps SubsidiaryData pristine for FX Translation Log (shows pre-elimination translated amounts)
NCI NOT deducted from consolidated IS	Correct IFRS 10 treatment — NCI share of profit shown only in EQ statement
openpyxl direct (not pandas ExcelWriter) for output	Full formatting control required for 7-tab report
Tricky Edge Cases to Handle
FX translation reserve: If FX diff not computed and posted to OCI (3200), the BS will fail the balance check — this provides implicit test coverage of the FX diff logic
NCI placement: NCI only in BS (3300) and EQ — NOT as a deduction in IS
Loan elimination (2300/2300): Uses side column in matrix to distinguish which entity holds asset vs liability side
Investment residual: Log WARNING if Parent 1700 ≠ Sub 3000 at historical rate; do not attempt IFRS 3 goodwill accounting
Blank rows in Excel: Skip rows where account_code cell is empty; stop after 3 consecutive blank rows
Parent as "subsidiary" file: consolidation_config.json identifies the parent entity; consolidator skips investment-vs-equity elimination for parent-vs-parent
Verification Steps
# Step 1: Install dependencies
pip install pandas openpyxl pydantic

# Step 2: Generate clean mock data
python mock_data_generator.py
# Expected: data/subsidiaries/*.xlsx, data/coa_mapping.xlsx, data/intercompany_matrix.xlsx created

# Step 3: Run consolidation
python main.py
# Expected: output/consolidated_report.xlsx created with 7 tabs
# Expected log output:
#   WARNING | eliminations | Unmapped account '999' in Sub SGD excluded from consolidation
#   WARNING | eliminations | ICO near-mismatch: Sub EUR 5100 vs Sub USD 4100 diff=0.20 USD (within tolerance)
#   INFO    | consolidator | BS balanced within tolerance
#   INFO    | main         | Consolidation complete. Output: output/consolidated_report.xlsx

# Step 4: Spot-check output
# Consolidated BS: Assets total should equal Liabilities + Equity + NCI
# Consolidated IS: Group Revenue excludes IC Revenue (4100); Group Net Profit = sum of all entities' net profits (including NCI's share)
# NCI line in Consolidated BS = 20% × Sub USD net assets post-elimination
# Eliminations Log should show all 3 ICO pairs + investment eliminations
# Validation tab should show the unmapped account WARNING for Sub SGD account 999