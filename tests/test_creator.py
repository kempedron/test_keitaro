import pytest
from sqlalchemy.orm import Session

from app.clients.keitaro import KeitaroAPIError
from app.models import CampaignAuditLog, CampaignRecord
from app.services.campaign_creator import CampaignCreator

PREFIX = "test_vdovichenko_"


class FakeCreatorClient:
    def __init__(self, fail_on_second_stream: bool = False) -> None:
        self.fail_on_second_stream = fail_on_second_stream
        self.stream_payloads: list[dict] = []
        self.archived: list[int] = []
        self.campaign_payload: dict | None = None

    async def get_offer(self, offer_id: int) -> dict:
        return {"id": offer_id, "name": "Demo offer"}

    async def create_campaign(self, payload: dict) -> dict:
        self.campaign_payload = payload
        return {"id": 777, "name": payload["name"], "alias": payload["alias"]}

    async def create_stream(self, payload: dict) -> dict:
        if self.fail_on_second_stream and payload["position"] == 2:
            raise KeitaroAPIError(422, "Invalid flow", payload={"name": "Invalid flow"})
        self.stream_payloads.append(payload)
        return {"id": 1000 + payload["position"], **payload}

    async def archive_campaign(self, campaign_id: int) -> dict:
        self.archived.append(campaign_id)
        return {"status": "archived"}


async def test_create_campaign_builds_two_flows(db_session: Session) -> None:
    client = FakeCreatorClient()
    creator = CampaignCreator(client, db_session, PREFIX)

    result = await creator.create(
        name="e2e_check",
        geo="mx, au",
        offer_id=18813,
        domain_id=1813,
        group_id=10332,
        traffic_source_id=836,
    )

    assert result["campaign"]["id"] == 777
    assert result["campaign"]["name"] == f"{PREFIX}e2e_check"
    assert client.campaign_payload["group_id"] == "10332"
    assert len(client.stream_payloads) == 2

    geo_flow, offer_flow = client.stream_payloads
    assert geo_flow["position"] == 1
    assert geo_flow["schema"] == "redirect"
    assert geo_flow["filters"][0]["payload"] == ["MX", "AU"]
    assert offer_flow["position"] == 2
    assert offer_flow["offers"] == [{"offer_id": 18813, "share": 100, "state": "active"}]

    record = db_session.query(CampaignRecord).one()
    assert record.keitaro_campaign_id == 777
    assert record.geo_codes == ["MX", "AU"]

    audit = db_session.query(CampaignAuditLog).one()
    assert audit.action == "create"
    assert audit.status == "success"
    assert audit.keitaro_campaign_id == 777


async def test_partial_failure_archives_campaign_and_logs_error(db_session: Session) -> None:
    client = FakeCreatorClient(fail_on_second_stream=True)
    creator = CampaignCreator(client, db_session, PREFIX)

    with pytest.raises(KeitaroAPIError) as captured:
        await creator.create(
            name="broken",
            geo="AU",
            offer_id=18813,
            domain_id=1813,
            group_id=10332,
            traffic_source_id=836,
        )

    assert captured.value.status_code == 422
    assert client.archived == [777]
    audit = db_session.query(CampaignAuditLog).one()
    assert audit.action == "create"
    assert audit.status == "error"
    assert "Invalid flow" in (audit.error_detail or "")
    assert audit.payload_snapshot["streams_created"] == [1001]


class ForbiddenOfferClient(FakeCreatorClient):
    async def get_offer(self, offer_id: int) -> dict:
        raise KeitaroAPIError(403, "Forbidden")


async def test_create_allows_offer_id_when_read_is_forbidden(db_session: Session) -> None:
    client = ForbiddenOfferClient()
    creator = CampaignCreator(client, db_session, PREFIX)

    result = await creator.create(
        name="hidden_offer",
        geo="AU",
        offer_id=17210,
        domain_id=1813,
        group_id=10332,
        traffic_source_id=836,
    )

    assert result["campaign"]["id"] == 777
    assert client.stream_payloads[1]["offers"] == [
        {"offer_id": 17210, "share": 100, "state": "active"}
    ]
    assert result["record"].initial_offer_id == 17210
