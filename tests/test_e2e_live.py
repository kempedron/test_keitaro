import os
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.campaign_editor import distribute_offer_ids

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_E2E") != "1",
        reason="set RUN_LIVE_E2E=1 to run against the shared Keitaro stand",
    ),
]

OFFER_IDS = [18813, 17210, 24800]


def _find_created_campaign(api: TestClient, name: str) -> int | None:
    response = api.get("/api/campaigns", params={"mine": "false", "q": name})
    if response.status_code != 200:
        return None
    for item in response.json().get("items", []):
        if item.get("name") == name and item.get("state") != "deleted":
            return int(item["id"])
    return None


def test_create_edit_and_archive_campaign() -> None:
    campaign_id = None
    body_ok = False
    requested_name = "e2e_check"
    full_name = f"{settings.normalized_prefix}{requested_name}"
    with TestClient(app) as api:
        try:
            print(f"[live-e2e] create {full_name}", flush=True)
            response = api.post(
                "/api/campaigns",
                json={"name": requested_name, "geo": "AU", "offer_id": 18813},
            )
            if response.status_code == 422:
                requested_name = f"e2e_check_{int(time.time())}"
                full_name = f"{settings.normalized_prefix}{requested_name}"
                print(f"[live-e2e] name busy, retry as {full_name}", flush=True)
                response = api.post(
                    "/api/campaigns",
                    json={"name": requested_name, "geo": "AU", "offer_id": 18813},
                )
            assert response.status_code == 201, response.text
            created = response.json()
            campaign_id = created["campaign"]["id"]
            full_name = created["campaign"]["name"]
            assert full_name == f"{settings.normalized_prefix}{requested_name}"
            assert len(created["streams"]) == 2
            print(f"[live-e2e] campaign #{campaign_id} created", flush=True)

            geo_flow, offer_flow = created["streams"]
            assert geo_flow["position"] == 1
            assert geo_flow["schema"] == "redirect"
            assert geo_flow["action_payload"].startswith("https://google.com")
            assert geo_flow["filters"][0]["name"] == "country"
            assert geo_flow["filters"][0]["mode"] == "accept"
            assert geo_flow["filters"][0]["payload"] == ["AU"]
            assert offer_flow["position"] == 2
            assert offer_flow["schema"] == "landings"
            assert offer_flow["offers"][0]["offer_id"] == 18813
            assert offer_flow["offers"][0]["share"] == 100
            print("[live-e2e] two flows verified", flush=True)

            detail_response = api.get(f"/api/campaigns/{campaign_id}")
            assert detail_response.status_code == 200, detail_response.text
            detail = detail_response.json()
            assert detail.get("target_stream_id"), detail
            stream_id = detail["target_stream_id"]
            assert stream_id == offer_flow["id"]

            print("[live-e2e] adding three offers", flush=True)
            response = api.put(
                f"/api/campaigns/{campaign_id}/streams/{stream_id}/offers",
                json={"offers": distribute_offer_ids(OFFER_IDS)},
            )
            assert response.status_code == 200, response.text
            stored = {
                offer["offer_id"]: offer["share"]
                for offer in response.json()["stream"]["offers"]
            }
            assert stored == {18813: 34, 17210: 33, 24800: 33}

            fresh_response = api.get(f"/api/campaigns/{campaign_id}")
            assert fresh_response.status_code == 200, fresh_response.text
            fresh = fresh_response.json()
            target = next(stream for stream in fresh["streams"] if stream["id"] == stream_id)
            assert {
                offer["offer_id"]: offer["share"] for offer in target["offers"]
            } == {18813: 34, 17210: 33, 24800: 33}
            print("[live-e2e] stored shares are 34/33/33", flush=True)

            print("[live-e2e] removing one offer", flush=True)
            response = api.put(
                f"/api/campaigns/{campaign_id}/streams/{stream_id}/offers",
                json={"offers": distribute_offer_ids(OFFER_IDS[:2])},
            )
            assert response.status_code == 200, response.text
            stored = {
                offer["offer_id"]: offer["share"]
                for offer in response.json()["stream"]["offers"]
            }
            assert stored == {18813: 50, 17210: 50}
            assert response.json()["action"] == "remove_offer"
            print("[live-e2e] stored shares are 50/50", flush=True)

            audit_response = api.get(f"/api/campaigns/{campaign_id}/audit")
            assert audit_response.status_code == 200, audit_response.text
            audit = audit_response.json()["items"]
            assert any(item["action"] == "create" for item in audit)
            assert any(item["action"] == "add_offer" for item in audit)
            assert any(item["action"] == "remove_offer" for item in audit)
            print("[live-e2e] audit verified", flush=True)
            body_ok = True
        finally:
            if campaign_id is None:
                try:
                    campaign_id = _find_created_campaign(api, full_name)
                except Exception as exc:
                    print(f"[live-e2e] cleanup lookup failed: {exc}", flush=True)
            if campaign_id is not None:
                try:
                    archived = api.post(f"/api/campaigns/{campaign_id}/archive")
                    if archived.status_code == 200:
                        print(f"[live-e2e] campaign #{campaign_id} archived", flush=True)
                    else:
                        message = (
                            f"[live-e2e] archive failed: "
                            f"{archived.status_code} {archived.text}"
                        )
                        print(message, flush=True)
                        if body_ok:
                            raise AssertionError(message)
                except Exception as exc:
                    print(f"[live-e2e] archive failed: {exc}", flush=True)
