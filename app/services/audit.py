from typing import Any

from sqlalchemy.orm import Session

from app.models import CampaignAuditLog


def write_audit(
    db: Session,
    campaign_id: int,
    action: str,
    payload_snapshot: dict[str, Any] | None,
    status: str,
    error_detail: str | None = None,
) -> None:
    entry = CampaignAuditLog(
        keitaro_campaign_id=campaign_id,
        action=action,
        payload_snapshot=payload_snapshot,
        status=status,
        error_detail=error_detail,
    )
    try:
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
