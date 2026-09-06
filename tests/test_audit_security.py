"""Regression coverage for discovery, authorization and transport trust boundaries."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import ClientSession, web
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import AbortFlow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kinosail.api import KinosailClient, KinosailError, normalize_url
from custom_components.kinosail.const import DOMAIN
from tests.helpers import Response, Session
from tests.test_config_flow_steps import discovery, flow


@pytest.mark.parametrize("source", ["zeroconf", "user", "finish"])
async def test_duplicate_server_cannot_replace_trusted_transport(hass, source) -> None:
    data = {CONF_URL: "https://trusted", CONF_VERIFY_SSL: True, "token": "existing-token"}
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server", data=data)
    entry.add_to_hass(hass)
    instance = flow(hass)
    instance.handler = DOMAIN
    instance.context["source"] = source
    instance._base_url = "https://untrusted"
    instance._verify_ssl = False
    with (
        patch.object(instance, "_probe", AsyncMock(return_value=("server", "Imposter"))),
        patch.object(instance, "_start_oauth", AsyncMock()) as authorize,
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
        pytest.raises(AbortFlow, match="already_configured"),
    ):
        if source == "zeroconf":
            await instance.async_step_zeroconf(discovery(id="server", url="https://untrusted", verify_ssl=False))
        elif source == "user":
            await instance.async_step_user({CONF_URL: "https://untrusted", CONF_VERIFY_SSL: False})
        else:
            await instance._finish({"serverId": "server", "name": "Imposter", "token": "new-token"})
    assert entry.data == data
    authorize.assert_not_awaited()
    reload.assert_not_called()


async def test_authorization_cannot_change_the_confirmed_server(hass) -> None:
    instance = flow(hass)
    instance.context["unique_id"] = "confirmed"
    with (
        patch.object(instance, "async_set_unique_id", AsyncMock()) as set_id,
        patch.object(instance, "async_create_entry", Mock()) as create,
        pytest.raises(KinosailError, match="another Kinosail Server"),
    ):
        await instance._finish({"serverId": "different", "name": "Other", "token": "token"})
    set_id.assert_not_awaited()
    create.assert_not_called()


async def test_authorization_accepts_the_confirmed_server(hass) -> None:
    instance = flow(hass)
    instance.context["unique_id"] = "confirmed"
    result = await instance._finish({"serverId": "confirmed", "name": "Server", "token": "token"})
    assert result["title"] == "Server"


@pytest.mark.parametrize("port", [True, "80", -1, 65536])
async def test_explicit_discovery_url_does_not_bypass_port_validation(hass, port) -> None:
    instance = flow(hass)
    with patch.object(instance, "async_set_unique_id", AsyncMock()) as set_id:
        result = await instance.async_step_zeroconf(discovery(id="server", port=port, url="https://server"))
    assert result["reason"] == "invalid_discovery"
    set_id.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "http://@server",
        "http://:@server",
        "http://ser\nver",
        "http://ser ver",
        "http://server\\evil",
        "http://ser\x00ver",
        "http://ser\x7fver",
    ],
)
def test_ambiguous_origins_are_rejected(url) -> None:
    with pytest.raises(ValueError):
        normalize_url(url)


@pytest.mark.parametrize("response", [TimeoutError(), RecursionError()])
async def test_transport_timeout_and_excessive_json_depth_are_translated(response) -> None:
    with pytest.raises(KinosailError, match="Could not connect"):
        await KinosailClient(Session(response), "https://server").probe()


@pytest.mark.parametrize("status", [300, 301, 302, 303, 307, 308, 399])
async def test_redirect_status_is_never_accepted_as_api_data(status) -> None:
    session = Session(Response(status, {"token": "unexpected"}))
    with pytest.raises(KinosailError, match="redirects"):
        await KinosailClient(session, "https://server").pair("12345678", "Home Assistant")
    assert session.calls[0][2]["allow_redirects"] is False
    assert session.calls[0][2]["timeout"].total == 10


async def test_real_http_redirect_never_forwards_pairing_code(socket_enabled) -> None:
    received = []

    async def redirect(request):
        received.append((request.path, await request.json()))
        raise web.HTTPTemporaryRedirect("/capture")

    async def capture(request):
        received.append((request.path, await request.json()))
        return web.json_response({"token": "stolen"})

    app = web.Application()
    app.router.add_post("/api/v1/home-assistant/pair", redirect)
    app.router.add_post("/capture", capture)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        async with ClientSession() as session:
            with pytest.raises(KinosailError, match="redirects"):
                await KinosailClient(session, f"http://127.0.0.1:{port}").pair("12345678", "Home Assistant")
        assert received == [("/api/v1/home-assistant/pair", {"code": "12345678", "name": "Home Assistant"})]
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "path",
    [
        "/home-assistant/media/other",
        "/home-assistant/media/item/../settings",
        "/home-assistant/media/%69tem",
        "/home-assistant/media/item#fragment",
        "/home-assistant/media/item?x=\nsecret",
        "/home-assistant/media/item?x=\\evil",
        "/home-assistant/media/item/",
    ],
)
async def test_playback_must_match_requested_item_without_ambiguous_path(path) -> None:
    client = KinosailClient(Session(Response(200, {"url": path})), "https://server")
    with pytest.raises(KinosailError, match="playback URL"):
        await client.playback("item")


async def test_bad_request_is_a_transport_error_not_a_redirect() -> None:
    with pytest.raises(KinosailError, match="Could not connect"):
        await KinosailClient(Session(Response(400, {})), "https://server").probe()
