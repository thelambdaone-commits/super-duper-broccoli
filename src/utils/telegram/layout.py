from __future__ import annotations

import html
from typing import Any

SEP = "───────────────────"
SEP_WIDE = "━━━━━━━━━━━━━━━━━━━━"

def html_url(url: str, label: str = "") -> str:
    """<a href='url'>label</a> — lien cliquable Telegram HTML."""
    if not label:
        # fallback: afficher host + début
        label = url.replace("https://", "").split("/")[0]
    return f"<a href='{html.escape(url)}'>{html.escape(label)}</a>"

def wallet_url_short(wallet: str) -> str:
    full = f"https://polymarket.com/profile/{wallet}"
    short = f"{wallet[:6]}...{wallet[-4:]}"
    return f"<a href='{full}'>{short}</a>"

def _html(value: Any) -> str:
    """Helper global pour échapper le HTML."""
    return html.escape(str(value if value is not None else ""), quote=False)
