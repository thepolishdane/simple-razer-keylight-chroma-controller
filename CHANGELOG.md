# Changelog

## v5.2
Fixes a light that would lag, stop responding, or get stuck on after working only briefly.

- **Heartbeat keep-alive.** The server now contacts each configured light every 30s so its WiFi radio never drops into power-save sleep (a sleeping radio ignores the first connection, which is what made a light "stop reacting").
- **Graceful heartbeat, not a rude one.** The keep-alive does a full polite exchange (connect, send hello, read the reply, close cleanly). An earlier bare connect-and-drop could wedge a light's single-connection control server and leave it unresponsive until a power-cycle. If a light ever does get wedged, unplug it for ~20s and plug it back in, then leave it a minute to rejoin WiFi.
- **Wider retry backoff** when sending a command: 5 attempts with growing gaps (0.3s up to 1.5s) instead of 3 fixed 0.2s tries, so a deep-asleep light wakes within a single button press.
- **Diagnosis note for anyone debugging:** the control port (TCP 10003) is the only reliable health signal for these lights. ICMP ping is not - a healthy light can ignore ping while its control port works fine, and a wedged light can answer ping while its control port is dead.

## v5.1
- Single-instance guard so a second launch cannot silently fight over the port.
- Retry to wake a light whose WiFi radio has gone to sleep.
- Error logging to `razer_controller.log` instead of silently swallowing failures.
- Atomic config save with a lock to prevent lost updates under rapid presses.
