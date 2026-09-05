"""Tests for the Kinosail setup and reconfiguration flows."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kinosail.api import KinosailClient
from custom_components.kinosail.const import DOMAIN


async def test_manual_setup_creates_entry(hass) -> None:
    """Configure Kinosail with the manual pairing fallback."""
    with (
        patch.object(KinosailClient, "probe", AsyncMock(return_value={"serverId": "server", "name": "Living Room"})),
        patch.object(
            KinosailClient,
            "pair",
            AsyncMock(return_value={"serverId": "server", "name": "Living Room", "token": "ks_secret"}),
        ),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "https://media.example/", CONF_VERIFY_SSL: True, "code": "12345678"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["title"] == "Living Room"
    assert result["data"] == {CONF_URL: "https://media.example", CONF_VERIFY_SSL: True, "token": "ks_secret"}


async def test_reconfigure_preserves_grant(hass) -> None:
    """Change transport settings for the same Server."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="server",
        title="Living Room",
        data={CONF_URL: "http://old.local:38127", CONF_VERIFY_SSL: False, "token": "ks_secret"},
    )
    entry.add_to_hass(hass)
    with patch.object(
        KinosailClient,
        "probe",
        AsyncMock(return_value={"serverId": "server", "name": "Living Room Server"}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "https://media.example/", CONF_VERIFY_SSL: True},
        )

    assert result["type"] is FlowResultType.ABORT, result
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Living Room Server"
    assert entry.data == {CONF_URL: "https://media.example", CONF_VERIFY_SSL: True, "token": "ks_secret"}


async def test_reconfigure_rejects_another_server_without_side_effects(hass) -> None:
    """Keep the existing entry when an address belongs to another Server."""
    original = {CONF_URL: "http://old.local:38127", CONF_VERIFY_SSL: False, "token": "ks_secret"}
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server", title="Living Room", data=original)
    entry.add_to_hass(hass)
    with patch.object(
        KinosailClient,
        "probe",
        AsyncMock(return_value={"serverId": "other", "name": "Other Server"}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "https://wrong.example", CONF_VERIFY_SSL: True},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.title == "Living Room"
    assert entry.data == original


async def test_reconfigure_rejects_pairing_fields_before_network_access(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server", data={CONF_URL: "https://server", CONF_VERIFY_SSL: True})
    entry.add_to_hass(hass)
    with patch.object(KinosailClient, "probe", AsyncMock()) as probe:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
            data={CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": "12345678"},
        )
    assert result["errors"] == {"base": "cannot_connect"}
    probe.assert_not_awaited()
