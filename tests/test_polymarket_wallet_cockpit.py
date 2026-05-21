


def test_wallet_deletion_archives_file(tmp_path, monkeypatch) -> None:
    from utils.credential_manager import CredentialManager
    import os

    temp_dir = str(tmp_path / "data")
    os.makedirs(temp_dir, exist_ok=True)
    wallet_path = os.path.join(temp_dir, "polymarket.wallet.enc")
    monkeypatch.setattr("utils.credential_manager.DEFAULT_DATA_DIR", temp_dir)
    monkeypatch.setattr("utils.credential_manager.POLYMARKET_WALLET_PATH", wallet_path)

    mgr = CredentialManager()
    chat_id = 99999
    wtype = "default"
    fake_data = {"address": "0x123", "POLYMARKET_WALLET_ADDRESS": "0x123"}
    mgr.save_user(chat_id, fake_data, wtype)

    path = mgr.get_user_file_path(chat_id, wtype)
    assert os.path.exists(path)
    assert path == wallet_path

    success = mgr.delete_user(chat_id, wtype)
    assert success is True
    assert not os.path.exists(path)

    archive_dir = os.path.join(temp_dir, "archives")
    assert os.path.exists(archive_dir)
    archived_files = os.listdir(archive_dir)
    assert len(archived_files) == 1
    assert archived_files[0].startswith("polymarket_wallet_")
    assert archived_files[0].endswith(".enc")
