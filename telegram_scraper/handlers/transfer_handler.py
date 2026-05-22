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
                "📤 <b>TRANSFERT DE FONDS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Usage: <code>/transfer &lt;montant&gt; &lt;token&gt; &lt;adresse_dest&gt;</code>\n\n"
                "💎 <b>Tokens supportés</b> : <code>MATIC</code>, <code>USDC</code>, <code>POL</code>\n"
                "⚙️ <b>Option</b> : <code>--dry-run</code> (simuler)\n\n"
                "💡 <i>Exemple: /transfer 10 USDC 0x742...f42dE</i>"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.HTML,
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
                text=f"❌ <b>MONTANT INVALIDE</b>\n\n<code>{amount_str}</code> n'est pas un nombre valide.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Validate address
        if not transfer_manager.wallet_manager.is_valid_address(to_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ <b>ADRESSE INVALIDE</b>\n\nL'adresse de destination est incorrecte.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Gas estimate
        gas_est = transfer_manager.estimate_gas_for_transfer(
            transfer_manager._from_address, to_address, token, amount
        )

        if "error" in gas_est:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ <b>ESTIMATION ÉCHOUÉE</b>\n\n{gas_est['error']}",
                parse_mode=ParseMode.HTML,
            )
            return

        # Show estimate
        estimate_msg = (
            "📤 <b>DEVIS DE TRANSFERT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Token</b> : <code>{token}</code>\n"
            f"• <b>Montant</b> : <code>{amount}</code>\n"
            f"• <b>Vers</b> : <code>{to_address[:6]}...{to_address[-4:]}</code>\n"
            f"• <b>Gaz Estimé</b> : <code>{gas_est['gas_estimate']} units</code>\n"
            f"• <b>Coût Total</b> : <code>{gas_est['estimated_gas_cost_gwei']:.6f} POL</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <i>Exécution en cours...</i>"
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=estimate_msg,
            parse_mode=ParseMode.HTML,
        )

        # Execute transfer
        receipt = await transfer_manager.transfer_tokens(
            to_address, token, amount, dry_run=dry_run
        )

        # Send receipt
        receipt_msg = transfer_manager.format_transfer_receipt(receipt)
        if "━━━━━━━━━" not in receipt_msg:
            receipt_msg = (
                "✅ <b>TRANSFERT TERMINÉ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{receipt_msg}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=receipt_msg,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Error in transfer handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>ERREUR TRANSFERT</b>\n\n<code>{str(e)[:100]}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_transfer_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transfer help command."""
    help_text = """
📤 <b>Transfer Commands</b>

• <code>/transfer &lt;amount&gt; &lt;token&gt; &lt;address&gt; [--dry-run]</code> — Transfer tokens
• <code>/transfer help</code> — Show this help

<b>Tokens:</b>
• MATIC (native token)
• USDC (stablecoin)
• POL (governance token)

<b>Options:</b>
• <code>--dry-run</code> — Simulate without executing

<b>Examples:</b>
• <code>/transfer 10 USDC 0x742d35Cc6634C0532925a3b844Bc9e7595f42dE</code>
• <code>/transfer 1 MATIC 0x742d35Cc6634C0532925a3b844Bc9e7595f42dE --dry-run</code>
"""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        parse_mode=ParseMode.HTML,
    )
