"""Constants for Kinosail."""

from dataclasses import dataclass

from .api import KinosailClient

DOMAIN = "kinosail"
PLATFORMS = ["media_player"]


@dataclass
class KinosailRuntime:
    """Runtime data for one Kinosail Server."""

    client: KinosailClient
    coordinator: object
    name: str
    server_id: str
