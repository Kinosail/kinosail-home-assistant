"""Constants for Kinosail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .api import KinosailClient

if TYPE_CHECKING:
    from .coordinator import KinosailCoordinator

DOMAIN = "kinosail"
PLATFORMS = ["media_player"]


@dataclass
class KinosailRuntime:
    """Runtime data for one Kinosail Server."""

    client: KinosailClient
    coordinator: KinosailCoordinator
    name: str
    server_id: str
