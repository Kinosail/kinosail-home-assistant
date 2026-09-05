"""Tests for shared configuration validation."""

import pytest
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL

from custom_components.kinosail.validation import advertised_bool, connection_input, transport_input


@pytest.mark.parametrize(
    "value",
    [
        {},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "extra": 1},
        {CONF_URL: "https://server"},
        {CONF_VERIFY_SSL: True},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: "true"},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": 1},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: True, "code": "invalid"},
    ],
)
def test_connection_input_rejects_malformed_values(value: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="invalid connection"):
        connection_input(value)


def test_connection_input_normalizes_valid_values() -> None:
    assert connection_input({CONF_URL: " https://server/ ", CONF_VERIFY_SSL: False, "code": " 12345678 "}) == (
        "https://server",
        False,
        "12345678",
    )
    assert connection_input({CONF_URL: "http://server", CONF_VERIFY_SSL: True}) == (
        "http://server",
        True,
        "",
    )


def test_transport_input_allows_only_a_url_and_boolean() -> None:
    assert transport_input({CONF_URL: " https://server/ ", CONF_VERIFY_SSL: False}) == ("https://server", False)
    for value in (
        {CONF_URL: "https://server", CONF_VERIFY_SSL: False, "code": "12345678"},
        {CONF_URL: "https://server"},
        {CONF_URL: "https://server", CONF_VERIFY_SSL: "false"},
    ):
        with pytest.raises(ValueError, match="invalid connection"):
            transport_input(value)


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, True, True),
        (None, False, False),
        (True, False, True),
        (False, True, False),
        ("TRUE", False, True),
        ("false", True, False),
    ],
)
def test_advertised_bool_accepts_unambiguous_values(value: object, default: bool, expected: bool) -> None:
    assert advertised_bool(value, default) is expected


@pytest.mark.parametrize("value", [0, 1, "yes", "", []])
def test_advertised_bool_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(ValueError, match="advertised boolean"):
        advertised_bool(value, True)
