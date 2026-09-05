"""Kinosail player polling."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import JSONObject, KinosailAuthError, KinosailClient, KinosailError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class KinosailCoordinator(DataUpdateCoordinator[list[JSONObject]]):
    """Keep active Kinosail browser players current."""

    def __init__(self, hass: HomeAssistant, client: KinosailClient) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=5))
        self.client = client

    async def _async_update_data(self) -> list[JSONObject]:
        try:
            return await self.client.players()
        except KinosailAuthError as err:
            raise ConfigEntryAuthFailed from err
        except KinosailError as err:
            raise UpdateFailed(str(err)) from err
