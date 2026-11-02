"""Conceptual decimal-unit adapter contracts; persisted pilot payloads use integer paisa.

Request definitions live in contracts.py. importer.py owns normalization and
reconcile.py owns the separately persisted attribution and financial reports.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CommerceOrder(BaseModel):
    order_id: str
    store_id: str
    ordered_at: datetime
    timezone: str
    source: str
    original_currency: str
    financial_status: str
    fulfillment_status: str
    gross_item_sales: Decimal = Field(ge=0)
    discounts: Decimal | None = Field(default=None, ge=0)
    refunded_amount: Decimal | None = Field(default=None, ge=0)
    merchandise_refunds: Decimal | None = Field(default=None, ge=0)
    net_item_sales: Decimal | None = None
    tax: Decimal | None = None
    shipping_charged: Decimal | None = None
    shipping_refunded: Decimal | None = None
    campaign_id: str | None = None
    utm_source: str | None = None
    utm_campaign: str | None = None


class CommerceOrderItem(BaseModel):
    order_id: str
    store_id: str
    sku: str
    quantity: int = Field(ge=0)
    line_amount: Decimal
    refunded_quantity: int | None = Field(default=None, ge=0)
    verified_cogs: Decimal | None = None


class CommerceCosts(BaseModel):
    store_id: str
    currency: str
    source: str
    cogs: Decimal | None = None
    payment_fees: Decimal | None = None
    fulfillment: Decimal | None = None
    packaging: Decimal | None = None
    other_variable_costs: Decimal | None = None


class AttributionLink(BaseModel):
    store_id: str
    order_id: str
    ad_dataset_id: str
    campaign_id: str | None = None
    evidence: str | None = None
    status: str = Field(pattern="^(matched|unmatched|ambiguous|excluded)$")
