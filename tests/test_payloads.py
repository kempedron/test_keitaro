import pytest

from app.services.campaign_creator import (
    build_alias,
    build_campaign_payload,
    build_geo_stream_payload,
    build_offer_stream_payload,
    normalize_campaign_name,
    parse_geo_codes,
)
from app.services.campaign_editor import build_stream_put_payload

PREFIX = "test_vdovichenko_"


def test_parse_geo_codes_normalizes_and_deduplicates() -> None:
    assert parse_geo_codes("MX, au;RO au") == ["MX", "AU", "RO"]
    assert parse_geo_codes(["au", "AU"]) == ["AU"]


@pytest.mark.parametrize("value", ["", "   ", "USA", "A1", "UK"])
def test_parse_geo_codes_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_geo_codes(value)


def test_normalize_campaign_name_prefixes_once() -> None:
    assert normalize_campaign_name("my campaign", PREFIX) == PREFIX + "my campaign"
    assert normalize_campaign_name(PREFIX + "my campaign", PREFIX) == PREFIX + "my campaign"
    assert normalize_campaign_name("Test_Vdovichenko_My", PREFIX) == PREFIX + "My"


def test_normalize_campaign_name_rejects_empty_base() -> None:
    with pytest.raises(ValueError):
        normalize_campaign_name(PREFIX, PREFIX)


def test_build_alias_is_slug_and_unique() -> None:
    first = build_alias("test_vdovichenko_My Campaign")
    second = build_alias("test_vdovichenko_My Campaign")
    assert first.startswith("test-vdovichenko-my-campaign-")
    assert first != second


def test_build_campaign_payload_matches_schema() -> None:
    payload = build_campaign_payload(
        name="test_vdovichenko_demo",
        alias="test-vdovichenko-demo-abc123",
        domain_id=1813,
        group_id=10332,
        traffic_source_id=836,
    )
    assert payload["name"] == "test_vdovichenko_demo"
    assert payload["alias"] == "test-vdovichenko-demo-abc123"
    assert payload["type"] == "position"
    assert payload["state"] == "active"
    assert payload["domain_id"] == 1813
    assert payload["group_id"] == "10332"
    assert payload["traffic_source_id"] == 836
    assert payload["cost_type"] == "CPC"
    assert payload["cost_value"] == 0


def test_build_geo_stream_payload() -> None:
    payload = build_geo_stream_payload(123, ["MX", "AU"])
    assert payload["campaign_id"] == 123
    assert payload["position"] == 1
    assert payload["type"] == "regular"
    assert payload["schema"] == "redirect"
    assert payload["action_type"] == "http"
    assert payload["action_payload"] == "https://google.com/"
    assert payload["filters"] == [
        {"name": "country", "mode": "accept", "payload": ["MX", "AU"]}
    ]
    assert payload["offers"] == []


def test_build_offer_stream_payload() -> None:
    payload = build_offer_stream_payload(123, 18813)
    assert payload["campaign_id"] == 123
    assert payload["position"] == 2
    assert payload["type"] == "default"
    assert payload["schema"] == "landings"
    assert payload["offers"] == [
        {"offer_id": 18813, "share": 100, "state": "active"}
    ]


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
    "filters": [
        {"id": 900, "name": "country", "mode": "accept", "payload": ["AU"], "oid": 900}
    ],
    "offers": [
        {"id": 1, "offer_id": 18813, "share": 100, "state": "active"},
    ],
    "triggers": [],
    "landings": [],
}


def test_build_stream_put_payload_preserves_flow_fields() -> None:
    payload = build_stream_put_payload(
        STREAM,
        [
            {"offer_id": 18813, "share": 50, "state": "active"},
            {"offer_id": 222, "share": 50, "state": "active"},
        ],
    )
    assert payload["campaign_id"] == 10
    assert payload["name"] == "Offers"
    assert payload["type"] == "default"
    assert payload["position"] == 2
    assert payload["schema"] == "landings"
    assert payload["action_type"] == "http"
    assert payload["filters"] == [
        {"id": 900, "name": "country", "mode": "accept", "payload": ["AU"]}
    ]
    assert payload["offers"] == [
        {"id": 1, "offer_id": 18813, "share": 50, "state": "active"},
        {"offer_id": 222, "share": 50, "state": "active"},
    ]
    assert "triggers" not in payload
    assert "landings" not in payload
