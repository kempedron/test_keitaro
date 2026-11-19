from app.routers.api import enrich_campaign


def test_enrich_campaign_resolves_names_and_url() -> None:
    campaign = {
        "id": 1,
        "alias": "test-campaign-abc",
        "domain_id": 1813,
        "group_id": 10332,
        "traffic_source_id": 836,
    }

    result = enrich_campaign(
        campaign,
        domain_names={1813: "kylovoa.com"},
        group_names={10332: "FORTESTS"},
        source_names={836: "FORTESTS"},
    )

    assert result["domain_name"] == "kylovoa.com"
    assert result["group_name"] == "FORTESTS"
    assert result["traffic_source_name"] == "FORTESTS"
    assert result["campaign_url"] == "https://kylovoa.com/test-campaign-abc"
    assert campaign == {
        "id": 1,
        "alias": "test-campaign-abc",
        "domain_id": 1813,
        "group_id": 10332,
        "traffic_source_id": 836,
    }


def test_enrich_campaign_keeps_existing_scheme() -> None:
    result = enrich_campaign(
        {"id": 2, "alias": "promo", "domain_id": 10},
        domain_names={10: "https://track.example.com/"},
    )

    assert result["campaign_url"] == "https://track.example.com/promo"


def test_enrich_campaign_without_alias_has_no_url() -> None:
    result = enrich_campaign({"id": 3, "domain_id": 10}, domain_names={10: "kylovoa.com"})

    assert "campaign_url" not in result
