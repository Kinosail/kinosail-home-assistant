"""Shared validation for Home Assistant flow inputs."""

from homeassistant.const import CONF_URL, CONF_VERIFY_SSL

from .api import KinosailError, normalize_url, validate_pairing_code

CONF_CODE = "code"
type FlowInput = dict[str, object]


def connection_input(user_input: FlowInput) -> tuple[str, bool, str]:
    """Strictly parse one user-entered connection before network access."""
    allowed = {CONF_URL, CONF_VERIFY_SSL, CONF_CODE}
    if user_input.keys() - allowed or not {CONF_URL, CONF_VERIFY_SSL} <= user_input.keys():
        raise ValueError("invalid connection input")
    verify_ssl = user_input[CONF_VERIFY_SSL]
    code = user_input.get(CONF_CODE, "")
    if not isinstance(verify_ssl, bool) or not isinstance(code, str):
        raise ValueError("invalid connection input")
    if code:
        try:
            code = validate_pairing_code(code)
        except KinosailError as err:
            raise ValueError("invalid connection input") from err
    return normalize_url(user_input[CONF_URL]), verify_ssl, code


def transport_input(user_input: FlowInput) -> tuple[str, bool]:
    """Strictly parse one transport-only update before network access."""
    if user_input.keys() != {CONF_URL, CONF_VERIFY_SSL} or not isinstance(user_input[CONF_VERIFY_SSL], bool):
        raise ValueError("invalid connection input")
    return normalize_url(user_input[CONF_URL]), user_input[CONF_VERIFY_SSL]


def advertised_bool(value: object, default: bool) -> bool:
    """Strictly parse one advertised boolean."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError("invalid advertised boolean")
