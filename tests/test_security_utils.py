from __future__ import annotations

from pathlib import Path

from utils.security_utils import decrypt_data, encrypt_data, get_encryption_key


def test_invalid_master_key_is_rotated(monkeypatch, tmp_path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    key_path = secrets_dir / "master.key"
    key_path.write_bytes(b"not-a-valid-fernet-key")

    monkeypatch.setenv("SECRETS_PATH", str(secrets_dir))

    key = get_encryption_key()

    assert key != b"not-a-valid-fernet-key"
    payload = encrypt_data("hello")
    assert decrypt_data(payload) == "hello"
    assert Path(key_path).read_bytes() == key
