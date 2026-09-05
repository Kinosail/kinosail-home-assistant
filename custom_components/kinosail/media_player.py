"""Active Kinosail browser players."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ID_PATTERN, JSONObject, JSONValue, KinosailError
from .const import DOMAIN, KinosailRuntime

FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Add each active Kinosail web player once."""
    runtime: KinosailRuntime = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def add_players() -> None:
        players = [player for player in runtime.coordinator.data or [] if isinstance(player.get("id"), str)]
        new = [player for player in players if player["id"] not in known]
        if new:
            known.update(player["id"] for player in new)
            async_add_entities([KinosailPlayer(runtime, player["id"]) for player in new])

    add_players()
    entry.async_on_unload(runtime.coordinator.async_add_listener(add_players))


class KinosailPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Control one active Kinosail browser player."""

    _attr_supported_features = FEATURES
    _attr_has_entity_name = True

    def __init__(self, runtime: KinosailRuntime, player_id: str) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self.player_id = player_id
        self._attr_unique_id = f"{runtime.server_id}-{player_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, runtime.server_id)},
            "name": runtime.name,
            "manufacturer": "Kinosail",
            "model": "Kinosail Server",
        }

    @property
    def player(self) -> JSONObject | None:
        return next((value for value in self.coordinator.data or [] if value.get("id") == self.player_id), None)

    def _value(self, key: str) -> JSONValue:
        player = self.player
        return player.get(key) if player else None

    @property
    def available(self) -> bool:
        return super().available and self.player is not None

    @property
    def name(self) -> str | None:
        value = self._value("name")
        return value if isinstance(value, str) else None

    @property
    def state(self) -> MediaPlayerState | None:
        value = self._value("state")
        states = {
            "playing": MediaPlayerState.PLAYING,
            "paused": MediaPlayerState.PAUSED,
            "buffering": MediaPlayerState.BUFFERING,
            "idle": MediaPlayerState.IDLE,
        }
        return states.get(value) if isinstance(value, str) else None

    @property
    def media_title(self) -> str | None:
        value = self._value("title")
        return value if isinstance(value, str) else None

    @property
    def media_position(self) -> float | None:
        value = self._value("position")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def media_duration(self) -> float | None:
        value = self._value("duration")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        return datetime.now(UTC) if self.player else None

    @property
    def volume_level(self) -> float | None:
        value = self._value("volume")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def is_volume_muted(self) -> bool | None:
        value = self._value("muted")
        return value if isinstance(value, bool) else None

    async def _command(self, command: str, **values: JSONValue) -> None:
        try:
            await self.runtime.client.command(self.player_id, command, **values)
        except KinosailError as err:
            raise HomeAssistantError("Could not control the Kinosail player") from err
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._command("play")

    async def async_media_pause(self) -> None:
        await self._command("pause")

    async def async_media_stop(self) -> None:
        await self._command("stop")

    async def async_media_seek(self, position: float) -> None:
        await self._command("seek", position=position)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._command("volume", volume=volume)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._command("mute", muted=mute)

    async def async_play_media(self, media_type: MediaType | str, media_id: str, **kwargs: object) -> None:
        del media_type, kwargs
        prefix = f"media-source://{DOMAIN}/"
        if not media_source.is_media_source_id(media_id) or not media_id.startswith(prefix):
            raise HomeAssistantError("Choose Library Content from the Kinosail media browser")
        parts = media_id[len(prefix) :].split("/")
        if (
            len(parts) != 2
            or (entry_id := parts[0]) not in self.hass.data[DOMAIN]
            or self.hass.data[DOMAIN][entry_id] is not self.runtime
            or not ID_PATTERN.fullmatch(item_id := parts[1])
        ):
            raise HomeAssistantError("Kinosail media item is invalid")
        await self._command("play_media", itemId=item_id)

    async def async_browse_media(
        self, media_content_type: MediaType | str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        del media_content_type
        entry_id = next(key for key, value in self.hass.data[DOMAIN].items() if value is self.runtime)
        return await media_source.async_browse_media(
            self.hass,
            media_content_id or f"media-source://{DOMAIN}/{entry_id}",
        )
