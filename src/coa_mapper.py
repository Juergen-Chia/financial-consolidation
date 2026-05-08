from __future__ import annotations
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class COAMapping:
    def __init__(self, coa_path: Path) -> None:
        self._df = pd.read_excel(coa_path, dtype=str)
        self._df = self._df.fillna("")
        self._df["group_code"] = self._df["group_code"].str.strip()

        # Discover entity-specific code columns dynamically (end with '_code', not 'group_code')
        self._entity_cols: list[str] = [
            c for c in self._df.columns
            if c.endswith("_code") and c != "group_code"
        ]

        # Build reverse lookup: {entity_col: {local_code: group_code}}
        self._reverse: dict[str, dict[str, str]] = {}
        for col in self._entity_cols:
            mapping: dict[str, str] = {}
            for _, row in self._df.iterrows():
                local_code = str(row[col]).strip()
                if local_code:
                    mapping[local_code] = str(row["group_code"]).strip()
            self._reverse[col] = mapping

        logger.info(
            "COA loaded: %d group accounts, entity columns: %s",
            len(self._df),
            self._entity_cols,
        )

    def entity_column_name(self, entity_name: str) -> str:
        return entity_name.lower().replace(" ", "_") + "_code"

    def get_group_code(self, entity_name: str, local_code: str) -> str | None:
        col = self.entity_column_name(entity_name)
        if col not in self._reverse:
            return None
        return self._reverse[col].get(str(local_code).strip())

    def get_group_account_name(self, group_code: str) -> str:
        row = self._df[self._df["group_code"] == str(group_code).strip()]
        if row.empty:
            return f"Unknown ({group_code})"
        return str(row.iloc[0]["group_account_name"])

    def classification(self, group_code: str) -> str:
        row = self._df[self._df["group_code"] == str(group_code).strip()]
        if row.empty or "classification" not in self._df.columns:
            return "Unknown"
        return str(row.iloc[0].get("classification", "Unknown"))

    def get_classification(self, group_code: str) -> str:
        return self.classification(group_code)

    def all_group_codes(self) -> list[str]:
        return list(self._df["group_code"].values)
