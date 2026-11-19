import json
from typing import Any

from sqlalchemy.orm import Session

from app.clients.keitaro import KeitaroAPIError, KeitaroClient
from app.models import CampaignRecord
from app.services.audit import write_audit


def equal_shares(count: int) -> list[int]:
    if count <= 0:
        return []
    base, remainder = divmod(100, count)
    return [base + 1 if index < remainder else base for index in range(count)]


def distribute_offer_ids(offer_ids: list[int]) -> list[dict[str, Any]]:
    shares = equal_shares(len(offer_ids))
    return [
        {"offer_id": offer_id, "share": share, "state": "active"}
        for offer_id, share in zip(offer_ids, shares, strict=True)
    ]


def normalize_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in offers:
        try:
            offer_id = int(item["offer_id"])
            share = int(item["share"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each offer requires integer offer_id and share") from exc
        state = str(item.get("state") or "active")
        if state not in ("active", "disabled"):
            raise ValueError(f"Invalid offer state: {state}")
        if share < 0 or share > 100:
            raise ValueError(f"Share for offer {offer_id} must be between 0 and 100")
        if offer_id in seen:
            raise ValueError(f"Offer {offer_id} is listed more than once")
        seen.add(offer_id)
        normalized.append({"offer_id": offer_id, "share": share, "state": state})

    active_total = sum(o["share"] for o in normalized if o["state"] == "active")
    has_active = any(o["state"] == "active" for o in normalized)
    if has_active and active_total != 100:
        raise ValueError(f"Active offer shares must sum to 100, got {active_total}")
    return normalized


def build_offers_payload(
    stream: dict[str, Any], offers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    existing_ids = {
        int(offer["offer_id"]): offer.get("id")
        for offer in stream.get("offers") or []
        if offer.get("offer_id") is not None
    }
    payload: list[dict[str, Any]] = []
    for offer in offers:
        entry: dict[str, Any] = {
            "offer_id": int(offer["offer_id"]),
            "share": int(offer["share"]),
            "state": offer.get("state") or "active",
        }
        existing_id = existing_ids.get(entry["offer_id"])
        if existing_id is not None:
            entry["id"] = int(existing_id)
        payload.append(entry)
    return payload


def build_stream_put_payload(
    stream: dict[str, Any], offers: list[dict[str, Any]]
) -> dict[str, Any]:
    filters = []
    for stream_filter in stream.get("filters") or []:
        entry: dict[str, Any] = {
            "name": stream_filter.get("name"),
            "mode": stream_filter.get("mode"),
            "payload": stream_filter.get("payload"),
        }
        if stream_filter.get("id") is not None:
            entry["id"] = int(stream_filter["id"])
        filters.append(entry)

    payload: dict[str, Any] = {
        "campaign_id": int(stream["campaign_id"]),
        "type": stream.get("type"),
        "name": stream.get("name"),
        "position": int(stream.get("position") or 1),
        "weight": stream.get("weight", 0),
        "comments": stream.get("comments") or "",
        "state": stream.get("state") or "active",
        "action_type": stream.get("action_type"),
        "action_payload": stream.get("action_payload")
        if stream.get("action_payload") is not None
        else "",
        "schema": stream.get("schema"),
        "collect_clicks": bool(stream.get("collect_clicks", True)),
        "filter_or": bool(stream.get("filter_or", False)),
        "offer_selection": stream.get("offer_selection") or "before_click",
        "filters": filters,
        "offers": build_offers_payload(stream, offers),
    }
    if stream.get("action_options") is not None:
        payload["action_options"] = stream["action_options"]
    return payload


def _filters_signature(stream: dict[str, Any]) -> list[tuple[str, str, str]]:
    signature = []
    for stream_filter in stream.get("filters") or []:
        signature.append(
            (
                str(stream_filter.get("name")),
                str(stream_filter.get("mode")),
                json.dumps(stream_filter.get("payload"), sort_keys=True, ensure_ascii=False),
            )
        )
    return signature


def _offers_map(stream: dict[str, Any]) -> dict[int, tuple[int, str]]:
    return {
        int(offer["offer_id"]): (int(offer.get("share") or 0), str(offer.get("state") or "active"))
        for offer in stream.get("offers") or []
        if offer.get("offer_id") is not None
    }


class CampaignEditor:
    def __init__(self, client: KeitaroClient, db: Session) -> None:
        self.client = client
        self.db = db

    async def _offer_names(self) -> dict[int, str]:
        try:
            offers = await self.client.list_offers()
        except KeitaroAPIError:
            return {}
        return {
            int(offer["id"]): str(offer.get("name") or f"Offer #{offer['id']}")
            for offer in offers
            if offer.get("id") is not None
        }

    async def get_detail(self, campaign_id: int) -> dict[str, Any]:
        campaign = await self.client.get_campaign(campaign_id)
        streams = await self.client.list_streams(campaign_id)
        offer_names = await self._offer_names()

        for stream in streams:
            view = []
            for offer in stream.get("offers") or []:
                offer_id = int(offer["offer_id"])
                view.append(
                    {
                        "offer_id": offer_id,
                        "name": offer_names.get(offer_id, f"Offer #{offer_id}"),
                        "share": int(offer.get("share") or 0),
                        "state": offer.get("state") or "active",
                        "id": offer.get("id"),
                    }
                )
            stream["offers_view"] = view

        target_stream_id = self.pick_target_stream(streams)
        record = (
            self.db.query(CampaignRecord)
            .filter(CampaignRecord.keitaro_campaign_id == campaign_id)
            .one_or_none()
        )
        return {
            "campaign": campaign,
            "streams": streams,
            "target_stream_id": target_stream_id,
            "record": record,
        }

    @staticmethod
    def pick_target_stream(streams: list[dict[str, Any]]) -> int | None:
        with_offers = [s for s in streams if s.get("offers")]
        if with_offers:
            landings = [s for s in with_offers if s.get("schema") == "landings"]
            chosen = (landings or with_offers)[0]
            return int(chosen["id"])
        landings_empty = [s for s in streams if s.get("schema") == "landings"]
        if landings_empty:
            return int(landings_empty[0]["id"])
        return None

    async def save_offers(
        self, campaign_id: int, stream_id: int, offers_input: list[dict[str, Any]]
    ) -> dict[str, Any]:
        before = await self.client.get_stream(stream_id)
        if int(before.get("campaign_id") or 0) != campaign_id:
            raise ValueError("Stream does not belong to the requested campaign")

        offers = normalize_offers(offers_input)
        payload = build_stream_put_payload(before, offers)
        await self.client.update_stream(stream_id, payload)
        fresh = await self.client.get_stream(stream_id)

        self._verify(before, fresh, offers)

        before_ids = set(_offers_map(before))
        after_ids = set(_offers_map(fresh))
        if after_ids - before_ids:
            action = "add_offer"
        elif before_ids - after_ids:
            action = "remove_offer"
        else:
            action = "update_shares"

        write_audit(
            self.db,
            campaign_id,
            action,
            {
                "stream_id": stream_id,
                "before": _offers_map(before),
                "requested": offers,
                "after": _offers_map(fresh),
                "payload": payload,
            },
            "success",
        )

        offer_names = await self._offer_names()
        fresh["offers_view"] = [
            {
                "offer_id": int(offer["offer_id"]),
                "name": offer_names.get(
                    int(offer["offer_id"]), f"Offer #{offer['offer_id']}"
                ),
                "share": int(offer.get("share") or 0),
                "state": offer.get("state") or "active",
                "id": offer.get("id"),
            }
            for offer in fresh.get("offers") or []
        ]
        return {"stream": fresh, "action": action}

    @staticmethod
    def _verify(
        before: dict[str, Any], fresh: dict[str, Any], requested: list[dict[str, Any]]
    ) -> None:
        expected = {
            int(offer["offer_id"]): (int(offer["share"]), offer.get("state") or "active")
            for offer in requested
        }
        actual = _offers_map(fresh)
        if expected != actual:
            write_failed = KeitaroAPIError(
                502,
                "Keitaro did not persist the requested offer shares. "
                f"Requested: {expected}; stored: {actual}",
                payload={"requested": expected, "stored": actual},
            )
            raise write_failed

        for key in ("name", "type", "position", "schema", "action_type", "campaign_id"):
            if before.get(key) != fresh.get(key):
                raise KeitaroAPIError(
                    502,
                    f"Refusing to continue: Keitaro changed flow field '{key}'",
                    payload={"before": before.get(key), "after": fresh.get(key)},
                )
        if _filters_signature(before) != _filters_signature(fresh):
            raise KeitaroAPIError(
                502,
                "Keitaro changed the flow filters during the offers update",
                payload={
                    "before": _filters_signature(before),
                    "after": _filters_signature(fresh),
                },
            )

    async def equalize(self, offer_ids: list[int]) -> list[dict[str, Any]]:
        return distribute_offer_ids(offer_ids)
