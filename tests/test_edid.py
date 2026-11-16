"""
tests/test_edid.py

Coverage for the EDID parser (src/host/edid.py). SAMSUNG_S27D390 is the
EDID a Samsung S27D390 monitor reported on a Raspberry Pi 4, read from
/sys/class/drm/card1-HDMI-A-1/edid: the base block plus one CTA-861
extension block. Its numeric serial is replaced with 12345678 and the base
block's checksum adjusted to match.
"""

from src.host.edid import parse_edid

SAMSUNG_S27D390 = bytes.fromhex(
    "00ffffffffffff004c2d670b4e61bc0006190103803c22782a9791a556549d250e5054bfef80714f81c08100"
    "81809500a9c0b3000101023a801871382d40582c450056502100001e011d007251d01e206e28550056502100"
    "001e000000fd00324b1e5111000a202020202020000000fc00533237443339300a2020202020016002031af1"
    "4690041f130312230907078301000066030c00100080011d00bc52d01e20b828554056502100001e8c0ad090"
    "204031200c4055005650210000188c0ad08a20e02d10103e9600565021000018000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000061"
)


def _with_checksum(block: bytearray) -> bytes:
    block[127] = (-sum(block[:127])) % 256
    return bytes(block)


def test_parses_a_real_samsung_monitor() -> None:
    assert len(SAMSUNG_S27D390) == 256

    info = parse_edid(SAMSUNG_S27D390)

    assert info is not None
    assert info.manufacturer_id == "SAM"
    assert info.make == "Samsung"
    assert info.model == "S27D390"
    assert info.product_code == 2919
    # No serial string descriptor, so the numeric serial number stands in.
    assert info.serial == "12345678"
    assert info.manufacture_year == 2015
    assert (info.native_width, info.native_height) == (1920, 1080)
    assert info.native_refresh_hz == 60.0
    # The preferred timing's millimetres agree with the 60 x 34 cm of the
    # base block, so the more precise value wins.
    assert (info.width_mm, info.height_mm) == (598, 336)


def test_only_the_base_block_is_needed() -> None:
    assert parse_edid(SAMSUNG_S27D390[:128]) == parse_edid(SAMSUNG_S27D390)


def test_a_serial_string_descriptor_wins_over_the_numeric_serial() -> None:
    block = bytearray(SAMSUNG_S27D390[:128])
    # Turn the range limits descriptor at offset 90 into a serial string.
    block[90:108] = bytes([0, 0, 0, 0xFF, 0]) + b"H4ZH100123\n  "
    info = parse_edid(_with_checksum(block))

    assert info is not None
    assert info.serial == "H4ZH100123"
    assert info.model == "S27D390"


def test_an_unknown_maker_keeps_its_id() -> None:
    block = bytearray(SAMSUNG_S27D390[:128])
    # "XYZ": X=24, Y=25, Z=26 packed into five bits each.
    value = (24 << 10) | (25 << 5) | 26
    block[8:10] = value.to_bytes(2, "big")
    info = parse_edid(_with_checksum(block))

    assert info is not None
    assert info.manufacturer_id == "XYZ"
    assert info.make == "XYZ"


def test_an_aspect_ratio_in_the_millimetre_fields_falls_back_to_centimetres() -> None:
    block = bytearray(SAMSUNG_S27D390[:128])
    # 16 x 9 "millimetres" in the preferred timing, as some TVs report.
    block[54 + 12], block[54 + 13], block[54 + 14] = 16, 9, 0
    info = parse_edid(_with_checksum(block))

    assert info is not None
    assert (info.width_mm, info.height_mm) == (600, 340)


def test_no_size_at_all_is_unknown() -> None:
    block = bytearray(SAMSUNG_S27D390[:128])
    block[21], block[22] = 0, 0
    block[54 + 12], block[54 + 13], block[54 + 14] = 0, 0, 0
    info = parse_edid(_with_checksum(block))

    assert info is not None
    assert (info.width_mm, info.height_mm) == (None, None)


def test_invalid_data_is_none() -> None:
    assert parse_edid(b"") is None
    assert parse_edid(SAMSUNG_S27D390[:100]) is None
    assert parse_edid(b"\x01" + SAMSUNG_S27D390[1:]) is None

    corrupted = bytearray(SAMSUNG_S27D390)
    corrupted[20] ^= 0xFF
    assert parse_edid(bytes(corrupted)) is None
