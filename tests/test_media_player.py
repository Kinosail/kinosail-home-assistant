"""Tests for Kinosail player state and setup."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.media_player import MediaPlayerState

from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.media_player import KinosailPlayer, async_setup_entry


def runtime(players: list[dict[str, object]], *, available: bool = True) -> SimpleNamespace:
    """Build the minimum coordinator runtime used by an entity."""
    coordinator = SimpleNamespace(
        data=players,
        updated_at=datetime.now(UTC),
        last_update_success=available,
        async_add_listener=Mock(return_value=Mock()),
        async_request_refresh=AsyncMock(),
    )
    return SimpleNamespace(
        client=SimpleNamespace(command=AsyncMock()),
        coordinator=coordinator,
        server_id="server",
        name="Server",
    )


async def test_setup_adds_each_player_only_once(hass) -> None:
    instance = runtime([{"id": "one"}, {"id": "two"}, {"id": 3}])
    entry = Mock(entry_id="entry")
    add_entities = Mock()
    hass.data[DOMAIN] = {"entry": instance}
    await async_setup_entry(hass, entry, add_entities)
    assert [entity.player_id for entity in add_entities.call_args.args[0]] == ["one", "two"]

    listener = instance.coordinator.async_add_listener.call_args.args[0]
    instance.coordinator.data.append({"id": "three"})
    listener()
    assert [entity.player_id for entity in add_entities.call_args.args[0]] == ["three"]
    listener()
    assert add_entities.call_count == 2
    entry.async_on_unload.assert_called_once()


def test_entity_exposes_valid_state_and_metadata() -> None:
    instance = runtime(
        [
            {
                "id": "player",
                "name": "TV",
                "state": "playing",
                "title": "Movie",
                "position": 12,
                "duration": 90.5,
                "volume": 0.5,
                "muted": True,
            }
        ]
    )
    player = KinosailPlayer(instance, "player")
    assert player.available
    assert player.name == "TV"
    assert player.state is MediaPlayerState.PLAYING
    assert player.media_title == "Movie"
    assert player.media_position == 12.0
    assert player.media_duration == 90.5
    assert player.media_position_updated_at is not None
    assert player.volume_level == 0.5
    assert player.is_volume_muted is True
    assert player.unique_id == "server-player"
    assert dict(player.device_info) == {
        "identifiers": {(DOMAIN, "server")},
        "name": "Server",
        "manufacturer": "Kinosail",
        "model": "Kinosail Server",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("paused", MediaPlayerState.PAUSED),
        ("buffering", MediaPlayerState.BUFFERING),
        ("idle", MediaPlayerState.IDLE),
        ("unknown", None),
        (1, None),
    ],
)
def test_state_mapping(raw: object, expected: MediaPlayerState | None) -> None:
    assert KinosailPlayer(runtime([{"id": "player", "state": raw}]), "player").state is expected


def test_entity_rejects_invalid_remote_property_types() -> None:
    instance = runtime(
        [{"id": "player", "name": 1, "title": 1, "position": True, "duration": True, "volume": True, "muted": 1}]
    )
    player = KinosailPlayer(instance, "player")
    assert player.name is None
    assert player.media_title is None
    assert player.media_position is None
    assert player.media_duration is None
    assert player.volume_level is None
    assert player.is_volume_muted is None


def test_missing_or_stale_player_is_unavailable() -> None:
    instance = runtime([], available=False)
    player = KinosailPlayer(instance, "missing")
    assert player.player is None
    assert not player.available
    assert player.name is None
    assert player.media_position_updated_at is None
