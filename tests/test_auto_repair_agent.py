from __future__ import annotations

from core.auto_repair_agent import build_test_command, collect_failures, infer_targeted_tests, redact_secrets


def test_collect_failures_classifies_import_and_syntax_errors() -> None:
    output = """
E   ModuleNotFoundError: No module named 'hvac'
E   SyntaxError: invalid syntax
    """
    failures = collect_failures(output)

    assert "import" in failures
    assert "syntax" in failures


def test_infer_targeted_tests_extracts_failed_files() -> None:
    output = """
FAILED tests/test_config_loader.py::test_loads_config_from_json_and_honors_env_override
ERROR collecting tests/test_main_agentic_clob.py
    """
    targets = infer_targeted_tests(output)

    assert targets == ["tests/test_config_loader.py", "tests/test_main_agentic_clob.py"]


def test_redact_secrets_masks_common_token_patterns() -> None:
    text = "token sk-abc1234567890123456789 and gsk_abc1234567890123456789 and 0x" + "a" * 64
    redacted = redact_secrets(text)

    assert "sk-abc1234567890123456789" not in redacted
    assert "gsk_abc1234567890123456789" not in redacted
    assert "0x" + "a" * 64 not in redacted


def test_build_test_command_targets_specific_files() -> None:
    cmd = build_test_command(["tests/test_config_loader.py", "tests/test_auto_repair_agent.py"])

    assert "tests/test_config_loader.py" in cmd
    assert "tests/test_auto_repair_agent.py" in cmd
