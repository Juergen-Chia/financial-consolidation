from __future__ import annotations
import logging
from pathlib import Path

import pandas as pd

from src.models import (
    EliminationEntry, SubsidiaryData, ValidationMessage
)
from src.fx_translator import FXTranslator

logger = logging.getLogger(__name__)

_ELIM_COUNTER = 0


def _ref(prefix: str) -> str:
    global _ELIM_COUNTER
    _ELIM_COUNTER += 1
    return f"{prefix}-{_ELIM_COUNTER:04d}"


class EliminationEngine:
    def __init__(self, matrix_path: Path, fx: FXTranslator, config: dict) -> None:
        self._matrix = pd.read_excel(matrix_path, dtype=str).fillna("")
        self._fx = fx
        self._tolerance: float = float(
            config.get("tolerance", {}).get("ico_mismatch_threshold_usd", 1.0)
        )
        logger.info("Intercompany matrix loaded: %d rows", len(self._matrix))

    def eliminate_intercompany(
        self,
        translated_data: dict[str, SubsidiaryData],
        validation_log: list[ValidationMessage],
    ) -> list[EliminationEntry]:
        entries: list[EliminationEntry] = []
        matrix = self._matrix

        processed_pairs: set[frozenset] = set()

        for _, row_a in matrix.iterrows():
            key_a = frozenset([
                row_a["from_entity"].strip(),
                row_a["to_entity"].strip(),
                row_a["account_type"].strip(),
            ])
            if key_a in processed_pairs:
                continue

            # Find counter-row
            mask = (
                (matrix["from_entity"].str.strip() == row_a["to_entity"].strip()) &
                (matrix["to_entity"].str.strip() == row_a["from_entity"].strip()) &
                (matrix["account_type"].str.strip() == row_a["account_type"].strip())
            )
            matching = matrix[mask]

            if matching.empty:
                validation_log.append(ValidationMessage(
                    severity="WARNING",
                    category="ICO_UNMATCHED",
                    message=(
                        f"No counter-entry for ICO: {row_a['from_entity']} -> "
                        f"{row_a['to_entity']} [{row_a['account_type']}]"
                    ),
                ))
                processed_pairs.add(key_a)
                continue

            row_b = matching.iloc[0]
            processed_pairs.add(key_a)
            processed_pairs.add(frozenset([
                row_b["from_entity"].strip(),
                row_b["to_entity"].strip(),
                row_b["account_type"].strip(),
            ]))

            amt_a_local = float(row_a["amount_original_ccy"])
            amt_b_local = float(row_b["amount_original_ccy"])
            ccy_a = row_a["currency"].strip().upper()
            ccy_b = row_b["currency"].strip().upper()

            account_code_a = str(row_a["group_account_code"]).strip()
            stmt_a = _classify_account_statement(account_code_a)
            rate_type = "closing" if stmt_a == "BS" else "average"

            amt_a_usd = self._fx.translate_amount(amt_a_local, ccy_a, rate_type)
            amt_b_usd = self._fx.translate_amount(amt_b_local, ccy_b, rate_type)

            diff = abs(amt_a_usd - amt_b_usd)
            if diff > self._tolerance:
                validation_log.append(ValidationMessage(
                    severity="WARNING",
                    category="ICO_MISMATCH",
                    message=(
                        f"ICO mismatch: {row_a['from_entity']} -> {row_a['to_entity']} "
                        f"[{row_a['account_type']}]: "
                        f"side A={amt_a_usd:.2f} USD vs side B={amt_b_usd:.2f} USD, "
                        f"diff={diff:.2f} USD"
                    ),
                ))
                logger.warning(
                    "ICO mismatch %.2f USD: %s / %s [%s]",
                    diff, row_a["from_entity"], row_a["to_entity"], row_a["account_type"]
                )
            else:
                logger.info(
                    "ICO match OK: %s <-> %s [%s] %.2f USD",
                    row_a["from_entity"], row_a["to_entity"], row_a["account_type"], amt_a_usd
                )

            elim_amount = round((amt_a_usd + amt_b_usd) / 2, 2)
            elim_type = "ICO_PL" if stmt_a == "IS" else "ICO_BALANCE"
            ref = _ref("ICO")

            entries.append(EliminationEntry(
                reference=ref,
                description=(
                    f"Eliminate ICO {row_a['from_entity']} -> {row_a['to_entity']}: "
                    f"{row_a['account_type']} (Side A)"
                ),
                from_entity=str(row_a["from_entity"]).strip(),
                to_entity=str(row_a["to_entity"]).strip(),
                account_code=account_code_a,
                account_name=str(row_a.get("account_type", "")),
                statement=stmt_a,
                amount_usd=elim_amount,
                elimination_type=elim_type,
            ))
            entries.append(EliminationEntry(
                reference=ref,
                description=(
                    f"Eliminate ICO {row_b['from_entity']} -> {row_b['to_entity']}: "
                    f"{row_b['account_type']} (Side B)"
                ),
                from_entity=str(row_b["from_entity"]).strip(),
                to_entity=str(row_b["to_entity"]).strip(),
                account_code=str(row_b["group_account_code"]).strip(),
                account_name=str(row_b.get("account_type", "")),
                statement=stmt_a,
                amount_usd=elim_amount,
                elimination_type=elim_type,
            ))

        logger.info("ICO eliminations: %d entries generated", len(entries))
        return entries

    def eliminate_investment_vs_equity(
        self,
        translated_data: dict[str, SubsidiaryData],
        consolidation_config: dict,
        validation_log: list[ValidationMessage],
    ) -> list[EliminationEntry]:
        """
        Eliminate parent 1700 against each subsidiary's SC (3000).
        Parent's 1700 records ownership% x sub SC at historical rates.
        Only the parent's ownership% of sub SC is eliminated (not 100%);
        NCI's share remains and is reclassified by calculate_nci().
        """
        entries: list[EliminationEntry] = []
        parent_name = consolidation_config["parent_entity"]
        entities_cfg = {e["name"]: e for e in consolidation_config["entities"]}
        parent = translated_data.get(parent_name)
        if parent is None:
            logger.warning("Parent entity '%s' not found -- skipping investment elimination", parent_name)
            return entries

        total_parent_investment = sum(
            l.amount_usd for l in parent.bs if l.group_code == "1700"
        )
        if total_parent_investment == 0.0:
            logger.info("Parent has no Investment in Subsidiaries (1700) -- skipping")
            return entries

        inv_ref = _ref("INV")

        # Eliminate the full parent 1700 balance in one entry
        entries.append(EliminationEntry(
            reference=inv_ref,
            description="Eliminate Investment in Subsidiaries (Parent 1700) -- full balance",
            from_entity=parent_name,
            to_entity="All subsidiaries",
            account_code="1700",
            account_name="Investment in Subsidiaries",
            statement="BS",
            amount_usd=total_parent_investment,
            elimination_type="INVESTMENT_EQUITY",
        ))
        logger.info("Eliminating Parent 1700 total: %.2f USD", total_parent_investment)

        # Eliminate parent's ownership% of each subsidiary's SC (3000)
        total_parent_sc_elim = 0.0
        for sub_name, sub in translated_data.items():
            if sub_name == parent_name:
                continue
            ownership_pct = entities_cfg.get(sub_name, {}).get("ownership_pct", 100) / 100
            sc_lines = [l for l in sub.bs if l.group_code == "3000"]
            sub_sc_usd = sum(l.amount_usd for l in sc_lines)
            if not sc_lines:
                logger.info("No Share Capital (3000) for %s -- skipping", sub_name)
                continue
            # Eliminate only parent's ownership share of the sub's SC
            parent_share_sc = round(ownership_pct * sub_sc_usd, 2)
            total_parent_sc_elim += parent_share_sc
            entries.append(EliminationEntry(
                reference=inv_ref,
                description=(
                    f"Eliminate {ownership_pct*100:.0f}% of {sub_name} SC "
                    f"(parent share: {parent_share_sc:.2f} USD)"
                ),
                from_entity=sub_name,
                to_entity=parent_name,
                account_code="3000",
                account_name="Share Capital",
                statement="BS",
                amount_usd=parent_share_sc,
                elimination_type="INVESTMENT_EQUITY",
            ))
            logger.info(
                "SC elimination for %s (%.0f%%): %.2f USD",
                sub_name, ownership_pct * 100, parent_share_sc
            )

        residual = round(total_parent_investment - total_parent_sc_elim, 2)
        if abs(residual) > 1.0:
            validation_log.append(ValidationMessage(
                severity="WARNING",
                category="INVESTMENT_RESIDUAL",
                message=(
                    f"Investment vs equity residual: "
                    f"Parent 1700={total_parent_investment:.2f} USD, "
                    f"Parent share of sub SCs={total_parent_sc_elim:.2f} USD, "
                    f"diff={residual:.2f} USD -- "
                    "Goodwill/Bargain purchase not handled; consult IFRS 3."
                ),
            ))

        return entries

    def calculate_nci(
        self,
        translated_data: dict[str, SubsidiaryData],
        consolidation_config: dict,
        all_eliminations: list[EliminationEntry],
    ) -> tuple[float, float, list[EliminationEntry]]:
        """
        NCI reclassification: NCI's share of sub equity is reclassified from
        the original equity codes (3000, 3100, 3200) into account 3300 (NCI).
        Net impact on total equity = zero (balanced reclassification).
        Parent's investment elimination already removed only the parent's ownership% of SC;
        NCI's remaining SC share + NCI's share of RE/OCI are reclassified here.
        """
        nci_entries: list[EliminationEntry] = []
        total_nci_bs = 0.0
        total_nci_pl = 0.0

        entities_cfg = {e["name"]: e for e in consolidation_config["entities"]}
        parent_name = consolidation_config["parent_entity"]

        for sub_name, sub in translated_data.items():
            if sub_name == parent_name:
                continue
            ownership = entities_cfg.get(sub_name, {}).get("ownership_pct", 100)
            if ownership >= 100:
                continue

            nci_pct = (100 - ownership) / 100
            ref = _ref("NCI")
            nci_total_bs = 0.0

            # Reclassify NCI's share of each equity line from its original code to 3300
            for line in sub.bs:
                if not (line.group_code.startswith("3") and line.group_code not in ("3300",)):
                    continue
                nci_share = round(nci_pct * line.amount_usd, 2)
                if nci_share == 0.0:
                    continue
                nci_total_bs += nci_share

                # Deduct from source equity account
                nci_entries.append(EliminationEntry(
                    reference=ref,
                    description=(
                        f"NCI reclassification: {nci_pct*100:.0f}% of "
                        f"{sub_name} {line.group_account_name} -> 3300"
                    ),
                    from_entity=sub_name,
                    to_entity="NCI",
                    account_code=line.group_code,
                    account_name=line.group_account_name,
                    statement="BS",
                    amount_usd=nci_share,
                    elimination_type="NCI",
                ))
                # Add to NCI account 3300
                nci_entries.append(EliminationEntry(
                    reference=ref,
                    description=(
                        f"NCI reclassification: {nci_pct*100:.0f}% of "
                        f"{sub_name} {line.group_account_name} into NCI equity"
                    ),
                    from_entity="NCI",
                    to_entity=sub_name,
                    account_code="3300",
                    account_name="Non-Controlling Interest",
                    statement="BS",
                    amount_usd=-nci_share,   # negative = credit to 3300 (adds equity)
                    elimination_type="NCI",
                ))

            total_nci_bs += nci_total_bs

            # NCI in P&L = NCI% * subsidiary net profit (income - expenses)
            income = sum(
                l.amount_usd for l in sub.is_
                if l.group_code.startswith("4") or l.group_code == "6300"
            )
            expenses = sum(
                l.amount_usd for l in sub.is_
                if l.group_code.startswith("5")
                or l.group_code in ("6100", "6200", "6400", "6500")
            )
            net_profit = income - expenses
            nci_pl = round(nci_pct * net_profit, 2)
            total_nci_pl += nci_pl

            logger.info(
                "NCI for %s: BS=%.2f USD, P&L=%.2f USD (%.0f%%)",
                sub_name, nci_total_bs, nci_pl, nci_pct * 100
            )

        return total_nci_bs, total_nci_pl, nci_entries


def _classify_account_statement(group_code: str) -> str:
    try:
        code_int = int(group_code)
    except (ValueError, TypeError):
        return "BS"
    if 4000 <= code_int <= 6999:
        return "IS"
    if 7000 <= code_int <= 8999:
        return "CF"
    return "BS"
