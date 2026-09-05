"""Tests for integration setup and coordinator updates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kinosail import async_setup_entry, async_unload_entry
from custom_components.kinosail.api import KinosailAuthError, KinosailError
from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.coordinator import _LOGGER as COORDINATOR_LOGGER
from custom_components.kinosail.coordinator import KinosailCoordinator


@pytest.mark.parametrize(
    "data",
    [
        {CONF_URL: None, CONF_VERIFY_SSL: True, "token": "token"},
        {CONF_URL: "ftp://server", CONF_VERIFY_SSL: True, "token": "token"},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "token": None},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "token": ""},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "token": "x" * 4097},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: "true", "token": "token"},
    ],
)
async def test_setup_rejects_invalid_stored_data_before_side_effects(hass, data: dict[str, object]) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    session = Mock()
    with patch("custom_components.kinosail.async_get_clientsession", return_value=session):
        with pytest.raises(ConfigEntryError, match="configuration is invalid"):
            await async_setup_entry(hass, entry)
    assert not session.mock_calls
    assert DOMAIN not in hass.data


@pytest.mark.parametrize("unique_id", ["server", None])
async def test_setup_stores_runtime_and_forwards_platforms(hass, unique_id: str | None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        title="Living Room",
        data={CONF_URL: "https://server/", CONF_VERIFY_SSL: False, "token": "token"},
    )
    coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    session = Mock()
    with (
        patch("custom_components.kinosail.async_get_clientsession", return_value=session) as get_session,
        patch("custom_components.kinosail.KinosailCoordinator", return_value=coordinator) as coordinator_type,
    ):
        assert await async_setup_entry(hass, entry)

    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.client.session is session
    assert runtime.client.token == "token"
    assert runtime.client.verify_ssl is False
    assert runtime.coordinator is coordinator
    assert runtime.name == "Living Room"
    assert runtime.server_id == (unique_id or entry.entry_id)
    assert runtime.client.base_url == "https://server"
    get_session.assert_called_once_with(hass)
    coordinator_type.assert_called_once_with(hass, runtime.client)
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(entry, ["media_player"])


async def test_setup_defaults_to_tls_verification(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: "https://server", "token": "token"})
    coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    with patch("custom_components.kinosail.KinosailCoordinator", return_value=coordinator):
        assert await async_setup_entry(hass, entry)
    assert hass.data[DOMAIN][entry.entry_id].client.verify_ssl is True


@pytest.mark.parametrize("token", ["t", "t" * 4096])
async def test_setup_accepts_exact_token_boundaries(hass, token: str) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: "https://server", "token": token})
    coordinator = SimpleNamespace(async_config_entry_first_refresh=AsyncMock())
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    with patch("custom_components.kinosail.KinosailCoordinator", return_value=coordinator):
        assert await async_setup_entry(hass, entry)
    assert hass.data[DOMAIN][entry.entry_id].client.token == token


@pytest.mark.parametrize("unloaded", [True, False])
async def test_unload_only_removes_successfully_unloaded_runtime(hass, unloaded: bool) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    runtime = object()
    hass.data[DOMAIN] = {entry.entry_id: runtime}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=unloaded)
    assert await async_unload_entry(hass, entry) is unloaded
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, ["media_player"])
    assert (entry.entry_id not in hass.data[DOMAIN]) is unloaded


@pytest.mark.parametrize(
    ("error", "expected"),
    [(KinosailAuthError("revoked"), ConfigEntryAuthFailed), (KinosailError("offline"), UpdateFailed)],
)
async def test_coordinator_translates_client_errors(hass, error: Exception, expected: type[Exception]) -> None:
    client = SimpleNamespace(players=AsyncMock(side_effect=error))
    with pytest.raises(expected) as raised:
        await KinosailCoordinator(hass, client)._async_update_data()
    assert raised.value.__cause__ is error
    if expected is UpdateFailed:
        assert str(raised.value) == "offline"


async def test_coordinator_returns_valid_players(hass) -> None:
    players = [{"id": "player"}]
    client = SimpleNamespace(players=AsyncMock(return_value=players))
    coordinator = KinosailCoordinator(hass, client)
    assert coordinator.client is client
    assert coordinator.hass is hass
    assert coordinator.logger is COORDINATOR_LOGGER
    assert coordinator.name == DOMAIN
    assert coordinator.update_interval.total_seconds() == 5
    assert await coordinator._async_update_data() == players
    client.players.assert_awaited_once_with()
