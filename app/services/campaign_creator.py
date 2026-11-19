import asyncio
import re
import secrets
from typing import Any

import pycountry
from sqlalchemy.orm import Session

from app.clients.keitaro import KeitaroAPIError, KeitaroClient
from app.models import CampaignRecord
from app.services.audit import write_audit

GOOGLE_REDIRECT_URL = "https://google.com/"


def parse_geo_codes(raw: str | list[str]) -> list[str]:
    chunks: list[str] = []
    if isinstance(raw, str):
        chunks = re.split(r"[,;\s]+", raw)
    else:
        for item in raw:
            if not isinstance(item, str):
                raise ValueError("Geo codes must be strings")
            chunks.extend(re.split(r"[,;\s]+", item))

    codes: list[str] = []
    for chunk in chunks:
        code = chunk.strip().upper()
        if not code:
            continue
        if len(code) != 2 or pycountry.countries.get(alpha_2=code) is None:
            raise ValueError(f"Invalid ISO-3166-1 alpha-2 country code: {code}")
        if code not in codes:
            codes.append(code)

    if not codes:
        raise ValueError("At least one geo country code is required")
    return codes


def normalize_campaign_name(name: str, prefix: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("Campaign name must not be empty")
    if cleaned.lower().startswith(prefix.lower()):
        cleaned = f"{prefix}{cleaned[len(prefix):]}"
    else:
        cleaned = f"{prefix}{cleaned}"
    if cleaned.lower() == prefix.lower():
        raise ValueError("Campaign name must contain something after the prefix")
    if len(cleaned) > 255:
        raise ValueError("Campaign name is too long (max 255 characters)")
    return cleaned


def build_alias(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return f"{slug or 'campaign'}-{secrets.token_hex(3)}"


def build_campaign_payload(
    *,
    name: str,
    alias: str,
    domain_id: int,
    group_id: int,
    traffic_source_id: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "alias": alias,
        "type": "position",
        "state": "active",
        "domain_id": domain_id,
        "group_id": str(group_id),
        "traffic_source_id": traffic_source_id,
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "notes": "Created via Adrobot T3 campaign manager",
    }


def build_geo_stream_payload(campaign_id: int, geo_codes: list[str]) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "name": f"{'/'.join(geo_codes)} \u2192 Google",
        "type": "regular",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": GOOGLE_REDIRECT_URL,
        "filters": [
            {
                "name": "country",
                "mode": "accept",
                "payload": list(geo_codes),
            }
        ],
        "offers": [],
        "collect_clicks": True,
        "filter_or": False,
        "offer_selection": "before_click",
        "state": "active",
        "comments": "",
        "weight": 0,
    }


def build_offer_stream_payload(campaign_id: int, offer_id: int) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "name": "Offers",
        "type": "default",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "action_payload": "",
        "filters": [],
        "offers": [
            {
                "offer_id": offer_id,
                "share": 100,
                "state": "active",
            }
        ],
        "collect_clicks": True,
        "filter_or": False,
        "offer_selection": "before_click",
        "state": "active",
        "comments": "",
        "weight": 0,
    }


class CampaignCreator:
    def __init__(self, client: KeitaroClient, db: Session, prefix: str) -> None:
        self.client = client
        self.db = db
        self.prefix = prefix

    async def create(
        self,
        *,
        name: str,
        geo: str | list[str],
        offer_id: int,
        domain_id: int,
        group_id: int,
        traffic_source_id: int,
    ) -> dict[str, Any]:
        geo_codes = parse_geo_codes(geo)
        final_name = normalize_campaign_name(name, self.prefix)
        alias = build_alias(final_name)

        try:
            await self.client.get_offer(offer_id)
        except KeitaroAPIError as exc:
            if exc.status_code != 403:
                raise

        campaign_payload = build_campaign_payload(
            name=final_name,
            alias=alias,
            domain_id=domain_id,
            group_id=group_id,
            traffic_source_id=traffic_source_id,
        )
        campaign = await self._create_campaign_resilient(campaign_payload)
        campaign_id = int(campaign["id"])

        record = CampaignRecord(
            keitaro_campaign_id=campaign_id,
            name=final_name,
            alias=alias,
            geo_codes=geo_codes,
            initial_offer_id=offer_id,
            domain_id=domain_id,
            group_id=group_id,
            traffic_source_id=traffic_source_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)

        first_stream_payload = build_geo_stream_payload(campaign_id, geo_codes)
        second_stream_payload = build_offer_stream_payload(campaign_id, offer_id)
        streams: list[dict[str, Any]] = []
        try:
            streams.append(
                await self._create_stream_resilient(campaign_id, first_stream_payload)
            )
            streams.append(
                await self._create_stream_resilient(campaign_id, second_stream_payload)
            )
        except Exception as exc:
            cleanup = await self._safe_archive(campaign_id)
            write_audit(
                self.db,
                campaign_id,
                "create",
                {
                    "campaign": campaign_payload,
                    "geo_stream": first_stream_payload,
                    "offer_stream": second_stream_payload,
                    "streams_created": [s.get("id") for s in streams],
                    "cleanup": cleanup,
                },
                "error",
                str(exc),
            )
            raise

        write_audit(
            self.db,
            campaign_id,
            "create",
            {
                "campaign": campaign_payload,
                "geo_stream": first_stream_payload,
                "offer_stream": second_stream_payload,
                "stream_ids": [s.get("id") for s in streams],
            },
            "success",
        )
        return {"campaign": campaign, "streams": streams, "record": record}

    async def _create_campaign_resilient(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.client.create_campaign(payload)
        except KeitaroAPIError as exc:
            if exc.status_code < 500:
                raise
            existing = await self._find_campaign(payload["alias"], payload["name"])
            if existing is not None:
                return existing
            raise

    async def _find_campaign(self, alias: str, name: str) -> dict[str, Any] | None:
        for attempt in range(6):
            try:
                campaigns = await self.client.list_campaigns()
            except KeitaroAPIError:
                campaigns = []
            for campaign in campaigns:
                if campaign.get("alias") == alias and campaign.get("state") != "deleted":
                    return campaign
            for campaign in campaigns:
                if campaign.get("name") == name and campaign.get("state") != "deleted":
                    return campaign
            if attempt < 5:
                await asyncio.sleep(10)
        return None

    async def _create_stream_resilient(
        self, campaign_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return await self.client.create_stream(payload)
        except KeitaroAPIError as exc:
            if exc.status_code < 500:
                raise
            for attempt in range(6):
                try:
                    streams = await self.client.list_streams(campaign_id)
                except KeitaroAPIError:
                    streams = []
                for stream in streams:
                    if (
                        int(stream.get("position") or 0) == int(payload["position"])
                        and stream.get("type") == payload["type"]
                    ):
                        return stream
                if attempt < 5:
                    await asyncio.sleep(5)
            raise

    async def _safe_archive(self, campaign_id: int) -> str:
        try:
            await self.client.archive_campaign(campaign_id)
            return "Campaign archived after a partial failure"
        except Exception as exc:
            return f"Cleanup failed: {exc}"

    async def archive_own(self, campaign_id: int) -> Any:
        return await self.client.archive_campaign(campaign_id)
