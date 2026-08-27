"""Kinosail Library Content in Home Assistant's media browser."""

from __future__ import annotations

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType, SearchMedia, SearchMediaQuery
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .api import KinosailError
from .const import DOMAIN, KinosailRuntime


async def async_get_media_source(hass: HomeAssistant) -> KinosailMediaSource:
    """Create the Kinosail media source."""
    return KinosailMediaSource(hass)


class KinosailMediaSource(MediaSource):
    """Browse every configured local Kinosail Server."""

    name = "Kinosail"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _runtime(self, entry_id: str) -> KinosailRuntime:
        runtime = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            raise BrowseError("Kinosail Server is not available")
        return runtime

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse servers or one server library."""
        if not item.identifier:
            children = [self._server(entry_id, runtime) for entry_id, runtime in self.hass.data.get(DOMAIN, {}).items()]
            return BrowseMediaSource(
                domain=DOMAIN,
                identifier=None,
                media_class=MediaClass.APP,
                media_content_type="",
                title="Kinosail",
                can_play=False,
                can_expand=True,
                children=children,
            )
        entry_id, separator, media_id = item.identifier.partition("/")
        if media_id:
            raise BrowseError("This Kinosail item cannot be expanded")
        runtime = self._runtime(entry_id)
        try:
            items = await runtime.client.library()
        except KinosailError as err:
            raise BrowseError("Could not browse Kinosail") from err
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=entry_id,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=runtime.name,
            can_play=False,
            can_expand=True,
            can_search=True,
            children=[self._item(entry_id, value) for value in items if isinstance(value, dict)],
        )

    async def async_search_media(self, item: MediaSourceItem, query: SearchMediaQuery) -> SearchMedia:
        """Search one Kinosail Server."""
        entry_id = (item.identifier or "").partition("/")[0]
        runtime = self._runtime(entry_id)
        try:
            items = await runtime.client.library(query.search_query)
        except KinosailError as err:
            raise BrowseError("Could not search Kinosail") from err
        return SearchMedia(result=[self._item(entry_id, value) for value in items if isinstance(value, dict)])

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a short-lived direct Kinosail stream."""
        entry_id, separator, media_id = item.identifier.partition("/")
        if not separator or not media_id or len(media_id) > 128:
            raise Unresolvable("Kinosail item is invalid")
        try:
            url, mime_type = await self._runtime(entry_id).client.playback(media_id)
        except (BrowseError, KinosailError) as err:
            raise Unresolvable("Could not resolve Kinosail media") from err
        return PlayMedia(url, mime_type)

    @staticmethod
    def _server(entry_id: str, runtime: KinosailRuntime) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=entry_id,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=runtime.name,
            can_play=False,
            can_expand=True,
        )

    @staticmethod
    def _item(entry_id: str, item: dict) -> BrowseMediaSource:
        kind = item.get("kind")
        media_class = MediaClass.MUSIC if kind in {"audio", "audiobook"} else MediaClass.VIDEO
        media_type = MediaType.MUSIC if kind in {"audio", "audiobook"} else MediaType.VIDEO
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{entry_id}/{item.get('id', '')}",
            media_class=media_class,
            media_content_type=media_type,
            title=str(item.get("title") or "Untitled"),
            can_play=True,
            can_expand=False,
        )
