"""
src/const.py

App-wide constants. VERSION is read from [project].version in
pyproject.toml so the version reported by GET /health
always matches the packaged version, whether run via Poetry or from the
Docker image (pyproject.toml is COPY'd into the image alongside src/, see
docker/bridge.Dockerfile).
"""

import tomllib
from pathlib import Path


def _load_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    return str(data["project"]["version"])


VERSION: str = _load_version()
NAME = "glados-terminal"
