import asyncio
from polymarket.execution.wallet_manager import PolymarketWalletManager
from utils.credential_manager import CredentialManager

async def main():
    mgr = CredentialManager()
    creds = mgr.load_and_decrypt()
    wm = PolymarketWalletManager(vault_handler=mgr)
    
    # Récupérer l'adresse proxy si elle existe
    proxy = creds.get('proxy_wallet')
    address = creds.get('address')
    
    soldes = await wm.recuperer_soldes_on_chain(address, proxy_address=proxy or "")
    print(f'Détails des soldes Polymarket/On-chain: {soldes}')

if __name__ == '__main__':
    asyncio.run(main())
