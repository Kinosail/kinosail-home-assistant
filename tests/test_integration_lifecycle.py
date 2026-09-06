"""Exercise real Home Assistant flows, entities and services with only HTTP mocked."""

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.kinosail.const import DOMAIN


async def test_pair_setup_control_and_unload(hass) -> None:
    player = {"id": "browser", "name": "TV", "state": "playing", "position": 12, "volume": 0.5}

    async def response(method, path, **kwargs):
        if path.endswith("/pair"):
            return {"serverId": "server", "name": "Server", "token": "paired-token"}
        if path.endswith("/players"):
            return {"players": [player]}
        if path.endswith("/commands"):
            player["state"] = "paused"
            return {"status": "queued"}
        return {"serverId": "server", "name": "Server"}

    with patch("custom_components.kinosail.api.KinosailClient.request", AsyncMock(side_effect=response)) as request:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": "12345678"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        entry = result["result"]
        assert entry.data["token"] == "paired-token"
        entity_id = er.async_get(hass).async_get_entity_id("media_player", DOMAIN, "server-browser")
        state = hass.states.get(entity_id)
        assert state.state == "playing"
        assert state.attributes["media_position"] == 12
        assert state.attributes["volume_level"] == 0.5
        await hass.services.async_call("media_player", "media_pause", {"entity_id": entity_id}, blocking=True)
        assert hass.states.get(entity_id).state == "paused"
        request.assert_any_await("POST", "/api/v1/home-assistant/players/browser/commands", json={"command": "pause"})
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.entry_id not in hass.data[DOMAIN]
        assert hass.states.get(entity_id).state == "unavailable"
        assert hass.states.get(entity_id).attributes["restored"] is True
