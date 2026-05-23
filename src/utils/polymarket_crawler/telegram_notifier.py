import warnings

warnings.warn(
    "crawler.telegram_notifier is deprecated, use telegram.signal_notifier instead",
    DeprecationWarning,
    stacklevel=2,
)

from telegram.signal_notifier import send_wallet_signals

__all__ = ["send_wallet_signals"]
