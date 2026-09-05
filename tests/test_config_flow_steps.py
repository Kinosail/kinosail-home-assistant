"""Tests for Kinosail discovery and recovery flow steps."""

from ipaddress import ip_address
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kinosail.api import KinosailDisabledError, KinosailError
from custom_components.kinosail.config_flow import KinosailConfigFlow
from custom_components.kinosail.const import DOMAIN


def flow(hass) -> KinosailConfigFlow:
    result = KinosailConfigFlow()
    result.hass = hass
    result.context = {}
    return result


def discovery(*, address: str = "192.0.2.1", port: int | None = 38127, **properties: object) -> ZeroconfServiceInfo:
    ip = ip_address(address)
    return ZeroconfServiceInfo(ip, [ip], port, "server.local.", "_kinosail._tcp.local.", "Kinosail", properties)


@pytest.mark.parametrize(
    "user_input",
    [
        {},
        {CONF_URL: "ftp://server", CONF_VERIFY_SSL: True},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": "bad"},
    ],
)
async def test_user_rejects_invalid_input_before_probe(hass, user_input: dict[str, object]) -> None:
    instance = flow(hass)
    with patch.object(instance, "_probe", AsyncMock()) as probe:
        result = await instance.async_step_user(user_input)
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["step_id"] == "user"
    assert result["data_schema"] is not None
    probe.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "message"),
    [(KinosailDisabledError("off"), "disabled"), (KinosailError("offline"), "cannot_connect")],
)
async def test_user_translates_probe_errors(hass, error: Exception, message: str) -> None:
    instance = flow(hass)
    with patch.object(instance, "_probe", AsyncMock(side_effect=error)):
        result = await instance.async_step_user({CONF_URL: "https://server", CONF_VERIFY_SSL: True})
    assert result["errors"] == {"base": message}
    assert result["step_id"] == "user"


async def test_user_without_pairing_code_starts_oauth(hass) -> None:
    instance = flow(hass)
    expected = {"type": "external"}
    with (
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Server"))) as probe,
        patch.object(instance, "async_set_unique_id", AsyncMock()) as set_id,
        patch.object(instance, "_abort_if_unique_id_configured", Mock()) as abort_existing,
        patch.object(instance, "_start_oauth", AsyncMock(return_value=expected)),
    ):
        assert await instance.async_step_user({CONF_URL: "https://server", CONF_VERIFY_SSL: True}) is expected
    probe.assert_awaited_once_with("https://server", True)
    set_id.assert_awaited_once_with("server")
    abort_existing.assert_called_once_with(updates={CONF_URL: "https://server", CONF_VERIFY_SSL: True})


async def test_user_with_pairing_code_passes_exact_code(hass) -> None:
    instance = flow(hass)
    expected = {"type": "create"}
    with (
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Server"))),
        patch.object(instance, "async_set_unique_id", AsyncMock()),
        patch.object(instance, "_abort_if_unique_id_configured", Mock()),
        patch.object(instance, "_manual_pair", AsyncMock(return_value=expected)) as pair,
    ):
        assert (
            await instance.async_step_user({CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": "12345678"})
            is expected
        )
    pair.assert_awaited_once_with("12345678")


@pytest.mark.parametrize(
    "info",
    [
        discovery(id=None),
        discovery(id="../bad"),
        discovery(id="server", port=None),
        discovery(id="server", port=0),
        discovery(id="server", port=65536),
        discovery(id="server", verify_ssl="yes"),
        discovery(id="server", tls="yes"),
        discovery(id="server", url=1),
        discovery(id="server", url="ftp://server"),
    ],
)
async def test_zeroconf_rejects_invalid_advertisements(hass, info: ZeroconfServiceInfo) -> None:
    result = await flow(hass).async_step_zeroconf(info)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery"


@pytest.mark.parametrize(
    ("info", "url", "verify_ssl"),
    [
        (discovery(id="server"), "http://192.0.2.1:38127", True),
        (discovery(id="server", port=1), "http://192.0.2.1:1", True),
        (discovery(id="server", port=65535), "http://192.0.2.1:65535", True),
        (discovery(address="2001:db8::1", id="server", tls="true"), "https://[2001:db8::1]:38127", True),
        (discovery(id="server", url="https://media.example/", verify_ssl="false"), "https://media.example", False),
    ],
)
async def test_zeroconf_normalizes_valid_advertisements(
    hass, info: ZeroconfServiceInfo, url: str, verify_ssl: bool
) -> None:
    instance = flow(hass)
    expected = {"type": "confirm"}
    with (
        patch.object(instance, "async_set_unique_id", AsyncMock()) as set_id,
        patch.object(instance, "_abort_if_unique_id_configured", Mock()) as abort_existing,
        patch.object(instance, "async_step_confirm", AsyncMock(return_value=expected)),
    ):
        assert await instance.async_step_zeroconf(info) is expected
    assert (instance._base_url, instance._verify_ssl) == (url, verify_ssl)
    set_id.assert_awaited_once_with("server")
    abort_existing.assert_called_once_with(updates={CONF_URL: url, CONF_VERIFY_SSL: verify_ssl})


async def test_zeroconf_uses_explicit_boolean_defaults(hass) -> None:
    instance = flow(hass)
    with (
        patch("custom_components.kinosail.config_flow.advertised_bool", side_effect=[True, False]) as parse_bool,
        patch.object(instance, "async_set_unique_id", AsyncMock()),
        patch.object(instance, "_abort_if_unique_id_configured", Mock()),
        patch.object(instance, "async_step_confirm", AsyncMock(return_value={"type": "confirm"})),
    ):
        await instance.async_step_zeroconf(discovery(id="server"))
    assert parse_bool.call_args_list[0].args == (None, True)
    assert parse_bool.call_args_list[1].args == (None, False)


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        (KinosailDisabledError("off"), "disabled"),
        (KinosailError("offline"), "cannot_connect"),
        (("other", "Other"), "cannot_connect"),
    ],
)
async def test_confirm_translates_probe_failures(hass, probe: Exception | tuple[str, str], message: str) -> None:
    instance = flow(hass)
    instance.context = {"unique_id": "server"}
    instance._base_url = "https://server"
    mocked = AsyncMock(side_effect=probe) if isinstance(probe, Exception) else AsyncMock(return_value=probe)
    with patch.object(instance, "_probe", mocked):
        result = await instance.async_step_confirm({})
    assert result["errors"] == {"base": message}
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"url": "https://server"}
    mocked.assert_awaited_once_with("https://server", True)


