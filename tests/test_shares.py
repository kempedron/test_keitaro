import pytest

from app.services.campaign_editor import (
    distribute_offer_ids,
    equal_shares,
    normalize_offers,
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, []),
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),
        (4, [25, 25, 25, 25]),
        (7, [15, 15, 14, 14, 14, 14, 14]),
    ],
)
def test_equal_shares_exact(count: int, expected: list[int]) -> None:
    assert equal_shares(count) == expected


@pytest.mark.parametrize("count", range(0, 26))
def test_equal_shares_invariant(count: int) -> None:
    shares = equal_shares(count)
    assert len(shares) == count
    if count:
        assert sum(shares) == 100
        assert max(shares) - min(shares) <= 1
    else:
        assert shares == []


def test_distribute_offer_ids_keeps_order() -> None:
    result = distribute_offer_ids([11, 22, 33])
    assert [item["share"] for item in result] == [34, 33, 33]
    assert [item["offer_id"] for item in result] == [11, 22, 33]
    assert all(item["state"] == "active" for item in result)


def test_normalize_offers_accepts_valid_distribution() -> None:
    offers = [
        {"offer_id": 1, "share": 34, "state": "active"},
        {"offer_id": 2, "share": 33, "state": "active"},
        {"offer_id": 3, "share": 33, "state": "active"},
    ]
    assert normalize_offers(offers) == offers


def test_normalize_offers_rejects_wrong_sum() -> None:
    with pytest.raises(ValueError, match="sum to 100"):
        normalize_offers(
            [
                {"offer_id": 1, "share": 50, "state": "active"},
                {"offer_id": 2, "share": 40, "state": "active"},
            ]
        )


def test_normalize_offers_ignores_disabled_for_sum() -> None:
    offers = [
        {"offer_id": 1, "share": 100, "state": "active"},
        {"offer_id": 2, "share": 0, "state": "disabled"},
    ]
    assert normalize_offers(offers) == offers


def test_normalize_offers_allows_empty_list() -> None:
    assert normalize_offers([]) == []


def test_normalize_offers_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="more than once"):
        normalize_offers(
            [
                {"offer_id": 1, "share": 50, "state": "active"},
                {"offer_id": 1, "share": 50, "state": "active"},
            ]
        )


def test_normalize_offers_rejects_out_of_range_share() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        normalize_offers([{"offer_id": 1, "share": 101, "state": "active"}])
