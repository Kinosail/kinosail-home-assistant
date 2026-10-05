"""Q12 isolated HTTP-client contracts; fake responses do not prove a live Server."""
from __future__ import annotations

import pytest
from aiohttp import ClientTimeout

from custom_components.kinosail.api import KinosailClient, KinosailError
from tests.helpers import Response, Session


def values(count: int, start: int = 0) -> list[dict[str, object]]:
    return [{"id": f"q12_{number:03d}", "title": f"Q12 Item {number:03d}", "kind": "video"}
            for number in range(start, start + count)]


def page(items: object, total: object, offset: object = 0, limit: object = 200) -> dict[str, object]:
    return {"items": items, "total": total, "offset": offset, "limit": limit, "view": "all"}


async def test_page_preserves_metadata_query_and_bounded_transport() -> None:
    session = Session(Response(200, page(values(200), 201)), Response(200, page(values(1, 200), 201, 200)))
    client = KinosailClient(session, "https://fixture.example", "q12-fixture-token")
    first = await client.library_page("Q12")
    final = await client.library_page("Q12", offset=200)
    assert (first.total, first.offset, first.limit, len(first.items)) == (201, 0, 200, 200)
    assert (final.total, final.offset, final.limit, len(final.items)) == (201, 200, 200, 1)
    assert first.items == values(200)
    assert final.items == values(1, 200)
    assert len(session.calls) == 2
    assert session.calls[0][2]["params"] == {"limit": 200, "q": "Q12"}
    assert session.calls[1][2]["params"] == {"limit": 200, "q": "Q12", "offset": 200}
    for method, url, options in session.calls:
        assert method == "GET" and url == "https://fixture.example/api/v1/home-assistant/library"
        assert options["headers"] == {"Authorization": "Bearer q12-fixture-token"}
        assert options["ssl"] is True and options["allow_redirects"] is False
        assert options["timeout"] == ClientTimeout(total=10)


async def test_legacy_library_list_and_wire_contract_stay_exact() -> None:
    items = values(200)
    session = Session(Response(200, page(items, 201)))
    assert await KinosailClient(session, "https://fixture.example").library("Q12") == items
    assert len(session.calls) == 1
    assert session.calls[0][2]["params"] == {"limit": 200, "q": "Q12"}


@pytest.mark.parametrize(("query", "offset", "limit"), [
    (None, 0, 200), ("x" * 513, 0, 200), ("\u00e9" * 257, 0, 200), ("\ud800", 0, 200),
    ("Q12", True, 200), ("Q12", -1, 200), ("Q12", 1_000_001, 200),
    ("Q12", 0.5, 200), ("Q12", "200", 200),
    ("Q12", 0, True), ("Q12", 0, 0), ("Q12", 0, 201), ("Q12", 0, 2.0),
])
async def test_page_input_rejection_precedes_network(query: object, offset: object, limit: object) -> None:
    session = Session()
    with pytest.raises(KinosailError):
        await KinosailClient(session, "https://fixture.example").library_page(query, offset=offset, limit=limit)
    assert session.calls == []


@pytest.mark.parametrize("payload", [
    {"items": []}, {"items": [], "total": 0, "limit": 200}, {"items": [], "total": 0, "offset": 0},
    page([], True), page([], -1), page([], "0"), page([], 0.0),
    page([], 0, True), page([], 0, -1), page([], 0, 1_000_001),
    page([], 0, 0, True), page([], 0, 0, 0), page([], 0, 0, 201),
    page(values(1), 0), page(values(1), 1, 1), page(values(1), 1, 0, 1),
    page(values(1), 2), page(None, 0), page([{"id": "../foreign"}], 1),
    page([{"id": "x" * 129}], 1), page(values(201), 201),
    page([{"id": "q12_duplicate"}, {"id": "q12_duplicate"}], 2),
])
async def test_page_denies_malformed_or_inconsistent_metadata(payload: object) -> None:
    session = Session(Response(200, payload))
    with pytest.raises(KinosailError):
        await KinosailClient(session, "https://fixture.example").library_page()
    assert len(session.calls) == 1


async def test_smaller_limit_and_boundary_query_remain_bounded() -> None:
    session = Session(Response(200, page(values(1), 1, 0, 1)))
    result = await KinosailClient(session, "https://fixture.example").library_page("x" * 512, limit=1)
    assert (result.total, result.limit, result.items) == (1, 1, values(1))
    assert session.calls[0][2]["params"] == {"limit": 1, "q": "x" * 512}


async def test_changed_library_empty_final_page_is_truthful() -> None:
    session = Session(Response(200, page([], 12, 200)))
    result = await KinosailClient(session, "https://fixture.example").library_page("Q12", offset=200)
    assert (result.items, result.total, result.offset, result.limit) == ([], 12, 200, 200)
    assert len(session.calls) == 1


async def test_maximum_offset_does_not_auto_fetch() -> None:
    session = Session(Response(200, page([], 0, 1_000_000)))
    result = await KinosailClient(session, "https://fixture.example").library_page(offset=1_000_000)
    assert result.offset == 1_000_000 and result.items == []
    assert len(session.calls) == 1
    assert session.calls[0][2]["params"] == {"limit": 200, "offset": 1_000_000}


async def test_initial_library_attaches_response_owned_immutable_page_metadata() -> None:
    session = Session(Response(200, page(values(200), 201)), Response(200, page(values(1), 1)))
    client = KinosailClient(session, "https://fixture.example", "q12-fixture-token")
    first = await client.library("Q12")
    assert isinstance(first, list) and first == values(200)
    first_page = first.page
    assert (first_page.total, first_page.offset, first_page.limit) == (201, 0, 200)
    second = await client.library("New Q12")
    assert isinstance(second, list) and second == values(1)
    assert (second.page.total, second.page.offset, second.page.limit) == (1, 0, 200)
    assert first.page is first_page and first.page is not second.page
    assert (first_page.total, first_page.offset, first_page.limit) == (201, 0, 200)
    for field in ("total", "offset", "limit"):
        with pytest.raises((AttributeError, TypeError)):
            setattr(first_page, field, 999)
    with pytest.raises((AttributeError, TypeError)):
        first.page = second.page
    assert len(session.calls) == 2
    assert session.calls[0][2]["params"] == {"limit": 200, "q": "Q12"}
    assert session.calls[1][2]["params"] == {"limit": 200, "q": "New Q12"}


@pytest.mark.parametrize("payload", [
    {"items": values(200)},
    page(values(200), True),
    page(values(200), 201, True),
    page(values(200), 201, 0, 201),
])
async def test_initial_library_legacy_items_remain_unpaged_without_valid_metadata(payload: dict) -> None:
    session = Session(Response(200, payload))
    result = await KinosailClient(session, "https://fixture.example").library()
    assert isinstance(result, list) and result == values(200)
    assert getattr(result, "page", None) is None
    assert len(session.calls) == 1 and session.calls[0][2]["params"] == {"limit": 200}
