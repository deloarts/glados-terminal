# installation

- [installation](#installation)
  - [1 support policy](#1-support-policy)
  - [2 requirements](#2-requirements)
  - [3 flash and prepare dietpi](#3-flash-and-prepare-dietpi)
  - [4 install docker](#4-install-docker)
  - [5 get this repo onto the device](#5-get-this-repo-onto-the-device)
  - [6 configure the environment](#6-configure-the-environment)
  - [7 pull and start](#7-pull-and-start)
  - [8 device paths (rfid / scanner)](#8-device-paths-rfid--scanner)
  - [9 infoscreen setup](#9-infoscreen-setup)
  - [10 harden the device](#10-harden-the-device)
  - [11 upgrade](#11-upgrade)
  - [12 uninstall](#12-uninstall)
  - [13 install with portainer](#13-install-with-portainer)
  - [14 non-docker alternative (not recommended)](#14-non-docker-alternative-not-recommended)

This document does not cover the local development loop, see [DEVELOPMENT.md](DEVELOPMENT.md).

## 1 support policy

The supported deployment is [DietPi](https://dietpi.com/) on a single-board computer (a Raspberry
Pi 4/5 or similar) running this repo's `docker-compose.yml`: one container for the hardware bridge,
one for the Chromium kiosk display. Both images are built by CI for `linux/arm64` with every release
and pulled from GHCR, see [section 7](#7-pull-and-start) and [RELEASING.md](RELEASING.md). The device
never builds them itself. Instead of running `docker compose` on the device, Portainer can deploy the same
`docker-compose.yml` as a stack, see [section 13](#13-install-with-portainer).

## 2 requirements

- A DietPi-supported SBC with a GPU capable of DRM/KMS (Raspberry Pi 4/5 recommended). DietPi's
  Raspberry Pi image ships with the KMS display driver off, [section 3](#display-driver) turns it
  on.
- A **headless** DietPi install — no desktop/X session running on the host. The `kiosk` container
  takes the display directly via DRM/KMS; a host desktop session would fight it for the same
  device.
- Network reachability from the device to wherever `glados-frontend` is served (the `KIOSK_URL`
  you'll set in [section 6](#6-configure-the-environment)).
- The RFID reader and/or barcode scanner physically attached, if this terminal uses them.
- A Glados server running Glados 0.1.x.

## 3 flash and prepare dietpi

Flash a DietPi image ([dietpi.com](https://dietpi.com/)) to the device's storage, boot it, and run
through the first-boot `dietpi-software`/`dietpi-config` setup as usual. Confirm networking is up
and SSH in:

```bash
ssh root@<device-ip>
```

### display driver

The `kiosk` container drives the display through the kernel's DRM/KMS driver, which shows up as
`/dev/dri`. DietPi's Raspberry Pi image ships without it: the `vc4-kms-v3d` overlay is commented out
in `config.txt`, and the GPU gets 16 MB of memory, which makes the firmware load its cut-down
variant. Without `/dev/dri`, starting the kiosk fails with `error gathering device information while
adding custom device "/dev/dri": no such file or directory`.

Turn the driver on and reboot. Older DietPi images keep the file at `/boot/config.txt` instead of
`/boot/firmware/config.txt`:

```bash
cp /boot/firmware/config.txt /boot/firmware/config.txt.bak
sed -i 's/^#dtoverlay=vc4-kms-v3d,noaudio$/dtoverlay=vc4-kms-v3d,noaudio/' /boot/firmware/config.txt
echo 'max_framebuffers=2' >> /boot/firmware/config.txt
sed -i -E 's/^gpu_mem_(256|512|1024)=16$/gpu_mem_\1=128/' /boot/firmware/config.txt
grep -nE '^(dtoverlay|max_framebuffers|gpu_mem)' /boot/firmware/config.txt
reboot
```

The `grep` must show `dtoverlay=vc4-kms-v3d,noaudio` uncommented; if it doesn't, the line in this
image differs, add it under `[all]` by hand. `noaudio` turns off sound over HDMI, which a kiosk
doesn't need. After the reboot, check that the driver is there:

```bash
ls -l /dev/dri   # card0 or card1, and renderD128
```

## 4 install docker

DietPi ships Docker Engine + the Compose plugin as a single `dietpi-software` entry. Exact menu
wording and IDs vary across DietPi releases — verify against the version installed:

```bash
dietpi-software
# search for "Docker Compose" (or "Docker") in the software list, select it, then Install
```

Confirm both are present:

```bash
docker --version
docker compose version
```

> [!NOTE]
> The compose file needs Docker Compose 2.24 or newer, for its optional `env_file` entries; nothing
> else in it is exotic. If `dietpi-software`'s bundled Docker version is older, fall back to
> [Docker's official install instructions](https://docs.docker.com/engine/install/debian/) for
> Debian/Raspberry Pi OS, which DietPi is based on.

## 5 get this repo onto the device

The device needs the repo for `docker-compose.yml`, `.env.example` and the kiosk's seccomp profile
(`docker/kiosk-seccomp.json`), not for the code. Check out the release to install, here `v0.1.0`:

```bash
mkdir -p /opt/glados-terminal
git clone https://github.com/deloarts/glados-terminal.git /opt/glados-terminal
cd /opt/glados-terminal
git checkout v0.1.0
```

`docker-compose.yml` at a release tag pulls the images of that release, so the checked-out tag is
the one setting that decides what runs.

If the GHCR packages are private (see [RELEASING.md, section 5](RELEASING.md#5-github-setup)), log in
once with a GitHub token that has only the `read:packages` scope:

```bash
docker login ghcr.io -u <github-user>
# paste the token as the password
```

Docker keeps it in `/root/.docker/config.json`. With public packages, skip this.

## 6 configure the environment

```bash
cp .env.example .env
nano .env
```

| Variable                | Purpose                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `DEBUG`                 | Must be `false` — `true` mounts `POST /debug/simulate`, never enable it on a real device      |
| `LOG_LEVEL`              | Minimum level written to stdout: `DEBUG`, `INFO`, `WARNING`, or `ERROR`                       |
| `LOG_FORMAT`             | `text` (human-readable) or `json` (one object per line, for a log aggregator)                 |
| `BRIDGE__PORT`           | Port the bridge listens on inside its container (default `8600`); `BRIDGE__HOST` is set by `docker-compose.yml`, not `.env` |
| `KIOSK_URL`              | The `glados-frontend` URL this device displays, e.g. `https://glados.example.com`. Required.  |
| `KIOSK_EXTRA_FLAGS`      | Optional extra Chromium flags for hardware-specific quirks; leave unset unless needed          |
| `KIOSK_CA_CERT`          | Optional internal CA certificate for the Glados server's certificate, see [internal certificate authority](#internal-certificate-authority) |
| `KIOSK_OUTPUT_MODE`      | Optional display resolution, e.g. `1920x1080` or `1920x1080@60Hz`, see [display settings](#display-settings) |
| `KIOSK_OUTPUT_TRANSFORM` | Optional rotation: `normal`, `90`, `180` or `270` (clockwise), see [display settings](#display-settings) |
| `KIOSK_OUTPUT_SCALE`     | Optional UI scale as a whole number, e.g. `1` or `2`, see [display settings](#display-settings) |
| `RFID__ENABLED`          | `true` to enable the evdev RFID reader driver                                                 |
| `RFID__DEVICE_PATH`      | `/dev/input/by-id/...` path for the reader, see [section 8](#8-device-paths-rfid--scanner)    |
| `SCANNER__ENABLED`       | `true` to enable the serial barcode/QR scanner driver                                         |
| `SCANNER__DEVICE_PATH`   | `/dev/serial/by-id/...` path for the scanner, see [section 8](#8-device-paths-rfid--scanner)  |
| `SCANNER__BAUD_RATE`     | Serial baud rate for the scanner (default `9600`)                                             |
| `MOCK__ENABLED`          | Must be `false` on a real device — it's a fake device with no hardware behind it              |
| `BRIDGE__ALLOWED_ORIGINS` | The origin of `KIOSK_URL` (scheme, host and optional port, no path or trailing slash), e.g. `https://glados.example.com`. Comma-separated if there are several |
| `IDENTITY__API_KEY`      | The terminal key for an infoscreen, see [section 9](#9-infoscreen-setup). Empty on a plain RFID or scanner terminal |
| `TERMINAL_VERSION`       | Leave unset: the images then match the checked-out tag. Only a test kiosk sets it, to `staging` or `release-candidate`, see [RELEASING.md, section 3](RELEASING.md#3-test-channels-staging-and-release-candidate) |

## 7 pull and start

```bash
docker compose pull
docker compose up -d
```

Verify:

```bash
docker compose ps
curl http://127.0.0.1:8600/health
curl http://127.0.0.1:8600/devices
```

The attached display should show the kiosk container's Chromium window pointed at `KIOSK_URL`. Tail
logs if it doesn't:

```bash
docker compose logs -f bridge
docker compose logs -f kiosk
```

### display settings

Without any settings the kiosk uses the display's preferred resolution, unrotated, at scale 1. To
change that, set these in `.env` and run `docker compose up -d kiosk`. They apply to every connected
display:

```bash
KIOSK_OUTPUT_MODE=1920x1080@60Hz   # resolution, the refresh rate is optional
KIOSK_OUTPUT_TRANSFORM=90          # normal, 90, 180 or 270, clockwise
KIOSK_OUTPUT_SCALE=2               # whole numbers only, see below
```

- **Mode:** must be one the display offers. To see the list, check
  `docker compose exec -u kiosk kiosk sh -c 'SWAYSOCK=$(ls /run/user/*/sway-ipc.*.sock) swaymsg -t get_outputs'`.
  For an unknown mode, sway falls back to the preferred one.
- **Rotation:** a touchscreen is rotated with the picture.
- **Scale:** use `KIOSK_OUTPUT_SCALE` for whole numbers only. The kiosk also accepts a fraction such as `1.5`, but sway then renders the page at another size and scales the picture, which blurs it. For any scale that is not a whole number, larger or smaller than 1 (e.g. `1.25` or `0.75`), leave `KIOSK_OUTPUT_SCALE` unset, so the output stays at scale 1, and let Chromium scale the page instead:

  ```bash
  KIOSK_EXTRA_FLAGS=--force-device-scale-factor=0.75
  ```

  The page stays sharp that way.

An invalid value stops the kiosk container with a message in `docker compose logs kiosk`.

### internal certificate authority

The kiosk's Chromium trusts the same public certificate authorities as any browser. If the Glados
server's certificate comes from an internal CA instead, or is self-signed, the display shows a
privacy error for `KIOSK_URL`. Nobody can click past it on a kiosk, and a certificate installed on
the host does not reach Chromium inside the container. Give the kiosk the CA certificate instead:

```bash
openssl x509 -in ca.pem -outform der | base64 -w0
```

Set the output, one long line, as `KIOSK_CA_CERT` in `.env` and run `docker compose up -d kiosk`.
Several CAs go in separated by commas. The log then says
`Trusting 1 extra CA certificate(s) from KIOSK_CA_CERT.`, and `chrome://policy` lists the
`CACertificates` policy. Chromium trusts the CA for every site, in addition to its built-in ones, so
only use a CA you control.

The server's certificate must name the address in `KIOSK_URL`: for e.g. `https://192.0.2.10`, its
Subject Alternative Names must contain `IP:192.0.2.10`; a certificate for a name does not cover
the IP and vice versa.

Never use `KIOSK_EXTRA_FLAGS=--ignore-certificate-errors` on a device in use: it switches off every
certificate check, for every site.

## 8 device paths (rfid / scanner)

Use the `by-id` paths, not `/dev/input/eventN` or `/dev/ttyUSBn` — those can renumber across
reboots or replugging, `by-id` paths don't.

Plug in the RFID reader, then:

```bash
ls -l /dev/input/by-id/
```

Pick the entry for the reader (usually ending in `-event-kbd` for a keyboard-wedge reader) and set
it as `RFID__DEVICE_PATH` in `.env`.

Plug in the scanner, then:

```bash
ls -l /dev/serial/by-id/
```

Set the matching entry as `SCANNER__DEVICE_PATH` in `.env`. Restart the bridge after either change:

```bash
docker compose up -d bridge
```

## 9 infoscreen setup

An infoscreen is a wall display that shows a screen built in Glados, with nobody at the device. It
signs in to Glados with its own key pair, which the bridge generates on first start and keeps in the
`identity` volume (`device_key.pem`). Nobody ever handles that key pair: the private key never
leaves the bridge, and Glados learns the public key when the device registers.

1. In Glados, go to Settings → API keys and click "Create terminal key". The key is shown once, as
   an `IDENTITY__API_KEY=...` line.
2. On the device, set these lines in `.env`:

   ```bash
   KIOSK_URL=https://<glados>/infoscreen
   BRIDGE__ALLOWED_ORIGINS=https://<glados>
   IDENTITY__API_KEY=<the key from step 1>
   ```

   `BRIDGE__ALLOWED_ORIGINS` is exactly the origin of `KIOSK_URL`, without a path or a trailing
   slash.
3. Start it with `docker compose up -d`. The display opens `/infoscreen`, registers and shows
   a pairing code.
4. In Glados, go to Resources → Terminals, approve the device by typing the pairing code shown on
   the display, name it and pick the screen it shows. The display switches within seconds.

The terminal key is only needed for the first registration. Revoking or rotating it in Glados stops
new devices from registering but never cuts off a device that is already approved.

`docker compose down -v` deletes the `identity` volume. The device then generates a new key pair on
the next start, shows up in Glados as a new device and has to be approved again. A plain
`docker compose down` or an upgrade keeps the identity.

A normal RFID or scanner terminal does not register with Glados this way: leave `IDENTITY__API_KEY`
empty there.

### display power

Glados can switch an infoscreen's display off at night, on weekends and on holidays, and back on.
Glados decides, the page in the kiosk asks the bridge, and the bridge carries it out: it cuts the
HDMI signal through sway and, when the display answers on HDMI-CEC, also puts it into standby and
wakes it again. Many TVs stay on showing "no signal" without the CEC part; most monitors without CEC
go to sleep on a missing signal by themselves.

Nothing needs setting up. `docker-compose.yml` shares the kiosk's runtime directory, where sway keeps
its control socket, with the bridge through the `kiosk-runtime` volume (in memory, empty at every
start), and the bridge image ships `cec-ctl`. The bridge reaches the CEC adapters (`/dev/cec0` and
`/dev/cec1` on a Raspberry Pi, one per HDMI port) through its `/dev` mount.

CEC has to be enabled on the TV, where it often has a brand name (Anynet+ at Samsung, SimpLink at
LG, Bravia Sync at Sony). Check it on the device, with the display showing the infoscreen:

```bash
curl http://127.0.0.1:8600/display
curl -X POST http://127.0.0.1:8600/display -H 'content-type: application/json' -d '{"power": "off"}'
curl -X POST http://127.0.0.1:8600/display -H 'content-type: application/json' -d '{"power": "on"}'
```

After `off` the display must go dark or into standby, after `on` it must show the infoscreen again.
In the answer, `cec_responding` says whether the display answered on CEC, and `last_error` shows what
failed. A 503 means sway could not be reached: check that the kiosk container runs.

### device details

The bridge reports the device for the terminal list in Glados: the computer's model, serial, memory,
temperature, under-voltage alarm and uptime, the host's OS and hostname, and the display's make,
model, serial, resolution and size (from its EDID). The host's `/etc/os-release` and `/etc/hostname`
are mounted read-only into the bridge container for this; a host without either file fails to start
the bridge. See them on the device with:

```bash
curl http://127.0.0.1:8600/device
```

Every field and its source is described in [BRIDGE_API.md, section 6](BRIDGE_API.md#6-device-details).
The bridge reports no IP or MAC address and no Docker version; Glados records the device's address
itself, and Portainer shows the Docker version.

## 10 harden the device

The device holds its private key and, for an infoscreen, a terminal key. Keep it a single-purpose
appliance:

- **SSH keys only.** Put your public key into `/root/.ssh/authorized_keys`, check that you can log
  in with it, then turn off password logins. DietPi's default SSH server is Dropbear: set
  `DROPBEAR_EXTRA_ARGS="-s -g"` in `/etc/default/dropbear` and run `systemctl restart dropbear`. With
  OpenSSH, set `PasswordAuthentication no` in `/etc/ssh/sshd_config` and run
  `systemctl restart ssh`.
- **Unattended security upgrades** for the host:

  ```bash
  apt install unattended-upgrades
  dpkg-reconfigure -plow unattended-upgrades
  ```

  These do not reach the containers. Chromium inside the `kiosk` image only gets updates with a new
  release, whose kiosk image is built with the Chromium Debian ships that day
  ([RELEASING.md, section 4](RELEASING.md#4-images)), so keep the device on the latest release.
- **Nothing else running.** Install only Docker and SSH through `dietpi-software`, no desktop, no
  web server, no file shares. With [Portainer](#13-install-with-portainer), the Edge Agent or a
  Portainer published to `127.0.0.1` is the only addition. The bridge port is published to
  `127.0.0.1` only and must stay that way.
- **`.env` readable by root only**, since it holds the terminal key:

  ```bash
  chown root:root /opt/glados-terminal/.env
  chmod 600 /opt/glados-terminal/.env
  ```

  A Portainer stack has no `.env` on the device. Portainer keeps the variables instead, and every
  Portainer administrator can read them.

### physical security

A kiosk stands where anyone can walk up to it. This setup keeps the local console logins, on the
display's first virtual terminal and on the serial console of the GPIO header, so a device can still
be recovered on site, and it leaves the SD card unencrypted. Both are only acceptable when nobody
can get at the device itself:

- **A locked case, fixed in place.** Mount the case to the wall or the machine with security
  screws or a lock. A case that can be carried away still hands over the SD card, and with it the
  device key, the Wi-Fi password and the Portainer Edge key.
- **Every port covered:** USB, Ethernet, the GPIO header and the SD card slot. The kiosk draws over
  the console but does not take it over, so a keyboard plugged into a USB port types into a root
  login prompt hidden behind the screen. An open Ethernet port lets a laptop reach SSH directly,
  bypassing whatever protects the Wi-Fi network.
- **No loose cables leaving the case.** The RFID reader, the scanner and a touchscreen connect over
  USB, so their cables are USB ports as well: unplug one, and a keyboard fits in its place. Keep the
  reader inside the case or behind a panel, or use cables that cannot be pulled out. An infoscreen
  only needs its HDMI cable.
- **Wi-Fi and heat.** A metal case blocks much of the Wi-Fi signal, and a Raspberry Pi 4 has no
  connector for an external antenna: in a metal case, connect the device over Ethernet, or use a
  lockable plastic case instead. A closed Raspberry Pi 4 throttles at around 80 °C unless the case
  works as its heat sink. After closing the case, watch `cpu_temperature_celsius` and
  `under_voltage` in `GET /device` ([BRIDGE_API.md](BRIDGE_API.md)) through a normal working day.
- **A long, unique root password per device**, kept in your password manager. It is what the
  console logins rely on. Every failed login costs 3 seconds, so a strong password cannot be
  guessed from a keyboard.

Inside a case too, turn off the keyboard shortcuts that reboot the device or kill the kiosk without
a login: the kernel's SysRq combinations and Ctrl+Alt+Del. Masking `ctrl-alt-del.target` alone is
not enough, systemd still forces a reboot when Ctrl+Alt+Del is pressed 7 times within 2 seconds;
the drop-in turns that off as well:

```bash
echo 'kernel.sysrq = 0' > /etc/sysctl.d/90-glados-terminal.conf
sysctl -p /etc/sysctl.d/90-glados-terminal.conf
systemctl mask ctrl-alt-del.target
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nCtrlAltDelBurstAction=none\n' > /etc/systemd/system.conf.d/90-glados-terminal.conf
systemctl daemon-reexec
```

`sysctl kernel.sysrq` must print `0`, `systemctl is-enabled ctrl-alt-del.target` must print
`masked`, and `systemctl show -p CtrlAltDelBurstAction` must print `CtrlAltDelBurstAction=none`.

If a device goes missing anyway, treat everything on its SD card as known:

1. In Glados, go to Resources → Terminals and delete the device. Revoking it is not enough: a revoked device that signs in again goes back to pending, shows a new pairing code and waits for approval, without any terminal key. A deleted device counts as unknown, and an unknown device can only register again with a valid terminal key.
2. If the device had a terminal key (`IDENTITY__API_KEY`), rotate it: create a new terminal key under Settings → API keys and revoke the old one, so the copy on the card cannot register the missing device or any other. Devices that are already approved keep working, because a known device signs in with its key pair alone; only devices set up later need the new key.
3. With [Portainer](#13-install-with-portainer), remove the device's environment, which makes its
   Edge key worthless.
4. If the device joined a Wi-Fi network with a shared password, change that password, then update
   every other device on that network.

### the kiosk container

> [!WARNING]
> This setup has not been tested on a real device yet. Check it with the steps below on the first
> device you install or upgrade.

The `kiosk` container is not privileged. What it gets and why:

- **Devices:** only `/dev/dri` (display) and `/dev/input` (touchscreen), taken when the container
  starts. A touchscreen plugged in later needs `docker compose restart kiosk`.
- **User:** the entrypoint starts as root, writes the Chromium policy file and starts `seatd`, then
  runs sway and Chromium as the unprivileged `kiosk` user. That user gets the host group IDs of the
  `/dev/dri` nodes, read when the container starts, so no host GIDs are baked into the image.
- **Sandbox:** Chromium runs with its sandbox (no `--no-sandbox`). Its renderers live in their own
  user, PID and network namespaces. Docker's default seccomp profile forbids creating those, so the
  container uses `docker/kiosk-seccomp.json`: Docker's default profile plus `clone` with namespace
  flags and `unshare`, nothing else. `no-new-privileges` is set as well.
- **Local Network Access:** recent Chromium versions ask before a public page may reach a loopback
  address such as the bridge, and nobody is at a wall display to answer. The entrypoint derives the
  origin from `KIOSK_URL` and writes a managed policy to
  `/etc/chromium/policies/managed/glados-terminal.json` that allows exactly that origin
  (`LocalNetworkAccessAllowedForUrls`, plus the older `InsecurePrivateNetworkRequestsAllowedForUrls`).

The host kernel must allow unprivileged user namespaces:

```bash
sysctl user.max_user_namespaces            # must be greater than 0
sysctl kernel.unprivileged_userns_clone    # only exists on Debian kernels; must be 1 if it does
```

Check it on the device after `docker compose up -d`:

```bash
docker compose logs kiosk
docker compose exec kiosk cat /etc/chromium/policies/managed/glados-terminal.json
docker compose exec kiosk sh -c 'for p in /proc/[0-9]*; do echo "$(stat -c %U $p) $(readlink $p/ns/user) $(tr "\0" " " < $p/cmdline | cut -c1-60)"; done'
```

The log must start with `Allowed local network access for <origin>` and must not contain
`No usable sandbox!`. The policy file must name the Glados origin. In the process list, sway and
Chromium run as `kiosk`, and the `--type=renderer` processes show a different `user:[...]`
namespace than the main Chromium process.

To see the same in the browser, plug in a keyboard, add this line to `.env` and run
`docker compose up -d kiosk`. Chromium opens the two pages as extra tabs; switch to them with
Ctrl+Tab:

```bash
KIOSK_EXTRA_FLAGS=chrome://policy chrome://sandbox
```

`chrome://policy` must list both policies with the Glados origin and status OK (a policy this
Chromium version does not know shows as unknown, which is harmless). `chrome://sandbox` must report
the namespace sandbox and the seccomp-BPF sandbox as active. Remove the line from `.env` again and
run `docker compose up -d kiosk`.

If the display stays dark or Chromium reports `No usable sandbox!`, check the host kernel settings above and report what `docker compose logs kiosk` shows, together with the release the device runs.

## 11 upgrade

Check out the new release, here `v0.2.0`, and pull its images:

```bash
cd /opt/glados-terminal
git fetch --tags
git checkout v0.2.0
docker compose pull
docker compose up -d
```

Compose only restarts the containers whose image or configuration changed. Read the release's
CHANGELOG section first: a new `.env` variable shows up there and in `.env.example`. To go back,
check out the previous tag and run the same two `docker compose` commands. The device key pair lives
in the `identity` volume, so an upgrade keeps the device registered in Glados.

Remove images older releases left behind with `docker image prune -a`.

## 12 uninstall

```bash
docker compose down
```

To also remove the device identity, so the device shows up in Glados as a new, unapproved one
the next time it starts:

```bash
docker compose down -v
```

To also remove the pulled images:

```bash
docker compose down --rmi all
```

Then remove the install directory:

```bash
rm -rf /opt/glados-terminal
```

## 13 install with portainer

[Portainer](https://www.portainer.io/) can run this repo's `docker-compose.yml` as a stack named
`glados-terminal`, instead of `git clone`, `.env` and `docker compose` on the device. The images,
containers and volumes are the same as in sections [5](#5-get-this-repo-onto-the-device)–[7](#7-pull-and-start);
only who runs Compose changes. Sections [3](#3-flash-and-prepare-dietpi) and
[4](#4-install-docker) still prepare the device, the variables of [section 6](#6-configure-the-environment)
are entered in Portainer instead of `.env`, and [section 10](#10-harden-the-device) still applies.

There are two setups:

- **Central Portainer with the Edge Agent**, for several kiosks: one Portainer server manages every
  device, and each device runs only the small Edge Agent, which connects out to the server. Nothing
  on the device accepts new incoming connections.
- **Portainer on every device**, for a single kiosk or a few: each device runs its own Portainer,
  reached over an SSH tunnel.

Once the device shows up in Portainer, the stack is deployed the same way in both setups, see
[deploy the stack](#deploy-the-stack).

> [!WARNING]
> Whoever is an administrator in Portainer controls the device completely: Portainer and the Edge
> Agent work through the Docker socket, and the Edge Agent also mounts the host's `/`. Give the
> Portainer server the same care as the devices, with HTTPS, strong passwords and backups.

### central portainer with the edge agent

The Portainer server itself runs on a central host, not on a kiosk; install it there following
[Portainer's documentation](https://docs.portainer.io/start/install-ce). Every kiosk must reach it
on two ports: `9443` (UI and API) and `8000` (the Edge Agent's tunnel). The kiosk itself opens no
port.

For each kiosk:

1. In Portainer, go to **Environments → Add environment**, choose **Docker Standalone**, then
   **Edge Agent Standard**. Name the environment after the kiosk, e.g. `kiosk-hall-1`, and check
   that the Portainer API server URL and the tunnel address are ones the kiosk can reach. Create
   it.
2. Portainer shows a `docker run` command for this one environment, with its own `EDGE_ID` and
   `EDGE_KEY`. It looks like this; copy the real one from Portainer:

   ```bash
   docker run -d --name portainer_edge_agent --restart always \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v /var/lib/docker/volumes:/var/lib/docker/volumes \
     -v /:/host \
     -v portainer_agent_data:/data \
     -e EDGE=1 \
     -e EDGE_ID=<id> \
     -e EDGE_KEY=<key> \
     -e EDGE_INSECURE_POLL=1 \
     portainer/agent:<server version>
   ```

   `EDGE_INSECURE_POLL=1` accepts a self-signed certificate on the server. Leave it out when the
   server has a certificate the kiosk trusts.
3. Run the command on the kiosk over SSH. Within a minute the environment shows as connected in
   Portainer.

Continue with [deploy the stack](#deploy-the-stack) in that environment.

### portainer on every device

Install Portainer CE on the kiosk and publish its UI to `127.0.0.1` only, like the bridge:

```bash
docker volume create portainer_data
docker run -d --name portainer --restart always \
  -p 127.0.0.1:9443:9443 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:lts
```

From your computer, open an SSH tunnel to it and go to `https://localhost:9443`:

```bash
ssh -L 9443:127.0.0.1:9443 root@<device-ip>
```

Create the administrator account right away: for security, Portainer stops after a few minutes
without one, and `docker restart portainer` gives it a new chance. Portainer then shows the device
itself as the environment `local`.

`dietpi-software` also offers Portainer, but it publishes the UI to the whole network. On a kiosk,
use the command above instead.

Continue with [deploy the stack](#deploy-the-stack) in the `local` environment.

### deploy the stack

If the GHCR packages are private (see [RELEASING.md, section 5](RELEASING.md#5-github-setup)), add
the registry once: **Registries → Add registry → Custom registry**, URL `ghcr.io`, with
authentication: your GitHub user and a token that has only the `read:packages` scope.

Then, in the kiosk's environment, go to **Stacks → Add stack**:

1. **Name:** exactly `glados-terminal`. The device key pair lives in the volume
   `glados-terminal_identity`, named after the stack: under another name the device generates a new
   key pair and has to be approved in Glados again.
2. **Build method:** **Repository**. The web editor and the upload do not work: the stack needs
   `docker/kiosk-seccomp.json` from the repository.
   - Repository URL: `https://github.com/deloarts/glados-terminal`
   - Repository reference: the release tag, e.g. `refs/tags/v0.1.0`. As in
     [section 5](#5-get-this-repo-onto-the-device), the tag decides which images run.
   - Compose path: `docker-compose.yml`
   - Authentication: on, with your GitHub user and a fine-grained token that can only read the
     contents of this repository.
   - Automatic updates: off. An upgrade is a deliberate change of the tag, see below.
3. **Environment variables:** switch to **Advanced mode** and paste the variables from
   [section 6](#6-configure-the-environment) as `KEY=VALUE` lines, without comments. Use
   `.env.example` as the template. Portainer writes them to the stack's `stack.env`, which
   `docker-compose.yml` reads.
4. **Deploy the stack.**

Verify as in [section 7](#7-pull-and-start), in Portainer instead of a shell: under **Containers**,
`glados-terminal-bridge-1` and `glados-terminal-kiosk-1` are running, and the display shows
`KIOSK_URL`.

A device that was installed with `docker compose` before keeps its identity when it moves to
Portainer: run `docker compose down` (without `-v`) in `/opt/glados-terminal`, then deploy the stack
under the name `glados-terminal`.

### operate the stack

- **Logs:** **Containers → `glados-terminal-kiosk-1` (or `-bridge-1`) → Logs**. This is the same as
  `docker compose logs`.
- **Device paths** ([section 8](#8-device-paths-rfid--scanner)): the bridge container sees the host's
  `/dev`. Open **Containers → `glados-terminal-bridge-1` → Console**, connect with `/bin/sh`, and run
  `ls -l /dev/input/by-id/` and `ls -l /dev/serial/by-id/` there.
- **Changing a variable**, e.g. a device path or the [display settings](#display-settings): change it
  on the stack's page under **Environment variables** and redeploy.
- **The kiosk checks** from [section 10](#the-kiosk-container): run the `docker compose exec kiosk ...`
  commands in the console of `glados-terminal-kiosk-1` instead.
- **Upgrade** ([section 11](#11-upgrade)): read the release's CHANGELOG section, then on the stack's
  page change the repository reference to the new tag, e.g. `refs/tags/v0.2.0`, and choose
  **Pull and redeploy**. To go back, set the previous tag the same way. Remove old images under
  **Images**.
- **Uninstall** ([section 12](#12-uninstall)): delete the stack. The `glados-terminal_identity`
  volume then remains under **Volumes**: keep it to bring the device back with the same identity,
  delete it to have the device show up in Glados as a new one. The `glados-terminal_kiosk-runtime`
  volume holds nothing worth keeping and can be deleted.

## 14 non-docker alternative (not recommended)

DietPi's own built-in Chromium kiosk autostart (a `dietpi-software` entry, configured via
`dietpi.txt`'s `SOFTWARE_CHROMIUM_AUTOSTART_URL=<glados-frontend URL>`) can display glados-frontend
without this repo's `kiosk` container at all. In that shape, the bridge would run directly via
Poetry (`poetry install --with hardware`) supervised by a hand-written systemd unit instead of
`docker/bridge.Dockerfile`.

This is documented only so the tradeoff is visible — sections [3](#3-flash-and-prepare-dietpi)–[13](#13-install-with-portainer)
(Docker Compose, directly or through Portainer) are the supported, maintained install path; this repo does not ship or maintain a
systemd unit for the bare-metal alternative.
