from __future__ import annotations

import os

import pytest
from unittest.mock import patch

from utils.credential_manager import CredentialManager
from utils.exceptions import QuantFatal
from utils.vault_handler import VaultHandler


TEST_PRIVATE_KEY = "0x" + "1" * 64
TEST_ENCRYPTION_KEY = "F9U0WUdQxZpg_NTGWJm6_u8x2J1r1JnjBIQI4cfLz68="


def _patch_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wallet_path = str(data_dir / "polymarket.wallet.enc")
    monkeypatch.setenv("DATA_PATH", str(data_dir))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setattr("utils.credential_manager.DEFAULT_DATA_DIR", str(data_dir))
    monkeypatch.setattr("utils.credential_manager.POLYMARKET_WALLET_PATH", wallet_path)
    monkeypatch.setattr("utils.vault_handler.POLYMARKET_WALLET_PATH", wallet_path)
    return wallet_path


def test_credential_manager_defaults_to_data_enc_path(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    wallet_path = _patch_data_dir(monkeypatch, tmp_path)

    manager = CredentialManager()
    assert manager._resolve_enc_path(wallet_path).name == "polymarket.wallet.enc"
    assert str(manager._resolve_enc_path(wallet_path)).startswith(str(tmp_path / "data"))


def test_vault_handler_prefers_data_enc_wallet_over_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    wallet_path = _patch_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SECRET_SOURCE", "env")
    monkeypatch.delenv("CLOB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("CHAT_ID", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("VAULT_ADDR", "false")

    manager = CredentialManager()
    with patch("utils.credential_manager.derive_clob_credentials") as derive:
        derive.return_value = {
            "CLOB_PRIVATE_KEY": TEST_PRIVATE_KEY,
            "CLOB_API_KEY": "api-key",
            "CLOB_API_SECRET": "api-secret",
            "CLOB_API_PASSPHRASE": "passphrase",
            "address": "0xwallet",
        }
        manager.get_or_generate_creds(TEST_PRIVATE_KEY, wallet_path)

    vault = VaultHandler()
    secrets = vault.fetch_quantum_secrets()

    assert secrets["CLOB_PRIVATE_KEY"] == TEST_PRIVATE_KEY
    assert secrets["CLOB_API_KEY"]
    assert secrets["CLOB_API_SECRET"]
    assert secrets["CLOB_API_PASSPHRASE"]
    assert os.path.exists(wallet_path)


def test_vault_handler_rejects_env_private_key_without_enc_wallet(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SECRET_SOURCE", "env")
    monkeypatch.setenv("CLOB_PRIVATE_KEY", TEST_PRIVATE_KEY)
    monkeypatch.delenv("CHAT_ID", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("VAULT_ADDR", "false")

    vault = VaultHandler()

    with pytest.raises(QuantFatal) as exc:
        vault.fetch_quantum_secrets()

    assert "CLOB_PRIVATE_KEY is missing from user credentials and encrypted vault" in str(exc.value)


def test_vault_handler_allows_paper_mode_without_clob_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SECRET_SOURCE", "env")
    monkeypatch.setenv("EXECUTION_MODE", "PAPER")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.delenv("CLOB_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.setenv("VAULT_ADDR", "false")

    vault = VaultHandler()
    secrets = vault.fetch_quantum_secrets()

    assert secrets["TELEGRAM_BOT_TOKEN"] == "token"
    assert "CLOB_PRIVATE_KEY" not in secrets


def test_credential_manager_rejects_wallet_path_outside_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_PATH", str(data_dir))
    monkeypatch.setenv("ENCRYPTION_KEY", "F9U0WUdQxZpg_NTGWJm6_u8x2J1r1JnjBIQI4cfLz68=")
    monkeypatch.setattr("utils.credential_manager.DEFAULT_DATA_DIR", str(data_dir))
    monkeypatch.setattr("utils.credential_manager.POLYMARKET_WALLET_PATH", str(data_dir / "polymarket.wallet.enc"))

    manager = CredentialManager()

    with pytest.raises(ValueError):
        manager.encrypt_and_save({"CLOB_PRIVATE_KEY": TEST_PRIVATE_KEY}, path="../outside.enc")
