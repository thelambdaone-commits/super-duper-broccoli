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
    """Handle /wallet balance command with Lobstar intuitive style."""
    try:
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
            text=(
                "💰 <b>CHECK BALANCE</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Usage: <code>/wallet balance &lt;adresse_ou_alias&gt;</code>\n\n"
                "💡 <i>Exemple: /wallet balance 0x71C...3a9</i>"
            ),
                parse_mode=ParseMode.HTML,
            )
            return

        wallet_address = args[0]
        
        # Validate address
        if not wallet_manager.is_valid_address(wallet_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ <b>ERREUR ADRESSE</b>\n\nL'adresse fournie n'est pas un format Ethereum/Polygon valide.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Get balance report
        report = wallet_manager.format_balance_report(wallet_address)
        
        # Wrap report in Lobstar style if it's not already
        if "━━━━━━━━━" not in report:
            report = (
                f"💰 <b>SOLDE DU WALLET</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{report}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Error in wallet balance handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>ERREUR SYSTÈME</b>\n\nUne erreur est survenue lors de la récupération du solde : <code>{str(e)[:100]}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_health(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_manager: WalletManager
) -> None:
    """Handle /wallet health command with Lobstar intuitive style."""
    try:
        health = wallet_manager.health_check()
        
        status_emoji = "🟢" if health["connected"] else "🔴"
        status_text = "OPÉRATIONNEL" if health["connected"] else "DÉCONNECTÉ"
        
        lines = [
            f"🛡️ <b>SANTÉ DU WALLET MANAGER</b>",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"• <b>Statut</b> : <code>{status_text}</code> {status_emoji}",
            f"• <b>Chain ID</b> : <code>{health['chain_id']}</code>",
            f"• <b>Bloc Actuel</b> : <code>{health.get('latest_block', 'N/A')}</code>",
            f"• <b>Latency</b> : <code>{health.get('latency_ms', 'N/A')}ms</code>",
        ]
        
        if not health["connected"] and "error" in health:
            lines.append(f"• <b>Erreur</b> : <code>{health['error'][:100]}</code>")
        
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Error in wallet health handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>ERREUR SANTÉ</b>\n\nImpossible de vérifier l'état du manager : <code>{str(e)[:100]}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet help command."""
    try:
        from utils.output_formatter import TelegramOutputFormatter
        formatter = TelegramOutputFormatter()
        help_text = formatter.format_help()
    except ImportError:
        help_text = """
🏦 <b>Wallet Commands</b>

<b>User Wallet Management:</b>
• <code>/wallet add &lt;profile&gt;</code> — Generate new ETH/POL wallet (default)
• <code>/wallet import &lt;profile&gt; &lt;private_key&gt;</code> — Import existing wallet (import)
• <code>/wallet use default</code> — Activate generated wallet
• <code>/wallet use import</code> — Activate imported wallet
• <code>/wallet set-proxy &lt;address&gt;</code> — Set Polymarket proxy wallet
• <code>/wallet list</code> — List your wallets
• <code>/wallet show</code> — Show your wallet addresses
• <code>/wallet status</code> — Show all wallets + active
• <code>/wallet delete</code> — Delete active wallet

<b>Admin Commands:</b>
• <code>/wallet balance &lt;address&gt;</code> — Check token balances
• <code>/wallet health</code> — Check wallet manager health

<b>Example:</b>
<code>/wallet add antigravity</code>
<code>/wallet import gemini 0xabc123...</code>
<code>/wallet set-proxy 0xproxy...</code>
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.HTML,
    )


async def handle_wallet_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet add <profile> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: <code>/wallet add &lt;profile_name&gt;</code>\nExample: <code>/wallet add antigravity</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        profile_name = args[0]
        mgr = CredentialManager()
        
        if mgr.user_exists(chat_id, "default"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ You already have a default wallet. Use <code>/wallet delete</code> first to create a new one, or use <code>/wallet use import</code> to switch to your imported wallet.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.generate_user_wallet(chat_id, profile_name, wallet_type="default")
        
        mgr.set_active_wallet_type(chat_id, "default")
        
        proxy = _proxy_resolver(chat_id, mgr, "default", user_data["address"])
        
        proxy_line = f"\n<b>Proxy Wallet:</b> <code>{proxy}</code>" if proxy else ""
        next_steps = "" if proxy else (
            "\n🔑 <b>Next Step:</b> Set your Polymarket proxy wallet:\n"
            "   <code>/wallet set-proxy &lt;proxy_address&gt;</code>"
        )
        
        msg = f"""
✅ <b>Wallet Created Successfully</b>

<b>Profile:</b> <code>{profile_name}</code>
<b>Address:</b> <code>{user_data['address']}</code>{proxy_line}{next_steps}

Your wallet is encrypted and stored in <code>default{chat_id}.enc</code>
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet add handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet import <profile> <private_key> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if len(args) < 2:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: <code>/wallet import &lt;profile_name&gt; &lt;private_key&gt;</code>\nExample: <code>/wallet import antigravity 0xabc123...</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        profile_name = args[0]
        private_key = args[1]
        
        if not private_key.startswith("0x") or len(private_key) != 66:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid private key format. Must be 0x-prefixed 64-char hex.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        mgr = CredentialManager()
        
        if mgr.user_exists(chat_id, "import"):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ You already have an imported wallet. Use <code>/wallet delete</code> first to import a new one.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.import_user_wallet(chat_id, profile_name, private_key, wallet_type="import")
        
        mgr.set_active_wallet_type(chat_id, "import")
        
        proxy = _proxy_resolver(chat_id, mgr, "import", user_data["address"])
        
        proxy_line = f"\n<b>Proxy Wallet:</b> <code>{proxy}</code>" if proxy else ""
        next_steps = "" if proxy else (
            "\n🔑 <b>Next Step:</b> Set your Polymarket proxy wallet:\n"
            "   <code>/wallet set-proxy &lt;proxy_address&gt;</code>"
        )
        
        msg = f"""
✅ <b>Wallet Imported Successfully</b>

<b>Profile:</b> <code>{profile_name}</code>
<b>Address:</b> <code>{user_data['address']}</code>{proxy_line}{next_steps}

⚠️ Store your private key securely! It cannot be recovered.
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet import handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_set_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet set-proxy <address> command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            usage_text = (
                "🎯 <b>Configure Polymarket Proxy Wallet</b>\n"
                "────────────────────────\n"
                "Le proxy wallet (Gnosis Safe) est le contrat qui détient vos positions et vos fonds sur la plateforme Polymarket.\n"
                "────────────────────────\n"
                "💡 <b>Usage</b> : <code>/wallet set-proxy &lt;adresse_proxy_safe&gt;</code>\n\n"
                "Exemple :\n"
                "<code>/wallet set-proxy 0x3915c544d673ed10959a45695cf643f8e63ec2b9</code>"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=usage_text,
                parse_mode=ParseMode.HTML,
            )
            return
        
        proxy_wallet = args[0]
        
        if not proxy_wallet.startswith("0x") or len(proxy_wallet) != 42:
            error_text = (
                "❌ <b>Address Format Invalid</b>\n"
                "────────────────────────\n"
                "L'adresse de votre Gnosis Safe Proxy doit être une adresse Ethereum valide :\n"
                "- Commencer par <code>0x</code>\n"
                "- Faire exactement 42 caractères de long\n"
                "────────────────────────\n"
                "💡 Veuillez vérifier votre saisie et réessayer."
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_text,
                parse_mode=ParseMode.HTML,
            )
            return
        
        mgr = CredentialManager()
        wallet_type = mgr.get_active_wallet_type(chat_id)
        
        if not mgr.user_exists(chat_id, wallet_type):
            no_wallet_text = (
                "❌ <b>No Active Wallet Found</b>\n"
                "────────────────────────\n"
                "Vous devez d'abord importer ou initialiser un wallet utilisateur avant de lui associer un proxy.\n"
                "────────────────────────\n"
                "💡 Envoyez votre clé privée ou seed phrase en DM pour configurer votre premier profil de trading !"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=no_wallet_text,
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.set_user_proxy(chat_id, proxy_wallet, wallet_type=wallet_type)
        
        success_text = (
            "🎯 <b>Polymarket Gnosis Safe Proxy Wallet Set</b>\n"
            "────────────────────────\n"
            "Votre proxy wallet a été configuré avec succès et lié à votre profil actif.\n"
            "Le cockpit a été mis à jour et est prêt à interroger la blockchain Polygon.\n"
            "────────────────────────\n"
            f"👤 <b>Active Profile</b> : <code>{user_data.get('profile_name', 'N/A')}</code>\n"
            f"⚙️ <b>Wallet Type</b>    : <code>{wallet_type.capitalize()}</code>\n"
            f"📌 <b>Proxy Address</b>  : <code>{proxy_wallet}</code>\n"
            "────────────────────────\n"
            "💡 <b>Tip</b> : Cliquez sur le bouton ci-dessous pour retourner au cockpit et voir vos soldes de jetons pUSD mis à jour !"
        )
        
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Return to Cockpit", callback_data="wallet_refresh")
        ]])
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=success_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet set-proxy handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>System Error</b>\n────────────────────────\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet list command - shows user's wallet."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet yet. Use <code>/wallet add &lt;profile&gt;</code> to create one.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.load_user(chat_id)
        
        proxy = user_data.get("proxy_wallet", "")
        proxy_display = f"<code>{proxy}</code>" if proxy else "<i>Not set</i>"
        
        msg = f"""
👤 <b>Your Wallet</b>

<b>Profile:</b> <code>{user_data.get('profile_name', 'N/A')}</code>
<b>ETH/POL Address:</b> <code>{user_data.get('address', 'N/A')}</code>
<b>Proxy Wallet:</b> {proxy_display}
<b>API Key:</b> <code>{user_data.get('clob_api_key', 'N/A')[:16]}...</code>
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet list handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet show command - shows addresses only (no private key)."""
    try:
        chat_id = get_chat_id(update)
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ You don't have a wallet yet. Use <code>/wallet add &lt;profile&gt;</code> to create one.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.load_user(chat_id)
        
        proxy = user_data.get("proxy_wallet", "")
        proxy_display = f"\n<b>Proxy:</b> <code>{proxy}</code>" if proxy else ""
        
        msg = f"""
🔐 <b>Your Addresses</b>

<b>ETH/POL:</b> <code>{user_data.get('address', 'N/A')}</code>{proxy_display}

Your private key is encrypted in <code>default{chat_id}.enc</code>
"""
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=msg,
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet show handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
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
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.load_user(chat_id, wallet_type)
        address = user_data.get("address", "")
        
        mgr.delete_user(chat_id, wallet_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🗑️ <b>Wallet Deleted</b>\n\nType: <code>{wallet_type}</code>\nAddress: <code>{address}</code>\nFile: <code>{wallet_type}{chat_id}.enc</code> removed.",
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet delete handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet use default|import command."""
    try:
        chat_id = get_chat_id(update)
        args = context.args
        
        if not args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Usage: <code>/wallet use default</code> or <code>/wallet use import</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        wallet_type = args[0].lower()
        if wallet_type not in ["default", "import"]:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid wallet type. Use <code>default</code> or <code>import</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        mgr = CredentialManager()
        
        if not mgr.user_exists(chat_id, wallet_type):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Wallet type <code>{wallet_type}</code> not found. Create it first with <code>/wallet {'add' if wallet_type == 'default' else 'import'}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        success = mgr.set_active_wallet_type(chat_id, wallet_type)
        
        if success:
            user_data = mgr.load_user(chat_id, wallet_type)
            address = user_data.get("address", "")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ <b>Wallet Activated</b>\n\nType: <code>{wallet_type}</code>\nAddress: <code>{address}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Failed to activate wallet.",
                parse_mode=ParseMode.HTML,
            )
        
    except Exception as e:
        logger.error(f"Error in wallet use handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
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
                parse_mode=ParseMode.HTML,
            )
        except ImportError:
            wallets = mgr.list_all_user_wallets(chat_id)
            
            if not wallets:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ No wallets found. Use <code>/wallet add</code> to create one.",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            lines = ["👤 <b>Your Wallets</b>", "────────────────────────"]
            for w in wallets:
                marker = "✅" if w.get("is_active") else "  "
                lines.append(f"{marker} <b>{w['type'].upper()}</b>: <code>{w['address']}</code>")
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
        
    except Exception as e:
        logger.error(f"Error in wallet status handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
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
                parse_mode=ParseMode.HTML,
            )
            return
        
        user_data = mgr.load_user(chat_id, wallet_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔐 <b>Wallet Backup Info</b>\n\n"
                 f"<b>Type</b>: <code>{wallet_type}</code>\n"
                 f"<b>Address</b>: <code>{user_data.get('address', 'N/A')}</code>\n"
                 f"<b>Profile</b>: <code>{user_data.get('profile_name', 'N/A')}</code>\n\n"
                 f"⚠️ <b>Warning</b>: Never share your private key!\n"
                 f"Your encrypted wallet is stored in <code>data/{wallet_type}{chat_id}.enc</code>\n\n"
                 f"To export your private key safely, use the CLI:\n"
                 f"<code>python -c \"from utils.credential_manager import CredentialManager; "
                 f"mgr = CredentialManager(); "
                 f"print(mgr.load_user('{chat_id}', '{wallet_type}')['private_key'])\"</code>",
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet backup handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
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
                text=f"❌ No {other_type} wallet found. Create one first with <code>/wallet {'add' if other_type == 'default' else 'import'}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        mgr.set_active_wallet_type(chat_id, other_type)
        user_data = mgr.load_user(chat_id, other_type)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔄 <b>Wallet Swapped</b>\n\n"
                 f"• From: <code>{current_type}</code>\n"
                 f"• To: <code>{other_type}</code>\n"
                 f"• Address: <code>{user_data.get('address', 'N/A')}</code>\n\n"
                 f"Run <code>/wallet status</code> to verify.",
            parse_mode=ParseMode.HTML,
        )
        
    except Exception as e:
        logger.error(f"Error in wallet swap handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
            parse_mode=ParseMode.HTML,
        )
