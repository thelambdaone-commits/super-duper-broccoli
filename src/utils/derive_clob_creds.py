
from eth_account import Account

try:
    from py_clob_client_v2 import ClobClient
except ModuleNotFoundError:
    from py_clob_client import ClobClient

from utils.secret_validation import validate_private_key_or_raise


class ClobCredentialDeriver:
    def __init__(self, private_key: str, host: str = "https://clob.polymarket.com") -> None:
        self.private_key = validate_private_key_or_raise(private_key, source="CLOB credential derivation")
        self.host = host
        self.wallet = Account.from_key(self.private_key)

    def derive(self) -> dict:
        import os
        # LOBSTAR V2: Prioritize explicit signature type from environment.
        # py_clob_client_v2 supports POLY_1271=3 for deposit-wallet flows.
        funder = os.getenv("POLYMARKET_PROXY_WALLET_ADDRESS") or None
        sig_type = 3 if funder else 0
        env_sig = os.getenv("POLYMARKET_SIGNATURE_TYPE")
        if env_sig is not None:
            try:
                sig_type = int(env_sig)
            except ValueError:
                pass

        client = ClobClient(
            host=self.host,
            key=self.private_key,
            chain_id=137,
            signature_type=sig_type,
            funder=funder,
        )
        # SDK FIX: create_or_derive_api_key does not exist. Use derive_api_key.
        creds = client.derive_api_key()
        return {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_API_SECRET": creds.api_secret,
            "CLOB_API_PASSPHRASE": creds.api_passphrase,
            "address": self.wallet.address,
            "POLYMARKET_PROXY_WALLET_ADDRESS": funder or "",
        }


def derive_clob_credentials(private_key: str) -> dict:
    return ClobCredentialDeriver(private_key).derive()
