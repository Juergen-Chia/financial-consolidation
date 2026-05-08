from __future__ import annotations
import json
import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.coa_mapper import COAMapping
from src.eliminations import EliminationEngine
from src.fx_translator import FXTranslator
from src.ico_detector import build_derived_matrix, validate_derived_matrix
from src.models import (
    ConsolidatedData, EliminationEntry, SubsidiaryData,
    ValidationMessage,
)
from src.reader import SubsidiaryReadError, discover_subsidiaries, read_subsidiary

logger = logging.getLogger(__name__)


class ConsolidationError(Exception):
    pass


class Consolidator:
    def __init__(self, config_dir: Path, data_dir: Path) -> None:
        self._config_dir = config_dir
        self._data_dir = data_dir
        self._subsidiaries_dir = data_dir / "subsidiaries"
        self._coa_path = data_dir / "coa_mapping.xlsx"
        self._matrix_path = data_dir / "intercompany_matrix.xlsx"
        self._fx_config_path = config_dir / "fx_rates.json"
        self._consol_config_path = config_dir / "consolidation_config.json"

    def run(self) -> ConsolidatedData:
        with open(self._consol_config_path, encoding="utf-8") as f:
            config = json.load(f)

        coa = COAMapping(self._coa_path)
        fx = FXTranslator(self._fx_config_path)
        validation_log: list[ValidationMessage] = []

        # Step 1: Discover and read
        paths = discover_subsidiaries(self._subsidiaries_dir)
        if not paths:
            raise ConsolidationError("No subsidiary files found in data/subsidiaries/")

        raw_data: dict[str, SubsidiaryData] = {}
        for path in paths:
            try:
                sub = read_subsidiary(path, coa)
            except SubsidiaryReadError as exc:
                raise ConsolidationError(str(exc)) from exc
            fx.validate_currency(sub.meta.currency)  # ERROR+halt if unknown
            raw_data[sub.meta.entity_name] = sub
            logger.info("Read %s (%s, %.0f%% owned)", sub.meta.entity_name, sub.meta.currency, sub.meta.ownership_pct)

        # Step 2: FX translation
        translated_data: dict[str, SubsidiaryData] = {}
        fx_log = []
        for name, sub in raw_data.items():
            translated, log_entries = fx.translate_subsidiary(sub)
            translated_data[name] = translated
            fx_log.extend(log_entries)

        # Step 3: Build elimination engine (auto-derive ICO pairs if configured)
        ico_cfg = config.get("ico_validation", {})
        if ico_cfg.get("auto_derive_from_subsidiaries", False):
            derived_df = build_derived_matrix(translated_data, coa, config, fx)
            file_matrix_df = pd.read_excel(self._matrix_path, dtype=str).fillna("")
            merged_df, has_fatal = validate_derived_matrix(
                derived_df, file_matrix_df, fx, config, validation_log
            )
            if has_fatal:
                raise ConsolidationError(
                    "ICO bilateral completeness check failed — see Validation tab for ICO_BILATERAL_MISSING"
                )
            elim_engine = EliminationEngine(self._matrix_path, fx, config, derived_df=merged_df)
        else:
            elim_engine = EliminationEngine(self._matrix_path, fx, config)

        # Step 3: ICO eliminations
        ico_entries = elim_engine.eliminate_intercompany(translated_data, validation_log)

        # Step 4: Investment vs equity elimination
        inv_entries = elim_engine.eliminate_investment_vs_equity(translated_data, config, validation_log)

        # Step 5: NCI
        nci_bs, nci_pl, nci_entries = elim_engine.calculate_nci(
            translated_data, config, ico_entries + inv_entries, coa=coa
        )

        all_eliminations = ico_entries + inv_entries + nci_entries

        # Step 6: Aggregate
        entity_order = [e["name"] for e in config["entities"]]
        entity_order = [e for e in entity_order if e in translated_data]

        bs_rows = self._aggregate("BS", translated_data, all_eliminations, coa, entity_order, nci_bs=nci_bs)
        is_rows = self._aggregate("IS", translated_data, all_eliminations, coa, entity_order)
        cf_rows = self._aggregate("CF", translated_data, all_eliminations, coa, entity_order)
        eq_rows = self._aggregate_equity(translated_data, entity_order, nci_pl)

        # Step 7: Validate
        self._validate_bs_balance(bs_rows, validation_log, config)
        self._validate_unmapped(raw_data, validation_log)
        self._validate_coa_coverage(coa, translated_data, validation_log)

        return ConsolidatedData(
            entities=entity_order,
            bs_rows=bs_rows,
            is_rows=is_rows,
            cf_rows=cf_rows,
            eq_rows=eq_rows,
            eliminations=all_eliminations,
            fx_log=fx_log,
            validation_messages=validation_log,
            nci_bs_usd=nci_bs,
            nci_pl_usd=nci_pl,
        )

    def _aggregate(
        self,
        statement: str,
        translated_data: dict[str, SubsidiaryData],
        eliminations: list[EliminationEntry],
        coa: COAMapping,
        entity_order: list[str],
        nci_bs: float = 0.0,
    ) -> list[dict]:
        # Build {group_code: {entity_name: sum_usd}}
        totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for entity_name in entity_order:
            sub = translated_data[entity_name]
            lines = {"BS": sub.bs, "IS": sub.is_, "CF": sub.cf}[statement]
            for line in lines:
                totals[line.group_code][entity_name] += line.amount_usd

        # Apply eliminations
        for entry in eliminations:
            if entry.statement != statement:
                continue
            code = entry.account_code
            entity = entry.from_entity

            if entry.elimination_type == "NCI":
                if entity in entity_order:
                    # Deduct NCI's share from source equity account (sub's column)
                    totals[code][entity] -= entry.amount_usd
                elif entity == "NCI":
                    # Add NCI's reclassified amount into 3300 group NCI column
                    # amount_usd is negative here (credit to 3300), so subtract to add
                    totals[code]["NCI"] = totals[code].get("NCI", 0.0) - entry.amount_usd
            else:
                # Standard elimination: subtract from the entity's column
                if entity in entity_order:
                    totals[code][entity] -= entry.amount_usd
                # "All subsidiaries" pseudo-entity (investment side A) has no column to adjust

        rows: list[dict] = []
        for group_code in coa.all_group_codes():
            entity_amounts = totals.get(group_code, {})
            if not any(v != 0.0 for v in entity_amounts.values()):
                continue
            row: dict = {
                "group_code": group_code,
                "group_account_name": coa.get_group_account_name(group_code),
            }
            group_total = 0.0
            for entity in entity_order:
                amt = entity_amounts.get(entity, 0.0)
                row[entity] = amt
                group_total += amt
            # Include NCI column if present
            if "NCI" in entity_amounts:
                row["NCI"] = entity_amounts["NCI"]
                group_total += entity_amounts["NCI"]
            row["Group Total"] = round(group_total, 2)
            rows.append(row)

        return rows

    def _aggregate_equity(
        self,
        translated_data: dict[str, SubsidiaryData],
        entity_order: list[str],
        nci_pl: float,
    ) -> list[dict]:
        component_order: list[str] = []
        seen: set[str] = set()
        data: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

        for entity in entity_order:
            sub = translated_data[entity]
            for eq in sub.eq:
                comp = eq.component
                if comp not in seen:
                    component_order.append(comp)
                    seen.add(comp)
                data[comp][entity]["opening"] += eq.opening_usd
                data[comp][entity]["movement"] += eq.movement_usd
                data[comp][entity]["closing"] += eq.closing_usd

        rows: list[dict] = []
        for comp in component_order:
            for col in ("opening", "movement", "closing"):
                row: dict = {"component": comp, "period": col.title()}
                group_total = 0.0
                for entity in entity_order:
                    amt = data[comp][entity].get(col, 0.0)
                    row[entity] = amt
                    group_total += amt
                row["Group Total"] = round(group_total, 2)
                rows.append(row)

        if nci_pl != 0.0:
            rows.append({
                "component": "NCI Share of Profit",
                "period": "Movement",
                **{e: 0.0 for e in entity_order},
                "Group Total": round(nci_pl, 2),
            })

        return rows

    def _validate_bs_balance(
        self,
        bs_rows: list[dict],
        validation_log: list[ValidationMessage],
        config: dict,
    ) -> None:
        threshold = float(config.get("tolerance", {}).get("bs_balance_threshold_usd", 1.0))
        total_assets = 0.0
        total_liab_equity = 0.0

        # We rely on the classification column from COA — but since we have rows already,
        # determine sign by checking if codes start with 1 (assets) vs 2/3 (liab+equity)
        for row in bs_rows:
            code = str(row["group_code"])
            amt = float(row.get("Group Total", 0.0))
            try:
                code_int = int(code)
            except ValueError:
                continue
            if 1000 <= code_int <= 1999:
                total_assets += amt
            elif 2000 <= code_int <= 3999:
                total_liab_equity += amt

        diff = abs(total_assets - total_liab_equity)
        logger.info(
            "BS validation: Assets=%.2f, Liabilities+Equity=%.2f, diff=%.2f",
            total_assets, total_liab_equity, diff
        )

        if diff > threshold:
            raise ConsolidationError(
                f"Balance Sheet out of balance: Assets={total_assets:.2f} vs "
                f"Liabilities+Equity={total_liab_equity:.2f}, diff={diff:.2f} USD "
                f"(threshold={threshold} USD)"
            )

        validation_log.append(ValidationMessage(
            severity="INFO",
            category="BS_BALANCE",
            message=f"Balance Sheet balanced within tolerance (diff={diff:.4f} USD)",
            detail=f"Assets={total_assets:.2f} | Liab+Equity={total_liab_equity:.2f}",
        ))

    def _validate_unmapped(
        self,
        raw_data: dict[str, SubsidiaryData],
        validation_log: list[ValidationMessage],
    ) -> None:
        for sub in raw_data.values():
            for ua in sub.unmapped_accounts:
                validation_log.append(ValidationMessage(
                    severity="WARNING",
                    category="UNMAPPED_ACCOUNT",
                    message=f"Unmapped account in {ua['entity']}: local code '{ua['local_code']}' ({ua['account_name']}) excluded",
                    detail=f"Statement={ua['statement']}, Amount={ua['amount']} {sub.meta.currency}",
                ))

    def _validate_coa_coverage(
        self,
        coa: COAMapping,
        translated_data: dict[str, SubsidiaryData],
        validation_log: list[ValidationMessage],
    ) -> None:
        all_used_codes: set[str] = set()
        for sub in translated_data.values():
            for lines in (sub.bs, sub.is_, sub.cf):
                for line in lines:
                    all_used_codes.add(line.group_code)

        for code in coa.all_group_codes():
            if code not in all_used_codes:
                validation_log.append(ValidationMessage(
                    severity="INFO",
                    category="UNUSED_ACCOUNT",
                    message=f"COA account {code} ({coa.get_group_account_name(code)}) has no data in any subsidiary",
                ))
