"""Exact boundary and delegation contracts for the Kinosail client."""

from unittest.mock import AsyncMock

import pytest

from custom_components.kinosail import api
from custom_components.kinosail.api import KinosailClient, KinosailError, normalize_url
from tests.helpers import Response, Session


def test_url_boundaries_and_independent_credentials() -> None:
    longest = "http://" + "a" * (2048 - len("http://"))
    assert len(longest) == 2048
    assert normalize_url(longest) == longest
    assert normalize_url("http://server:1") == "http://server:1"
    assert normalize_url("http://server:65535") == "http://server:65535"
    with pytest.raises(ValueError):
        normalize_url("http://" + "a" * 2042)
    for value in ("https://user@server", "https://:password@server", "https://server/#fragment"):
        with pytest.raises(ValueError):
            normalize_url(value)


async def test_request_allows_exact_size_and_uses_bounded_reads() -> None:
    prefix, suffix = b'{"value":"', b'"}'
    response = Response(200, raw=prefix + b"x" * (api.MAX_RESPONSE_BYTES - len(prefix) - len(suffix)) + suffix)
    result = await KinosailClient(Session(response), "https://server").probe()
    assert len(result["value"]) == api.MAX_RESPONSE_BYTES - len(prefix) - len(suffix)
    assert response.read_limits[0] == 65536
    assert response.read_limits[-1] == 1
    assert all(0 < limit <= 65536 for limit in response.read_limits)


async def test_unauthenticated_request_ignores_existing_token() -> None:
    session = Session(Response(200, {}))
    assert KinosailClient(session, "https://server").token == ""
    await KinosailClient(session, "https://server", "token").probe()
    assert session.calls[0][2]["headers"] == {}


async def test_request_rejects_relative_path_before_network() -> None:
    session = Session()
    with pytest.raises(KinosailError, match="request path"):
        await KinosailClient(session, "https://server").request("GET", "relative")
    assert session.calls == []


async def test_probe_delegates_exact_contract() -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"serverId": "server"})
    assert await client.probe() == {"serverId": "server"}
    client.request.assert_awaited_once_with("GET", "/api/v1/home-assistant", authenticated=False)


async def test_pair_trims_values_and_delegates_exact_contract() -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"token": "token"})
    assert await client.pair(" 12345678 ", " Server ") == {"token": "token"}
    client.request.assert_awaited_once_with(
        "POST",
        "/api/v1/home-assistant/pair",
        json={"code": "12345678", "name": "Server"},
        authenticated=False,
    )
    client.request.reset_mock()
    assert await client.pair("12345678", "x" * 80) == {"token": "token"}
    client.request.assert_awaited_once()


async def test_oauth_delegates_exact_contract() -> None:
    data = {"code": "one-use"}
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"token": "token"})
    assert await client.oauth_token(data) == {"token": "token"}
    client.request.assert_awaited_once_with("POST", "/api/v1/home-assistant/token", data=data, authenticated=False)


async def test_player_cardinality_and_id_boundaries() -> None:
    players = [{"id": str(index)} for index in range(api.MAX_PLAYERS)]
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"players": players})
    assert await client.players() == players
    client.request.assert_awaited_once_with("GET", "/api/v1/home-assistant/players")
    client.request.return_value = {"players": [{"id": "x" * 128}]}
    assert await client.players() == [{"id": "x" * 128}]
    client.request.return_value = {"players": [{"id": "x" * 129}]}
    with pytest.raises(KinosailError):
        await client.players()


async def test_library_query_cardinality_and_id_boundaries() -> None:
    items = [{"id": str(index)} for index in range(api.MAX_LIBRARY_ITEMS)]
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"items": items})
    assert await client.library("x" * api.MAX_LIBRARY_QUERY) == items
    client.request.assert_awaited_once_with(
        "GET", "/api/v1/home-assistant/library", params={"limit": 200, "q": "x" * api.MAX_LIBRARY_QUERY}
    )
    client.request.return_value = {"items": [{"id": "x" * 128}]}
    assert await client.library() == [{"id": "x" * 128}]
    client.request.return_value = {"items": [{"id": "x" * 129}]}
    with pytest.raises(KinosailError):
        await client.library()


@pytest.mark.parametrize(
    ("command", "values"),
    [
        ("seek", {"position": 0}),
        ("seek", {"position": 1e9}),
        ("volume", {"volume": 0}),
        ("volume", {"volume": 1}),
        ("play_media", {"itemId": "x" * 128}),
    ],
)
async def test_command_boundaries_delegate_exact_contract(command: str, values: dict[str, object]) -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={})
    await client.command("x" * 128, command, **values)
    client.request.assert_awaited_once_with(
        "POST", f"/api/v1/home-assistant/players/{'x' * 128}/commands", json={"command": command, **values}
    )


@pytest.mark.parametrize(
    ("command", "values"),
    [("seek", {"position": 1e9 + 1}), ("volume", {"volume": -0.1}), ("play_media", {"itemId": "x" * 129})],
)
async def test_command_rejects_values_just_outside_boundaries(command: str, values: dict[str, object]) -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock()
    with pytest.raises(KinosailError):
        await client.command("player", command, **values)
    client.request.assert_not_awaited()


async def test_unknown_command_rejects_otherwise_valid_play_media_values() -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock()
    with pytest.raises(KinosailError):
        await client.command("player", "unknown", itemId="movie")
    client.request.assert_not_awaited()


async def test_playback_delegates_exact_contract() -> None:
    client = KinosailClient(Session(), "https://server")
    client.request = AsyncMock(return_value={"url": "/home-assistant/media/item", "mimeType": "video/mp4"})
    assert await client.playback("item") == ("https://server/home-assistant/media/item", "video/mp4")
    client.request.assert_awaited_once_with("POST", "/api/v1/home-assistant/playback/item", json={})
