from typing import Optional

from eth_account import Account
from py_clob_client_v2 import ClobClient


class ClobCredentialDeriver:
    def __init__(self, private_key: str, host: str = "https://clob.polymarket.com") -> None:
        self.private_key = private_key
        self.host = host
        self.wallet = Account.from_key(private_key)

    def derive(self) -> dict:
        client = ClobClient(
            host=self.host,
            key=self.private_key,
            chain_id=137,
            signature_type=2,
        )
        creds = client.create_or_derive_api_key()
        return {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_API_SECRET": creds.api_secret,
            "CLOB_API_PASSPHRASE": creds.api_passphrase,
            "address": self.wallet.address,
        }


def derive_clob_credentials(private_key: str) -> dict:
    return ClobCredentialDeriver(private_key).derive()
