# AUDIT FIX PLAN — LOBSTAR Quant Agentic Trading Core

**Date:** 2026-05-21
**Auditor:** Automated Deep Audit
**Status:** 625/628 tests passing (99.5%)

---

## Priority Legend

| Priority | Definition |
|----------|------------|
| 🔴 CRITICAL | Blocks production operation or causes data loss |
| 🟡 HIGH   | Degrades functionality, causes test failures, or risks instability |
| 🟠 MEDIUM | Non-blocking improvements, config cleanup, documentation |
| 🟢 LOW    | Nice-to-have, cosmetic, or future-proofing |

---

## 🔴 CRITICAL

### C1. FreqAIEngine: `name 'Side' is not defined` (NameError)

**File:** `core/freqai_engine.py:102,135`
**Impact:** Any call to `clob_execute()` or `post_order()` would crash with a NameError because `Side` (from `py_clob_client`) is not imported. The error was swallowed by a generic `except Exception` handler, returning `"REJECTED"` instead of `"LOCAL_REJECT_MIN_NOTIONAL"`.
**Fix Applied:** Replaced `Side.BUY`/`Side.SELL` with string literals `"BUY"`/`"SELL"` since this version of `py_clob_client` doesn't export a `Side` class.
**Status:** ✅ FIXED

### C2. Wallet reconciliation calls non-existent `sync_capital` on ledger

**File:** `core/health_supervisor_agent.py:236`
**Impact:** The `reconcile_wallet_balances()` method calls `self.ledger.sync_capital(onchain_usdc)` but the test's `FakeLedger` doesn't implement it, causing AttributeError.
**Fix Applied:** Added `sync_capital()` method to `FakeLedger` in `tests/test_health_supervisor_agent.py`
**Status:** ✅ FIXED

---

## 🟡 HIGH

### H1. Integration E2E Tests Fail (3 tests)

**Files:** `tests/integration/test_pipeline_e2e.py`
**Issue:** `signal_decision_service.py` mocks (`SimpleNamespace`) lack `get_open_positions()` and `get_capital_summary()` methods. These are pre-existing failures unrelated to this session's changes.
**Fix Plan:**
1. Add the missing methods to the mock objects in the test file
2. Or refactor tests to use proper `unittest.mock.MagicMock` instead of `SimpleNamespace`
**Estimated Impact:** Low (test-only, no production impact)
**Priority:** 🟡 HIGH (for test completeness)
**Status:** ⏳ NOT YET FIXED

### H2. Core PM2 Process: 17 Restarts

**File:** `ecosystem.config.js`
**Issue:** `quant-agentic-core` process has restarted 17 times (max_restarts=25). This suggests crashes during operation.
**Fix Plan:**
1. Check `logs/pm2-error.log` for crash patterns
2. Common causes: DuckDB locking, Telegram polling timeouts, RPC failures
3. Consider increasing `restart_delay` from 1s to 5s
**Estimated Impact:** Medium (instability in production)
**Priority:** 🟡 HIGH
**Status:** ⏳ INVESTIGATE

### H3. Training pipeline stale (3+ days without training)

**Files:** `user_data/models/training_runs.jsonl`, `scripts/rl_feedback_loop.py`
**Issue:** Last training run was 2026-05-18 (3 days ago). Models may be stale for current market conditions.
**Fix Plan:**
1. Verify `rl_feedback_loop.py` is scheduled (cron/systemd timer)
2. Check for errors in training logs
3. Manually trigger a training cycle: `.venv/bin/python scripts/rl_feedback_loop.py`
**Estimated Impact:** Medium (degraded model accuracy)
**Priority:** 🟡 HIGH
**Status:** ⏳ INVESTIGATE

### H4. Autonomic Healer: `setdefault` instead of direct assignment for RPC failover

**File:** `core/autonomic_healer.py:138`
**Issue:** `os.environ.setdefault("POLYGON_RPC_URL", backup_rpc)` does NOT override when `.env` already sets `POLYGON_RPC_URL`. The backup RPC never takes effect during Alchemy outages.
**Fix Applied:** Changed to `os.environ["POLYGON_RPC_URL"] = backup_rpc`
**Status:** ✅ FIXED

---

## 🟠 MEDIUM

### M1. `training_summary.json` references wrong path

**File:** `user_data/models/training_summary.json`
**Issue:** Points to `/home/.../quant-agentic-trading-core-v2/` instead of current directory. This misleads any tooling that reads this file for model discovery.
**Fix Plan:**
1. Update the `models_dir` and `tracking_file` paths to current directory
**Estimated Impact:** Low (cosmetic, no runtime impact)
**Priority:** 🟠 MEDIUM
**Status:** ⏳ NOT YET FIXED

