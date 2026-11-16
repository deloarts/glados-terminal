"""
src/host/sysfs.py

Small readers for the kernel's pseudo files under /proc and /sys. Any of
them can be missing on a given board or kernel, so a file that cannot be
read yields None and the field it feeds is reported as unknown.
"""

from pathlib import Path


def read_text(path: Path) -> str | None:
    """The file's content without surrounding whitespace and without the
    NUL terminator device-tree strings carry."""
    try:
        return path.read_text(errors="replace").strip().strip("\0").strip() or None
    except OSError:
        return None


def read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def drm_connectors(drm_dir: Path) -> list[Path]:
    """The display connectors of every card (card1-HDMI-A-1 and so on),
    without writeback connectors, which have no display behind them."""
    try:
        entries = sorted(drm_dir.glob("card*-*"))
    except OSError:
        return []
    return [p for p in entries if "-Writeback-" not in p.name]


def connector_name(path: Path) -> str:
    """card1-HDMI-A-1 becomes HDMI-A-1, the name sway uses as well."""
    return path.name.split("-", 1)[1]
