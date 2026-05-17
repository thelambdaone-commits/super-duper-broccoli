import logging
import os
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.wallet_manager import WalletManager
from utils.credential_manager import CredentialManager

logger = logging.getLogger("WalletHandler")


def get_chat_id(update: Update) -> int:
    return update.effective_chat.id


async def handle_wallet_balance(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_manager: WalletManager
) -> None:
    """Handle /wallet balance command."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet balance <wallet_address>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        wallet_address = args[0]
        
        # Validate address
        if not wallet_manager.is_valid_address(wallet_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid Ethereum address",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Get balance report
        report = wallet_manager.format_balance_report(wallet_address)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in wallet balance handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_health(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_manager: WalletManager
) -> None:
    """Handle /wallet health command."""
    try:
        health = wallet_manager.health_check()
        
        status_emoji = "✅" if health["connected"] else "❌"
        status_text = health["status"].upper()
        
        lines = [
            f"{status_emoji} **Wallet Manager Health**",
            f"• Status: `{status_text}`",
            f"• Chain ID: `{health['chain_id']}`",
            f"• Latest Block: `{health.get('latest_block', 'N/A')}`",
        ]
        
        if "error" in health:
            lines.append(f"• Error: `{health['error'][:100]}`")
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in wallet health handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet help command."""
    try:
        from utils.output_formatter import TelegramOutputFormatter
        formatter = TelegramOutputFormatter()
        help_text = formatter.format_help()
    except ImportError:
        help_text = """
🏦 **Wallet Commands**

*User Wallet Management:*
• `/wallet add <profile>` — Generate new ETH/POL wallet (defaut)
• `/wallet import <profile> <private_key>` — Import existing wallet (import)
• `/wallet use defaut` — Activate generated wallet
• `/wallet use import` — Activate imported wallet
• `/wallet set-proxy <address>` — Set Polymarket proxy wallet
• `/wallet list` — List your wallets
• `/wallet show` — Show your wallet addresses
• `/wallet status` — Show all wallets + active
• `/wallet delete` — Delete active wallet

*Admin Commands:*
• `/wallet balance <address>` — Check token balances
• `/wallet health` — Check wallet manager health

**Example:**
`/wallet add antigravity`
`/wallet import gemini 0xabc123...`
`/wallet set-proxy 0xproxy...`
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_wallet_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet add <profile> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet add <profile_name>`\nExample: `/wallet add antigravity`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        profile_name = args[0]
        mgr = CredentialManager()
        
        if mgr.user_exists(chat_id, "defaut"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ You already have a defaut wallet. Use `/wallet delete` first to create a new one, or use `/wallet use import` to switch to your imported wallet.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.generate_user_wallet(chat_id, profile_name, wallet_type="defaut")
        
        mgr.set_active_wallet_type(chat_id, "defaut")
        
        msg = f"""
✅ **Wallet Created Successfully**

*Profile:* `{profile_name}`
*Address:* `{user_data['address']}`

🔑 **Next Steps:**
1. Set your Polymarket proxy wallet:
   `/wallet set-proxy <proxy_address>`

