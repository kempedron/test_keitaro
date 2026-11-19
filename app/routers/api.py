from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import CampaignRecord
from app.routers.deps import get_client, get_references
from app.schemas import (
    CampaignCreateIn,
    CampaignCreateOut,
    CampaignDetailOut,
    CampaignRecordOut,
    EqualizeIn,
    EqualizeOut,
    OffersUpdateIn,
)
from app.services.audit import write_audit
from app.services.campaign_creator import CampaignCreator
from app.services.campaign_editor import CampaignEditor, distribute_offer_ids
from app.services.references import pick_default_id

router = APIRouter(prefix="/api")


def _record_out(record: CampaignRecord | None) -> CampaignRecordOut | None:
    return CampaignRecordOut.model_validate(record) if record is not None else None


def _simple(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(item["id"]),
            "name": item.get("name") or f"#{item['id']}",
            "state": item.get("state") or "active",
        }
        for item in items
        if item.get("id") is not None
    ]


def _name_map(items: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(item["id"]): str(item["name"])
        for item in items
        if item.get("id") is not None
    }


def _campaign_url(campaign: dict[str, Any], domain_name: str | None) -> str | None:
    alias = str(campaign.get("alias") or "").strip()
    domain = str(domain_name or campaign.get("domain") or "").strip()
    if not alias or not domain:
        return None
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return f"{domain.rstrip('/')}/{alias}"


def enrich_campaign(
    campaign: dict[str, Any],
    *,
    domain_names: dict[int, str] | None = None,
    group_names: dict[int, str] | None = None,
    source_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    result = dict(campaign)
    domain_id = result.get("domain_id")
    if domain_id is not None and domain_names:
        name = domain_names.get(int(domain_id))
        if name:
            result["domain_name"] = name
    group_id = result.get("group_id")
    if group_id is not None and group_names:
        name = group_names.get(int(group_id))
        if name:
            result["group_name"] = name
    source_id = result.get("traffic_source_id")
    if source_id is not None and source_names:
        name = source_names.get(int(source_id))
        if name:
            result["traffic_source_name"] = name
    url = _campaign_url(result, result.get("domain_name"))
    if url:
        result["campaign_url"] = url
    return result


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "prefix": settings.normalized_prefix,
        "keitaro_base_url": settings.keitaro_base_url,
    }


