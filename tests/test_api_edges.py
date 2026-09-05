"""Edge and failure-path tests for the Kinosail HTTP client."""

import pytest
from aiohttp import ClientConnectionError

from custom_components.kinosail import api
from custom_components.kinosail.api import KinosailAuthError, KinosailClient, KinosailError
from tests.helpers import Response, Session


@pytest.mark.parametrize(
    "response",
    [
        ClientConnectionError("offline"),
        Response(500, {}),
        Response(200, raw=b"{"),
        Response(200, raw=b"\xff"),
    ],
)
async def test_request_translates_transport_and_decode_failures(response: Response | Exception) -> None:
    with pytest.raises(KinosailError, match="Could not connect"):
        await KinosailClient(Session(response), "https://media.example").probe()


async def test_request_rejects_non_object_json_and_handles_all_auth_statuses() -> None:
    with pytest.raises(KinosailError, match="invalid response"):
        await KinosailClient(Session(Response(200, [])), "https://media.example").probe()
    with pytest.raises(KinosailAuthError):
        await KinosailClient(Session(Response(403, {})), "https://media.example").probe()
    with pytest.raises(KinosailError, match="Could not connect"):
        await KinosailClient(Session(Response(404, {})), "https://media.example").request("GET", "/other")


@pytest.mark.parametrize("name", [None, "", " ", "x" * 81])
async def test_pairing_rejects_invalid_names_without_a_request(name: object) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="pairing"):
        await KinosailClient(session, "https://media.example").pair(" 12345678 ", name)
    assert session.calls == []


@pytest.mark.parametrize(
    "players",
    [
        {},
        ["player"],
        [{"id": 1}],
        [{"id": "../player"}],
    ],
)
async def test_players_reject_malformed_remote_values(players: object) -> None:
    client = KinosailClient(Session(Response(200, {"players": players})), "https://media.example", "token")
    with pytest.raises(KinosailError, match="invalid players"):
        await client.players()


async def test_players_accept_missing_empty_and_valid_lists() -> None:
    client = KinosailClient(
        Session(Response(200, {}), Response(200, {"players": [{"id": "web_1", "name": "TV"}]})),
        "https://media.example",
        "token",
    )
    assert await client.players() == []
    assert await client.players() == [{"id": "web_1", "name": "TV"}]


@pytest.mark.parametrize("query", [None, 1, "x" * (api.MAX_LIBRARY_QUERY + 1)])
async def test_library_rejects_invalid_queries_without_a_request(query: object) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="query"):
        await KinosailClient(session, "https://media.example", "token").library(query)
    assert session.calls == []


@pytest.mark.parametrize(
    "items",
    [
        {},
        ["item"],
        [{"id": 1}],
        [{"id": "../item"}],
        [{"id": str(index)} for index in range(api.MAX_LIBRARY_ITEMS + 1)],
    ],
)
async def test_library_rejects_malformed_remote_values(items: object) -> None:
    client = KinosailClient(Session(Response(200, {"items": items})), "https://media.example", "token")
    with pytest.raises(KinosailError, match="invalid library"):
        await client.library()


async def test_library_sends_bounded_queries_and_accepts_valid_items() -> None:
    session = Session(Response(200, {}), Response(200, {"items": [{"id": "movie_1", "title": "Movie"}]}))
    client = KinosailClient(session, "https://media.example", "token")
    assert await client.library() == []
    assert await client.library("movie") == [{"id": "movie_1", "title": "Movie"}]
    assert session.calls[0][2]["params"] == {"limit": 200}
    assert session.calls[1][2]["params"] == {"limit": 200, "q": "movie"}


@pytest.mark.parametrize("item_id", [None, 1, "../item"])
async def test_playback_rejects_invalid_item_ids_without_a_request(item_id: object) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="item ID"):
        await KinosailClient(session, "https://media.example", "token").playback(item_id)
    assert session.calls == []


@pytest.mark.parametrize("url", [None, 1, "https://attacker.example/media"])
async def test_playback_rejects_nonlocal_remote_urls(url: object) -> None:
    client = KinosailClient(Session(Response(200, {"url": url})), "https://media.example", "token")
    with pytest.raises(KinosailError, match="playback URL"):
        await client.playback("movie_1")


@pytest.mark.parametrize("mime_type", [None, "", 1])
async def test_playback_defaults_invalid_mime_types(mime_type: object) -> None:
    client = KinosailClient(
        Session(Response(200, {"url": "/home-assistant/media/movie_1", "mimeType": mime_type})),
        "https://media.example",
        "token",
    )
    assert await client.playback("movie_1") == (
        "https://media.example/home-assistant/media/movie_1",
        "application/octet-stream",
    )
