"""Tests for Kinosail player actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.kinosail.api import KinosailError
from custom_components.kinosail.media_player import KinosailPlayer


async def test_command_error_is_safe_for_the_home_assistant_ui() -> None:
    """Translate a Kinosail command failure to a user-facing service error."""
    client = SimpleNamespace(command=AsyncMock(side_effect=KinosailError("private detail")))
    coordinator = SimpleNamespace(data=[], async_add_listener=lambda _: None)
    runtime = SimpleNamespace(client=client, coordinator=coordinator, server_id="server", name="Server")
    player = KinosailPlayer(runtime, "player")

    with pytest.raises(HomeAssistantError, match="Could not control the Kinosail player") as error:
        await player.async_media_play()

    assert "private detail" not in str(error.value)
