import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.wallet_manager import WalletManager
from utils.transfer_manager import TransferManager

logger = logging.getLogger("TransferHandler")


async def handle_transfer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    transfer_manager: TransferManager,
) -> None:
    """Handle /transfer command with Lobstar style."""
    try:
        args = context.args
        
        if len(args) < 3:
            help_text = (
                "📤 *TRANSFERT DE FONDS*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Usage: `/transfer <montant> <token> <adresse_dest>`\n\n"
                "💎 *Tokens supportés* : `MATIC`, `USDC`, `POL`\n"
                "⚙️ *Option* : `--dry-run` (simuler)\n\n"
                "💡 _Exemple: /transfer 10 USDC 0x742...f42dE_"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        amount_str = args[0]
        token = args[1].upper()
        to_address = args[2]
        dry_run = "--dry-run" in args

        try:
            amount = float(amount_str)
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ *MONTANT INVALIDE*\n\n`{amount_str}` n'est pas un nombre valide.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Validate address
        if not transfer_manager.wallet_manager.is_valid_address(to_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ *ADRESSE INVALIDE*\n\nL'adresse de destination est incorrecte.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Gas estimate
        gas_est = transfer_manager.estimate_gas_for_transfer(
            transfer_manager._from_address, to_address, token, amount
        )

        if "error" in gas_est:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ *ESTIMATION ÉCHOUÉE*\n\n{gas_est['error']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Show estimate
        estimate_msg = (
            "📤 *DEVIS DE TRANSFERT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Token* : `{token}`\n"
            f"• *Montant* : `{amount}`\n"
            f"• *Vers* : `{to_address[:6]}...{to_address[-4:]}`\n"
            f"• *Gaz Estimé* : `{gas_est['gas_estimate']} units`\n"
            f"• *Coût Total* : `{gas_est['estimated_gas_cost_gwei']:.6f} POL`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ _Exécution en cours..._"
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=estimate_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

        # Execute transfer
        receipt = await transfer_manager.transfer_tokens(
            to_address, token, amount, dry_run=dry_run
        )

        # Send receipt
        receipt_msg = transfer_manager.format_transfer_receipt(receipt)
        if "━━━━━━━━━" not in receipt_msg:
            receipt_msg = (
                "✅ *TRANSFERT TERMINÉ*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{receipt_msg}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=receipt_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in transfer handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ *ERREUR TRANSFERT*\n\n`{str(e)[:100]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_transfer_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transfer help command."""
    help_text = """
📤 **Transfer Commands**

• `/transfer <amount> <token> <address> [--dry-run]` — Transfer tokens
• `/transfer help` — Show this help

**Tokens:**
• MATIC (native token)
• USDC (stablecoin)
• POL (governance token)

**Options:**
• `--dry-run` — Simulate without executing

**Examples:**
• `/transfer 10 USDC 0x742d35Cc6634C0532925a3b844Bc9e7595f42dE`
• `/transfer 1 MATIC 0x742d35Cc6634C0532925a3b844Bc9e7595f42dE --dry-run`
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.MARKDOWN,
    )