Your wallet is encrypted and stored in `defaut{chat_id}.enc`
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet add handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet import <profile> <private_key> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if len(args) < 2:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet import <profile_name> <private_key>`\nExample: `/wallet import antigravity 0xabc123...`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        profile_name = args[0]
        private_key = args[1]
        
        if not private_key.startswith("0x") or len(private_key) != 66:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid private key format. Must be 0x-prefixed 64-char hex.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr = CredentialManager()
        
        if mgr.user_exists(chat_id, "import"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ You already have an imported wallet. Use `/wallet delete` first to import a new one.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.import_user_wallet(chat_id, profile_name, private_key, wallet_type="import")
        
        mgr.set_active_wallet_type(chat_id, "import")
        
        msg = f"""
✅ **Wallet Imported Successfully**

*Profile:* `{profile_name}`
*Address:* `{user_data['address']}`

🔑 **Next Steps:**
1. Set your Polymarket proxy wallet:
   `/wallet set-proxy <proxy_address>`

⚠️ Store your private key securely! It cannot be recovered.
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet import handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_set_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet set-proxy <address> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet set-proxy <polymarket_proxy_address>`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        proxy_wallet = args[0]
        
        if not proxy_wallet.startswith("0x") or len(proxy_wallet) != 42:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid Ethereum address format.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet yet. Use `/wallet add <profile>` to create one.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.set_user_proxy(chat_id, proxy_wallet)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ **Proxy Wallet Set**\n\nAddress: `{proxy_wallet}`\nProfile: `{user_data.get('profile_name', 'N/A')}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet set-proxy handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet list command - shows user's wallet."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet yet. Use `/wallet add <profile>` to create one.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.load_user(chat_id)
        
        proxy = user_data.get("proxy_wallet", "")
        proxy_display = f"`{proxy}`" if proxy else "_Not set_"
        
        msg = f"""
👤 **Your Wallet**

*Profile:* `{user_data.get('profile_name', 'N/A')}`
*ETH/POL Address:* `{user_data.get('address', 'N/A')}`
*Proxy Wallet:* {proxy_display}
*API Key:* `{user_data.get('clob_api_key', 'N/A')[:16]}...`
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet list handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet show command - shows addresses only (no private key)."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet yet. Use `/wallet add <profile>` to create one.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.load_user(chat_id)
        
        proxy = user_data.get("proxy_wallet", "")
        proxy_display = f"\n*Proxy:* `{proxy}`" if proxy else ""
        
        msg = f"""
🔐 **Your Addresses**

*ETH/POL:* `{user_data.get('address', 'N/A')}`{proxy_display}

Your private key is encrypted in `defaut{chat_id}.enc`
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet show handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet delete command."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        wallet_type = mgr.get_active_wallet_type(chat_id)
        
        if not mgr.user_exists(chat_id, wallet_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet to delete.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.load_user(chat_id, wallet_type)
        address = user_data.get("address", "")
        
        mgr.delete_user(chat_id, wallet_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🗑️ **Wallet Deleted**\n\nType: `{wallet_type}`\nAddress: `{address}`\nFile: `{wallet_type}{chat_id}.enc` removed.",
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet delete handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet use defaut|import command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet use defaut` or `/wallet use import`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        wallet_type = args[0].lower()
        if wallet_type not in ["defaut", "import"]:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid wallet type. Use `defaut` or `import`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id, wallet_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Wallet type `{wallet_type}` not found. Create it first with `/wallet {'add' if wallet_type == 'defaut' else 'import'}`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        success = mgr.set_active_wallet_type(chat_id, wallet_type)
        
        if success:
            user_data = mgr.load_user(chat_id, wallet_type)
            address = user_data.get("address", "")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ **Wallet Activated**\n\nType: `{wallet_type}`\nAddress: `{address}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Failed to activate wallet.",
                parse_mode=ParseMode.MARKDOWN,
            )
        
    except Exception as e:
        logger.error(f"Error in wallet use handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet status command - shows all wallets."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        try:
            from utils.output_formatter import TelegramOutputFormatter
            formatter = TelegramOutputFormatter()
            
            user_info = mgr.get_user_info(str(chat_id))
            text = formatter.format_wallet_info(user_info, str(chat_id))
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except ImportError:
            wallets = mgr.list_all_user_wallets(chat_id)
            
            if not wallets:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ No wallets found. Use `/wallet add` to create one.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            
            lines = ["👤 *Your Wallets*", "────────────────────────"]
            for w in wallets:
                marker = "✅" if w.get("is_active") else "  "
                lines.append(f"{marker} *{w['type'].upper()}*: `{w['address']}`")
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
        
    except Exception as e:
        logger.error(f"Error in wallet status handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet backup command - exports wallet address for backup."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        wallet_type = mgr.get_active_wallet_type(chat_id)
        
        if not mgr.user_exists(chat_id, wallet_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ No active wallet found.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.load_user(chat_id, wallet_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔐 *Wallet Backup Info*\n\n"
                 f"*Type*: `{wallet_type}`\n"
                 f"*Address*: `{user_data.get('address', 'N/A')}`\n"
                 f"*Profile*: `{user_data.get('profile_name', 'N/A')}`\n\n"
                 f"⚠️ *Warning*: Never share your private key!\n"
                 f"Your encrypted wallet is stored in `data/{wallet_type}{chat_id}.enc`\n\n"
                 f"To export your private key safely, use the CLI:\n"
                 f"`python -c \"from utils.credential_manager import CredentialManager; "
                 f"mgr = CredentialManager(); "
                 f"print(mgr.load_user('{chat_id}', '{wallet_type}')['private_key'])\"`",
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet backup handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_wallet_swap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet swap command - swap between defaut and import."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        current_type = mgr.get_active_wallet_type(chat_id)
        other_type = "import" if current_type == "defaut" else "defaut"
        
        if not mgr.user_exists(chat_id, other_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ No {other_type} wallet found. Create one first with `/wallet {'add' if other_type == 'defaut' else 'import'}`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr.set_active_wallet_type(chat_id, other_type)
        user_data = mgr.load_user(chat_id, other_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔄 **Wallet Swapped**\n\n"
                 f"• From: `{current_type}`\n"
                 f"• To: `{other_type}`\n"
                 f"• Address: `{user_data.get('address', 'N/A')}`\n\n"
                 f"Run `/wallet status` to verify.",
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet swap handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.MARKDOWN,
        )
