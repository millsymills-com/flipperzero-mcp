# Security Policy

## Reporting a vulnerability

Email the maintainer or open a private security advisory on GitHub. Please do
not file public issues for unpatched vulnerabilities.

## Supported versions

Only the latest release receives security fixes.

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## WiFi credentials and firmware config

The ESP32 bridge firmware stores the operator's WiFi credentials in NVS at
runtime (set through the device's captive portal); they are never written to
source.

The ESP-IDF build-config file `firmware/tcp_uart_bridge/sdkconfig` is generated
locally and may contain build-time values; it is **gitignored** and must not be
committed. Only `firmware/tcp_uart_bridge/sdkconfig.defaults` is tracked, and it
ships with credential values blanked out. Set the captive-portal AP password
before flashing; do not commit a populated value.

## What the repo guarantees

- No WiFi SSID, password, or other secret is committed in any tracked file.
- The live `sdkconfig` is gitignored; only the sanitized `sdkconfig.defaults`
  is tracked.
