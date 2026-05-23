from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger("PMXTAdapterService")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PMXT_DIR = PROJECT_ROOT / "scripts" / "pmxt_adapter"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@dataclass(slots=True)
class PMXTAdapterConfig:
    enabled: bool = os.getenv("PMXT_ADAPTER_ENABLED", "true").lower() == "true"
    auto_interval_seconds: int = int(os.getenv("PMXT_ADAPTER_INTERVAL_SECONDS", "1800"))
    data_dir: Path = Path(os.getenv("PMXT_DATA_DIR", PROJECT_ROOT / "data" / "pmxt"))

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def converted_dir(self) -> Path:
        return self.data_dir / "converted"

    @property
    def side_map_path(self) -> Path:
        return self.data_dir / "side_map.json"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def state_path(self) -> Path:
        return self.state_dir / "pmxt_adapter_state.json"


class PMXTAdapterService:
    def __init__(self, config: PMXTAdapterConfig | None = None) -> None:
        self.config = config or PMXTAdapterConfig()
        self._v2_adapter = None
        self._gamma_adapter = None
        self._lock = asyncio.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.config.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.config.converted_dir.mkdir(parents=True, exist_ok=True)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)

    def _read_state(self) -> dict[str, Any]:
        if not self.config.state_path.exists():
            return {
                "processed_files": {},
                "last_run_at": 0.0,
                "last_success_at": 0.0,
                "last_error": "",
                "last_stats": {},
            }
        try:
            return json.loads(self.config.state_path.read_text())
        except Exception:
            return {
                "processed_files": {},
                "last_run_at": 0.0,
                "last_success_at": 0.0,
                "last_error": "state_read_failed",
                "last_stats": {},
            }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.config.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def _deps_status(self) -> dict[str, bool]:
        return {
            "polars": importlib.util.find_spec("polars") is not None,
            "pyarrow": importlib.util.find_spec("pyarrow") is not None,
        }

    def _ensure_modules_loaded(self) -> None:
        deps = self._deps_status()
        if not all(deps.values()):
            missing = [name for name, present in deps.items() if not present]
            raise RuntimeError(f"pmxt dependencies missing: {', '.join(missing)}")
        if self._v2_adapter is None:
            self._v2_adapter = _load_module(
                "pmxt_v2_to_v1_adapter",
                PMXT_DIR / "v2_to_v1_adapter.py",
            )
        if self._gamma_adapter is None:
            self._gamma_adapter = _load_module(
                "pmxt_extend_side_map_gamma",
                PMXT_DIR / "extend_side_map_gamma.py",
            )

    def status(self) -> dict[str, Any]:
        state = self._read_state()
        deps = self._deps_status()
        incoming_files = sorted(self.config.incoming_dir.glob("*.parquet"))
        converted_files = sorted(self.config.converted_dir.glob("*.parquet"))
        return {
            "enabled": self.config.enabled,
            "dependencies": deps,
            "adapter_files_present": all(
                (PMXT_DIR / filename).exists()
                for filename in ("v2_to_v1_adapter.py", "extend_side_map_gamma.py")
            ),
            "incoming_dir": str(self.config.incoming_dir),
            "converted_dir": str(self.config.converted_dir),
            "side_map_path": str(self.config.side_map_path),
            "side_map_exists": self.config.side_map_path.exists(),
            "incoming_file_count": len(incoming_files),
            "converted_file_count": len(converted_files),
            "last_run_at": state.get("last_run_at", 0.0),
            "last_success_at": state.get("last_success_at", 0.0),
            "last_error": state.get("last_error", ""),
            "processed_count": len(state.get("processed_files", {})),
            "last_stats": state.get("last_stats", {}),
        }

    async def run_cycle(self, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._run_cycle_blocking, force)

    def _run_cycle_blocking(self, force: bool = False) -> dict[str, Any]:
        state = self._read_state()
        state["last_run_at"] = time.time()
        state["last_error"] = ""
        if not self.config.enabled and not force:
            self._write_state(state)
            return {"status": "SKIPPED", "reason": "disabled"}

        try:
            self._ensure_modules_loaded()

            processed_files = state.setdefault("processed_files", {})
            stats: dict[str, Any] = {"processed": [], "skipped": [], "failed": []}

            for v2_file in sorted(self.config.incoming_dir.glob("*.parquet")):
                output_file = self.config.converted_dir / v2_file.name
                file_key = v2_file.name
                if output_file.exists() and not force:
                    stats["skipped"].append(file_key)
                    processed_files.setdefault(file_key, {"output": str(output_file)})
                    continue

                condition_ids_file = self.config.state_dir / f"{v2_file.stem}.condition_ids.txt"
                self._v2_adapter.extract_market_ids([v2_file], condition_ids_file)
                market_ids = [
                    line.strip()
                    for line in condition_ids_file.read_text().splitlines()
                    if line.strip()
                ]
                self._gamma_adapter.extend(
                    self.config.side_map_path,
                    market_ids,
                    skip_known=True,
                )
                conversion_stats = self._v2_adapter.convert_file(
                    v2_file,
                    output_file,
                    side_map_path=self.config.side_map_path,
                )
                stats["processed"].append(conversion_stats)
                processed_files[file_key] = {
                    "output": str(output_file),
                    "converted_at": time.time(),
                    "rows_out": conversion_stats.get("rows_out", 0),
                }

            state["last_success_at"] = time.time()
            state["last_stats"] = stats
            self._write_state(state)
            return {
                "status": "OK",
                "processed_count": len(stats["processed"]),
                "skipped_count": len(stats["skipped"]),
                "stats": stats,
            }
        except Exception as e:
            logger.error(f"PMXT cycle failed: {e}")
            state["last_error"] = str(e)
            self._write_state(state)
            return {"status": "FAILED", "reason": str(e)}

    async def download_and_convert(self, stamp: str) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._download_and_convert_blocking, stamp)

    def _download_and_convert_blocking(self, stamp: str) -> dict[str, Any]:
        self._ensure_modules_loaded()
        output_file = self.config.converted_dir / f"polymarket_orderbook_{stamp}.parquet"
        raw_file = self.config.incoming_dir / f"polymarket_orderbook_{stamp}.parquet"
        self._v2_adapter.download_v2(stamp, raw_file)
        condition_ids_file = self.config.state_dir / f"polymarket_orderbook_{stamp}.condition_ids.txt"
        self._v2_adapter.extract_market_ids([raw_file], condition_ids_file)
        market_ids = [
            line.strip()
            for line in condition_ids_file.read_text().splitlines()
            if line.strip()
        ]
        self._gamma_adapter.extend(self.config.side_map_path, market_ids, skip_known=True)
        stats = self._v2_adapter.convert_file(raw_file, output_file, side_map_path=self.config.side_map_path)
        state = self._read_state()
        state["last_run_at"] = time.time()
        state["last_success_at"] = time.time()
        state["last_error"] = ""
        state.setdefault("processed_files", {})[raw_file.name] = {
            "output": str(output_file),
            "converted_at": time.time(),
            "rows_out": stats.get("rows_out", 0),
        }
        state["last_stats"] = {"download_and_convert": stats}
        self._write_state(state)
        return {"status": "OK", "stats": stats}

    def format_status_html(self) -> str:
        status = self.status()
        deps = status["dependencies"]
        dep_text = ", ".join(f"{k}={'OK' if v else 'MISSING'}" for k, v in deps.items())
        return (
            "🗃️ <b>PMXT ADAPTER STATUS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Enabled</b> : <code>{status['enabled']}</code>\n"
            f"• <b>Deps</b> : <code>{dep_text}</code>\n"
            f"• <b>Incoming Files</b> : <code>{status['incoming_file_count']}</code>\n"
            f"• <b>Converted Files</b> : <code>{status['converted_file_count']}</code>\n"
            f"• <b>Side Map</b> : <code>{status['side_map_exists']}</code>\n"
            f"• <b>Processed Count</b> : <code>{status['processed_count']}</code>\n"
            f"• <b>Last Error</b> : <code>{status['last_error'] or 'none'}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

