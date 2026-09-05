"""Tests for Kinosail flow helpers and OAuth exchange."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import http as http_helper
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kinosail.api import KinosailDisabledError, KinosailError
from custom_components.kinosail.config_flow import KinosailConfigFlow, KinosailOAuth2Implementation
from custom_components.kinosail.const import DOMAIN


def flow(hass) -> KinosailConfigFlow:
    result = KinosailConfigFlow()
    result.hass = hass
    return result


def test_flow_metadata_and_schemas(hass) -> None:
    instance = flow(hass)
    assert instance._base_url == ""
    assert instance._verify_ssl is True
    assert instance._reauth_entry is None
    assert instance.logger.name == "custom_components.kinosail.config_flow"
    assert instance._schema("https://server", False)({}) == {
        CONF_URL: "https://server",
        CONF_VERIFY_SSL: False,
        "code": "",
    }
    assert instance._reconfigure_schema("https://server", True)({}) == {
        CONF_URL: "https://server",
        CONF_VERIFY_SSL: True,
    }
    assert instance._schema()({}) == {CONF_URL: "", CONF_VERIFY_SSL: True, "code": ""}


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"serverId": None, "name": "Server"},
        {"serverId": "../bad", "name": "Server"},
        {"serverId": "server", "name": None},
        {"serverId": "server", "name": ""},
        {"serverId": "server", "name": "x" * 257},
    ],
)
async def test_probe_rejects_invalid_remote_identity(hass, data: dict[str, object]) -> None:
    instance = flow(hass)
    with patch("custom_components.kinosail.config_flow.KinosailClient.probe", AsyncMock(return_value=data)):
        with pytest.raises(KinosailError, match="discovery response"):
            await instance._probe("https://server", True)


async def test_start_oauth_configures_local_implementation(hass) -> None:
    instance = flow(hass)
    instance._base_url = "https://server"
    instance._verify_ssl = False
    with patch.object(instance, "async_step_auth", AsyncMock(return_value={"type": "external"})):
        assert await instance._start_oauth() == {"type": "external"}
    assert isinstance(instance.flow_impl, KinosailOAuth2Implementation)
    assert instance.flow_impl.hass is hass
    assert instance.flow_impl._base_url == "https://server"
    assert instance.flow_impl._verify_ssl is False


def test_oauth_redirect_prefers_frontend_and_falls_back(hass) -> None:
    implementation = KinosailOAuth2Implementation(hass, "https://server", False)
    assert implementation.hass is hass
    assert implementation.domain == "https://server"
    assert implementation.client_id == "home-assistant"
    assert implementation.authorize_url == "https://server/home-assistant/authorize"
    assert implementation.token_url == "https://server/api/v1/home-assistant/token"
    request_token = http_helper.current_request.set(
        SimpleNamespace(headers={config_entry_oauth2_flow.HEADER_FRONTEND_BASE: "https://frontend"})
    )
    try:
        assert implementation.redirect_uri == f"https://frontend{config_entry_oauth2_flow.AUTH_CALLBACK_PATH}"
    finally:
        http_helper.current_request.reset(request_token)
    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_redirect_uri", return_value="https://fallback"
    ):
        assert implementation.redirect_uri == "https://fallback"


async def test_oauth_token_exchange_adds_client_id(hass) -> None:
    implementation = KinosailOAuth2Implementation(hass, "https://server", False)
    oauth_token = AsyncMock(return_value={"access_token": "token"})
    client = Mock(oauth_token=oauth_token)
    session = object()
    with (
        patch("custom_components.kinosail.config_flow.async_get_clientsession", return_value=session) as get_session,
        patch("custom_components.kinosail.config_flow.KinosailClient", return_value=client) as client_type,
    ):
        assert await implementation._token_request({"code": "one-use"}) == {"access_token": "token"}
    get_session.assert_called_once_with(hass)
    client_type.assert_called_once_with(session, "https://server", verify_ssl=False)
    oauth_token.assert_awaited_once_with({"code": "one-use", "client_id": "home-assistant"})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"serverId": None, "name": "Server", "token": "token"},
        {"serverId": "../bad", "name": "Server", "token": "token"},
        {"serverId": "server", "name": "Server", "token": None},
        {"serverId": "server", "name": "Server", "token": ""},
        {"serverId": "server", "name": "Server", "token": "x" * 4097},
        {"serverId": "server", "name": None, "token": "token"},
        {"serverId": "server", "name": "", "token": "token"},
        {"serverId": "server", "name": "x" * 257, "token": "token"},
    ],
)
async def test_finish_rejects_invalid_authorization(hass, data: dict[str, object]) -> None:
    with pytest.raises(KinosailError, match="authorization response"):
        await flow(hass)._finish(data)


async def test_finish_updates_matching_reauth_entry(hass) -> None:
    instance = flow(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server")
    instance._reauth_entry = entry
    instance._base_url = "https://server"
    expected = {"type": "abort"}
    with patch.object(instance, "async_update_reload_and_abort", return_value=expected) as update:
        assert await instance._finish({"serverId": "server", "name": "Server", "access_token": "token"}) is expected
    update.assert_called_once_with(
        entry,
        title="Server",
        data={CONF_URL: "https://server", CONF_VERIFY_SSL: True, "token": "token"},
    )


async def test_finish_rejects_other_server_during_reauth(hass) -> None:
    instance = flow(hass)
    instance._reauth_entry = MockConfigEntry(domain=DOMAIN, unique_id="server")
    with pytest.raises(KinosailError, match="another Kinosail Server"):
        await instance._finish({"serverId": "other", "name": "Other", "token": "token"})


@pytest.mark.parametrize(
    ("error", "reason"),
    [(KinosailDisabledError("off"), "disabled"), (KinosailError("bad"), "oauth_failed")],
)
async def test_creation_translates_authorization_failures(hass, error: Exception, reason: str) -> None:
    instance = flow(hass)
    instance.external_data = {"code": "one-use"}
    instance.flow_impl = SimpleNamespace(async_resolve_external_data=AsyncMock(side_effect=error))
    assert (await instance.async_step_creation({"ignored": True}))["reason"] == reason


async def test_creation_finishes_resolved_authorization(hass) -> None:
    instance = flow(hass)
    data = {"serverId": "server", "name": "Server", "token": "token"}
    instance.external_data = {"code": "one-use"}
    instance.flow_impl = SimpleNamespace(async_resolve_external_data=AsyncMock(return_value=data))
    with patch.object(instance, "_finish", AsyncMock(return_value={"type": "create"})) as finish:
        assert await instance.async_step_creation() == {"type": "create"}
    finish.assert_awaited_once_with(data)
    instance.flow_impl.async_resolve_external_data.assert_awaited_once_with({"code": "one-use"})


async def test_probe_and_manual_pair_delegate_exact_contract(hass) -> None:
    instance = flow(hass)
    instance._base_url = "https://server"
    instance._verify_ssl = False
    session = object()
    client = Mock(
        probe=AsyncMock(return_value={"serverId": "server", "name": "Server"}),
        pair=AsyncMock(return_value={"serverId": "server", "name": "Server", "token": "token"}),
    )
    with (
        patch("custom_components.kinosail.config_flow.async_get_clientsession", return_value=session),
        patch("custom_components.kinosail.config_flow.KinosailClient", return_value=client) as client_type,
        patch.object(instance, "_finish", AsyncMock(return_value={"type": "create"})) as finish,
    ):
        assert await instance._probe("https://server", False) == ("server", "Server")
        assert await instance._manual_pair("12345678") == {"type": "create"}
    assert client_type.call_args_list[0].args == (session, "https://server")
    assert client_type.call_args_list[0].kwargs == {"verify_ssl": False}
    assert client_type.call_args_list[1].args == (session, "https://server")
    assert client_type.call_args_list[1].kwargs == {"verify_ssl": False}
    client.probe.assert_awaited_once_with()
    client.pair.assert_awaited_once_with("12345678", "Home Assistant")
    finish.assert_awaited_once_with({"serverId": "server", "name": "Server", "token": "token"})


async def test_reconfigure_strictly_parses_and_probes_transport(hass) -> None:
    instance = flow(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server", data={CONF_URL: "https://old", CONF_VERIFY_SSL: True})
    user_input = {CONF_URL: "https://server", CONF_VERIFY_SSL: False}
    with (
        patch.object(instance, "_get_reconfigure_entry", return_value=entry),
        patch(
            "custom_components.kinosail.config_flow.transport_input", return_value=("https://server", False)
        ) as parse,
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Server"))) as probe,
        patch.object(instance, "async_update_reload_and_abort", return_value={"type": "abort"}),
    ):
        assert (await instance.async_step_reconfigure(user_input))["type"] == "abort"
    parse.assert_called_once_with(user_input)
    probe.assert_awaited_once_with("https://server", False)


@pytest.mark.parametrize("name", ["S", "S" * 256])
async def test_probe_accepts_exact_name_boundaries(hass, name: str) -> None:
    instance = flow(hass)
    with patch(
        "custom_components.kinosail.config_flow.KinosailClient.probe",
        AsyncMock(return_value={"serverId": "server", "name": name}),
    ):
        assert await instance._probe("https://server", True) == ("server", name)


@pytest.mark.parametrize(("token", "name"), [("t", "S"), ("t" * 4096, "S" * 256)])
async def test_finish_accepts_exact_authorization_boundaries(hass, token: str, name: str) -> None:
    instance = flow(hass)
    instance._base_url = "https://server"
    instance._verify_ssl = False
    expected = {"type": "create"}
    with (
        patch.object(instance, "async_set_unique_id", AsyncMock()) as set_id,
        patch.object(instance, "_abort_if_unique_id_configured", Mock()) as abort_existing,
        patch.object(instance, "async_create_entry", return_value=expected) as create,
    ):
        assert await instance._finish({"serverId": "x" * 128, "name": name, "token": token}) is expected
    set_id.assert_awaited_once_with("x" * 128)
    abort_existing.assert_called_once_with(updates={CONF_URL: "https://server", CONF_VERIFY_SSL: False})
    create.assert_called_once_with(
        title=name, data={CONF_URL: "https://server", CONF_VERIFY_SSL: False, "token": token}
    )
