"""Tests for the narrow Kinosail HTTP client."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "kinosail_api", Path(__file__).parents[1] / "custom_components/kinosail/api.py"
)
api = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(api)
KinosailAuthError, KinosailClient = api.KinosailAuthError, api.KinosailClient
KinosailDisabledError, KinosailError, normalize_url = api.KinosailDisabledError, api.KinosailError, api.normalize_url


class Response:
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self.body = body
        self.content = self
        self.raw = json.dumps(body).encode()
        self.offset = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            from aiohttp import ClientResponseError, RequestInfo
            from multidict import CIMultiDict, CIMultiDictProxy

            headers = CIMultiDictProxy(CIMultiDict())
            raise ClientResponseError(RequestInfo("GET", None, headers, None), (), status=self.status)

    async def read(self, limit: int) -> bytes:
        chunk = self.raw[self.offset : self.offset + limit]
        self.offset += len(chunk)
        return chunk


class Session:
    def __init__(self, *responses: Response) -> None:
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://server",
        "https://",
        "https://user:pass@server",
        "https://server/path",
        "https://server/?token=x",
        "x" * 2049,
    ],
)
def test_normalize_url_rejects_ambiguous_values(value: str) -> None:
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


@pytest.mark.parametrize("code", ["", "1234567", "123456789", "abcdefgh", "１２３４５６７８"])
@pytest.mark.asyncio
async def test_pairing_rejects_invalid_codes_without_a_request(code: str) -> None:
    session = Session()
    with pytest.raises(KinosailError, match="pairing"):
        await KinosailClient(session, "https://media.example").pair(code, "Home Assistant")
    assert session.calls == []
