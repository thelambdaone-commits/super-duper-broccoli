import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from utils.credential_manager import CredentialManager

def main():
    load_dotenv()
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if not encryption_key:
        print("Error: ENCRYPTION_KEY not found in .env")
        sys.exit(1)

    mgr = CredentialManager(encryption_key=encryption_key)
    
    print("--- Institutional Wallet Generation ---")
    pk = mgr.get_or_generate_private_key()
    # Also generate CLOB credentials
    mgr.get_or_generate_creds(pk)
    
    print("\nSUCCESS: Institutional wallet and CLOB credentials generated and encrypted.")
    print(f"Files created in: {os.getenv('DATA_PATH', './data')}/")
    print(" - clob_wallet.enc (Private Key)")
    print(" - defaut.enc (CLOB API Access)")
    print("\nIMPORTANT: Keep your ENCRYPTION_KEY safe. These files cannot be decrypted without it.")

if __name__ == "__main__":
    main()
