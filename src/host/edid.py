"""
src/host/edid.py

Parses the base block of a display's EDID, the 128 bytes every HDMI or
DisplayPort display reports about itself, which the kernel exposes as
/sys/class/drm/<connector>/edid. Only what a terminal list needs is read:
who made the display, its model name and serial, when it was built, its
preferred (native) resolution and its physical size. Extension blocks
(CTA-861 and others) are ignored, so a TV that lists its 4K mode only in
an extension reports the preferred mode of its base block.

Display data is untrusted input from whatever is plugged in, so the
parser never raises: a block that is too short, lacks the fixed header
or fails its checksum yields None, and every field it cannot read is
None.
"""

from dataclasses import dataclass

EDID_HEADER = bytes.fromhex("00ffffffffffff00")
BLOCK_SIZE = 128

# Plug and Play IDs of common display makers, so the list shows
# "Samsung" rather than "SAM". An ID missing here is shown as it is.
_VENDOR_NAMES = {
    "ACI": "Asus",
    "ACR": "Acer",
    "AOC": "AOC",
    "AUS": "Asus",
    "BNQ": "BenQ",
    "DEL": "Dell",
    "EIZ": "Eizo",
    "ENC": "Eizo",
    "FUS": "Fujitsu",
    "GSM": "LG",
    "HIQ": "Hyundai",
    "HPN": "HP",
    "HWP": "HP",
    "IVM": "Iiyama",
    "LEN": "Lenovo",
    "LGD": "LG Display",
    "MEI": "Panasonic",
    "MSI": "MSI",
    "NEC": "NEC",
    "PHL": "Philips",
    "SAM": "Samsung",
    "SHP": "Sharp",
    "SNY": "Sony",
    "TCL": "TCL",
    "TSB": "Toshiba",
    "VSC": "ViewSonic",
}


@dataclass(frozen=True)
class EdidInfo:
    manufacturer_id: str | None
    make: str | None
    model: str | None
    product_code: int
    serial: str | None
    manufacture_year: int | None
    native_width: int | None
    native_height: int | None
    native_refresh_hz: float | None
    width_mm: int | None
    height_mm: int | None


@dataclass(frozen=True)
class _Timing:
    width: int
    height: int
    refresh_hz: float | None
    width_mm: int
    height_mm: int


def parse_edid(data: bytes) -> EdidInfo | None:
    """Returns the facts of the base block, or None when `data` is not a
    valid EDID."""
    if len(data) < BLOCK_SIZE or data[:8] != EDID_HEADER:
        return None
    block = data[:BLOCK_SIZE]
    if sum(block) % 256 != 0:
        return None

    manufacturer_id = _manufacturer_id(block[8], block[9])
    names: list[str] = []
    serials: list[str] = []
    timing: _Timing | None = None
    for offset in (54, 72, 90, 108):
        descriptor = block[offset : offset + 18]
        if descriptor[0] or descriptor[1]:
            if timing is None:
                timing = _detailed_timing(descriptor)
        elif descriptor[3] == 0xFC:
            names.append(_descriptor_text(descriptor))
        elif descriptor[3] == 0xFF:
            serials.append(_descriptor_text(descriptor))

    numeric_serial = int.from_bytes(block[12:16], "little")
    serial = next((s for s in serials if s), None)
    if serial is None and numeric_serial:
        serial = str(numeric_serial)

    width_mm, height_mm = _physical_size(block[21], block[22], timing)
    return EdidInfo(
        manufacturer_id=manufacturer_id,
        make=_VENDOR_NAMES.get(manufacturer_id, manufacturer_id) if manufacturer_id else None,
        model="".join(names) or None,
        product_code=int.from_bytes(block[10:12], "little"),
        serial=serial,
        manufacture_year=block[17] + 1990 if block[17] else None,
        native_width=timing.width if timing else None,
        native_height=timing.height if timing else None,
        native_refresh_hz=timing.refresh_hz if timing else None,
        width_mm=width_mm,
        height_mm=height_mm,
    )


def _manufacturer_id(high: int, low: int) -> str | None:
    """Three letters packed into five bits each, "A" being 1."""
    value = (high << 8) | low
    codes = [(value >> 10) & 0x1F, (value >> 5) & 0x1F, value & 0x1F]
    if not all(1 <= code <= 26 for code in codes):
        return None
    return "".join(chr(ord("A") + code - 1) for code in codes)


def _descriptor_text(descriptor: bytes) -> str:
    """Up to 13 characters, ended by a line feed and padded with spaces.
    Anything outside printable ASCII is dropped."""
    raw = descriptor[5:18].split(b"\n", 1)[0]
    return "".join(chr(b) for b in raw if 0x20 <= b < 0x7F).strip()


def _detailed_timing(descriptor: bytes) -> _Timing | None:
    pixel_clock_hz = int.from_bytes(descriptor[0:2], "little") * 10_000
    h_active = descriptor[2] | ((descriptor[4] & 0xF0) << 4)
    h_blank = descriptor[3] | ((descriptor[4] & 0x0F) << 8)
    v_active = descriptor[5] | ((descriptor[7] & 0xF0) << 4)
    v_blank = descriptor[6] | ((descriptor[7] & 0x0F) << 8)
    if not h_active or not v_active:
        return None
    total = (h_active + h_blank) * (v_active + v_blank)
    refresh = round(pixel_clock_hz / total, 2) if total else None
    return _Timing(
        width=h_active,
        height=v_active,
        refresh_hz=refresh,
        width_mm=descriptor[12] | ((descriptor[14] & 0xF0) << 4),
        height_mm=descriptor[13] | ((descriptor[14] & 0x0F) << 8),
    )


def _physical_size(
    width_cm: int, height_cm: int, timing: _Timing | None
) -> tuple[int, int] | tuple[None, None]:
    """The preferred timing gives the size in millimetres, the base block
    in whole centimetres. Some displays put an aspect ratio such as 16 by
    9 into the millimetre fields, so those only win when they agree with
    the centimetres, or are plausible on their own when the centimetres
    are missing."""
    timing_size = (timing.width_mm, timing.height_mm) if timing else (0, 0)
    if width_cm and height_cm:
        base = (width_cm * 10, height_cm * 10)
        if all(t and abs(t - b) <= 10 for t, b in zip(timing_size, base, strict=True)):
            return timing_size
        return base
    if all(t >= 50 for t in timing_size):
        return timing_size
    return None, None
