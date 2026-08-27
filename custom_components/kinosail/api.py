"""Small async client for the Kinosail Home Assistant API."""

from __future__ import annotations

import json as json_module
import re
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from aiohttp import ClientError, ClientSession

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PLAYERS = 64
MAX_LIBRARY_ITEMS = 200
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class KinosailError(Exception):
    """Base Kinosail error."""


class KinosailAuthError(KinosailError):
    """The Kinosail grant is invalid or revoked."""


class KinosailDisabledError(KinosailError):
    """The Kinosail Home Assistant setting is off."""


def normalize_url(value: str) -> str:
    """Validate and normalize one local Kinosail URL."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid URL")
    if parsed.path not in {"", "/"}:
        raise ValueError("invalid URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


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
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Send a bounded Kinosail API request."""
        headers = {"Authorization": f"Bearer {self.token}"} if authenticated and self.token else {}
        try:
            async with self.session.request(
                method,
                urljoin(self.base_url + "/", path.lstrip("/")),
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
                chunks, size = [], 0
                while chunk := await response.content.read(min(65536, MAX_RESPONSE_BYTES + 1 - size)):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise KinosailError("Kinosail response is too large")
                data = json_module.loads(b"".join(chunks))
        except (ClientError, ValueError) as err:
            if isinstance(err, KinosailError):
                raise
            raise KinosailError("Could not connect to Kinosail") from err
        if not isinstance(data, dict):
            raise KinosailError("Kinosail returned an invalid response")
        return data

    async def probe(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/home-assistant", authenticated=False)

    async def pair(self, code: str, name: str) -> dict[str, Any]:
        code, name = code.strip(), name.strip()
        if len(code) != 8 or not code.isascii() or not code.isdigit() or not name or len(name) > 80:
            raise KinosailError("Kinosail pairing code and name are invalid")
        return await self.request(
            "POST", "/api/v1/home-assistant/pair", json={"code": code, "name": name}, authenticated=False
        )

    async def oauth_token(self, data: dict[str, Any]) -> dict[str, Any]:
        """Exchange one browser-approved authorization code."""
        return await self.request("POST", "/api/v1/home-assistant/token", data=data, authenticated=False)

    async def players(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/api/v1/home-assistant/players")
        players = data.get("players", [])
        if (
            not isinstance(players, list)
            or len(players) > MAX_PLAYERS
            or any(
                not isinstance(player, dict) or not ID_PATTERN.fullmatch(str(player.get("id", "")))
                for player in players
            )
        ):
            raise KinosailError("Kinosail returned invalid players")
        return players

    async def command(self, player_id: str, command: str, **values: Any) -> None:
        if not ID_PATTERN.fullmatch(player_id):
            raise KinosailError("Kinosail player ID is invalid")
        await self.request(
            "POST", f"/api/v1/home-assistant/players/{player_id}/commands", json={"command": command, **values}
        )

    async def library(self, query: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": 200}
        if query:
            params["q"] = query
        data = await self.request("GET", "/api/v1/home-assistant/library", params=params)
        items = data.get("items", [])
        if (
            not isinstance(items, list)
            or len(items) > MAX_LIBRARY_ITEMS
            or any(not isinstance(item, dict) or not ID_PATTERN.fullmatch(str(item.get("id", ""))) for item in items)
        ):
            raise KinosailError("Kinosail returned invalid library data")
        return items

    async def playback(self, item_id: str) -> tuple[str, str]:
        if not ID_PATTERN.fullmatch(item_id):
            raise KinosailError("Kinosail item ID is invalid")
        data = await self.request("POST", f"/api/v1/home-assistant/playback/{item_id}", json={})
        path = data.get("url")
        if not isinstance(path, str) or not path.startswith("/home-assistant/media/"):
            raise KinosailError("Kinosail returned an invalid playback URL")
        mime_type = data.get("mimeType")
        if not isinstance(mime_type, str) or not mime_type:
            mime_type = "application/octet-stream"
        return urljoin(self.base_url + "/", path.lstrip("/")), mime_type
