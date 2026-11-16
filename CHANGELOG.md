# changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-11-16

The first release of glados-terminal, the shop-floor kiosk terminal for [Glados](https://github.com/deloarts/glados). It works with Glados 0.1.x.

### What it does

- A hardware bridge daemon owns the devices attached to the kiosk: an evdev RFID reader and a serial QR/barcode scanner. Each runs supervised and is restarted with backoff after a failure, and their events reach the Glados page in the kiosk over `GET /ws/events`. `GET /health` and `GET /devices` report the bridge's and each device's status.
- The bridge is reachable on the device's loopback interface only, and only pages from the origins in `BRIDGE__ALLOWED_ORIGINS` can use it from a browser.
- Device identity for infoscreens: the bridge generates an Ed25519 key pair into the `identity` volume, hands the public key and the terminal key from `.env` to the page at `GET /identity` and signs the Glados sign-in challenge at `POST /identity/sign`. The private key never leaves the bridge. A new device shows a pairing code until someone approves it in Glados.
- Display power: `POST /display` switches the display off and on for an infoscreen's schedule, through sway and, on a TV that answers on HDMI-CEC, through standby. `GET /display` reports its state.
- Device details: `GET /device` reports the computer, the host's OS and hostname, every display connector with the display's EDID data, and the display state, for the terminal list in Glados.
- A kiosk container shows the Glados page in Chromium under sway, as an unprivileged user with Chromium's sandbox. `KIOSK_OUTPUT_MODE`, `KIOSK_OUTPUT_TRANSFORM` and `KIOSK_OUTPUT_SCALE` set the display's resolution, rotation and scale, and `KIOSK_CA_CERT` adds an internal certificate authority for a Glados server with an internal certificate.
- Every bridge route and its JSON is documented in [docs/BRIDGE_API.md](docs/BRIDGE_API.md).

### Requirements

- A Raspberry Pi 4 or 5, or another DietPi-supported single-board computer with a DRM/KMS capable GPU, running a 64-bit headless DietPi. The images are published for `linux/arm64` only.
- Docker with Docker Compose 2.24 or newer. The device pulls the images `ghcr.io/deloarts/glados-terminal/bridge` and `ghcr.io/deloarts/glados-terminal/kiosk` and builds nothing itself.
- A Glados 0.1.x server reachable from the device.
- Optionally Portainer, centrally with the Edge Agent or on the device, to run `docker-compose.yml` as a stack.

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for provisioning a device, the infoscreen setup and hardening, and [docs/RELEASING.md](docs/RELEASING.md) for the versioning and release policy.
