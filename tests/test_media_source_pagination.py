"""Q12 isolated public media-source contracts; no live HA frontend/network proof."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from homeassistant.components.media_player import BrowseError, MediaClass, SearchMediaQuery
from homeassistant.components.media_source import MediaSourceError, MediaSourceItem, Unresolvable

from custom_components.kinosail.api import KinosailClient
from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.media_source import KinosailMediaSource
from tests.helpers import Response, Session


def values(count: int, start: int = 0) -> list[dict[str, object]]:
    return [{"id": f"q12_{number:03d}", "title": f"Q12 Item {number:03d}", "kind": "video"}
            for number in range(start, start + count)]


def page(count: int, total: int, offset: int = 0) -> dict[str, object]:
    return {"items": values(count, offset), "total": total, "offset": offset, "limit": 200, "view": "all"}


def location(hass, identifier: str, domain: str = DOMAIN) -> MediaSourceItem:
    return MediaSourceItem(hass, domain, identifier, None)


def encoded(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")


def continuation(query: str = "", offset: int = 200, entry: str = "entry") -> str:
    return "entry/@page/" + encoded({"version": 1, "entry": entry, "query": query, "offset": offset})


def noncanonical_continuation() -> str:
    payload = {"version": 1, "entry": "entry", "query": "", "offset": 200}
    token = encoded(payload)
    if len(token) % 4 == 0:
        payload["query"] = "Q"
        token = encoded(payload)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return "entry/@page/" + token[:-1] + alphabet[alphabet.index(token[-1]) + 1]


def source(hass, session: Session) -> KinosailMediaSource:
    client = KinosailClient(session, "https://fixture.example", "q12-fixture-token")
    hass.data[DOMAIN] = {"entry": SimpleNamespace(client=client, name="Fictional Q12")}
    return KinosailMediaSource(hass)


def next_entries(children) -> list:
    return [child for child in children if child.identifier and "/@page/" in child.identifier]


def assert_count(children, title: str) -> None:
    summaries = [child for child in children if child.title == title]
    assert len(summaries) == 1
    assert summaries[0].can_play is False and summaries[0].can_expand is False


async def test_browse_offers_count_and_one_nonplayable_next(hass) -> None:
    session = Session(Response(200, page(200, 201)), Response(200, page(1, 201, 200)))
    instance = source(hass, session)
    first = await instance.async_browse_media(location(hass, "entry"))
    assert first.title == "Fictional Q12" and first.can_search is True
    playable = [child for child in first.children if child.can_play]
    assert len(playable) == 200
    assert [child.identifier for child in playable] == [f"entry/q12_{number:03d}" for number in range(200)]
    assert [child.title for child in playable] == [f"Q12 Item {number:03d}" for number in range(200)]
    assert all(not child.can_expand for child in playable)
    assert_count(first.children, "Showing 1-200 of 201")
    next_page = next_entries(first.children)
    assert len(next_page) == 1
    assert next_page[0].identifier == continuation()
    assert next_page[0].media_class == MediaClass.DIRECTORY
    assert next_page[0].can_play is False and next_page[0].can_expand is True
    final = await instance.async_browse_media(location(hass, next_page[0].identifier))
    assert [child.identifier for child in final.children if child.can_play] == ["entry/q12_200"]
    assert_count(final.children, "Showing 201-201 of 201")
    assert final.can_search is True
    assert next_entries(final.children) == []
    assert len(session.calls) == 2
    assert session.calls[1][2]["params"] == {"limit": 200, "offset": 200}


async def test_existing_search_keeps_query_through_next_directory(hass) -> None:
    session = Session(Response(200, page(200, 201)), Response(200, page(1, 201, 200)))
    instance = source(hass, session)
    result = await instance.async_search_media(location(hass, "entry"), SearchMediaQuery(search_query="Q12"))
    playable = [child for child in result.result if child.can_play]
    assert len(playable) == 200
    assert [child.identifier for child in playable] == [f"entry/q12_{number:03d}" for number in range(200)]
    assert [child.title for child in playable] == [f"Q12 Item {number:03d}" for number in range(200)]
    assert all(not child.can_expand for child in playable)
    assert_count(result.result, "Showing 1-200 of 201")
    next_page = next_entries(result.result)
    assert len(next_page) == 1 and next_page[0].identifier == continuation("Q12")
    final = await instance.async_browse_media(location(hass, next_page[0].identifier))
    assert_count(final.children, "Showing 201-201 of 201")
    assert session.calls[0][2]["params"] == {"limit": 200, "q": "Q12"}
    assert session.calls[1][2]["params"] == {"limit": 200, "q": "Q12", "offset": 200}


async def test_short_library_preserves_existing_titles_items_and_search(hass) -> None:
    session = Session(Response(200, page(2, 2)))
    result = await source(hass, session).async_browse_media(location(hass, "entry"))
    assert result.title == "Fictional Q12" and result.can_search is True
    assert [child.identifier for child in result.children] == ["entry/q12_000", "entry/q12_001"]
    assert [child.title for child in result.children] == ["Q12 Item 000", "Q12 Item 001"]
    assert all(child.can_play and not child.can_expand for child in result.children)


async def test_changed_library_empty_final_page_stops(hass) -> None:
    session = Session(Response(200, page(0, 12, 200)))
    result = await source(hass, session).async_browse_media(location(hass, continuation("Q12")))
    assert_count(result.children, "Showing 0-0 of 12")
    assert all(not child.can_play for child in result.children)
    assert next_entries(result.children) == []
    assert len(session.calls) == 1


@pytest.mark.parametrize("identifier", [
    "entry/@page/", "entry/@page/%%%", "entry/@page/" + "A" * 2049,
    continuation() + "=", noncanonical_continuation(),
    "entry/@page/" + encoded({"version": True, "entry": "entry", "query": "", "offset": 200}),
    "entry/@page/" + encoded({"version": 1.0, "entry": "entry", "query": "", "offset": 200}),
    "entry/@page/" + encoded({"version": 1, "entry": "entry", "query": None, "offset": 200}),
    "entry/@page/" + encoded({"version": 1, "entry": "entry", "query": 1, "offset": 200}),
    "entry/@page/" + encoded({"version": 2, "entry": "entry", "query": "", "offset": 200}),
    "entry/@page/" + encoded({"version": 1, "entry": "entry", "query": "", "offset": True}),
    continuation(offset=-1), continuation(offset=1_000_001), continuation(entry="foreign"),
    continuation(query="x" * 513), continuation(query="\u00e9" * 257),
    "missing/@page/" + encoded({"version": 1, "entry": "missing", "query": "", "offset": 200}),
    "entry/@page/" + encoded({"version": 1, "entry": "entry", "query": "", "offset": 200, "extra": 1}),
    "entry/@page/" + base64.urlsafe_b64encode(b'{"version":1,"entry":"entry","query":"","offset":200,"offset":400}').decode().rstrip("="),
    "entry/@page/" + encoded({"version": 1, "entry": "entry", "query": "", "offset": 200}) + "/nested",
])
async def test_bad_or_foreign_continuation_fails_before_requests(hass, identifier: str) -> None:
    session = Session()
    with pytest.raises(BrowseError):
        await source(hass, session).async_browse_media(location(hass, identifier))
    with pytest.raises(Unresolvable):
        await source(hass, session).async_resolve_media(location(hass, identifier))
    assert session.calls == []


async def test_foreign_domain_page_cannot_reach_runtime(hass) -> None:
    session = Session()
    with pytest.raises(BrowseError):
        await source(hass, session).async_browse_media(location(hass, continuation(), domain="foreign"))
    assert session.calls == []


async def test_continuation_never_resolves_or_calls_playback(hass) -> None:
    session = Session()
    with pytest.raises(Unresolvable):
        await source(hass, session).async_resolve_media(location(hass, continuation()))
    assert session.calls == []


async def test_continuation_failure_uses_fixed_error_and_retains_retry_scope(hass) -> None:
    session = Session(Response(500, {"private": "unexported fixture failure"}), Response(200, page(1, 201, 200)))
    instance = source(hass, session)
    with pytest.raises(BrowseError, match="^Could not browse Kinosail$"):
        await instance.async_browse_media(location(hass, continuation("Q12")))
    recovered = await instance.async_browse_media(location(hass, continuation("Q12")))
    assert_count(recovered.children, "Showing 201-201 of 201")
    assert len(session.calls) == 2
    assert session.calls[0][2]["params"] == session.calls[1][2]["params"] == {"limit": 200, "q": "Q12", "offset": 200}


@pytest.mark.parametrize("total", [201, 401])
async def test_search_from_continuing_or_final_directory_starts_new_query(hass, total: int) -> None:
    count = min(200, total - 200)
    session = Session(Response(200, page(count, total, 200)), Response(200, page(2, 2)))
    instance = source(hass, session)
    foreign = Session()
    hass.data[DOMAIN]["other"] = SimpleNamespace(
        client=KinosailClient(foreign, "https://other.example", "other-fixture-token"),
        name="Other fictional Q12",
    )
    identifier = continuation("Old Q12")
    directory = await instance.async_browse_media(location(hass, identifier))
    assert directory.can_search is True
    assert len(next_entries(directory.children)) == (1 if total == 401 else 0)
    before = len(session.calls)
    found = await instance.async_search_media(location(hass, identifier), SearchMediaQuery(search_query="New Q12"))
    assert [child.identifier for child in found.result] == ["entry/q12_000", "entry/q12_001"]
    assert [child.title for child in found.result] == ["Q12 Item 000", "Q12 Item 001"]
    assert all(child.can_play and not child.can_expand for child in found.result)
    assert next_entries(found.result) == []
    assert len(session.calls) == before + 1
    method, url, options = session.calls[-1]
    assert method == "GET" and url == "https://fixture.example/api/v1/home-assistant/library"
    assert options["params"] == {"limit": 200, "q": "New Q12"}
    assert options["headers"] == {"Authorization": "Bearer q12-fixture-token"}
    assert foreign.calls == []


async def test_offset_ceiling_stops_next_even_when_more_results_exist(hass) -> None:
    session = Session(Response(200, page(200, 1_000_201, 1_000_000)))
    result = await source(hass, session).async_browse_media(location(hass, continuation("Q12", 1_000_000)))
    assert_count(result.children, "Showing 1000001-1000200 of 1000201")
    assert [child.identifier for child in result.children if child.can_play] == [
        f"entry/q12_{number:03d}" for number in range(1_000_000, 1_000_200)
    ]
    assert result.can_search is True and next_entries(result.children) == []
    assert len(session.calls) == 1
    assert session.calls[0][2]["params"] == {"limit": 200, "q": "Q12", "offset": 1_000_000}


@pytest.mark.parametrize("identifier", ["entry", continuation("Old Q12")])
async def test_lone_surrogate_search_is_fixed_public_error_before_transport(hass, identifier: str) -> None:
    session = Session()
    with pytest.raises(MediaSourceError, match="^Kinosail search query is invalid$"):
        await source(hass, session).async_search_media(location(hass, identifier), SearchMediaQuery(search_query="\ud800"))
    assert session.calls == []


@pytest.mark.parametrize("payload", [
    {"items": values(200)},
    {"items": values(200), "total": True, "offset": 0, "limit": 200, "view": "all"},
])
async def test_initial_legacy_or_invalid_metadata_never_creates_paging_children(hass, payload: dict) -> None:
    session = Session(Response(200, payload), Response(200, payload))
    instance = source(hass, session)
    browsed = await instance.async_browse_media(location(hass, "entry"))
    searched = await instance.async_search_media(location(hass, "entry"), SearchMediaQuery(search_query="Q12"))
    for children in (browsed.children, searched.result):
        assert len(children) == 200 and all(child.can_play and not child.can_expand for child in children)
        assert [child.identifier for child in children] == [f"entry/q12_{number:03d}" for number in range(200)]
        assert next_entries(children) == []
    assert len(session.calls) == 2
