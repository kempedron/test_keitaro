from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.keitaro import KeitaroAPIError
from app.database import Base, get_db
from app.main import app
from app.models import CampaignRecord  # noqa: F401


class FakeReferences:
    async def offers(self) -> list[dict[str, Any]]:
        return [{"id": 18813, "name": "Visible offer", "state": "active"}]

    async def domains(self) -> list[dict[str, Any]]:
        return [{"id": 1813, "name": "kylovoa.com", "state": "active"}]

    async def groups(self) -> list[dict[str, Any]]:
        return [{"id": 10332, "name": "FORTESTS", "state": "active"}]

    async def traffic_sources(self) -> list[dict[str, Any]]:
        return [{"id": 836, "name": "FORTESTS", "state": "active"}]


class FakeKeitaro:
    def __init__(self) -> None:
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, dict[str, Any]] = {}
        self.next_campaign_id = 5000
        self.next_stream_id = 1000
        self.archived: list[int] = []

    async def get_offer(self, offer_id: int) -> dict[str, Any]:
        if offer_id != 18813:
            raise KeitaroAPIError(403, "Forbidden")
        return {"id": offer_id, "name": "Visible offer"}

    async def list_offers(self) -> list[dict[str, Any]]:
        return [{"id": 18813, "name": "Visible offer", "state": "active"}]

    async def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self.next_campaign_id
        self.next_campaign_id += 1
        campaign = {
            **deepcopy(payload),
            "id": campaign_id,
            "state": "active",
            "domain": "kylovoa.com",
        }
        self.campaigns[campaign_id] = campaign
        return deepcopy(campaign)

    async def create_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        stream_id = self.next_stream_id
        self.next_stream_id += 1
        stream = {**deepcopy(payload), "id": stream_id}
        self.streams[stream_id] = stream
        return deepcopy(stream)

    async def list_campaigns(self) -> list[dict[str, Any]]:
        return [deepcopy(campaign) for campaign in self.campaigns.values()]

    async def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        if campaign_id not in self.campaigns:
            raise KeitaroAPIError(404, "Campaign not found")
        return deepcopy(self.campaigns[campaign_id])

    async def list_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        return [
            deepcopy(stream)
            for stream in self.streams.values()
            if stream["campaign_id"] == campaign_id
        ]

    async def get_stream(self, stream_id: int) -> dict[str, Any]:
        if stream_id not in self.streams:
            raise KeitaroAPIError(404, "Stream not found")
        return deepcopy(self.streams[stream_id])

    async def update_stream(
        self, stream_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        stream = self.streams[stream_id]
        stream.update(deepcopy(payload))
        stream["id"] = stream_id
        return deepcopy(stream)

    async def archive_campaign(self, campaign_id: int) -> dict[str, Any]:
        self.campaigns[campaign_id]["state"] = "deleted"
        self.archived.append(campaign_id)
        return {"status": "archived"}


def test_offline_create_edit_verify_and_archive() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    original_client = getattr(app.state, "keitaro_client", None)
    original_references = getattr(app.state, "references", None)
    fake = FakeKeitaro()
    app.state.keitaro_client = fake
    app.state.references = FakeReferences()
    app.dependency_overrides[get_db] = override_get_db
    api = TestClient(app)
    campaign_id = None
    try:
        created = api.post(
            "/api/campaigns",
            json={"name": "e2e_offline", "geo": "AU", "offer_id": 18813},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        campaign_id = body["campaign"]["id"]
        assert body["campaign"]["name"] == "test_vdovichenko_e2e_offline"
        assert body["campaign"]["domain_name"] == "kylovoa.com"
        assert body["campaign"]["group_name"] == "FORTESTS"
        assert body["campaign"]["traffic_source_name"] == "FORTESTS"
        assert body["campaign"]["campaign_url"].startswith("https://kylovoa.com/")
        assert len(body["streams"]) == 2

        geo_stream, offer_stream = body["streams"]
        assert geo_stream["position"] == 1
        assert geo_stream["filters"][0]["payload"] == ["AU"]
        assert offer_stream["offers"][0]["offer_id"] == 18813
        stream_id = offer_stream["id"]

        detail = api.get(f"/api/campaigns/{campaign_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["target_stream_id"] == stream_id
        assert detail.json()["campaign"]["traffic_source_name"] == "FORTESTS"

        updated = api.put(
            f"/api/campaigns/{campaign_id}/streams/{stream_id}/offers",
            json={
                "offers": [
                    {"offer_id": 18813, "share": 34, "state": "active"},
                    {"offer_id": 17210, "share": 33, "state": "active"},
                    {"offer_id": 24800, "share": 33, "state": "active"},
                ]
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["action"] == "add_offer"
        assert {
            offer["offer_id"]: offer["share"]
            for offer in fake.streams[stream_id]["offers"]
        } == {18813: 34, 17210: 33, 24800: 33}

        removed = api.put(
            f"/api/campaigns/{campaign_id}/streams/{stream_id}/offers",
            json={
                "offers": [
                    {"offer_id": 18813, "share": 50, "state": "active"},
                    {"offer_id": 17210, "share": 50, "state": "active"},
                ]
            },
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["action"] == "remove_offer"
        assert {
            offer["offer_id"]: offer["share"]
            for offer in removed.json()["stream"]["offers"]
        } == {18813: 50, 17210: 50}

        audit = api.get(f"/api/campaigns/{campaign_id}/audit")
        assert audit.status_code == 200, audit.text
        actions = {item["action"] for item in audit.json()["items"]}
        assert {"create", "add_offer", "remove_offer"} <= actions

        archived = api.post(f"/api/campaigns/{campaign_id}/archive")
        assert archived.status_code == 200, archived.text
        assert fake.campaigns[campaign_id]["state"] == "deleted"
        assert fake.archived == [campaign_id]
    finally:
        app.dependency_overrides.clear()
        if original_client is None:
            try:
                delattr(app.state, "keitaro_client")
            except AttributeError:
                pass
        else:
            app.state.keitaro_client = original_client
        if original_references is None:
            try:
                delattr(app.state, "references")
            except AttributeError:
                pass
        else:
            app.state.references = original_references
        Base.metadata.drop_all(engine)
        engine.dispose()
