import logging
import os
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.wallet_manager import WalletManager
from utils.credential_manager import CredentialManager

logger = logging.getLogger("WalletHandler")


def _proxy_resolver(chat_id: int, mgr: CredentialManager, wallet_type: str, address: str) -> str:
    """Query Gamma API to auto-resolve Polymarket proxy wallet for the given address."""
    import httpx
    try:
        r = httpx.get(
            f"https://gamma-api.polymarket.com/public-profile?address={address}",
            timeout=5.0,
        )
        if r.status_code == 200:
            resolved = r.json().get("proxyWallet")
            if resolved:
                mgr.set_user_proxy(chat_id, resolved, wallet_type=wallet_type)
                logger.info(
                    "Auto-resolved proxy wallet %s for %s (%s)",
                    resolved, wallet_type, address[:10],
                )
                return resolved
        logger.info("No proxy wallet found on Gamma API for %s", address[:10])
    except Exception as e:
        logger.warning("Gamma API proxy resolution failed for %s: %s", address[:10], e)
    return ""


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
• `/wallet add <profile>` — Generate new ETH/POL wallet (default)
• `/wallet import <profile> <private_key>` — Import existing wallet (import)
• `/wallet use default` — Activate generated wallet
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
        
        if mgr.user_exists(chat_id, "default"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ You already have a default wallet. Use `/wallet delete` first to create a new one, or use `/wallet use import` to switch to your imported wallet.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.generate_user_wallet(chat_id, profile_name, wallet_type="default")
        
        mgr.set_active_wallet_type(chat_id, "default")
        
        proxy = _proxy_resolver(chat_id, mgr, "default", user_data["address"])
        
        proxy_line = f"\n*Proxy Wallet:* `{proxy}`" if proxy else ""
        next_steps = "" if proxy else (
            "\n🔑 *Next Step:* Set your Polymarket proxy wallet:\n"
            "   `/wallet set-proxy <proxy_address>`"
        )
        
        msg = f"""
✅ **Wallet Created Successfully**

*Profile:* `{profile_name}`
*Address:* `{user_data['address']}`{proxy_line}{next_steps}

Your wallet is encrypted and stored in `default{chat_id}.enc`
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
        
        proxy = _proxy_resolver(chat_id, mgr, "import", user_data["address"])
        
        proxy_line = f"\n*Proxy Wallet:* `{proxy}`" if proxy else ""
        next_steps = "" if proxy else (
            "\n🔑 *Next Step:* Set your Polymarket proxy wallet:\n"
            "   `/wallet set-proxy <proxy_address>`"
        )
        
        msg = f"""
✅ **Wallet Imported Successfully**

*Profile:* `{profile_name}`
*Address:* `{user_data['address']}`{proxy_line}{next_steps}

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
            usage_text = (
                "🎯 *Configure Polymarket Proxy Wallet*\n"
                "────────────────────────\n"
                "Le proxy wallet (Gnosis Safe) est le contrat qui détient vos positions et vos fonds sur la plateforme Polymarket.\n"
                "────────────────────────\n"
                "💡 *Usage* : `/wallet set-proxy <adresse_proxy_safe>`\n\n"
                "Exemple :\n"
                "`/wallet set-proxy 0x3915c544d673ed10959a45695cf643f8e63ec2b9`"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=usage_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        proxy_wallet = args[0]
        
        if not proxy_wallet.startswith("0x") or len(proxy_wallet) != 42:
            error_text = (
                "❌ *Address Format Invalid*\n"
                "────────────────────────\n"
                "L'adresse de votre Gnosis Safe Proxy doit être une adresse Ethereum valide :\n"
                "- Commencer par `0x`\n"
                "- Faire exactement 42 caractères de long\n"
                "────────────────────────\n"
                "💡 Veuillez vérifier votre saisie et réessayer."
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr = CredentialManager()
        wallet_type = mgr.get_active_wallet_type(chat_id)
        
        if not mgr.user_exists(chat_id, wallet_type):
            no_wallet_text = (
                "❌ *No Active Wallet Found*\n"
                "────────────────────────\n"
                "Vous devez d'abord importer ou initialiser un wallet utilisateur avant de lui associer un proxy.\n"
                "────────────────────────\n"
                "💡 Envoyez votre clé privée ou seed phrase en DM pour configurer votre premier profil de trading !"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=no_wallet_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        user_data = mgr.set_user_proxy(chat_id, proxy_wallet, wallet_type=wallet_type)
        
        success_text = (
            "🎯 *Polymarket Gnosis Safe Proxy Wallet Set*\n"
            "────────────────────────\n"
            "Votre proxy wallet a été configuré avec succès et lié à votre profil actif.\n"
            "Le cockpit a été mis à jour et est prêt à interroger la blockchain Polygon.\n"
            "────────────────────────\n"
            f"👤 *Active Profile* : `{user_data.get('profile_name', 'N/A')}`\n"
            f"⚙️ *Wallet Type*    : `{wallet_type.capitalize()}`\n"
            f"📌 *Proxy Address*  : `{proxy_wallet}`\n"
            "────────────────────────\n"
            "💡 *Tip* : Cliquez sur le bouton ci-dessous pour retourner au cockpit et voir vos soldes de jetons pUSD mis à jour !"
        )
        
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")
        ]])
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=success_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet set-proxy handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ *System Error*\n────────────────────────\n`{str(e)[:200]}`",
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

Your private key is encrypted in `default{chat_id}.enc`
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
    """Handle /wallet use default|import command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: `/wallet use default` or `/wallet use import`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        wallet_type = args[0].lower()
        if wallet_type not in ["default", "import"]:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid wallet type. Use `default` or `import`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id, wallet_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Wallet type `{wallet_type}` not found. Create it first with `/wallet {'add' if wallet_type == 'default' else 'import'}`.",
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
    """Handle /wallet swap command - swap between default and import."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        current_type = mgr.get_active_wallet_type(chat_id)
        other_type = "import" if current_type == "default" else "default"
        
        if not mgr.user_exists(chat_id, other_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ No {other_type} wallet found. Create one first with `/wallet {'add' if other_type == 'default' else 'import'}`.",
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
