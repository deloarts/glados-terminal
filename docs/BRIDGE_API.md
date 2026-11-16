# bridge api

- [bridge api](#bridge-api)
  - [1 conventions](#1-conventions)
  - [2 status](#2-status)
  - [3 device events](#3-device-events)
  - [4 identity](#4-identity)
  - [5 display power](#5-display-power)
    - [5.1 get /display](#51-get-display)
    - [5.2 post /display](#52-post-display)
  - [6 device details](#6-device-details)
  - [7 errors](#7-errors)

The HTTP and WebSocket interface the bridge offers to the glados-frontend page running in the kiosk.
glados-frontend codes against these shapes, so a change to any of them is a bridge protocol change and
a minor version ([RELEASING.md, section 1](RELEASING.md#1-versioning-policy)).

## 1 conventions

- The bridge listens on `http://localhost:8600`, reachable from the kiosk's Chromium and from the
  device itself, never from the network.
- Field names are snake_case. Datetimes are UTC in ISO 8601. A field the bridge cannot determine on
  this device is `null`, never left out: every field listed here is always present.
- **Origin check:** the identity, display and device routes refuse a request whose `Origin` header
  is not in `BRIDGE__ALLOWED_ORIGINS` with a 403, before the body is looked at. A request without
  `Origin` (curl, a script on the device) is allowed. `/health` and `/devices` only rely on CORS.
- The identity, display and device routes answer with `Cache-Control: no-store`.

## 2 status

`GET /health`:

```json
{"status": "ok", "version": "0.1.0", "devices": [{"name": "rfid", "status": "ready"}]}
```

`GET /devices` answers the `devices` list alone. A device's `status` is `starting`, `ready`, `error`
or `stopped`.

## 3 device events

`GET /ws/events` is a WebSocket that sends every device event as one JSON message:

```json
{"type": "rfid.tag_read", "device": "rfid", "ts": "2026-01-01T12:00:00+00:00", "data": {"tag": "0123456789"}}
```

| `type` | `data` |
| --- | --- |
| `rfid.tag_read` | `{"tag": "<uid>"}` |
| `scanner.read` | `{"code": "<payload>", "symbology": "<name>" \| null}` |
| `device.status` | `{"status": "starting" \| "ready" \| "error" \| "stopped", "detail": "<text>" \| null}` |

A connection with an `Origin` outside `BRIDGE__ALLOWED_ORIGINS` is closed before it is accepted.

## 4 identity

`GET /identity`:

```json
{"public_key": "<raw 32-byte Ed25519 key, base64url without padding>", "api_key": "<IDENTITY__API_KEY>"}
```

`api_key` is `null` when `IDENTITY__API_KEY` is empty.

`POST /identity/sign` with `{"nonce": "<32 to 128 characters of base64url or .>"}` answers
`{"signature": "<64-byte Ed25519 signature, base64url without padding>"}`, made over the bytes
`glados-terminal-auth-v1:` followed by the nonce. Any other nonce gets a 422. 503 when the device has
no usable key.

## 5 display power

Glados decides when a display is off; the page asks the bridge to carry it out. The bridge cuts the
HDMI signal through sway in the kiosk container and, when the display answers on HDMI-CEC, also puts
it into standby and wakes it again, since many TVs stay on showing "no signal" otherwise. Off sends
CEC standby first and then cuts the signal; on restores the signal first and then sends CEC
image-view-on.

The bridge never switches the display by itself. It does not remember a requested state across a
restart of the bridge, and a restarted kiosk container starts with the display on, so the page asks
again after either.

### 5.1 get /display

```json
{
  "power": "on",
  "requested_power": "off",
  "changed_at": "2026-11-03T22:00:00.123456Z",
  "sway_reachable": true,
  "cec_available": true,
  "cec_responding": true,
  "last_error": null
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `power` | `"on"`, `"off"` or `null` | The display power right now, as sway reports it (`on` when any output is powered). While sway cannot be reached, e.g. while the kiosk container restarts, the kernel's power state of the connected displays stands in. `null` when neither knows of a display. |
| `requested_power` | `"on"`, `"off"` or `null` | What the last `POST /display` asked for since the bridge started, `null` before the first. |
| `changed_at` | datetime or `null` | When the last `POST /display` ran. |
| `sway_reachable` | boolean | Whether sway answered on this request. `false` means `POST /display` would fail. |
| `cec_available` | boolean | A CEC adapter (`/dev/cec*`) and `cec-ctl` exist. Says nothing about whether the display supports CEC. |
| `cec_responding` | boolean or `null` | Whether a display answered on CEC at the last `POST /display`. `null` before the first, or when the device has no CEC adapter. |
| `last_error` | string or `null` | What went wrong at the last `POST /display`, from sway or CEC, `null` when it fully worked. A display that does not answer on CEC is not an error. |

### 5.2 post /display

Request:

```json
{"power": "off"}
```

`power` is `"on"` or `"off"`; anything else gets a 422. The answer is the display state after the
change, in the shape of `GET /display`, with status 200.

When sway cannot switch the display (the kiosk is not running, or sway refused), the answer is a 503
with `{"detail": "Could not switch the display off: <reason>"}`. CEC was still tried, and
`GET /display` keeps the reason in `last_error`. A CEC failure alone keeps the 200 and only shows in
`last_error`.

## 6 device details

`GET /device` describes the device for the terminal list in Glados. The computer's model, serial,
memory, kernel and architecture and the host's OS and hostname are read once when the bridge starts;
temperature, under-voltage, uptime, the connectors and the display state on every request.

```json
{
  "computer": {
    "model": "Raspberry Pi 4 Model B Rev 1.5",
    "serial": "1000000012345678",
    "memory_total_bytes": 3927805952,
    "memory_installed_bytes": 4294967296,
    "kernel": "6.18.50+rpt-rpi-v8",
    "architecture": "aarch64",
    "cpu_temperature_celsius": 49.2,
    "under_voltage": false,
    "uptime_seconds": 20392
  },
  "host": {
    "hostname": "kiosk-01",
    "os_name": "Debian GNU/Linux 13 (trixie)",
    "os_id": "debian",
    "os_version_id": "13"
  },
  "connectors": [
    {
      "connector": "HDMI-A-1",
      "connected": true,
      "enabled": true,
      "dpms": "on",
      "edid": {
        "manufacturer_id": "SAM",
        "make": "Samsung",
        "model": "S27D390",
        "product_code": 2919,
        "serial": "12345678",
        "manufacture_year": 2015,
        "native_width": 1920,
        "native_height": 1080,
        "native_refresh_hz": 60.0,
        "width_mm": 598,
        "height_mm": 336
      }
    },
    {
      "connector": "HDMI-A-2",
      "connected": false,
      "enabled": false,
      "dpms": null,
      "edid": null
    }
  ],
  "display": {
    "power": "on",
    "requested_power": null,
    "changed_at": null,
    "sway_reachable": true,
    "cec_available": true,
    "cec_responding": null,
    "last_error": null
  }
}
```

`computer`:

| Field | Type | Source and meaning |
| --- | --- | --- |
| `model` | string or `null` | `/proc/device-tree/model`; on a board without a device tree, the DMI vendor and product name. |
| `serial` | string or `null` | `/proc/device-tree/serial-number`, else the DMI product serial. |
| `memory_total_bytes` | integer or `null` | `MemTotal` from `/proc/meminfo`: what the kernel can use, a little less than what is installed. |
| `memory_installed_bytes` | integer or `null` | The installed RAM from a Raspberry Pi's revision code, `null` on other boards. |
| `kernel` | string or `null` | The running kernel release. |
| `architecture` | string | The kernel's machine name, e.g. `aarch64`. |
| `cpu_temperature_celsius` | number or `null` | The CPU's thermal zone, one decimal. |
| `under_voltage` | boolean or `null` | The Raspberry Pi firmware's under-voltage alarm (`rpi_volt` under `/sys/class/hwmon`), `true` while the supply is too low. `null` where the kernel does not expose it. The firmware's throttling flags are not exposed to the kernel on these boards and are not reported. |
| `uptime_seconds` | integer or `null` | Seconds since the device booted. |

`host` comes from the host's `/etc/os-release` and `/etc/hostname`, which `docker-compose.yml` mounts
read-only into the bridge container. All four fields are `null` when those files are not mounted;
the container's own files describe the bridge image, not the device, and are never used instead.
`os_name` is `PRETTY_NAME` (else `NAME`), `os_id` is `ID`, `os_version_id` is `VERSION_ID`.

`connectors` lists every display connector of the device's graphics cards (`/sys/class/drm`), in
name order, writeback connectors left out. `connector` is the name sway uses as well. `connected` is
`true` only when the kernel sees a display. `enabled` is whether the connector is driving a picture
(`null` if unknown). `dpms` is the kernel's power state of a connected display, `null` for an empty
port.

`edid` is what the display reports about itself, `null` when the port is empty or the data is not
valid. Only the 128-byte base block is read:

| Field | Type | Meaning |
| --- | --- | --- |
| `manufacturer_id` | string or `null` | The three-letter Plug and Play ID, e.g. `SAM`. |
| `make` | string or `null` | The maker's name for well-known IDs, e.g. `Samsung`, else the ID itself. |
| `model` | string or `null` | The display's name descriptor, e.g. `S27D390`. |
| `product_code` | integer | The maker's product code. |
| `serial` | string or `null` | The serial number descriptor, else the numeric serial in decimal, `null` when neither is set. |
| `manufacture_year` | integer or `null` | The year of manufacture (or model year). |
| `native_width`, `native_height` | integer or `null` | The preferred mode in pixels. A TV that lists its 4K mode only in an extension block reports the base block's preferred mode. |
| `native_refresh_hz` | number or `null` | The preferred mode's refresh rate, two decimals. |
| `width_mm`, `height_mm` | integer or `null` | The visible picture size. |

`display` is the display power state, exactly as `GET /display` answers it.

## 7 errors

| Status | When |
| --- | --- |
| 403 | `Origin` present and not in `BRIDGE__ALLOWED_ORIGINS` (identity, display and device routes). |
| 422 | The request body does not match (`POST /identity/sign`, `POST /display`). |
| 503 | The part behind the route is not available: no usable device key (identity routes), sway could not switch the display (`POST /display`), or the bridge was started without display control or device details. |

Error bodies are FastAPI's `{"detail": "<text>"}`. The page must keep working when the bridge is
absent or answers with an error: a display that cannot be switched stays as it is.
