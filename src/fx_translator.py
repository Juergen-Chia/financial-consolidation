from __future__ import annotations
import json
import logging
from pathlib import Path

from src.models import (
    AccountLine, EquityLine, FxTranslationEntry, SubsidiaryData
)

logger = logging.getLogger(__name__)

STATEMENT_RATE_MAP: dict[str, str] = {
    "BS": "closing",
    "IS": "average",
    "CF": "average",
}

# IAS 21: equity BS items use historical rate; assets/liabilities use closing rate
_EQUITY_BS_CODES = {"3000", "3100"}   # SC and Retained Earnings


class FXConfigError(Exception):
    pass


class FXTranslator:
    def __init__(self, fx_config_path: Path) -> None:
        with open(fx_config_path, encoding="utf-8") as f:
            config = json.load(f)
        self._reporting_currency: str = config["reporting_currency"]
        self._rates: dict[str, dict[str, float]] = config["rates"]
        logger.info(
            "FX config loaded: reporting=%s, currencies=%s",
            self._reporting_currency,
            list(self._rates.keys()),
        )

    def validate_currency(self, currency: str) -> None:
        if currency not in self._rates:
            raise FXConfigError(
                f"Currency '{currency}' not found in fx_rates.json — "
                "add it before running consolidation."
            )

    def get_rate(self, currency: str, rate_type: str) -> float:
        if currency == self._reporting_currency:
            return 1.0
        rates = self._rates.get(currency, {})
        key = f"{rate_type}_rate"
        if key not in rates:
            logger.warning(
                "Rate type '%s' missing for %s; falling back to closing_rate", rate_type, currency
            )
            return rates.get("closing_rate", 1.0)
        return rates[key]

    def translate_amount(self, amount: float, currency: str, rate_type: str) -> float:
        rate = self.get_rate(currency, rate_type)
        return round(amount * rate, 2)

    def translate_subsidiary(
        self, sub: SubsidiaryData
    ) -> tuple[SubsidiaryData, list[FxTranslationEntry]]:
        currency = sub.meta.currency
        fx_log: list[FxTranslationEntry] = []

        def translate_bs_lines(lines: list[AccountLine]) -> list[AccountLine]:
            translated = []
            for line in lines:
                # IAS 21: equity items at historical rate, assets/liabilities at closing rate
                if line.group_code in _EQUITY_BS_CODES:
                    rate_type = "historical"
                else:
                    rate_type = "closing"
                amount_usd = self.translate_amount(line.amount_local, currency, rate_type)
                fx_log.append(FxTranslationEntry(
                    entity_name=sub.meta.entity_name,
                    statement="BS",
                    group_code=line.group_code,
                    account_name=line.group_account_name,
                    amount_local=line.amount_local,
                    currency=currency,
                    rate_type=rate_type,
                    rate_used=self.get_rate(currency, rate_type),
                    amount_usd=amount_usd,
                ))
                translated.append(line.model_copy(update={"amount_usd": amount_usd}))
            return translated

        def translate_pl_lines(lines: list[AccountLine], stmt: str) -> list[AccountLine]:
            rate_type = STATEMENT_RATE_MAP[stmt]
            translated = []
            for line in lines:
                amount_usd = self.translate_amount(line.amount_local, currency, rate_type)
                fx_log.append(FxTranslationEntry(
                    entity_name=sub.meta.entity_name,
                    statement=stmt,
                    group_code=line.group_code,
                    account_name=line.group_account_name,
                    amount_local=line.amount_local,
                    currency=currency,
                    rate_type=rate_type,
                    rate_used=self.get_rate(currency, rate_type),
                    amount_usd=amount_usd,
                ))
                translated.append(line.model_copy(update={"amount_usd": amount_usd}))
            return translated

        def translate_eq(lines: list[EquityLine]) -> list[EquityLine]:
            translated = []
            for line in lines:
                # Opening equity at historical; P&L movement at average; closing at closing
                opening_usd = self.translate_amount(line.opening_local, currency, "historical")
                movement_usd = self.translate_amount(line.movement_local, currency, "average")
                closing_usd = self.translate_amount(line.closing_local, currency, "closing")
                translated.append(line.model_copy(update={
                    "opening_usd": opening_usd,
                    "movement_usd": movement_usd,
                    "closing_usd": closing_usd,
                }))
            return translated

        bs_translated = translate_bs_lines(sub.bs)
        is_translated = translate_pl_lines(sub.is_, "IS")
        cf_translated = translate_pl_lines(sub.cf, "CF")
        eq_translated = translate_eq(sub.eq)

        # IAS 21.41: FX reserve = Assets(closing) - Liabilities(closing) - Equity(historical)
        # This is the balancing figure posted to OCI (3200) to make BS balance
        fx_reserve = self._compute_fx_reserve(bs_translated, currency)

        if abs(fx_reserve) > 0.01 and currency != self._reporting_currency:
            logger.info(
                "FX translation reserve for %s: %.2f USD -> posted to OCI (3200)",
                sub.meta.entity_name, fx_reserve
            )
            oci_line = AccountLine(
                group_code="3200",
                group_account_name="Other Comprehensive Income (FX Reserve)",
                amount_local=0.0,
                amount_usd=fx_reserve,
                currency=currency,
                entity_name=sub.meta.entity_name,
                statement="BS",
            )
            bs_translated.append(oci_line)
            fx_log.append(FxTranslationEntry(
                entity_name=sub.meta.entity_name,
                statement="BS",
                group_code="3200",
                account_name="FX Translation Reserve (IAS 21.41)",
                amount_local=0.0,
                currency=currency,
                rate_type="balancing",
                rate_used=0.0,
                amount_usd=fx_reserve,
            ))

        updated = sub.model_copy(update={
            "bs": bs_translated,
            "is_": is_translated,
            "cf": cf_translated,
            "eq": eq_translated,
        })
        return updated, fx_log

    def _compute_fx_reserve(self, bs_translated: list[AccountLine], currency: str) -> float:
        """
        IAS 21.41: FX reserve = Assets(closing) - Liabilities(closing) - Equity(historical)

        Assets: codes 1000-1999 (positive = DR balance)
        Liabilities: codes 2000-2999 (positive = CR balance, subtracts from assets)
        Equity: codes 3000-3199 (positive = CR balance, historical rate already applied)
        """
        if currency == self._reporting_currency:
            return 0.0

        total_assets = 0.0
        total_liabilities = 0.0
        total_equity_historical = 0.0

        for line in bs_translated:
            try:
                code_int = int(line.group_code)
            except (ValueError, TypeError):
                continue
            if 1000 <= code_int <= 1999:
                total_assets += line.amount_usd
            elif 2000 <= code_int <= 2999:
                total_liabilities += line.amount_usd
            elif 3000 <= code_int <= 3199:
                total_equity_historical += line.amount_usd

        fx_reserve = round(total_assets - total_liabilities - total_equity_historical, 2)
        return fx_reserve
