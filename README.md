# Kinosail for Home Assistant

This custom integration connects Home Assistant directly to a local [Kinosail](https://github.com/MikeO7/Kinosail) Server.

It provides:

- Kinosail Library Content in Home Assistant's media browser.
- Short-lived direct playback URLs. Home Assistant does not relay media.
- `media_player` entities for active Kinosail browser players.
- Play, pause, stop, seek, volume, mute, and play-media controls.
- A one-time local pairing flow with a revocable integration-only token.

## Install with HACS

1. Open HACS in Home Assistant.
2. Add `https://github.com/MikeO7/Kinosail-Home-Assistant` as a custom integration repository.
3. Install Kinosail and restart Home Assistant.
4. In Kinosail, open **Settings → Access → Integrations**.
5. Enable **Home Assistant** and create a one-time pairing code.
6. In Home Assistant, select **Settings → Devices & services → Add integration → Kinosail**.
7. Enter the local Kinosail Server URL and pairing code.

Keep certificate verification enabled when Home Assistant trusts the Kinosail certificate. If you use Kinosail's private certificate, add its local certificate authority to the Home Assistant host first.

Disabling Home Assistant in Kinosail withdraws the API and revokes every Home Assistant token.

## Manual install

Copy `custom_components/kinosail` into the Home Assistant `custom_components` directory, then restart Home Assistant.

## Privacy boundary

Kinosail stays the media origin. This integration polls only active player state and library data. It does not use a cloud service, MQTT broker, media proxy, or sidecar.
