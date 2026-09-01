"""Connect Kinosail to Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import http as http_helper
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import ID_PATTERN, KinosailClient, KinosailDisabledError, KinosailError, normalize_url
from .const import DOMAIN

CONF_CODE = "code"
CLIENT_ID = "home-assistant"
_LOGGER = logging.getLogger(__name__)


class KinosailOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2ImplementationWithPkce):
    """Use Home Assistant's signed popup callback with Kinosail transport settings."""

    def __init__(self, hass: Any, base_url: str, verify_ssl: bool) -> None:
        super().__init__(
            hass,
            base_url,
            CLIENT_ID,
            f"{base_url}/home-assistant/authorize",
            f"{base_url}/api/v1/home-assistant/token",
        )
        self._base_url = base_url
        self._verify_ssl = verify_ssl

    @property
    def redirect_uri(self) -> str:
        """Keep the callback on the Home Assistant instance when the frontend identifies it."""
        request = http_helper.current_request.get()
        if request is not None and (
            frontend_base := request.headers.get(config_entry_oauth2_flow.HEADER_FRONTEND_BASE)
        ):
            return f"{frontend_base}{config_entry_oauth2_flow.AUTH_CALLBACK_PATH}"
        return super().redirect_uri

    async def _token_request(self, data: dict[str, Any]) -> dict[str, Any]:
        client = KinosailClient(
            async_get_clientsession(self.hass), self._base_url, verify_ssl=self._verify_ssl
        )
        return await client.oauth_token({**data, "client_id": self.client_id})


class KinosailConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Configure one local Kinosail Server."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._base_url = ""
        self._verify_ssl = True
        self._name = "Kinosail"
        self._reauth_entry = None

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @staticmethod
    def _schema(default_url: str = "", default_verify_ssl: bool = True) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_URL, default=default_url): str,
                vol.Required(CONF_VERIFY_SSL, default=default_verify_ssl): bool,
                vol.Optional(CONF_CODE, default=""): str,
            }
        )

    async def _probe(self, base_url: str, verify_ssl: bool) -> tuple[str, str]:
        data = await KinosailClient(
            async_get_clientsession(self.hass), base_url, verify_ssl=verify_ssl
        ).probe()
        server_id, name = data.get("serverId"), data.get("name")
        if not all(isinstance(value, str) and value for value in (server_id, name)):
            raise KinosailError("Kinosail discovery response is invalid")
        return server_id, name

    async def _start_oauth(self) -> FlowResult:
        self.flow_impl = KinosailOAuth2Implementation(self.hass, self._base_url, self._verify_ssl)
        return await self.async_step_auth()

    async def _manual_pair(self, code: str) -> FlowResult:
        data = await KinosailClient(
            async_get_clientsession(self.hass), self._base_url, verify_ssl=self._verify_ssl
        ).pair(code, "Home Assistant")
        return await self._finish(data)

    async def _finish(self, data: dict[str, Any]) -> FlowResult:
        server_id = data.get("serverId")
        token = data.get("access_token", data.get("token"))
        name = data.get("name")
        if not all(isinstance(value, str) and value for value in (server_id, token, name)):
            raise KinosailError("Kinosail authorization response is invalid")
        if self._reauth_entry is not None:
            if server_id != self._reauth_entry.unique_id:
                raise KinosailError("Authorization belongs to another Kinosail Server")
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                title=name,
                data={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl, "token": token},
            )
        await self.async_set_unique_id(server_id)
        self._abort_if_unique_id_configured(
            updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl}
        )
        return self.async_create_entry(
            title=name,
            data={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl, "token": token},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._base_url = normalize_url(user_input[CONF_URL])
                self._verify_ssl = user_input[CONF_VERIFY_SSL]
                server_id, self._name = await self._probe(self._base_url, self._verify_ssl)
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl}
                )
                if code := user_input.get(CONF_CODE, "").strip():
                    return await self._manual_pair(code)
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except (KinosailError, ValueError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        """Offer one discovered, enabled Kinosail Server."""
        server_id = discovery_info.properties.get("id")
        if (
            not isinstance(server_id, str)
            or not ID_PATTERN.fullmatch(server_id)
            or discovery_info.port is None
            or not 1 <= discovery_info.port <= 65535
        ):
            return self.async_abort(reason="invalid_discovery")
        verify_ssl = str(discovery_info.properties.get("verify_ssl", "true")).lower()
        if verify_ssl not in {"true", "false"}:
            return self.async_abort(reason="invalid_discovery")
        scheme = "https" if str(discovery_info.properties.get("tls", "false")).lower() == "true" else "http"
        host = f"[{discovery_info.host}]" if ":" in discovery_info.host else discovery_info.host
        discovered_url = discovery_info.properties.get("url")
        try:
            self._base_url = normalize_url(
                discovered_url
                if isinstance(discovered_url, str)
                else f"{scheme}://{host}:{discovery_info.port}"
            )
        except ValueError:
            return self.async_abort(reason="invalid_discovery")
        self._verify_ssl = verify_ssl == "true"
        await self.async_set_unique_id(server_id)
        self._abort_if_unique_id_configured(
            updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl}
        )
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm a discovered Server before opening its approval page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_id, self._name = await self._probe(self._base_url, self._verify_ssl)
                if server_id != self.unique_id:
                    raise KinosailError("Discovered Server identity changed")
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except KinosailError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="confirm", description_placeholders={"url": self._base_url}, errors=errors
        )

    async def async_step_creation(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Store the browser-approved persistent integration token."""
        try:
            return await self._finish(await self.flow_impl.async_resolve_external_data(self.external_data))
        except KinosailDisabledError:
            return self.async_abort(reason="disabled")
        except KinosailError:
            return self.async_abort(reason="oauth_failed")

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start reauthorization after revocation."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Use browser approval or the manual code fallback."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._base_url = normalize_url(user_input[CONF_URL])
                self._verify_ssl = user_input[CONF_VERIFY_SSL]
                server_id, self._name = await self._probe(self._base_url, self._verify_ssl)
                if server_id != self._reauth_entry.unique_id:
                    raise KinosailError("Authorization belongs to another Kinosail Server")
                if code := user_input.get(CONF_CODE, "").strip():
                    return await self._manual_pair(code)
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except (KinosailError, ValueError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._schema(
                self._reauth_entry.data[CONF_URL],
                self._reauth_entry.data.get(CONF_VERIFY_SSL, True),
            ),
            errors=errors,
        )
