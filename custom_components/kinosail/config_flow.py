"""Connect Kinosail to Home Assistant."""

from __future__ import annotations

import logging
from typing import cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import http as http_helper
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import (
    ID_PATTERN,
    URL_SCHEME_HTTP,
    URL_SCHEME_HTTPS,
    JSONObject,
    KinosailClient,
    KinosailDisabledError,
    KinosailError,
    normalize_url,
)
from .const import DOMAIN
from .validation import CONF_CODE, FlowInput, advertised_bool, connection_input, transport_input

CLIENT_ID = "home-assistant"
_LOGGER = logging.getLogger(__name__)


class KinosailOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2ImplementationWithPkce):
    """Use Home Assistant's signed popup callback with Kinosail transport settings."""

    def __init__(self, hass: HomeAssistant, base_url: str, verify_ssl: bool) -> None:
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

    async def _token_request(self, data: FlowInput) -> JSONObject:
        client = KinosailClient(async_get_clientsession(self.hass), self._base_url, verify_ssl=self._verify_ssl)
        return await client.oauth_token({**cast(JSONObject, data), "client_id": self.client_id})


class KinosailConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Configure one local Kinosail Server."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._base_url = ""
        self._verify_ssl = True
        self._reauth_entry: ConfigEntry | None = None

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

    @staticmethod
    def _reconfigure_schema(default_url: str, default_verify_ssl: bool) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_URL, default=default_url): str,
                vol.Required(CONF_VERIFY_SSL, default=default_verify_ssl): bool,
            }
        )

    async def _probe(self, base_url: str, verify_ssl: bool) -> tuple[str, str]:
        data = await KinosailClient(async_get_clientsession(self.hass), base_url, verify_ssl=verify_ssl).probe()
        server_id, name = data.get("serverId"), data.get("name")
        if (
            not isinstance(server_id, str)
            or not ID_PATTERN.fullmatch(server_id)
            or not isinstance(name, str)
            or not 1 <= len(name) <= 256
        ):
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

    async def _finish(self, data: JSONObject) -> FlowResult:
        server_id = data.get("serverId")
        token = data.get("access_token", data.get("token"))
        name = data.get("name")
        if (
            not isinstance(server_id, str)
            or not ID_PATTERN.fullmatch(server_id)
            or not isinstance(token, str)
            or not 1 <= len(token) <= 4096
            or not isinstance(name, str)
            or not 1 <= len(name) <= 256
        ):
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
        self._abort_if_unique_id_configured(updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl})
        return self.async_create_entry(
            title=name,
            data={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl, "token": token},
        )

    async def async_step_user(self, user_input: FlowInput | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._base_url, self._verify_ssl, code = connection_input(user_input)
                server_id, _ = await self._probe(self._base_url, self._verify_ssl)
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl}
                )
                if code:
                    return await self._manual_pair(code)
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except KinosailError, ValueError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        """Offer one discovered, enabled Kinosail Server."""
        try:
            server_id = discovery_info.properties.get("id")
            if (
                not isinstance(server_id, str)
                or not ID_PATTERN.fullmatch(server_id)
                or discovery_info.port is None
                or discovery_info.port < 1
            ):
                raise ValueError("invalid discovery")
            verify_ssl = advertised_bool(discovery_info.properties.get("verify_ssl"), True)
            tls = advertised_bool(discovery_info.properties.get("tls"), False)
            discovered_url = discovery_info.properties.get("url")
            if discovered_url is not None and not isinstance(discovered_url, str):
                raise ValueError("invalid discovery")
            host = f"[{discovery_info.host}]" if ":" in discovery_info.host else discovery_info.host
            scheme = URL_SCHEME_HTTPS if tls else URL_SCHEME_HTTP
            self._base_url = normalize_url(
                discovered_url if discovered_url is not None else f"{scheme}://{host}:{discovery_info.port}"
            )
        except ValueError:
            return self.async_abort(reason="invalid_discovery")
        self._verify_ssl = verify_ssl
        await self.async_set_unique_id(server_id)
        self._abort_if_unique_id_configured(updates={CONF_URL: self._base_url, CONF_VERIFY_SSL: self._verify_ssl})
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: FlowInput | None = None) -> FlowResult:
        """Confirm a discovered Server before opening its approval page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server_id, _ = await self._probe(self._base_url, self._verify_ssl)
                if server_id != self.unique_id:
                    raise KinosailError("Discovered Server identity changed")
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except KinosailError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="confirm", description_placeholders={"url": self._base_url}, errors=errors)

    async def async_step_creation(self, user_input: FlowInput | None = None) -> FlowResult:
        """Store the browser-approved persistent integration token."""
        del user_input
        try:
            return await self._finish(await self.flow_impl.async_resolve_external_data(self.external_data))
        except KinosailDisabledError:
            return self.async_abort(reason="disabled")
        except KinosailError:
            return self.async_abort(reason="oauth_failed")

    async def async_step_reauth(self, entry_data: FlowInput) -> FlowResult:
        """Start reauthorization after revocation."""
        del entry_data
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_unsuccessful")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: FlowInput | None = None) -> FlowResult:
        """Use browser approval or the manual code fallback."""
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_unsuccessful")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._base_url, self._verify_ssl, code = connection_input(user_input)
                server_id, _ = await self._probe(self._base_url, self._verify_ssl)
                if server_id != entry.unique_id:
                    raise KinosailError("Authorization belongs to another Kinosail Server")
                if code:
                    return await self._manual_pair(code)
                return await self._start_oauth()
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except KinosailError, ValueError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._schema(
                entry.data[CONF_URL],
                entry.data.get(CONF_VERIFY_SSL, True),
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: FlowInput | None = None) -> FlowResult:
        """Change the Server address without replacing its grant."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url, verify_ssl = transport_input(user_input)
                server_id, name = await self._probe(base_url, verify_ssl)
                if server_id != entry.unique_id:
                    raise KinosailError("Connection belongs to another Kinosail Server")
                return self.async_update_reload_and_abort(
                    entry,
                    title=name,
                    data_updates={CONF_URL: base_url, CONF_VERIFY_SSL: verify_ssl},
                )
            except KinosailDisabledError:
                errors["base"] = "disabled"
            except KinosailError, ValueError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._reconfigure_schema(entry.data[CONF_URL], entry.data.get(CONF_VERIFY_SSL, True)),
            errors=errors,
        )
