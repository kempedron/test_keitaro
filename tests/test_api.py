from fastapi.testclient import TestClient

from app.main import app


class FakeReferences:
    async def offers(self) -> list[dict]:
        return [
            {"id": 18813, "name": "Demo offer", "state": "active"},
            {"id": 222, "name": "Another offer", "state": "active"},
        ]


def make_client() -> TestClient:
    app.state.references = FakeReferences()
    return TestClient(app)


def test_health() -> None:
    client = make_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["prefix"] == "test_vdovichenko_"


def test_offers_search_filters_by_query() -> None:
    client = make_client()
    response = client.get("/api/references/offers", params={"q": "demo"})
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [18813]


def test_equalize_endpoint_returns_exact_shares() -> None:
    client = make_client()
    response = client.post("/api/shares/equalize", json={"offer_ids": [1, 2, 3]})
    assert response.status_code == 200
    payload = response.json()
    assert [item["share"] for item in payload["offers"]] == [34, 33, 33]
    assert payload["total"] == 100


def test_equalize_rejects_duplicate_ids() -> None:
    client = make_client()
    response = client.post("/api/shares/equalize", json={"offer_ids": [1, 1]})
    assert response.status_code == 400


def test_index_page_renders() -> None:
    client = make_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "test_vdovichenko_" in response.text
