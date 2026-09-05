"""Home Assistant support for Kinosail."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KinosailClient, normalize_url
from .const import DOMAIN, PLATFORMS, KinosailRuntime
from .coordinator import KinosailCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one paired Kinosail Server."""
    url = entry.data.get("url")
    token = entry.data.get("token")
    verify_ssl = entry.data.get("verify_ssl", True)
    if (
        not isinstance(url, str)
        or not isinstance(token, str)
        or not 1 <= len(token) <= 4096
        or not isinstance(verify_ssl, bool)
    ):
        raise ConfigEntryError("Kinosail configuration is invalid")
    try:
        url = normalize_url(url)
    except ValueError as err:
        raise ConfigEntryError("Kinosail configuration is invalid") from err
    client = KinosailClient(
        async_get_clientsession(hass),
        url,
        token,
        verify_ssl,
    )
    coordinator = KinosailCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = KinosailRuntime(
        client, coordinator, entry.title, entry.unique_id or entry.entry_id
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one Kinosail Server."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
