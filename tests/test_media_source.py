"""Tests for the Kinosail media source."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.media_player import BrowseError, MediaClass, MediaType, SearchMediaQuery
from homeassistant.components.media_source import MediaSourceItem, Unresolvable

from custom_components.kinosail.api import KinosailError
from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.media_source import KinosailMediaSource, async_get_media_source


def item(hass, identifier: str) -> MediaSourceItem:
    return MediaSourceItem(hass, DOMAIN, identifier, None)


def runtime(*, library: object = None, playback: object = None) -> SimpleNamespace:
    client = SimpleNamespace(
        library=AsyncMock(return_value=[] if library is None else library),
        playback=AsyncMock(return_value=("https://server/media", "video/mp4") if playback is None else playback),
    )
    return SimpleNamespace(client=client, name="Living Room")


async def test_factory_and_root_browse_list_configured_servers(hass) -> None:
    source = await async_get_media_source(hass)
    hass.data[DOMAIN] = {"entry": runtime()}
    result = await source.async_browse_media(item(hass, ""))
    assert result.title == "Kinosail"
    assert result.media_class is MediaClass.APP
    assert result.identifier is None
    assert result.domain == DOMAIN
    assert result.media_content_type == ""
    assert result.can_play is False
    assert result.can_expand is True
    server = result.children[0]
    assert server.domain == DOMAIN
    assert server.identifier == "entry"
    assert server.media_class is MediaClass.DIRECTORY
    assert server.media_content_type == ""
    assert server.title == "Living Room"
    assert server.can_play is False
    assert server.can_expand is True


async def test_server_browse_maps_library_items(hass) -> None:
    instance = runtime(
        library=[
            {"id": "song", "kind": "audio", "title": "Song"},
            {"id": "book", "kind": "audiobook", "title": "Book"},
            {"id": "movie", "kind": "video", "title": ""},
            {"id": "other", "kind": 1, "title": 1},
        ]
    )
    hass.data[DOMAIN] = {"entry": instance}
    result = await KinosailMediaSource(hass).async_browse_media(item(hass, "entry"))
    assert result.can_search
    assert result.title == "Living Room"
    assert result.domain == DOMAIN
    assert result.identifier == "entry"
    assert result.media_class is MediaClass.DIRECTORY
    assert result.media_content_type == ""
    assert result.can_play is False
    assert result.can_expand is True
    assert [child.identifier for child in result.children] == ["entry/song", "entry/book", "entry/movie", "entry/other"]
    assert [child.media_content_type for child in result.children] == [
        MediaType.MUSIC,
        MediaType.MUSIC,
        MediaType.VIDEO,
        MediaType.VIDEO,
    ]
    assert [child.title for child in result.children] == ["Song", "Book", "Untitled", "Untitled"]
    assert all(
        child.domain == DOMAIN
        and child.media_class in {MediaClass.MUSIC, MediaClass.VIDEO}
        and child.can_play is True
        and child.can_expand is False
        for child in result.children
    )


async def test_root_browse_and_runtime_handle_missing_domain(hass) -> None:
    source = KinosailMediaSource(hass)
    assert source.domain == DOMAIN
    result = await source.async_browse_media(item(hass, ""))
    assert result.children == []
    with pytest.raises(BrowseError, match="not available"):
        source._runtime("missing")


@pytest.mark.parametrize("identifier", ["missing", "entry/movie"])
async def test_browse_rejects_missing_servers_and_nested_items(hass, identifier: str) -> None:
    hass.data[DOMAIN] = {"entry": runtime()}
    message = "cannot be expanded" if "/" in identifier else "not available"
    with pytest.raises(BrowseError, match=message):
        await KinosailMediaSource(hass).async_browse_media(item(hass, identifier))


async def test_browse_translates_library_error(hass) -> None:
    instance = runtime()
    instance.client.library.side_effect = KinosailError("private")
    hass.data[DOMAIN] = {"entry": instance}
    with pytest.raises(BrowseError, match="Could not browse Kinosail") as error:
        await KinosailMediaSource(hass).async_browse_media(item(hass, "entry"))
    assert "private" not in str(error.value)


async def test_search_maps_results_and_query(hass) -> None:
    instance = runtime(library=[{"id": "movie", "kind": "video", "title": "Movie"}])
    hass.data[DOMAIN] = {"entry": instance}
    query = SearchMediaQuery(search_query="movie")
    result = await KinosailMediaSource(hass).async_search_media(item(hass, "entry"), query)
    assert result.result[0].identifier == "entry/movie"
    instance.client.library.assert_awaited_once_with("movie")


async def test_search_translates_library_error(hass) -> None:
    instance = runtime()
    instance.client.library.side_effect = KinosailError("private")
    hass.data[DOMAIN] = {"entry": instance}
    with pytest.raises(BrowseError, match="Could not search Kinosail"):
        await KinosailMediaSource(hass).async_search_media(item(hass, "entry"), SearchMediaQuery(search_query="x"))


@pytest.mark.parametrize("identifier", ["", "entry/movie"])
async def test_search_rejects_missing_or_nested_server_identifier(hass, identifier: str) -> None:
    instance = runtime()
    hass.data[DOMAIN] = {"entry": instance, "XXXX": instance}
    message = "search location is invalid" if identifier else "not available"
    with pytest.raises(BrowseError, match=message):
        await KinosailMediaSource(hass).async_search_media(item(hass, identifier), SearchMediaQuery(search_query="x"))
    instance.client.library.assert_not_awaited()


@pytest.mark.parametrize("identifier", ["item", "entry/", "entry/folder/item", f"entry/{'x' * 129}"])
async def test_resolve_rejects_invalid_item_before_playback(hass, identifier: str) -> None:
    instance = runtime()
    hass.data[DOMAIN] = {"entry": instance}
    with pytest.raises(Unresolvable, match="item is invalid"):
        await KinosailMediaSource(hass).async_resolve_media(item(hass, identifier))
    instance.client.playback.assert_not_awaited()


async def test_resolve_returns_direct_media(hass) -> None:
    instance = runtime(playback=("https://server/media", "video/mp4"))
    hass.data[DOMAIN] = {"entry": instance}
    result = await KinosailMediaSource(hass).async_resolve_media(item(hass, "entry/movie"))
    assert (result.url, result.mime_type) == ("https://server/media", "video/mp4")
    instance.client.playback.assert_awaited_once_with("movie")


async def test_resolve_accepts_maximum_length_item_id(hass) -> None:
    instance = runtime()
    hass.data[DOMAIN] = {"entry": instance}
    result = await KinosailMediaSource(hass).async_resolve_media(item(hass, f"entry/{'x' * 128}"))
    assert result.url == "https://server/media"
    instance.client.playback.assert_awaited_once_with("x" * 128)


@pytest.mark.parametrize("missing", [True, False])
async def test_resolve_translates_missing_server_and_client_error(hass, missing: bool) -> None:
    instance = runtime()
    if not missing:
        instance.client.playback.side_effect = KinosailError("private")
    hass.data[DOMAIN] = {} if missing else {"entry": instance}
    with pytest.raises(Unresolvable, match="Could not resolve Kinosail"):
        await KinosailMediaSource(hass).async_resolve_media(item(hass, "entry/movie"))