async def test_confirm_form_and_success(hass) -> None:
    instance = flow(hass)
    instance.context = {"unique_id": "server"}
    instance._base_url = "https://server"
    form = await instance.async_step_confirm()
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "confirm"
    assert form["description_placeholders"] == {"url": "https://server"}
    expected = {"type": "external"}
    with (
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Server"))) as probe,
        patch.object(instance, "_start_oauth", AsyncMock(return_value=expected)),
    ):
        assert await instance.async_step_confirm({}) is expected
    probe.assert_awaited_once_with("https://server", True)


async def test_reauth_handles_missing_entry_or_state(hass) -> None:
    instance = flow(hass)
    instance.context = {"entry_id": "missing"}
    assert (await instance.async_step_reauth({}))["reason"] == "reauth_unsuccessful"
    assert (await instance.async_step_reauth_confirm())["reason"] == "reauth_unsuccessful"


async def test_reauth_loads_existing_entry_and_shows_confirmation(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="server",
        data={CONF_URL: "https://server", CONF_VERIFY_SSL: True},
    )
    entry.add_to_hass(hass)
    instance = flow(hass)
    instance.context = {"entry_id": entry.entry_id}
    result = await instance.async_step_reauth({})
    assert result["type"] is FlowResultType.FORM
    assert instance._reauth_entry is entry


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        (KinosailDisabledError("off"), "disabled"),
        (KinosailError("offline"), "cannot_connect"),
        (("other", "Other"), "cannot_connect"),
    ],
)
async def test_reauth_translates_failures(hass, probe: Exception | tuple[str, str], message: str) -> None:
    instance = flow(hass)
    instance._reauth_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", CONF_VERIFY_SSL: True}
    )
    mocked = AsyncMock(side_effect=probe) if isinstance(probe, Exception) else AsyncMock(return_value=probe)
    with patch.object(instance, "_probe", mocked):
        result = await instance.async_step_reauth_confirm({CONF_URL: "https://server", CONF_VERIFY_SSL: True})
    assert result["errors"] == {"base": message}
    assert result["step_id"] == "reauth_confirm"
    mocked.assert_awaited_once_with("https://server", True)


@pytest.mark.parametrize("code", ["", "12345678"])
async def test_reauth_starts_selected_authorization_method(hass, code: str) -> None:
    instance = flow(hass)
    instance._reauth_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", CONF_VERIFY_SSL: True}
    )
    expected = {"type": "authorize"}
    with (
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Server"))) as probe,
        patch.object(instance, "_manual_pair", AsyncMock(return_value=expected)) as manual,
        patch.object(instance, "_start_oauth", AsyncMock(return_value=expected)) as oauth,
    ):
        assert (
            await instance.async_step_reauth_confirm({CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": code})
            is expected
        )
    (manual if code else oauth).assert_awaited_once()
    probe.assert_awaited_once_with("https://server", True)
    if code:
        manual.assert_awaited_once_with("12345678")


async def test_reauth_form_uses_existing_transport(hass) -> None:
    instance = flow(hass)
    instance._reauth_entry = MockConfigEntry(
        domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", CONF_VERIFY_SSL: False}
    )
    result = await instance.async_step_reauth_confirm()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["data_schema"] is not None
    assert result["data_schema"]({})[CONF_VERIFY_SSL] is False


async def test_reauth_form_defaults_missing_tls_setting(hass) -> None:
    instance = flow(hass)
    instance._reauth_entry = MockConfigEntry(domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server"})
    result = await instance.async_step_reauth_confirm()
    assert result["data_schema"]({})[CONF_VERIFY_SSL] is True


async def test_reconfigure_translates_disabled_server(hass) -> None:
    instance = flow(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", CONF_VERIFY_SSL: False}
    )
    with (
        patch.object(instance, "_get_reconfigure_entry", return_value=entry),
        patch.object(instance, "_probe", AsyncMock(side_effect=KinosailDisabledError("off"))) as probe,
    ):
        result = await instance.async_step_reconfigure({CONF_URL: "https://server", CONF_VERIFY_SSL: False})
    assert result["errors"] == {"base": "disabled"}
    assert result["step_id"] == "reconfigure"
    assert result["data_schema"] is not None
    probe.assert_awaited_once_with("https://server", False)


async def test_reconfigure_form_defaults_missing_tls_setting(hass) -> None:
    instance = flow(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", None: False})
    with patch.object(instance, "_get_reconfigure_entry", return_value=entry):
        result = await instance.async_step_reconfigure()
    assert result["step_id"] == "reconfigure"
    assert result["data_schema"]({}) == {CONF_URL: "https://server", CONF_VERIFY_SSL: True}
