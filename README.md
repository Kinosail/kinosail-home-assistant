# Kinosail for Home Assistant

This custom integration connects Home Assistant directly to a local [Kinosail](https://github.com/MikeO7/kinosail-player) Server.

It provides:

- Kinosail Library Content in Home Assistant's media browser.
- Short-lived direct playback URLs. Home Assistant does not relay media.
- `media_player` entities for active Kinosail browser players.
- Play, pause, stop, seek, volume, mute, and play-media controls.
- Automatic local discovery and Owner approval in a secure browser popup.
- A one-time pairing code fallback with the same revocable integration-only token.

## Install with HACS

1. Open HACS in Home Assistant.
2. Add `https://github.com/MikeO7/kinosail-home-assistant` as a custom integration repository.
3. Install Kinosail and restart Home Assistant.
4. In Kinosail, open **Settings → Access → Integrations**.
5. Enable **Home Assistant**, then select **Add to Home Assistant**.
6. Approve the connection in the Kinosail popup.

Home Assistant also offers enabled Kinosail Servers that it discovers through local mDNS. Enter the Server URL when multicast discovery cannot cross the container network. The one-time code in Kinosail Settings remains a manual fallback.

Discovery verifies a trusted Kinosail certificate. It uses the confirmed local connection without certificate validation for Kinosail's private certificate. Manual setup keeps this choice visible.

Disabling Home Assistant in Kinosail withdraws mDNS discovery and the API. It also revokes every Home Assistant token.

## Manual install

Copy `custom_components/kinosail` into the Home Assistant `custom_components` directory, then restart Home Assistant.

## Privacy boundary

Kinosail stays the media origin. This integration polls only active player state and library data. It does not use a cloud service, MQTT broker, media proxy, or sidecar.
