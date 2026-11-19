import copy

import pytest
from sqlalchemy.orm import Session

from app.clients.keitaro import KeitaroAPIError
from app.models import CampaignAuditLog, CampaignRecord
from app.services.campaign_editor import CampaignEditor

STREAM = {
    "id": 55,
    "campaign_id": 10,
    "type": "default",
    "name": "Offers",
    "position": 2,
    "weight": 0,
    "comments": "",
    "state": "active",
    "action_type": "http",
    "action_payload": "",
    "schema": "landings",
    "collect_clicks": True,
    "filter_or": False,
    "offer_selection": "before_click",
    "filters": [{"id": 900, "name": "country", "mode": "accept", "payload": ["AU"]}],
    "offers": [{"id": 1, "offer_id": 18813, "share": 100, "state": "active"}],
}


class FakeEditorClient:
    def __init__(self, apply_updates: bool = True) -> None:
        self.stream = copy.deepcopy(STREAM)
        self.apply_updates = apply_updates
        self.updated_payload: dict | None = None
        self.offers = [
            {"id": 18813, "name": "Offer A"},
            {"id": 222, "name": "Offer B"},
            {"id": 333, "name": "Offer C"},
        ]

    async def get_stream(self, stream_id: int) -> dict:
        return copy.deepcopy(self.stream)

    async def update_stream(self, stream_id: int, payload: dict) -> dict:
        self.updated_payload = copy.deepcopy(payload)
        if self.apply_updates:
            self.stream["offers"] = [
                {**offer, "id": index + 1}
                for index, offer in enumerate(payload["offers"])
            ]
        return copy.deepcopy(self.stream)

    async def list_offers(self) -> list[dict]:
        return self.offers

    async def get_campaign(self, campaign_id: int) -> dict:
        return {"id": campaign_id, "name": "test_vdovichenko_editor"}

    async def list_streams(self, campaign_id: int) -> list[dict]:
        return [copy.deepcopy(self.stream)]


async def test_save_offers_redistributes_and_writes_audit(db_session: Session) -> None:
    client = FakeEditorClient()
    editor = CampaignEditor(client, db_session)
    db_session.add(
        CampaignRecord(
            keitaro_campaign_id=10,
            name="test_vdovichenko_editor",
            alias="test-vdovichenko-editor",
            geo_codes=["AU"],
            initial_offer_id=18813,
            domain_id=1813,
            group_id=10332,
            traffic_source_id=836,
        )
    )
    db_session.commit()

    result = await editor.save_offers(
        10,
        55,
        [
            {"offer_id": 18813, "share": 34, "state": "active"},
            {"offer_id": 222, "share": 33, "state": "active"},
            {"offer_id": 333, "share": 33, "state": "active"},
        ],
    )

    shares = {offer["offer_id"]: offer["share"] for offer in result["stream"]["offers"]}
    assert shares == {18813: 34, 222: 33, 333: 33}
    assert result["action"] == "add_offer"

    assert client.updated_payload["name"] == "Offers"
    assert client.updated_payload["position"] == 2
    assert client.updated_payload["schema"] == "landings"
    assert client.updated_payload["filters"][0]["id"] == 900
    assert client.updated_payload["offers"][0]["id"] == 1

    audit = db_session.query(CampaignAuditLog).one()
    assert audit.action == "add_offer"
    assert audit.status == "success"


async def test_save_offers_detects_keitaro_mismatch(db_session: Session) -> None:
    client = FakeEditorClient(apply_updates=False)
    editor = CampaignEditor(client, db_session)

    with pytest.raises(KeitaroAPIError) as captured:
        await editor.save_offers(
            10,
            55,
            [
                {"offer_id": 18813, "share": 50, "state": "active"},
                {"offer_id": 222, "share": 50, "state": "active"},
            ],
        )

    assert captured.value.status_code == 502
    assert "did not persist" in captured.value.detail


async def test_get_detail_marks_target_stream_and_resolves_names(db_session: Session) -> None:
    client = FakeEditorClient()
    editor = CampaignEditor(client, db_session)

    detail = await editor.get_detail(10)

    assert detail["target_stream_id"] == 55
    assert detail["streams"][0]["offers_view"][0]["name"] == "Offer A"
    assert detail["record"] is None


def test_pick_target_stream_prefers_landings_with_offers() -> None:
    streams = [
        {"id": 1, "schema": "redirect", "offers": []},
        {"id": 2, "schema": "landings", "offers": []},
        {"id": 3, "schema": "landings", "offers": [{"offer_id": 1}]},
    ]
    assert CampaignEditor.pick_target_stream(streams) == 3
    assert CampaignEditor.pick_target_stream(streams[:2]) == 2
    assert CampaignEditor.pick_target_stream([{"id": 1, "schema": "redirect", "offers": []}]) is None
