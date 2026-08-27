"""Pair Kinosail with Home Assistant."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KinosailClient, KinosailDisabledError, KinosailError, normalize_url
from .const import DOMAIN

CONF_CODE = "code"


class KinosailConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local Kinosail Server."""

    VERSION = 1

    async def _pair(self, user_input: dict[str, Any]) -> tuple[str, str, str, str]:
        base_url = normalize_url(user_input[CONF_URL])
        client = KinosailClient(
            async_get_clientsession(self.hass),
            base_url,
            verify_ssl=user_input[CONF_VERIFY_SSL],
        )
        await client.probe()
        paired = await client.pair(user_input[CONF_CODE].strip(), "Home Assistant")
        server_id, token, name = paired.get("serverId"), paired.get("token"), paired.get("name")
        if not all(isinstance(value, str) and value for value in (server_id, token, name)):
            raise KinosailError("Kinosail pairing response is invalid")
        return base_url, server_id, token, name

    @staticmethod
    def _schema(default_url: str = "", default_verify_ssl: bool = True) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_URL, default=default_url): str,
                vol.Required(CONF_CODE): vol.All(str, vol.Length(min=8, max=8)),
                vol.Required(CONF_VERIFY_SSL, default=default_verify_ssl): bool,
            }
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, server_id, token, name = await self._pair(user_input)
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except (KinosailError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_URL: base_url, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL]}
                )
                return self.async_create_entry(
                    title=name,
                    data={CONF_URL: base_url, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL], "token": token},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start pairing again after a token is revoked."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Replace one revoked Kinosail token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, server_id, token, name = await self._pair(user_input)
                if server_id != self._reauth_entry.unique_id:
                    raise KinosailError("Pairing code belongs to another Kinosail Server")
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except (KinosailError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    title=name,
                    data={CONF_URL: base_url, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL], "token": token},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._schema(
                self._reauth_entry.data[CONF_URL],
                self._reauth_entry.data.get(CONF_VERIFY_SSL, True),
            ),
            errors=errors,
        )