### M2. Missing `AUTONOMOUS_REAL_EXECUTION_ENABLED` variable

**File:** `.env`
**Issue:** Per previous audit (DEEP_AUDIT_REPORT.md), this env var is "not defined in .env", which blocks autonomous real execution.
**Fix Plan:**
1. Add `AUTONOMOUS_REAL_EXECUTION_ENABLED=0` to `.env` (disabled by default for safety)
2. Only set to `1` after verifying all safety checks pass
**Estimated Impact:** Low (feature not currently used)
**Priority:** 🟠 MEDIUM
**Status:** ⏳ NOT YET FIXED

### M3. ANTHROPIC_API_KEY is a placeholder

**File:** `.env`
**Issue:** Key is `sk-ant-your_anthropic_key_here` — Claude integration non-functional.
**Fix Plan:** Replace with a valid Anthropic API key if Claude integration is needed.
**Estimated Impact:** Low (other LLMs are configured)
**Priority:** 🟠 MEDIUM
**Status:** ⏳ NOT YET FIXED

### M4. `.gitignore` missing IDE directory exclusions

**File:** `.gitignore`
**Issue:** Previous audit flagged missing `.cursor/`, `.vscode/`, `.idea/`, `.antigravity/` entries.
**Fix Plan:** Append IDE exclusion patterns to `.gitignore`.
**Estimated Impact:** Low (prevents accidental commits of IDE metadata)
**Priority:** 🟠 MEDIUM
**Status:** ⏳ NOT YET FIXED

### M5. Brave Search Skill needs full replacement (RSS fallback)

**File:** `agent_skills/brave_search_skill/`
**Issue:** The skill was renamed and functionality replaced with RSS feeds, but the directory name still says "brave_search_skill". The RSS aggregator was using `feedparser` (external dependency).
**Fix Applied:**
- Updated `skill.json` name/description to "News Aggregator Search Skill"
- Rewrote `utils/rss_aggregator.py` to use stdlib only (`urllib` + `xml.etree.ElementTree`)
- Removed `feedparser` dependency from aggregator
- Added `"start"` to `command_router.py` mapping for `/start` command
**Status:** ✅ FIXED

### M6. Command Router missing `/start` handler

**File:** `core/command_router.py`
**Issue:** `LobstarCommandRouter.command_mapping` did not include `"start"`, so `/start` command was silently ignored.
**Fix Applied:** Added `"start": self.display_main_dashboard` to the command mapping.
**Status:** ✅ FIXED

### M7. ProbabilityCalibrator security check blocks test

**File:** `tests/test_telegram_broadcaster.py`
**Issue:** `ProbabilityCalibrator.load()` validates path is within `ALLOWED_DIR` (`user_data/models`), but test saves to `tmp_path` (temp directory).
**Fix Applied:** Added `monkeypatch.setattr(ProbabilityCalibrator, "ALLOWED_DIR", str(tmp_path))` to bypass path check.
**Status:** ✅ FIXED

---

## 🟢 LOW

### L1. Tests produce 33 warnings

**Details:**
- 20 sklearn warning: "X does not have valid feature names"
- 3 RuntimeWarning: "coroutine was never awaited" in signal_executor.py
- Various resource warnings
**Fix Plan:** Address unawaited coroutines and sklearn warnings in test fixtures.
**Estimated Impact:** Minimal

### L2. `.env.example` MODE=PAPER vs `.env` MODE=SHADOW

**Details:** Template says PAPER but live config uses SHADOW (real small-cap execution).
**Fix Plan:** Update `.env.example` to match or add comment explaining difference.
**Estimated Impact:** Minimal

### L3. CONFIGURATION_AUDIT.md is in French

**Details:** Previous audit is entirely in French. This may hinder non-French-speaking team members.
**Fix Plan:** Provide an English translation or bilingual version.
**Estimated Impact:** Minimal

---

## Execution Priority Order

```
1. 🔴 C1, C2   → Already FIXED
2. 🔴 H4       → Already FIXED (setdefault bug)
3. 🟡 H1       → Fix integration test mocks
4. 🟡 H2       → Investigate core crash pattern
5. 🟡 H3       → Restart training pipeline
6. 🟠 M1-M4    → Config cleanup
7. 🟢 L1-L3    → Nice-to-have improvements
```

## Summary

| Category | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| 🔴 CRITICAL | 2 | 2 | 0 |
| 🟡 HIGH | 4 | 1 | 3 |
| 🟠 MEDIUM | 7 | 3 | 4 |
| 🟢 LOW | 3 | 0 | 3 |
| **TOTAL** | **16** | **6** | **10** |