@router.get("/references/offers")
async def offers_reference(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    references = get_references(request)
    offers = await references.offers()
    needle = q.strip().lower()
    matched = []
    for offer in offers:
        if offer.get("id") is None:
            continue
        name = str(offer.get("name") or "")
        offer_id = str(offer["id"])
        if needle and needle not in name.lower() and needle not in offer_id:
            continue
        matched.append(
            {
                "id": int(offer["id"]),
                "name": name or f"Offer #{offer['id']}",
                "state": offer.get("state") or "active",
                "group_id": offer.get("group_id"),
            }
        )
        if len(matched) >= limit:
            break
    matched.sort(key=lambda item: item["state"] != "active")
    return {"items": matched, "total": len(matched)}


@router.get("/references/domains")
async def domains_reference(request: Request) -> dict[str, Any]:
    items = _simple(await get_references(request).domains())
    return {"items": items, "default_id": pick_default_id(items)}


@router.get("/references/groups")
async def groups_reference(request: Request) -> dict[str, Any]:
    items = _simple(await get_references(request).groups())
    return {"items": items, "default_id": pick_default_id(items)}


@router.get("/references/traffic_sources")
async def traffic_sources_reference(request: Request) -> dict[str, Any]:
    items = _simple(await get_references(request).traffic_sources())
    return {"items": items, "default_id": pick_default_id(items)}


@router.post("/campaigns", response_model=CampaignCreateOut, status_code=201)
async def create_campaign(
    payload: CampaignCreateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    references = get_references(request)
    domain_items = _simple(await references.domains())
    group_items = _simple(await references.groups())
    source_items = _simple(await references.traffic_sources())
    domain_id = payload.domain_id or pick_default_id(domain_items)
    group_id = payload.group_id or pick_default_id(group_items)
    traffic_source_id = payload.traffic_source_id or pick_default_id(source_items)
    if not domain_id or not group_id or not traffic_source_id:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve domain, group or traffic source for the campaign",
        )

    creator = CampaignCreator(get_client(request), db, settings.normalized_prefix)
    try:
        result = await creator.create(
            name=payload.name,
            geo=payload.geo,
            offer_id=payload.offer_id,
            domain_id=int(domain_id),
            group_id=int(group_id),
            traffic_source_id=int(traffic_source_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "campaign": enrich_campaign(
            result["campaign"],
            domain_names=_name_map(domain_items),
            group_names=_name_map(group_items),
            source_names=_name_map(source_items),
        ),
        "streams": result["streams"],
        "record": _record_out(result["record"]),
    }


@router.get("/campaigns")
async def list_campaigns(
    request: Request,
    mine: bool = Query(default=True),
    q: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    campaigns = await get_client(request).list_campaigns()
    prefix = settings.normalized_prefix.lower()
    needle = q.strip().lower()
    local_ids = {
        row[0]
        for row in db.query(CampaignRecord.keitaro_campaign_id).all()
    }

    items = []
    for campaign in campaigns:
        name = str(campaign.get("name") or "")
        alias = str(campaign.get("alias") or "")
        campaign_id = str(campaign.get("id") or "")
        if mine and not name.lower().startswith(prefix):
            continue
        if needle and needle not in name.lower() and needle not in alias.lower() and needle != campaign_id:
            continue
        items.append(
            {
                "id": int(campaign["id"]),
                "name": name,
                "alias": alias,
                "state": campaign.get("state") or "active",
                "domain_id": campaign.get("domain_id"),
                "group_id": campaign.get("group_id"),
                "traffic_source_id": campaign.get("traffic_source_id"),
                "created_at": campaign.get("created_at"),
                "is_local": int(campaign["id"]) in local_ids,
            }
        )
    items.sort(key=lambda item: item["id"], reverse=True)
    return {"items": items, "total": len(items), "prefix": settings.normalized_prefix}


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailOut)
async def campaign_detail(
    campaign_id: int, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    editor = CampaignEditor(get_client(request), db)
    detail = await editor.get_detail(campaign_id)
    references = get_references(request)
    try:
        domain_items = _simple(await references.domains())
        group_items = _simple(await references.groups())
        source_items = _simple(await references.traffic_sources())
    except Exception:
        domain_items, group_items, source_items = [], [], []
    detail["campaign"] = enrich_campaign(
        detail["campaign"],
        domain_names=_name_map(domain_items),
        group_names=_name_map(group_items),
        source_names=_name_map(source_items),
    )
    detail["record"] = _record_out(detail.get("record"))
    return detail


@router.put("/campaigns/{campaign_id}/streams/{stream_id}/offers")
async def update_stream_offers(
    campaign_id: int,
    stream_id: int,
    payload: OffersUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    editor = CampaignEditor(get_client(request), db)
    try:
        result = await editor.save_offers(
            campaign_id, stream_id, [offer.model_dump() for offer in payload.offers]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/shares/equalize", response_model=EqualizeOut)
async def equalize_shares(payload: EqualizeIn) -> dict[str, Any]:
    if len(set(payload.offer_ids)) != len(payload.offer_ids):
        raise HTTPException(status_code=400, detail="Offer IDs must be unique")
    offers = distribute_offer_ids(payload.offer_ids)
    return {"offers": offers, "total": sum(item["share"] for item in offers)}


@router.post("/campaigns/{campaign_id}/archive")
async def archive_campaign(
    campaign_id: int, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    client = get_client(request)
    campaign = await client.get_campaign(campaign_id)
    name = str(campaign.get("name") or "")
    if not name.lower().startswith(settings.normalized_prefix.lower()):
        raise HTTPException(
            status_code=400,
            detail=(
                "Refusing to archive a campaign outside the "
                f"'{settings.normalized_prefix}' scope"
            ),
        )
    await client.archive_campaign(campaign_id)
    write_audit(
        db,
        campaign_id,
        "archive",
        {"campaign_name": name},
        "success",
    )
    return {"status": "archived", "campaign_id": campaign_id}


@router.get("/campaigns/{campaign_id}/audit")
async def campaign_audit(
    campaign_id: int, db: Session = Depends(get_db), limit: int = Query(default=50, ge=1, le=200)
) -> dict[str, Any]:
    from app.models import CampaignAuditLog

    rows = (
        db.query(CampaignAuditLog)
        .filter(CampaignAuditLog.keitaro_campaign_id == campaign_id)
        .order_by(CampaignAuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "action": row.action,
                "status": row.status,
                "error_detail": row.error_detail,
                "payload": row.payload_snapshot,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }
