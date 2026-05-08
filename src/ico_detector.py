from __future__ import annotations
import logging

import pandas as pd

from src.models import SubsidiaryData, ValidationMessage, classify_account_statement

logger = logging.getLogger(__name__)


def build_derived_matrix(
    subsidiaries: dict[str, SubsidiaryData],
    coa,
    config: dict,
    fx,
) -> pd.DataFrame:
    """Read sub.ico from each SubsidiaryData and build the 7-column matrix DataFrame.

    Columns: from_entity, to_entity, account_type, group_account_code,
             amount_original_ccy, currency, side, _source
    """
    rows = []
    for entity_name, sub in subsidiaries.items():
        for line in sub.ico:
            classification = coa.get_classification(line.group_code)
            side = _classification_to_side(classification)
            rows.append({
                "from_entity": entity_name,
                "to_entity": line.to_party,
                "account_type": line.account_type,
                "group_account_code": line.group_code,
                "amount_original_ccy": line.amount_local,
                "currency": line.currency,
                "side": side,
                "_source": "AUTO_DERIVED",
            })

    if not rows:
        return pd.DataFrame(columns=[
            "from_entity", "to_entity", "account_type", "group_account_code",
            "amount_original_ccy", "currency", "side", "_source",
        ])
    return pd.DataFrame(rows)


def _classification_to_side(classification: str) -> str:
    mapping = {
        "Asset": "asset",
        "Liability": "liability",
        "Equity": "equity",
        "Income": "income",
        "Expense": "expense",
        "CF": "cf",
    }
    return mapping.get(classification, "asset")


