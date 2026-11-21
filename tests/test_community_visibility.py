"""Visibility rules for community prices (strict mode)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from supermarket_comparison.storage import (
    CommunityPriceInput,
    Database,
    Repository,
)


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


def entry(**overrides: object) -> CommunityPriceInput:
    data: dict[str, object] = {
        "name": "Bio Butter 250g",
        "store": "lidl",
        "price": 2.49,
        "postal_code": "65618",
        "quantity": 0.25,
        "unit": "kg",
        "scout_id": "Scout-A",
    }
    data.update(overrides)
    return CommunityPriceInput(**data)  # type: ignore[arg-type]


def identity(repository: Repository) -> str:
    from supermarket_comparison.storage import identity_of

    return identity_of(ean=None, name="Bio Butter 250g", unit="kg", quantity=0.25)


def aggregate(repository: Repository) -> dict | None:
    return repository.community.aggregate(
        identity=identity(repository), store="lidl", postal_code="65618"
    )


def test_pending_price_is_not_visible(repository: Repository) -> None:
    created = repository.community.add_price(entry())

    assert created["status"] == "pending"
    assert aggregate(repository) is None


def test_approved_price_is_visible(repository: Repository) -> None:
    created = repository.community.add_price(entry())

    repository.community.approve(created["id"], reviewer="admin")

    result = aggregate(repository)
    assert result is not None
    assert result["median_price"] == pytest.approx(2.49)


def test_three_distinct_scouts_verify(repository: Repository) -> None:
    created = repository.community.add_price(entry())

    for scout in ("B", "C", "D"):
        repository.community.confirm(created["id"], scout)

    assert repository.community.get_price(created["id"])["status"] == "verified"
    assert aggregate(repository) is not None


def test_same_scout_twice_counts_once(repository: Repository) -> None:
    created = repository.community.add_price(entry())
    repository.community.confirm(created["id"], "B")
    updated = repository.community.confirm(created["id"], "B")

    # author + B
    assert updated["confirmations"] == 2
    assert updated["status"] == "pending"


def test_rejected_stays_hidden_after_confirm(repository: Repository) -> None:
    created = repository.community.add_price(entry())
    repository.community.reject(created["id"], reviewer="admin", reason="Unsinn")
    repository.community.confirm(created["id"], "B")
    repository.community.confirm(created["id"], "C")
    repository.community.confirm(created["id"], "D")

    assert repository.community.get_price(created["id"])["status"] == "rejected"
    assert aggregate(repository) is None


def test_approve_all_pending_skips_review(repository: Repository) -> None:
    repository.community.add_price(entry())
    repository.community.add_price(
        entry(name="Milch", price=999.99, unit="l", quantity=1.0)
    )

    approved = repository.community.approve_all_pending(reviewer="admin")

    assert approved == 1
    assert aggregate(repository) is not None


def test_review_queue_lists_flagged_entries(repository: Repository) -> None:
    repository.community.add_price(
        entry(name="Milch", price=999.99, unit="l", quantity=1.0)
    )
    repository.community.add_price(entry())

    queue = repository.community.review_queue()
    counts = repository.community.review_counts()

    assert [item["name"] for item in queue] == ["Milch"]
    assert counts == {"pending": 1, "pending_review": 1}


def test_review_reason_is_persisted(repository: Repository) -> None:
    created = repository.community.add_price(
        entry(name="Milch", price=999.99, unit="l", quantity=1.0)
    )

    assert created["status"] == "pending_review"
    assert created["review_reason"]


def test_aggregation_ignores_pending_review(repository: Repository) -> None:
    repository.community.add_price(
        entry(name="Milch", price=999.99, unit="l", quantity=1.0)
    )

    assert (
        repository.community.aggregate(
            identity="txt:milch|1l", store="lidl", postal_code="65618"
        )
        is None
    )
