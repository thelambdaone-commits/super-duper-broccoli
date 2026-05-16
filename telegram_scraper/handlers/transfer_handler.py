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
    """Handle /transfer command."""
    try:
        args = context.args
        
        if len(args) < 3:
            help_text = """
Usage: `/transfer <amount> <token> <to_address> [--dry-run]`

**Tokens:** MATIC, USDC, POL

**Example:**
`/transfer 10 USDC 0x742d...f42dE`
`/transfer 1 MATIC 0x742d...f42dE --dry-run`
"""
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
                text=f"❌ Invalid amount: {amount_str}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Validate address
        if not transfer_manager.wallet_manager.is_valid_address(to_address):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Invalid recipient address",
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
                text=f"❌ Gas estimation failed: {gas_est['error']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Show estimate
        estimate_msg = f"""
📤 **Transfer Estimate**

• Token: `{token}`
• Amount: `{amount}`
• To: `{to_address[:6]}...{to_address[-4:]}`
• Gas: `{gas_est['gas_estimate']} units`
• Gas Price: `{gas_est['avg_gas_price_gwei']:.2f} GWEI`
• Est. Gas Cost: `{gas_est['estimated_gas_cost_gwei']:.4f} GWEI`

Proceeding with transfer...
"""
        
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
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=receipt_msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"Error in transfer handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)[:200]}",
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
