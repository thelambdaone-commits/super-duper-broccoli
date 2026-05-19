"""
Telegram message safety and formatting helpers.

Provides secure message formatting, escape utilities, and best-practice patterns
for python-telegram-bot >= 20.0.

Reference: https://docs.python-telegram-bot.org/en/stable/
"""

from typing import Optional, Sequence
from telegram.helpers import escape_markdown_v2
from telegram.constants import ParseMode


def safe_markdown_v2(text: str) -> str:
    """
    Safely escape text for Markdown V2 parsing.
    
    This is the **correct** way to include user data in Markdown V2 messages.
    
    Args:
        text: Raw text that may contain special characters
        
    Returns:
        Escaped text safe for ParseMode.MARKDOWN_V2
        
    Example:
        >>> ticker = "BTC_USD"
        >>> price = "50,000.00"
        >>> msg = f"Buy *{safe_markdown_v2(ticker)}* @ {safe_markdown_v2(price)}"
    """
    return escape_markdown_v2(text)


def safe_format_trade(
    ticker: str,
    action: str,
    price: float,
    amount: Optional[float] = None,
    edge: Optional[float] = None,
) -> str:
    """
    Format a trading signal message safely.
    
    Args:
        ticker: Asset ticker (e.g., "BTC", "SOL")
        action: Trade action ("BUY", "SELL", "HOLD")
        price: Entry/current price
        amount: Optional amount
        edge: Optional edge percentage
        
    Returns:
        Safe Markdown V2 formatted message
        
    Example:
        >>> msg = safe_format_trade("BTC_USD", "BUY", 50000.5, amount=0.1, edge=0.05)
        >>> # Output: *BTC_USD* 🔴 **BUY** @ $50000.50 | 0.1 units | +5.0% edge
    """
    ticker_safe = safe_markdown_v2(ticker)
    action_safe = safe_markdown_v2(action)
    price_safe = safe_markdown_v2(f"{price:,.2f}")
    
    emoji = "🟢" if action.upper() == "BUY" else "🔴" if action.upper() == "SELL" else "⚪"
    text = f"{emoji} *{action_safe}* {ticker_safe} @ ${price_safe}"
    
    if amount is not None:
        amount_safe = safe_markdown_v2(f"{amount:.4f}")
        text += f" | {amount_safe} units"
    
    if edge is not None:
        edge_pct = edge * 100
        edge_safe = safe_markdown_v2(f"{edge_pct:.2f}%")
        text += f" | {edge_safe} edge"
    
    return text


def safe_format_market(
    market_name: str,
    probability: float,
    volume: Optional[float] = None,
    liquidity: Optional[str] = None,
) -> str:
    """
    Format market information safely.
    
    Args:
        market_name: Market name/description
        probability: Market probability (0-1)
        volume: Optional 24h volume
        liquidity: Optional liquidity level
        
    Returns:
        Safe Markdown V2 formatted message
    """
    market_safe = safe_markdown_v2(market_name)
    prob_pct = probability * 100
    prob_safe = safe_markdown_v2(f"{prob_pct:.1f}%")
    
    text = f"📊 *{market_safe}*\nProbability: {prob_safe}"
    
    if volume is not None:
        volume_safe = safe_markdown_v2(f"${volume:,.0f}")
        text += f"\nVolume: {volume_safe}"
    
    if liquidity is not None:
        liquidity_safe = safe_markdown_v2(liquidity)
        text += f"\nLiquidity: {liquidity_safe}"
    
    return text


def safe_format_wallet(
    address: str,
    balance: float,
    currency: str = "USDC",
    status: str = "ACTIVE",
) -> str:
    """
    Format wallet information safely.
    
    Args:
        address: Wallet address (will be shortened)
        balance: Wallet balance
        currency: Currency code
        status: Wallet status
        
    Returns:
        Safe Markdown V2 formatted message
    """
    # Shorten address for display (first 6 + last 4)
    if len(address) > 10:
        addr_display = f"{address[:6]}...{address[-4:]}"
    else:
        addr_display = address
    
    addr_safe = safe_markdown_v2(addr_display)
    balance_safe = safe_markdown_v2(f"{balance:,.2f}")
    currency_safe = safe_markdown_v2(currency)
    status_safe = safe_markdown_v2(status)
    
    emoji = "✅" if status.upper() == "ACTIVE" else "⏸️" if status.upper() == "PAUSED" else "❌"
    
    return (
        f"{emoji} *Wallet:* {addr_safe}\n"
        f"Balance: {balance_safe} {currency_safe}\n"
        f"Status: {status_safe}"
    )


def safe_format_error(error_type: str, message: str, context: Optional[str] = None) -> str:
    """
    Format error message safely (without exposing internal details).
    
    Args:
        error_type: Error type (e.g., "ValidationError", "NetworkError")
        message: User-friendly error message
        context: Optional context about what failed
        
    Returns:
        Safe Markdown V2 formatted error message
    """
    error_safe = safe_markdown_v2(error_type)
    msg_safe = safe_markdown_v2(message)
    
    text = f"❌ *{error_safe}*\n{msg_safe}"
    
    if context:
        context_safe = safe_markdown_v2(context)
        text += f"\n_Context: {context_safe}_"
    
    return text


def safe_code_block(code: str, language: str = "") -> str:
    """
    Format code safely in a code block.
    
    Args:
        code: Code to display
        language: Optional language for syntax highlighting
        
    Returns:
        Markdown V2 code block
        
    Note:
        Code blocks don't require escaping, but are wrapped safely.
    """
    # Code blocks are safe from markup, but we still escape for safety
    code_safe = escape_markdown_v2(code)
    if language:
        language_safe = escape_markdown_v2(language)
        return f"```{language_safe}\n{code_safe}\n```"
    return f"```\n{code_safe}\n```"


def split_and_escape(
    text: str,
    limit: int = 3900,
) -> Sequence[str]:
    """
    Split a message into safe chunks while respecting Markdown V2 escaping.
    
    Args:
        text: Text to split (already escaped if needed)
        limit: Maximum characters per chunk (default 3900 for safety margin)
        
    Returns:
        List of message chunks
        
    Note:
        Assumes input is already escaped if it contains Markdown V2 formatting.
    """
    if len(text) <= limit:
        return [text]
    
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append("".join(current).rstrip())
                current = []
                current_len = 0
            # Split long lines
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit].rstrip())
            continue
        
        if current_len + len(line) > limit:
            chunks.append("".join(current).rstrip())
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)
    
    if current:
        chunks.append("".join(current).rstrip())
    
    return [chunk for chunk in chunks if chunk]


# ============================================================================
# Backward compatibility with existing code
# ============================================================================

def escape_text(text: str) -> str:
    """Alias for safe_markdown_v2 for backward compatibility."""
    return safe_markdown_v2(text)


# ============================================================================
# Constants for use in messages
# ============================================================================

EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_WARNING = "⚠️"
EMOJI_INFO = "ℹ️"
EMOJI_WAITING = "⏳"

PARSE_MODE_DEFAULT = ParseMode.MARKDOWN_V2  # Always use V2
