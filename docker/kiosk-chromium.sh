#!/bin/sh
# Started by sway (docker/kiosk-sway.conf) as the kiosk user, with the
# environment docker/kiosk-entrypoint.sh set up.
#
# Chromium runs with its sandbox: no --no-sandbox. The namespace sandbox
# needs the clone and unshare rules in docker/kiosk-seccomp.json and a
# host kernel that allows unprivileged user namespaces, see
# docs/INSTALLATION.md. --ozone-platform=wayland: Chromium talks to
# sway's Wayland socket directly instead of X11. KIOSK_EXTRA_FLAGS is an
# escape hatch for hardware-specific flags (e.g. GPU quirks on a given Pi
# revision) this script should not have to guess at -- left unquoted
# deliberately so it word-splits into multiple flags, and vanishes
# cleanly (zero extra args) when unset.
#
# When Chromium exits, sway exits with it, the container stops and
# Docker's restart policy starts it again. Without this, a crashed
# Chromium would leave sway showing an empty screen.
chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --ozone-platform=wayland \
  --enable-features=UseOzonePlatform \
  ${KIOSK_EXTRA_FLAGS} \
  "$KIOSK_URL"
swaymsg exit
