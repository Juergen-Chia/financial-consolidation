from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class EntityMeta(BaseModel):
    entity_name: str
    currency: str
    reporting_period: str
    ownership_pct: float


class AccountLine(BaseModel):
    group_code: str
    group_account_name: str
    amount_local: float
    amount_usd: float = 0.0
    currency: str
    entity_name: str
    statement: Literal["BS", "IS", "CF"]


class EquityLine(BaseModel):
    component: str
    opening_local: float
    movement_local: float
    closing_local: float
    opening_usd: float = 0.0
    movement_usd: float = 0.0
    closing_usd: float = 0.0
    entity_name: str


class SubsidiaryData(BaseModel):
    meta: EntityMeta
    bs: list[AccountLine] = Field(default_factory=list)
    is_: list[AccountLine] = Field(default_factory=list)
    cf: list[AccountLine] = Field(default_factory=list)
    eq: list[EquityLine] = Field(default_factory=list)
    unmapped_accounts: list[dict] = Field(default_factory=list)


class EliminationEntry(BaseModel):
    reference: str
    description: str
    from_entity: str
    to_entity: str
    account_code: str
    account_name: str
    statement: str
    amount_usd: float
    elimination_type: Literal["ICO_BALANCE", "ICO_PL", "INVESTMENT_EQUITY", "NCI"]


class FxTranslationEntry(BaseModel):
    entity_name: str
    statement: str
    group_code: str
    account_name: str
    amount_local: float
    currency: str
    rate_type: str
    rate_used: float
    amount_usd: float


class ValidationMessage(BaseModel):
    severity: Literal["INFO", "WARNING", "ERROR"]
    category: str
    message: str
    detail: str = ""


class ConsolidatedData(BaseModel):
    entities: list[str]
    bs_rows: list[dict]
    is_rows: list[dict]
    cf_rows: list[dict]
    eq_rows: list[dict]
    eliminations: list[EliminationEntry] = Field(default_factory=list)
    fx_log: list[FxTranslationEntry] = Field(default_factory=list)
    validation_messages: list[ValidationMessage] = Field(default_factory=list)
    nci_bs_usd: float = 0.0
    nci_pl_usd: float = 0.0

    model_config = {"arbitrary_types_allowed": True}
