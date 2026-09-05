"""Tests for the narrow Kinosail HTTP client."""

from __future__ import annotations

import pytest

from custom_components.kinosail import api
from custom_components.kinosail.api import (
    KinosailAuthError,
    KinosailClient,
    KinosailDisabledError,
    KinosailError,
    normalize_url,
)
from tests.helpers import Response, Session


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://server",
        "https://",
        "https://user:pass@server",
        "https://server/path",
        "https://server/?token=x",
        "http://server:",
        "http://server:0",
        "http://server:65536",
        "http://server:abc",
        "http://server:1.5",
        "x" * 2049,
        None,
    ],
)
def test_normalize_url_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(ValueError):
        normalize_url(value)


def test_normalize_url_keeps_only_the_origin() -> None:
    assert normalize_url(" https://media.example:38127/ ") == "https://media.example:38127"


@pytest.mark.asyncio
async def test_pairing_and_direct_playback_contract() -> None:
    session = Session(
        Response(200, {"name": "Kinosail", "serverId": "server"}),
        Response(201, {"name": "Kinosail", "serverId": "server", "token": "ks_secret"}),
        Response(
            200,
            {
                "url": "/home-assistant/media/item?expires=1&signature=signed",
                "mimeType": "video/mp4",
            },
        ),
    )
    client = KinosailClient(session, "https://media.example")
    assert (await client.probe())["serverId"] == "server"
    assert (await client.pair("12345678", "Home Assistant"))["token"] == "ks_secret"
    client.token = "ks_secret"
    assert await client.playback("item") == (
        "https://media.example/home-assistant/media/item?expires=1&signature=signed",
        "video/mp4",
    )
    assert session.calls[0][2]["headers"] == {}
    assert session.calls[2][2]["headers"] == {"Authorization": "Bearer ks_secret"}


@pytest.mark.asyncio
async def test_oauth_token_exchange_uses_form_data_without_authentication() -> None:
    session = Session(Response(200, {"access_token": "ks_secret", "serverId": "server", "name": "Kinosail"}))
    client = KinosailClient(session, "https://media.example")
    form = {
        "grant_type": "authorization_code",
        "client_id": "home-assistant",
        "code": "one-use-code",
        "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
        "code_verifier": "v" * 64,
    }
    assert (await client.oauth_token(form))["access_token"] == "ks_secret"
    assert session.calls == [
        (
            "POST",
            "https://media.example/api/v1/home-assistant/token",
            {"json": None, "data": form, "params": None, "headers": {}, "ssl": True},
        )
    ]


@pytest.mark.asyncio
async def test_disabled_and_revoked_are_distinct() -> None:
    with pytest.raises(KinosailDisabledError):
        await KinosailClient(Session(Response(404, {})), "https://media.example").probe()
    with pytest.raises(KinosailAuthError):
        await KinosailClient(Session(Response(401, {})), "https://media.example", "ks_revoked").players()


@pytest.mark.asyncio
async def test_response_size_is_bounded() -> None:
    response = Response(200, {"value": "x" * api.MAX_RESPONSE_BYTES})
    with pytest.raises(api.KinosailError, match="too large"):
        await KinosailClient(Session(response), "https://media.example").probe()


@pytest.mark.asyncio
async def test_remote_ids_and_cardinality_are_bounded_before_use() -> None:
    client = KinosailClient(Session(), "https://media.example", "ks_secret")
    with pytest.raises(KinosailError, match="item ID"):
        await client.playback("../settings")
    with pytest.raises(KinosailError, match="player ID"):
        await client.command("../settings", "pause")
    players = KinosailClient(
        Session(Response(200, {"players": [{"id": f"player-{index}"} for index in range(api.MAX_PLAYERS + 1)]})),
        "https://media.example",
        "ks_secret",
    )
    with pytest.raises(KinosailError, match="invalid players"):
        await players.players()

    library = KinosailClient(
        Session(Response(200, {"items": [{"id": "../settings"}]})),
        "https://media.example",
        "ks_secret",
    )
    with pytest.raises(KinosailError, match="invalid library"):
        await library.library()


@pytest.mark.parametrize(
    ("command", "values"),
    [
        ("unknown", {}),
        ("play", {"position": 1}),
        ("seek", {}),
        ("seek", {"position": -1}),
        ("seek", {"position": True}),
        ("volume", {"volume": 1.1}),
        ("mute", {"muted": "yes"}),
        ("play_media", {"itemId": 1}),
        ("play_media", {"itemId": "../settings"}),
    ],
)
@pytest.mark.asyncio
async def test_commands_reject_invalid_values_without_a_request(command: str, values: dict) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="command"):
        await KinosailClient(session, "https://media.example", "ks_secret").command("player", command, **values)
    assert session.calls == []


@pytest.mark.parametrize(
    ("command", "values"),
    [
        ("play", {}),
        ("pause", {}),
        ("stop", {}),
        ("seek", {"position": 12.5}),
        ("volume", {"volume": 0.5}),
        ("mute", {"muted": True}),
        ("play_media", {"itemId": "movie_1"}),
    ],
)
@pytest.mark.asyncio
async def test_commands_send_only_validated_values(command: str, values: dict) -> None:
    session = Session(Response(202, {"status": "queued"}))
    await KinosailClient(session, "https://media.example", "ks_secret").command("player", command, **values)
    assert session.calls[0][2]["json"] == {"command": command, **values}


@pytest.mark.asyncio
async def test_library_rejects_oversized_query_without_a_request() -> None:
    session = Session()
    with pytest.raises(KinosailError, match="query"):
        await KinosailClient(session, "https://media.example", "ks_secret").library("x" * 513)
    assert session.calls == []


@pytest.mark.parametrize("code", ["", "1234567", "123456789", "abcdefgh", "１２３４５６７８", None])
@pytest.mark.asyncio
async def test_pairing_rejects_invalid_codes_without_a_request(code: object) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="pairing"):
        await KinosailClient(session, "https://media.example").pair(code, "Home Assistant")
    assert session.calls == []
