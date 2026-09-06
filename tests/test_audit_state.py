"""Regression tests for player timing and quality measurement."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_source import Unresolvable
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.kinosail.api import KinosailError
from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.coordinator import KinosailCoordinator
from custom_components.kinosail.media_player import KinosailPlayer
from custom_components.kinosail.media_source import KinosailMediaSource
from scripts.quality_metrics import functions
from tests.test_media_source import runtime


async def test_position_timestamp_tracks_successful_poll_not_property_reads(hass) -> None:
    client = SimpleNamespace(players=AsyncMock(return_value=[{"id": "player", "position": 10}]))
    coordinator = KinosailCoordinator(hass, client)
    assert coordinator.updated_at is None
    instance = SimpleNamespace(coordinator=coordinator, client=client, server_id="server", name="Server")
    player = KinosailPlayer(instance, "player")
    now = datetime(2026, 9, 6, tzinfo=UTC)
    with patch("custom_components.kinosail.coordinator.datetime") as clock:
        clock.now.return_value = now
        coordinator.data = await coordinator._async_update_data()
        assert player.media_position_updated_at == now
        clock.now.assert_called_once_with(UTC)
        clock.now.return_value = now + timedelta(seconds=5)
        assert player.media_position_updated_at == now
        coordinator.data = await coordinator._async_update_data()
        assert player.media_position_updated_at == now + timedelta(seconds=5)
        client.players.side_effect = KinosailError("offline")
        clock.now.return_value = now + timedelta(seconds=10)
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert player.media_position_updated_at == now + timedelta(seconds=5)


async def test_resolving_root_returns_actionable_error_without_playback(hass) -> None:
    instance = runtime()
    hass.data[DOMAIN] = {"entry": instance}
    with pytest.raises(Unresolvable, match="item is invalid"):
        await KinosailMediaSource(hass).async_resolve_media(SimpleNamespace(identifier=None))
    instance.client.playback.assert_not_awaited()


def test_quality_metrics_include_class_methods_and_closures() -> None:
    source = """
def outer():
    def nested():
        return 1
    return nested()
class Client:
    def request(self, value):
        def inner():
            return 2
        if value:
            return inner()
        return 0
"""
    blocks = {block.fullname: block.complexity for block in functions(source)}
    assert blocks == {"outer": 1, "nested": 1, "Client.request": 2, "inner": 1}
