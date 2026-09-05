"""Small async client for the Kinosail Home Assistant API."""

from __future__ import annotations

import json as json_module
import re
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientError, ClientSession

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PLAYERS = 64
MAX_LIBRARY_ITEMS = 200
MAX_LIBRARY_QUERY = 512
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
COMMANDS = {"play", "pause", "stop", "seek", "volume", "mute", "play_media"}
URL_SCHEME_HTTP = "http"
URL_SCHEME_HTTPS = "https"
URL_SCHEMES = {URL_SCHEME_HTTP, URL_SCHEME_HTTPS}

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


class KinosailError(Exception):
    """Base Kinosail error."""


class KinosailAuthError(KinosailError):
    """The Kinosail grant is invalid or revoked."""


class KinosailDisabledError(KinosailError):
    """The Kinosail Home Assistant setting is off."""


def validate_pairing_code(value: object) -> str:
    """Return one normalized eight-digit pairing code."""
    if not isinstance(value, str):
        raise KinosailError("Kinosail pairing code and name are invalid")
    value = value.strip()
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise KinosailError("Kinosail pairing code and name are invalid")
    return value


def normalize_url(value: object) -> str:
    """Validate and normalize one local Kinosail URL."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in URL_SCHEMES or not parsed.hostname:
        raise ValueError("invalid URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid URL")
    if parsed.path not in {"", "/"}:
        raise ValueError("invalid URL")
    if parsed.netloc.endswith(":"):
        raise ValueError("invalid URL")
    try:
        port = parsed.port
    except ValueError as err:
        raise ValueError("invalid URL") from err
    if port == 0:
        raise ValueError("invalid URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class KinosailClient:
    """Access one Kinosail Server without relaying media."""

    def __init__(self, session: ClientSession, base_url: str, token: str = "", verify_ssl: bool = True) -> None:
        self.session = session
        self.base_url = normalize_url(base_url)
        self.token = token
        self.verify_ssl = verify_ssl

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: JSONObject | None = None,
        data: JSONObject | None = None,
        params: JSONObject | None = None,
        authenticated: bool = True,
    ) -> JSONObject:
        """Send a bounded Kinosail API request."""
        if not path.startswith("/"):
            raise KinosailError("Kinosail request path is invalid")
        headers = {"Authorization": f"Bearer {self.token}"} if authenticated and self.token else {}
        try:
            async with self.session.request(
                method,
                self.base_url + path,
                json=json,
                data=data,
                params=params,
                headers=headers,
                ssl=self.verify_ssl,
            ) as response:
                if response.status in {401, 403}:
                    raise KinosailAuthError("Kinosail authorization failed")
                if response.status == 404 and path.startswith("/api/v1/home-assistant"):
                    raise KinosailDisabledError("Home Assistant is disabled in Kinosail")
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                while chunk := await response.content.read(min(65536, MAX_RESPONSE_BYTES + 1 - size)):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise KinosailError("Kinosail response is too large")
                payload = cast(JSONValue, json_module.loads(b"".join(chunks)))
        except (ClientError, UnicodeDecodeError, ValueError) as err:
            raise KinosailError("Could not connect to Kinosail") from err
        if not isinstance(payload, dict):
            raise KinosailError("Kinosail returned an invalid response")
        return payload

    async def probe(self) -> JSONObject:
        return await self.request("GET", "/api/v1/home-assistant", authenticated=False)

    async def pair(self, code: object, name: object) -> JSONObject:
        code = validate_pairing_code(code)
        if not isinstance(name, str):
            raise KinosailError("Kinosail pairing code and name are invalid")
        name = name.strip()
        if not name or len(name) > 80:
            raise KinosailError("Kinosail pairing code and name are invalid")
        return await self.request(
            "POST", "/api/v1/home-assistant/pair", json={"code": code, "name": name}, authenticated=False
        )

    async def oauth_token(self, data: JSONObject) -> JSONObject:
        """Exchange one browser-approved authorization code."""
        return await self.request("POST", "/api/v1/home-assistant/token", data=data, authenticated=False)

    async def players(self) -> list[JSONObject]:
        data = await self.request("GET", "/api/v1/home-assistant/players")
        players = data.get("players", [])
        if (
            not isinstance(players, list)
            or len(players) > MAX_PLAYERS
            or any(
                not isinstance(player, dict)
                or not isinstance(player.get("id"), str)
                or not ID_PATTERN.fullmatch(player["id"])
                for player in players
            )
        ):
            raise KinosailError("Kinosail returned invalid players")
        return cast(list[JSONObject], players)

    async def command(self, player_id: object, command: object, **values: JSONValue) -> None:
        if not isinstance(player_id, str) or not ID_PATTERN.fullmatch(player_id):
            raise KinosailError("Kinosail player ID is invalid")
        if not isinstance(command, str) or command not in COMMANDS:
            raise KinosailError("Kinosail player command is invalid")
        if command in {"play", "pause", "stop"}:
            valid = not values
        elif command == "seek":
            valid = _number_in_range(values, "position", 1e9)
        elif command == "volume":
            valid = _number_in_range(values, "volume", 1)
        elif command == "mute":
            valid = values.keys() == {"muted"} and isinstance(values["muted"], bool)
        else:
            item_id = values.get("itemId")
            valid = (
                values.keys() == {"itemId"} and isinstance(item_id, str) and ID_PATTERN.fullmatch(item_id) is not None
            )
        if not valid:
            raise KinosailError("Kinosail player command is invalid")
        await self.request(
            "POST", f"/api/v1/home-assistant/players/{player_id}/commands", json={"command": command, **values}
        )

    async def library(self, query: object = "") -> list[JSONObject]:
        if not isinstance(query, str) or len(query) > MAX_LIBRARY_QUERY:
            raise KinosailError("Kinosail library query is invalid")
        params: JSONObject = {"limit": 200}
        if query:
            params["q"] = query
        data = await self.request("GET", "/api/v1/home-assistant/library", params=params)
        items = data.get("items", [])
        if (
            not isinstance(items, list)
            or len(items) > MAX_LIBRARY_ITEMS
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not ID_PATTERN.fullmatch(item["id"])
                for item in items
            )
        ):
            raise KinosailError("Kinosail returned invalid library data")
        return cast(list[JSONObject], items)

    async def playback(self, item_id: object) -> tuple[str, str]:
        if not isinstance(item_id, str) or not ID_PATTERN.fullmatch(item_id):
            raise KinosailError("Kinosail item ID is invalid")
        data = await self.request("POST", f"/api/v1/home-assistant/playback/{item_id}", json={})
        path = data.get("url")
        if not isinstance(path, str) or not path.startswith("/home-assistant/media/"):
            raise KinosailError("Kinosail returned an invalid playback URL")
        mime_type = data.get("mimeType")
        if not isinstance(mime_type, str) or not mime_type:
            mime_type = "application/octet-stream"
        return self.base_url + path, mime_type


def _number_in_range(values: JSONObject, name: str, maximum: float) -> bool:
    value = values.get(name)
    return (
        values.keys() == {name}
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 <= value <= maximum
    )
