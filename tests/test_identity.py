"""
tests/test_identity.py

Coverage for the device identity store (src/identity/store.py),
GET /identity and POST /identity/sign (src/api/identity.py). Every test
uses its own tmp_path as the state directory, so nothing touches
/var/lib/glados-terminal.
"""

import base64
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.events.bus import EventBus
from src.identity.store import KEY_FILE_NAME
from src.identity.store import IdentityError
from src.identity.store import IdentityStore
from src.infrastructure.config import cfg

ALLOWED = "https://glados.example.com"
DISALLOWED = "https://evil.example.com"
NONCE = "dGhpcy1pcy1hLXRlc3Qtbm9uY2UtdGhhdC1pcy1sb25nLWVub3VnaA"


def _client(identity: IdentityStore | None) -> TestClient:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    return TestClient(create_app(bus=bus, manager=manager, identity=identity))


def _b64url_decode(value: str) -> bytes:
    assert "=" not in value
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.bridge, "allowed_origins", [ALLOWED])


def test_key_is_created_once_and_kept(tmp_path: Path) -> None:
    first = IdentityStore(state_dir=tmp_path, api_key=None).public_key()
    pem = (tmp_path / KEY_FILE_NAME).read_bytes()
    second = IdentityStore(state_dir=tmp_path, api_key=None).public_key()

    assert first == second
    assert len(_b64url_decode(first)) == 32
    assert (tmp_path / KEY_FILE_NAME).read_bytes() == pem
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")


def test_key_file_and_dir_are_private(tmp_path: Path) -> None:
    IdentityStore(state_dir=tmp_path / "state", api_key=None).public_key()

    assert stat.S_IMODE((tmp_path / "state" / KEY_FILE_NAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "state").stat().st_mode) == 0o700


@pytest.mark.parametrize("content", [b"", b"not a key", b"-----BEGIN PRIVATE KEY-----\nAAAA\n"])
def test_invalid_key_file_is_an_error_not_a_new_identity(tmp_path: Path, content: bytes) -> None:
    (tmp_path / KEY_FILE_NAME).write_bytes(content)

    with pytest.raises(IdentityError):
        IdentityStore(state_dir=tmp_path, api_key=None).public_key()
    assert (tmp_path / KEY_FILE_NAME).read_bytes() == content


def test_signature_verifies_against_the_public_key_with_the_domain_prefix(
    tmp_path: Path,
) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)
    public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(store.public_key()))

    signature = _b64url_decode(store.sign(NONCE))

    assert len(signature) == 64
    public_key.verify(signature, b"glados-terminal-auth-v1:" + NONCE.encode("ascii"))


def test_empty_api_key_means_none(tmp_path: Path) -> None:
    assert IdentityStore(state_dir=tmp_path, api_key="").api_key is None


def test_identity_returns_public_key_and_api_key(tmp_path: Path) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key="gak_test")

    response = _client(store).get("/identity", headers={"Origin": ALLOWED})

    assert response.status_code == 200
    assert response.json() == {"public_key": store.public_key(), "api_key": "gak_test"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_identity_api_key_is_null_when_empty(tmp_path: Path) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key="")

    response = _client(store).get("/identity", headers={"Origin": ALLOWED})

    assert response.status_code == 200
    assert response.json()["api_key"] is None


def test_sign_returns_a_verifiable_signature(tmp_path: Path) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)
    public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(store.public_key()))

    response = _client(store).post(
        "/identity/sign", json={"nonce": NONCE}, headers={"Origin": ALLOWED}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == ALLOWED
    signature = _b64url_decode(response.json()["signature"])
    public_key.verify(signature, b"glados-terminal-auth-v1:" + NONCE.encode("ascii"))


@pytest.mark.parametrize(
    "body",
    [
        {"nonce": "a" * 31},
        {"nonce": "a" * 129},
        {"nonce": "a" * 31 + "="},
        {"nonce": "a" * 31 + "+"},
        {"nonce": "a" * 31 + "/"},
        {"nonce": "a" * 32 + "\n"},
        {"nonce": "a" * 31 + "ä"},
        {"nonce": 12345678901234567890123456789012345},
        {},
    ],
)
def test_sign_rejects_a_bad_nonce(tmp_path: Path, body: dict[str, object]) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)

    response = _client(store).post("/identity/sign", json=body, headers={"Origin": ALLOWED})

    assert response.status_code == 422


def test_sign_accepts_the_backends_dotted_challenge(tmp_path: Path) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)
    public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(store.public_key()))
    # A made-up challenge in the backend's shape: version, Unix timestamp,
    # random part and MAC, joined by dots, each part as long as the real one.
    nonce = "v1.1767225600.exampleRandomPart0123456.notARealSignature-onlyTheShapeMatters_00000"

    response = _client(store).post(
        "/identity/sign", json={"nonce": nonce}, headers={"Origin": ALLOWED}
    )

    assert response.status_code == 200
    signature = _b64url_decode(response.json()["signature"])
    public_key.verify(signature, b"glados-terminal-auth-v1:" + nonce.encode("ascii"))


@pytest.mark.parametrize("length", [32, 128])
def test_sign_accepts_the_length_bounds(tmp_path: Path, length: int) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)

    response = _client(store).post(
        "/identity/sign", json={"nonce": "A-_9" * (length // 4)}, headers={"Origin": ALLOWED}
    )

    assert response.status_code == 200


def test_identity_refuses_a_disallowed_origin(tmp_path: Path) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key="gak_test")

    response = _client(store).get("/identity", headers={"Origin": DISALLOWED})

    assert response.status_code == 403
    assert "gak_test" not in response.text
    assert not (tmp_path / KEY_FILE_NAME).exists()


@pytest.mark.parametrize("body", [{"nonce": NONCE}, {"nonce": "bad"}])
def test_sign_refuses_a_disallowed_origin(tmp_path: Path, body: dict[str, object]) -> None:
    store = IdentityStore(state_dir=tmp_path, api_key=None)

    response = _client(store).post("/identity/sign", json=body, headers={"Origin": DISALLOWED})

    assert response.status_code == 403
    assert "signature" not in response.text


def test_missing_origin_is_allowed_on_both_routes(tmp_path: Path) -> None:
    client = _client(IdentityStore(state_dir=tmp_path, api_key=None))

    assert client.get("/identity").status_code == 200
    assert client.post("/identity/sign", json={"nonce": NONCE}).status_code == 200


def test_both_routes_answer_503_without_a_store() -> None:
    client = _client(None)

    assert client.get("/identity", headers={"Origin": ALLOWED}).status_code == 503
    response = client.post("/identity/sign", json={"nonce": NONCE}, headers={"Origin": ALLOWED})
    assert response.status_code == 503


def test_both_routes_answer_503_when_the_state_dir_is_unusable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    client = _client(IdentityStore(state_dir=blocker, api_key=None))

    assert client.get("/identity", headers={"Origin": ALLOWED}).status_code == 503
    response = client.post("/identity/sign", json={"nonce": NONCE}, headers={"Origin": ALLOWED})
    assert response.status_code == 503


def test_both_routes_answer_503_when_the_key_file_is_invalid(tmp_path: Path) -> None:
    (tmp_path / KEY_FILE_NAME).write_text("not a key")
    client = _client(IdentityStore(state_dir=tmp_path, api_key=None))

    assert client.get("/identity", headers={"Origin": ALLOWED}).status_code == 503
    response = client.post("/identity/sign", json={"nonce": NONCE}, headers={"Origin": ALLOWED})
    assert response.status_code == 503
    assert (tmp_path / KEY_FILE_NAME).read_text() == "not a key"
