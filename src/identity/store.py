"""
src/identity/store.py

This device's identity for glados-backend: an Ed25519 key pair, generated
once on first use and kept in the state directory, plus the API key
provisioned in the environment. The glados-frontend page running in the
kiosk reads the public key and the API key through GET /identity and has
the bridge sign the backend's sign-in challenge through
POST /identity/sign. The private key never leaves this process.

The store only keeps the key and signs with it. It never checks a
credential and never decides anything from one; glados-backend alone
decides whether this device is known, approved and allowed to see
anything. Keeping the key here, not in the browser, means the device
keeps its identity when the kiosk container is rebuilt or Chromium's
profile is wiped. Only removing the state directory (the Docker volume)
gives it a new one.

Every signature covers SIGNATURE_DOMAIN followed by the nonce, so a
signature made for the device sign-in can never be passed off as a
signature over anything else this key might sign in the future.
"""

import base64
import os
import threading
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.infrastructure.logging.logger import log

KEY_FILE_NAME = "device_key.pem"
SIGNATURE_DOMAIN = b"glados-terminal-auth-v1:"


class IdentityError(Exception):
    """The device key could not be read or created."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class IdentityStore:
    def __init__(self, state_dir: Path, api_key: str | None) -> None:
        self._key_path = state_dir / KEY_FILE_NAME
        self._api_key = api_key or None
        self._key: Ed25519PrivateKey | None = None
        # FastAPI runs the sync identity routes in a thread pool, so two
        # first requests could otherwise both create a key and hand out
        # different public keys.
        self._lock = threading.Lock()

    @property
    def api_key(self) -> str | None:
        return self._api_key

    def public_key(self) -> str:
        """The raw 32-byte Ed25519 public key, base64url without padding."""
        raw = (
            self._private_key()
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        return _b64url(raw)

    def sign(self, nonce: str) -> str:
        """Signs SIGNATURE_DOMAIN plus the ASCII nonce and returns the
        64-byte signature, base64url without padding. The caller makes
        sure the nonce is ASCII."""
        signature = self._private_key().sign(SIGNATURE_DOMAIN + nonce.encode("ascii"))
        return _b64url(signature)

    def _private_key(self) -> Ed25519PrivateKey:
        """Loads the key, creating it on first use. Retried on every call
        until it succeeds, so a state directory that only becomes
        writable after startup still works without a restart."""
        with self._lock:
            if self._key is None:
                self._key = self._load_or_create()
            return self._key

    def _load_or_create(self) -> Ed25519PrivateKey:
        try:
            if self._key_path.exists():
                return self._read()
            return self._create()
        except OSError as e:
            raise IdentityError(f"Cannot access {self._key_path}: {e}") from e

    def _read(self) -> Ed25519PrivateKey:
        """Never regenerates over a file that exists but cannot be used:
        that would silently turn an approved device into an unknown one,
        so it is an error for a human to resolve."""
        data = self._key_path.read_bytes()
        hint = "Delete it to give this device a new identity."
        try:
            key = serialization.load_pem_private_key(data, password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm) as e:
            raise IdentityError(f"{self._key_path} is not a usable private key. {hint}") from e
        if not isinstance(key, Ed25519PrivateKey):
            raise IdentityError(f"{self._key_path} is not an Ed25519 private key. {hint}")
        return key

    def _create(self) -> Ed25519PrivateKey:
        """Writes to a temporary file first and renames it into place, so a
        crash halfway through never leaves a truncated key file behind."""
        self._key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        tmp_path = self._key_path.with_suffix(".tmp")
        # A temporary file left over from a crash may carry other
        # permissions, and O_CREAT would keep them, so start fresh.
        tmp_path.unlink(missing_ok=True)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._key_path)
        log.info("Created a new device key at %s.", self._key_path)
        return key
