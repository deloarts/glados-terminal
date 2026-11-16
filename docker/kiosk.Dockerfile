# ─── Kiosk display container ───────────────────────────────
# Headless Wayland kiosk: sway drives the display directly via DRM/KMS
# -- no X server, no desktop session, this container IS the display. Its
# config (docker/kiosk-sway.conf) reduces it to a single fullscreen
# Chromium; sway rather than a single-app compositor such as cage
# because it can set the display's mode, rotation and scale, which the
# KIOSK_OUTPUT_* variables in .env feed it. seatd hands sway the
# DRM/input device permissions a non-logind, non-desktop environment
# would otherwise need a full seat/session stack for.
#
# The entrypoint starts as root only to run seatd and to write the
# Chromium policy file and sway's display settings, then drops to the
# unprivileged `kiosk` user for sway and Chromium (see
# docker/kiosk-entrypoint.sh). setpriv, which does the drop, ships with
# util-linux in the base image.
#
# Debian 13 (trixie), the release the Raspberry Pi hosts run as well. Its
# sway 1.10, wlroots 0.18 and Mesa 25 replace bookworm's sway 1.7,
# wlroots 0.15 and Mesa 22, which left parts of a rotated or scaled
# picture unpainted. sway 1.10 names the output power command `power`
# (sway 1.7 called it `dpms`); the bridge picks the word from the sway
# version, see src/host/sway.py.
FROM debian:trixie-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sway \
        chromium \
        seatd \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# The video group inside the image is the one the seatd socket is
# shared with. Access to the host's DRM nodes is granted at start time
# instead, by the GIDs those nodes carry on the host, which differ
# across DietPi images.
RUN useradd --system --uid 10001 --user-group --groups video \
        --create-home --home-dir /home/kiosk --shell /usr/sbin/nologin kiosk

COPY docker/kiosk-sway.conf /etc/glados-kiosk/sway.conf
COPY docker/kiosk-chromium.sh /usr/local/bin/kiosk-chromium
COPY docker/kiosk-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/kiosk-chromium

ENTRYPOINT ["/entrypoint.sh"]
