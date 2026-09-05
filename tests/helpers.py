"""Small test doubles shared by the integration tests."""

from __future__ import annotations

import json

from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy


class Response:
    """Minimal asynchronous HTTP response."""

    def __init__(self, status: int, body: object = None, *, raw: bytes | None = None) -> None:
        self.status = status
        self.content = self
        self.raw = json.dumps(body).encode() if raw is None else raw
        self.offset = 0
        self.read_limits: list[int] = []

    async def __aenter__(self) -> Response:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            headers = CIMultiDictProxy(CIMultiDict())
            raise ClientResponseError(RequestInfo("GET", None, headers, None), (), status=self.status)

    async def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        chunk = self.raw[self.offset : self.offset + limit]
        self.offset += len(chunk)
        return chunk


class Session:
    """Record requests and return configured responses."""

    def __init__(self, *responses: Response | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> Response:
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
