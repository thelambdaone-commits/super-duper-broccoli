import asyncio
from polymarket.execution.wallet_manager import PolymarketWalletManager
from utils.credential_manager import CredentialManager

async def main():
    mgr = CredentialManager()
    creds = mgr.load_and_decrypt()
    wm = PolymarketWalletManager(vault_handler=mgr)
    soldes = await wm.recuperer_soldes_on_chain(creds.get('address'))
    print(f'Soldes: {soldes}')

if __name__ == '__main__':
    asyncio.run(main())
