import json

import httpx
import pytest

from app.clients.keitaro import KeitaroAPIError, KeitaroClient

BASE_URL = "https://example.test/admin_api/v1"


def make_client(handler) -> KeitaroClient:
    return KeitaroClient(
        base_url=BASE_URL,
        api_key="unit-test-key",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("status", "body", "expected_detail"),
    [
        (401, {"error": "Unauthorized"}, "Unauthorized"),
        (404, {"error": "Campaign not found"}, "Campaign not found"),
        (422, {"name": "Name is required"}, "Name is required"),
        (422, {"errors": {"name": ["Invalid"]}}, '{"name": ["Invalid"]}'),
    ],
)
async def test_error_mapping(status: int, body: dict, expected_detail: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = make_client(handler)
    try:
        with pytest.raises(KeitaroAPIError) as captured:
            await client.get_campaign(1)
    finally:
        await client.aclose()

    error = captured.value
    assert error.status_code == status
    assert error.detail == expected_detail
    assert error.as_dict()["keitaro_status"] == status
    assert error.as_dict()["payload"] == body


async def test_connection_error_maps_to_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(KeitaroAPIError) as captured:
            await client.list_campaigns()
    finally:
        await client.aclose()

    assert captured.value.status_code == 502
    assert "connection error" in captured.value.detail.lower()


async def test_success_sends_api_key_and_parses_json() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("Api-Key")
        seen["method"] = request.method
        seen["content_type"] = request.headers.get("Content-Type")
        seen["body"] = json.loads(request.content or b"{}")
        return httpx.Response(200, json={"id": 1, "name": "test_vdovichenko_x"})

    client = make_client(handler)
    try:
        result = await client.create_campaign({"name": "test_vdovichenko_x", "alias": "a"})
    finally:
        await client.aclose()

    assert result["id"] == 1
    assert seen["api_key"] == "unit-test-key"
    assert seen["method"] == "POST"
    assert seen["content_type"] == "application/json"
    assert seen["body"]["name"] == "test_vdovichenko_x"


async def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.clients.keitaro.settings.keitaro_api_key", "")
    with pytest.raises(ValueError):
        KeitaroClient(base_url=BASE_URL)
