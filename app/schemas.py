from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str | list[str] = Field(
        description="ISO-3166-1 alpha-2 code(s), e.g. 'AU' or 'MX, AU, RO'"
    )
    offer_id: int = Field(gt=0)
    domain_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    traffic_source_id: int | None = Field(default=None, gt=0)


class OfferShareIn(BaseModel):
    offer_id: int = Field(gt=0)
    share: int = Field(ge=0, le=100)
    state: str = Field(default="active", pattern="^(active|disabled)$")


class OffersUpdateIn(BaseModel):
    offers: list[OfferShareIn] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def check_duplicates(self) -> "OffersUpdateIn":
        seen: set[int] = set()
        for offer in self.offers:
            if offer.offer_id in seen:
                raise ValueError(f"Offer {offer.offer_id} is listed more than once")
            seen.add(offer.offer_id)
        return self


class EqualizeIn(BaseModel):
    offer_ids: list[int] = Field(default_factory=list, max_length=200)


class CampaignRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keitaro_campaign_id: int
    name: str
    alias: str
    geo_codes: list[str]
    initial_offer_id: int | None
    domain_id: int | None
    group_id: int | None
    traffic_source_id: int | None
    created_at: datetime
    updated_at: datetime


class CampaignCreateOut(BaseModel):
    campaign: dict[str, Any]
    streams: list[dict[str, Any]]
    record: CampaignRecordOut | None = None


class CampaignDetailOut(BaseModel):
    campaign: dict[str, Any]
    streams: list[dict[str, Any]]
    target_stream_id: int | None = None
    record: CampaignRecordOut | None = None


class EqualizeOut(BaseModel):
    offers: list[OfferShareIn]
    total: int


class ErrorOut(BaseModel):
    detail: str
    keitaro_status: int | None = None
    method: str | None = None
    path: str | None = None
    payload: Any = None
