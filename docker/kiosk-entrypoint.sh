#!/bin/sh
set -e

# KIOSK_URL is the glados-frontend page this device displays (see
# .env.example). There is no sane default: a kiosk pointed at nothing is
# a silent misconfiguration, not a usable fallback.
if [ -z "$KIOSK_URL" ]; then
  echo "KIOSK_URL is not set. Point it at the glados-frontend URL for this terminal (see .env.example)." >&2
  exit 1
fi

# ── Origin of KIOSK_URL ─────────────────────────────────────────────────
# scheme://host[:port] in lower case, no user info, no path, and no
# port when it is the scheme's default. The host is checked against a
# strict pattern because it goes into a JSON file below.
scheme=$(printf '%s' "${KIOSK_URL%%://*}" | tr 'A-Z' 'a-z')
rest=${KIOSK_URL#*://}
hostport=${rest%%/*}
hostport=${hostport%%\?*}
hostport=${hostport%%#*}
hostport=$(printf '%s' "${hostport##*@}" | tr 'A-Z' 'a-z')
case "$scheme" in
  http | https) ;;
  *)
    echo "KIOSK_URL must start with http:// or https://, got '$KIOSK_URL'." >&2
    exit 1
    ;;
esac
if ! printf '%s' "$hostport" | grep -Eq '^([A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(:[0-9]+)?$'; then
  echo "Cannot read a host from KIOSK_URL '$KIOSK_URL'." >&2
  exit 1
fi
case "$scheme:$hostport" in
  https:*:443) hostport=${hostport%:443} ;;
  http:*:80) hostport=${hostport%:80} ;;
esac
origin="$scheme://$hostport"

# ── Chromium Local Network Access policy ────────────────────────────────
# The glados-frontend page talks to the bridge on localhost:8600. Recent
# Chromium versions treat a request from a public origin to a loopback
# address as local network access and ask the user first, and nobody is
# there to answer on a wall display. This managed policy allows exactly
# the KIOSK_URL origin to make those requests, and no other page.
# LocalNetworkAccessAllowedForUrls is the current policy name;
# InsecurePrivateNetworkRequestsAllowedForUrls is its predecessor from
# the Private Network Access rollout, set as well for older Chromium
# builds. Written as root into a root-owned directory, so the kiosk user
# Chromium runs as cannot change it.
#
# KIOSK_CA_CERT optionally adds certificate authorities Chromium trusts
# on top of its built-in ones, for a Glados server whose certificate an
# internal CA issued: base64 DER, one line per certificate, several
# separated by commas (see .env.example). The CACertificates policy
# takes exactly that form. Each value is checked against the base64
# alphabet because it goes into the JSON file, and must decode to a DER
# SEQUENCE, so a pasted PEM header or a typo fails here instead of as a
# certificate error on the display.
ca_certs=
ca_count=0
set -f
old_ifs=$IFS
IFS=,
for cert in ${KIOSK_CA_CERT:-}; do
  cert=$(printf '%s' "$cert" | tr -d ' \t\r\n')
  [ -n "$cert" ] || continue
  if ! printf '%s' "$cert" | grep -Eq '^[A-Za-z0-9+/]+={0,2}$' \
    || [ "$(printf '%s' "$cert" | base64 -d 2>/dev/null | head -c 1 | od -An -tx1 | tr -d ' ')" != 30 ]; then
    echo "KIOSK_CA_CERT must be base64 DER certificates separated by commas, see .env.example." >&2
    exit 1
  fi
  ca_certs="$ca_certs${ca_certs:+, }\"$cert\""
  ca_count=$((ca_count + 1))
done
IFS=$old_ifs
set +f

policy_dir=/etc/chromium/policies/managed
mkdir -p "$policy_dir"
umask 022
{
  printf '{\n'
  printf '  "LocalNetworkAccessAllowedForUrls": ["%s"],\n' "$origin"
  printf '  "InsecurePrivateNetworkRequestsAllowedForUrls": ["%s"]' "$origin"
  if [ -n "$ca_certs" ]; then printf ',\n  "CACertificates": [%s]' "$ca_certs"; fi
  printf '\n}\n'
} > "$policy_dir/glados-terminal.json.tmp"
mv "$policy_dir/glados-terminal.json.tmp" "$policy_dir/glados-terminal.json"
echo "Allowed local network access for $origin."
if [ "$ca_count" -gt 0 ]; then echo "Trusting $ca_count extra CA certificate(s) from KIOSK_CA_CERT."; fi

# ── Display settings ────────────────────────────────────────────────────
# KIOSK_OUTPUT_MODE, KIOSK_OUTPUT_TRANSFORM and KIOSK_OUTPUT_SCALE (see
# .env.example) become sway `output` lines for every connected display.
# Each is optional: unset, sway uses the display's preferred mode,
# unrotated, at scale 1. Each value is checked against a strict pattern
# because it goes into sway's config. A rotated display also rotates
# touch input: the libinput calibration matrix turns the touchscreen's
# raw coordinates with the picture, since sway does not do that itself.
mode=${KIOSK_OUTPUT_MODE:-}
transform=${KIOSK_OUTPUT_TRANSFORM:-}
scale=${KIOSK_OUTPUT_SCALE:-}
if [ -n "$mode" ] && ! printf '%s' "$mode" | grep -Eq '^[0-9]+x[0-9]+(@[0-9]+(\.[0-9]+)?Hz)?$'; then
  echo "KIOSK_OUTPUT_MODE must look like 1920x1080 or 1920x1080@60Hz, got '$mode'." >&2
  exit 1
fi
case "$transform" in
  '' | normal) calibration= ;;
  90) calibration='0 -1 1 1 0 0' ;;
  180) calibration='-1 0 1 0 -1 1' ;;
  270) calibration='0 1 0 -1 0 1' ;;
  *)
    echo "KIOSK_OUTPUT_TRANSFORM must be normal, 90, 180 or 270, got '$transform'." >&2
    exit 1
    ;;
esac
if [ -n "$scale" ] && ! printf '%s' "$scale" | grep -Eq '^[0-9]+(\.[0-9]+)?$'; then
  echo "KIOSK_OUTPUT_SCALE must be a number such as 1 or 2, got '$scale'." >&2
  exit 1
fi
output_conf=/etc/glados-kiosk/output.conf
{
  echo "# Written by the entrypoint from KIOSK_OUTPUT_* at container start."
  if [ -n "$mode" ]; then echo "output * mode $mode"; fi
  if [ -n "$transform" ]; then echo "output * transform $transform"; fi
  if [ -n "$scale" ]; then echo "output * scale $scale"; fi
  if [ -n "$calibration" ]; then echo "input type:touch calibration_matrix $calibration"; fi
} > "$output_conf.tmp"
mv "$output_conf.tmp" "$output_conf"
echo "Display: mode ${mode:-preferred}, transform ${transform:-normal}, scale ${scale:-1}."

# ── seatd ───────────────────────────────────────────────────────────────
# seatd stays root: it opens /dev/dri and /dev/input on sway's behalf and
# passes the open file descriptors over its socket, which only the video
# group may use. SEATD_VTBOUND=0 because this container has no virtual
# terminal; nothing else on the device competes for the display (the host
# runs no desktop, see docs/INSTALLATION.md), so there is no VT switching
# to coordinate.
SEATD_VTBOUND=0 seatd -g video &
i=0
while [ ! -S /run/seatd.sock ]; do
  i=$((i + 1))
  if [ "$i" -gt 50 ]; then
    echo "seatd did not create /run/seatd.sock within 5 seconds." >&2
    exit 1
  fi
  sleep 0.1
done

# ── Drop to the kiosk user ──────────────────────────────────────────────
# Chromium's GPU process and Mesa open the DRM render node directly, not
# through seatd, so the kiosk user also gets the group IDs the DRM nodes
# carry on the host. Reading them here avoids baking host GIDs into the
# image. GID 0 is never handed out.
groups=video
for node in /dev/dri/*; do
  [ -c "$node" ] || continue
  gid=$(stat -c %g "$node")
  if [ "$gid" = 0 ]; then
    echo "Skipping $node: it belongs to group 0, which the kiosk user never gets." >&2
    continue
  fi
  groups="$groups,$gid"
done

# The runtime directory is the `kiosk-runtime` volume (docker-compose.yml),
# which the bridge mounts as well to reach sway's IPC socket for
# POST /display. The volume outlives this container while the bridge
# runs, so sockets of an earlier sway are removed first and the bridge
# only ever finds the current one.
kiosk_uid=$(id -u kiosk)
runtime_dir="/run/user/$kiosk_uid"
mkdir -p "$runtime_dir"
rm -f "$runtime_dir"/sway-ipc.*.sock
chown kiosk:kiosk "$runtime_dir"
chmod 0700 "$runtime_dir"

# sway starts Chromium through /usr/local/bin/kiosk-chromium, which
# inherits this environment, KIOSK_URL and KIOSK_EXTRA_FLAGS included.
# WLR_LIBINPUT_NO_DEVICES=1: a wall display has no keyboard, mouse or
# touchscreen, and sway would refuse to start without input devices.
exec env HOME=/home/kiosk USER=kiosk LOGNAME=kiosk \
  XDG_RUNTIME_DIR="$runtime_dir" LIBSEAT_BACKEND=seatd \
  WLR_LIBINPUT_NO_DEVICES=1 \
  setpriv --reuid=kiosk --regid=kiosk --groups="$groups" --inh-caps=-all \
  sway --config /etc/glados-kiosk/sway.conf
