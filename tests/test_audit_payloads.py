"""Reject malformed remote state before Home Assistant entities consume it."""

import pytest

from custom_components.kinosail.api import KinosailClient, KinosailError
from tests.helpers import Response, Session


@pytest.mark.parametrize("raw", [b'{"token":"first","token":"second"}', b'{"players":[{"id":"a","id":"b"}]}'])
async def test_duplicate_json_keys_are_rejected(raw) -> None:
    with pytest.raises(KinosailError, match="Could not connect"):
        await KinosailClient(Session(Response(200, raw=raw)), "https://server").probe()


@pytest.mark.parametrize("key,maximum", [("position", 1e9), ("duration", 1e9), ("volume", 1)])
@pytest.mark.parametrize("value", [None, True, "0.5", -1, float("nan"), float("inf"), float("-inf"), 10**310])
async def test_invalid_player_numbers_never_reach_entities(key, maximum, value) -> None:
    client = KinosailClient(Session(Response(200, {"players": [{"id": "player", key: value}]})), "https://server")
    with pytest.raises(KinosailError, match="invalid players"):
        await client.players()


@pytest.mark.parametrize("key,maximum", [("position", 1e9), ("duration", 1e9), ("volume", 1)])
async def test_player_numeric_boundaries(key, maximum) -> None:
    for value in (0, maximum):
        players = [{"id": "player", key: value}]
        client = KinosailClient(Session(Response(200, {"players": players})), "https://server")
        assert await client.players() == players
    client = KinosailClient(Session(Response(200, {"players": [{"id": "player", key: maximum + 1}]})), "https://server")
    with pytest.raises(KinosailError, match="invalid players"):
        await client.players()


async def test_duplicate_players_cannot_create_duplicate_entities() -> None:
    client = KinosailClient(Session(Response(200, {"players": [{"id": "player"}, {"id": "player"}]})), "https://server")
    with pytest.raises(KinosailError, match="invalid players"):
        await client.players()


@pytest.mark.parametrize(
    "token", [" ", "token\r\nInjected: true", "token with spaces", "tökén", "bad:token", "=", "a=b"]
)
async def test_invalid_tokens_are_never_stored_or_used(hass, token) -> None:
    from unittest.mock import Mock, patch

    from homeassistant.exceptions import ConfigEntryError
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.kinosail import async_setup_entry
    from custom_components.kinosail.const import DOMAIN
    from tests.test_config_flow_steps import flow

    instance = flow(hass)
    with patch.object(instance, "async_create_entry", Mock()) as create:
        with pytest.raises(KinosailError, match="authorization response"):
            await instance._finish({"serverId": "server", "name": "Server", "token": token})
    create.assert_not_called()
    with patch("custom_components.kinosail.async_get_clientsession") as session:
        with pytest.raises(ConfigEntryError):
            await async_setup_entry(
                hass, MockConfigEntry(domain=DOMAIN, data={"url": "https://server", "token": token})
            )
    session.assert_not_called()
    assert DOMAIN not in hass.data


def test_bearer_token_accepts_standard_alphabet_and_padding() -> None:
    from custom_components.kinosail.api import valid_token

    assert valid_token("Ab09-._~+/==")
