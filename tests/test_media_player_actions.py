"""Tests for Kinosail player actions."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.kinosail.api import KinosailError
from custom_components.kinosail.const import DOMAIN
from custom_components.kinosail.media_player import KinosailPlayer
from tests.test_media_player import runtime


async def test_command_refreshes_state() -> None:
    instance = runtime([])
    player = KinosailPlayer(instance, "player")
    await player._command("seek", position=10)
    instance.client.command.assert_awaited_once_with("player", "seek", position=10)
    instance.coordinator.async_request_refresh.assert_awaited_once()


async def test_command_error_is_safe_for_the_home_assistant_ui() -> None:
    instance = runtime([])
    instance.client.command.side_effect = KinosailError("private detail")
    player = KinosailPlayer(instance, "player")
    with pytest.raises(HomeAssistantError, match="Could not control the Kinosail player") as error:
        await player.async_media_play()
    assert "private detail" not in str(error.value)
    instance.coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "args", "command", "values"),
    [
        ("async_media_play", (), "play", {}),
        ("async_media_pause", (), "pause", {}),
        ("async_media_stop", (), "stop", {}),
        ("async_media_seek", (12.5,), "seek", {"position": 12.5}),
        ("async_set_volume_level", (0.5,), "volume", {"volume": 0.5}),
        ("async_mute_volume", (True,), "mute", {"muted": True}),
    ],
)
async def test_action_wrappers(method: str, args: tuple[object, ...], command: str, values: dict[str, object]) -> None:
    player = KinosailPlayer(runtime([]), "player")
    player._command = AsyncMock()
    await getattr(player, method)(*args)
    player._command.assert_awaited_once_with(command, **values)


@pytest.mark.parametrize(
    "media_id",
    [
        "https://example.com/movie",
        f"media-source://{DOMAIN}",
        f"media-source://{DOMAIN}/missing/item",
        f"media-source://{DOMAIN}/entry",
        f"media-source://{DOMAIN}/entry/",
        f"media-source://{DOMAIN}/entry/bad.id",
        f"media-source://{DOMAIN}/entry/folder/item",
    ],
)
async def test_play_media_rejects_foreign_or_malformed_ids_without_a_command(hass, media_id: str) -> None:
    instance = runtime([])
    player = KinosailPlayer(instance, "player")
    player.hass = hass
    hass.data[DOMAIN] = {"entry": instance}
    player._command = AsyncMock()
    expected = (
        "Choose Library Content from the Kinosail media browser"
        if not media_id.startswith(f"media-source://{DOMAIN}/")
        else "Kinosail media item is invalid"
    )
    with pytest.raises(HomeAssistantError, match=f"^{expected}$"):
        await player.async_play_media("video", media_id)
    player._command.assert_not_awaited()


async def test_play_media_rejects_nested_item_even_if_prefix_matches_an_entry(hass) -> None:
    instance = runtime([])
    player = KinosailPlayer(instance, "player")
    player.hass = hass
    hass.data[DOMAIN] = {"entry": instance, "entry/folder": instance}
    player._command = AsyncMock()
    with pytest.raises(HomeAssistantError, match="^Kinosail media item is invalid$"):
        await player.async_play_media("video", f"media-source://{DOMAIN}/entry/folder/item")
    player._command.assert_not_awaited()


async def test_play_media_sends_validated_local_item(hass) -> None:
    instance = runtime([])
    player = KinosailPlayer(instance, "player")
    player.hass = hass
    hass.data[DOMAIN] = {"entry": instance}
    player._command = AsyncMock()
    await player.async_play_media("video", f"media-source://{DOMAIN}/entry/movie", ignored=True)
    player._command.assert_awaited_once_with("play_media", itemId="movie")


@pytest.mark.parametrize("media_id", [None, "media-source://kinosail/entry/movie"])
async def test_browse_media_uses_requested_or_root_id(hass, media_id: str | None) -> None:
    instance = runtime([])
    player = KinosailPlayer(instance, "player")
    player.hass = hass
    hass.data[DOMAIN] = {"entry": instance}
    expected = object()
    with patch(
        "custom_components.kinosail.media_player.media_source.async_browse_media", AsyncMock(return_value=expected)
    ) as browse:
        assert await player.async_browse_media("video", media_id) is expected
    browse.assert_awaited_once_with(hass, media_id or f"media-source://{DOMAIN}/entry")
