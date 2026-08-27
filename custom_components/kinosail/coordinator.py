"""Kinosail player polling."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KinosailAuthError, KinosailClient, KinosailError
from .const import DOMAIN


class KinosailCoordinator(DataUpdateCoordinator[list[dict]]):
    """Keep active Kinosail browser players current."""

    def __init__(self, hass: HomeAssistant, client: KinosailClient) -> None:
        super().__init__(hass, name=DOMAIN, update_interval=timedelta(seconds=5))
        self.client = client

    async def _async_update_data(self) -> list[dict]:
        try:
            return await self.client.players()
        except KinosailAuthError as err:
            raise ConfigEntryAuthFailed from err
        except KinosailError as err:
            raise UpdateFailed(str(err)) from err
