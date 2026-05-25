from __future__ import annotations

import re
from types import SimpleNamespace

from interface.command_router import COMMAND_REGISTRY, CommandRouter


class _FakeApplication:
    def __init__(self) -> None:
        self.handlers = []

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)


def _registered_commands(router: CommandRouter) -> set[str]:
    commands: set[str] = set()
    for handler in router.app.handlers:
        for command in getattr(handler, "commands", []):
            commands.add(str(command))
    return commands


def test_command_registry_handlers_exist() -> None:
    missing = [
        (name, meta["func"])
        for name, meta in COMMAND_REGISTRY.items()
        if not hasattr(CommandRouter, meta["func"])
    ]
    assert missing == []


def test_register_all_registers_every_registry_command_and_aliases() -> None:
    app = _FakeApplication()
    listener = SimpleNamespace(application=app, access_control=None)
    router = CommandRouter(listener)

    router.register_all()

    commands = _registered_commands(router)
    expected = set(COMMAND_REGISTRY)
    expected.update({"man", "help"})

    for asset in ("btc", "eth", "sol", "xrp", "hype", "doge", "bnb", "ada", "avax", "link", "sui", "pepe", "wif", "ton", "near"):
        expected.add(asset)
        for suffix in ("5", "15", "1h", "4h", "1d"):
            expected.add(f"{asset}{suffix}")

    assert expected.issubset(commands)


def test_lobstar_listener_sensitive_wallet_commands_are_not_registered_directly() -> None:
    source = open("src/interface/telegram_listener.py", "r", encoding="utf-8").read()

    assert re.search(r'^\s*self\.application\.add_handler\(CommandHandler\("gen", self\._cmd_gen\)\)', source, re.M) is None
    assert re.search(r'^\s*self\.application\.add_handler\(CommandHandler\("generate_wallet", self\._cmd_gen\)\)', source, re.M) is None
    assert re.search(r'^\s*self\.application\.add_handler\(CommandHandler\("import", self\._cmd_import\)\)', source, re.M) is None