def validate_derived_matrix(
    derived_df: pd.DataFrame,
    matrix_file_df: pd.DataFrame,
    fx,
    config: dict,
    validation_log: list[ValidationMessage],
) -> tuple[pd.DataFrame, bool]:
    """Run 5 validation gates and return (merged_df, has_fatal_errors).

    Gate order: 4 (dedup/merge) -> 1 (bilateral) -> 2 (FX tolerance) ->
                3 (account type consistency) -> 5 (currency mismatch)
    """
    ico_cfg = config.get("ico_validation", {})
    timing_threshold = float(ico_cfg.get("timing_diff_threshold_usd", 5.0))
    require_bilateral = bool(ico_cfg.get("require_bilateral_confirmation", True))
    has_fatal = False

    merge_key = ["from_entity", "to_entity", "account_type"]

    # Gate 4: Merge — matrix file rows win on (from_entity, to_entity, account_type) conflict
    if not matrix_file_df.empty:
        matrix_file_df = matrix_file_df.copy()
        matrix_file_df["_source"] = "MATRIX_FILE"

        if not derived_df.empty:
            matrix_keys = set(
                zip(
                    matrix_file_df["from_entity"].str.strip(),
                    matrix_file_df["to_entity"].str.strip(),
                    matrix_file_df["account_type"].str.strip(),
                )
            )
            derived_keys = list(
                zip(
                    derived_df["from_entity"],
                    derived_df["to_entity"],
                    derived_df["account_type"],
                )
            )
            override_mask = [k in matrix_keys for k in derived_keys]
            for i, is_override in enumerate(override_mask):
                if is_override:
                    row = derived_df.iloc[i]
                    key = (row["from_entity"], row["to_entity"], row["account_type"])
                    msg = f"Matrix-file row overrides auto-derived row: {key}"
                    validation_log.append(ValidationMessage(
                        severity="INFO",
                        category="ICO_MANUAL_OVERRIDE_APPLIED",
                        message=msg,
                    ))
                    logger.info("ICO_MANUAL_OVERRIDE_APPLIED: %s", key)

            non_overridden = derived_df[[not o for o in override_mask]]
            merged_df = pd.concat([matrix_file_df, non_overridden], ignore_index=True)
        else:
            merged_df = matrix_file_df.copy()
    else:
        merged_df = derived_df.copy() if not derived_df.empty else pd.DataFrame(
            columns=["from_entity", "to_entity", "account_type", "group_account_code",
                     "amount_original_ccy", "currency", "side", "_source"]
        )

    if merged_df.empty:
        return merged_df, False

    # Normalise string columns to avoid whitespace mismatches in subsequent gates
    for col in ["from_entity", "to_entity", "account_type"]:
        if col in merged_df.columns:
            merged_df[col] = merged_df[col].astype(str).str.strip()

    # Gate 1: Bilateral completeness
    for _, row in merged_df.iterrows():
        entity_a = row["from_entity"]
        entity_b = row["to_entity"]
        acct_type = row["account_type"]

        counter = merged_df[
            (merged_df["from_entity"] == entity_b) &
            (merged_df["to_entity"] == entity_a) &
            (merged_df["account_type"] == acct_type)
        ]
        if counter.empty:
            severity = "ERROR" if require_bilateral else "WARNING"
            msg = (
                f"ICO_BILATERAL_MISSING: {entity_a}->{entity_b} [{acct_type}] "
                "has no counter-row"
            )
            validation_log.append(ValidationMessage(
                severity=severity,
                category="ICO_BILATERAL_MISSING",
                message=msg,
            ))
            if severity == "ERROR":
                logger.error(msg)
            else:
                logger.warning(msg)
            if require_bilateral:
                has_fatal = True

    # Gate 2: FX tolerance check per bilateral pair
    processed_pairs_g2: set[frozenset] = set()
    for _, row in merged_df.iterrows():
        entity_a = row["from_entity"]
        entity_b = row["to_entity"]
        acct_type = row["account_type"]
        pair_key: frozenset = frozenset([entity_a + "|" + acct_type, entity_b + "|" + acct_type])
        if pair_key in processed_pairs_g2:
            continue
        processed_pairs_g2.add(pair_key)

        counter = merged_df[
            (merged_df["from_entity"] == entity_b) &
            (merged_df["to_entity"] == entity_a) &
            (merged_df["account_type"] == acct_type)
        ]
        if counter.empty:
            continue

        try:
            amt_a = float(row["amount_original_ccy"])
            ccy_a = str(row["currency"]).strip().upper()
            amt_b = float(counter.iloc[0]["amount_original_ccy"])
            ccy_b = str(counter.iloc[0]["currency"]).strip().upper()

            stmt_a_g2 = classify_account_statement(str(row.get("group_account_code", "0")).strip())
            stmt_b_g2 = classify_account_statement(str(counter.iloc[0].get("group_account_code", "0")).strip())
            rate_a_g2 = "closing" if stmt_a_g2 == "BS" else "average"
            rate_b_g2 = "closing" if stmt_b_g2 == "BS" else "average"
            usd_a = amt_a * fx.get_rate(ccy_a, rate_a_g2)
            usd_b = amt_b * fx.get_rate(ccy_b, rate_b_g2)
            diff = abs(usd_a - usd_b)

            if diff > timing_threshold:
                msg = (
                    f"ICO_TIMING_DIFF: {entity_a}<->{entity_b} [{acct_type}] "
                    f"FX diff = {diff:.2f} USD > threshold {timing_threshold}"
                )
                validation_log.append(ValidationMessage(
                    severity="WARNING",
                    category="ICO_TIMING_DIFF",
                    message=msg,
                ))
                logger.warning(msg)
        except Exception:
            pass

    # Gate 3: Account type consistency (side pairing)
    processed_pairs_g3: set[frozenset] = set()
    for _, row in merged_df.iterrows():
        entity_a = row["from_entity"]
        entity_b = row["to_entity"]
        acct_type = row["account_type"]
        pair_key = frozenset([entity_a + "|" + acct_type, entity_b + "|" + acct_type])
        if pair_key in processed_pairs_g3:
            continue
        processed_pairs_g3.add(pair_key)

        counter = merged_df[
            (merged_df["from_entity"] == entity_b) &
            (merged_df["to_entity"] == entity_a) &
            (merged_df["account_type"] == acct_type)
        ]
        if counter.empty:
            continue

        side_a = str(row.get("side", "")).lower()
        side_b = str(counter.iloc[0].get("side", "")).lower()
        valid_pairs = {
            ("asset", "liability"), ("liability", "asset"),
            ("income", "expense"), ("expense", "income"),
        }
        if (side_a, side_b) not in valid_pairs:
            msg = (
                f"ICO_ACCOUNT_TYPE_INCONSISTENCY: {entity_a}<->{entity_b} [{acct_type}] "
                f"unexpected side pairing: {side_a}<->{side_b}"
            )
            validation_log.append(ValidationMessage(
                severity="WARNING",
                category="ICO_ACCOUNT_TYPE_INCONSISTENCY",
                message=msg,
            ))
            logger.warning(msg)

    # Gate 5: Currency mismatch
    processed_pairs_g5: set[frozenset] = set()
    for _, row in merged_df.iterrows():
        entity_a = row["from_entity"]
        entity_b = row["to_entity"]
        acct_type = row["account_type"]
        pair_key = frozenset([entity_a + "|" + acct_type, entity_b + "|" + acct_type])
        if pair_key in processed_pairs_g5:
            continue
        processed_pairs_g5.add(pair_key)

        counter = merged_df[
            (merged_df["from_entity"] == entity_b) &
            (merged_df["to_entity"] == entity_a) &
            (merged_df["account_type"] == acct_type)
        ]
        if counter.empty:
            continue

        ccy_a = str(row.get("currency", "")).strip().upper()
        ccy_b = str(counter.iloc[0].get("currency", "")).strip().upper()
        if ccy_a and ccy_b and ccy_a != ccy_b:
            msg = (
                f"ICO_CURRENCY_MISMATCH: {entity_a}<->{entity_b} [{acct_type}] "
                f"currencies {ccy_a}!={ccy_b} (cross-currency ICO, valid but flagged)"
            )
            validation_log.append(ValidationMessage(
                severity="WARNING",
                category="ICO_CURRENCY_MISMATCH",
                message=msg,
            ))
            logger.info(msg)

    return merged_df, has_fatal
