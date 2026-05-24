from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from utils.config_loader import get_health_config

logger = logging.getLogger("ResourceGovernor")


@dataclass(frozen=True)
class ResourceSnapshot:
    timestamp: float
    cpu_percent: float | None
    memory_percent: float | None
    rss_mb: float | None
    gpu_util_percent: float | None
    gpu_memory_percent: float | None
    mode: str
    reasons: tuple[str, ...]


class ResourceGovernor:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = ResourceSnapshot(time.time(), None, None, None, None, None, "nominal", ())
        self._sample_interval_seconds = float(get_health_config("resource_sample_interval_seconds", 5.0))
        self._last_sample_ts = 0.0
        self._profile_multipliers = {
            "nominal": {"latency": 1.0, "normal": 1.0, "heavy": 1.0},
            "constrained": {"latency": 1.25, "normal": 1.75, "heavy": 3.0},
            "critical": {"latency": 2.0, "normal": 3.0, "heavy": 6.0},
        }

    def current_snapshot(self) -> ResourceSnapshot:
        with self._lock:
            return self._snapshot

    def sample_if_due(self, *, force: bool = False) -> ResourceSnapshot:
        now = time.time()
        with self._lock:
            if not force and (now - self._last_sample_ts) < self._sample_interval_seconds:
                return self._snapshot
            snapshot = self._collect_snapshot(now)
            self._snapshot = snapshot
            self._last_sample_ts = now
            return snapshot

    def interval_multiplier(self, profile: str) -> float:
        snapshot = self.current_snapshot()
        profile_map = self._profile_multipliers.get(snapshot.mode, self._profile_multipliers["nominal"])
        return float(profile_map.get(profile, profile_map["normal"]))

    def should_skip_job(self, profile: str) -> bool:
        snapshot = self.current_snapshot()
        return snapshot.mode == "critical" and profile == "heavy"

    def _collect_snapshot(self, timestamp: float) -> ResourceSnapshot:
        cpu_percent, memory_percent, rss_mb = self._read_process_resources()
        gpu_util_percent, gpu_memory_percent = self._read_gpu_resources()
        mode, reasons = self._classify(cpu_percent, memory_percent, gpu_util_percent, gpu_memory_percent)
        snapshot = ResourceSnapshot(
            timestamp=timestamp,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            rss_mb=rss_mb,
            gpu_util_percent=gpu_util_percent,
            gpu_memory_percent=gpu_memory_percent,
            mode=mode,
            reasons=tuple(reasons),
        )
        if snapshot.mode != "nominal":
            logger.warning("Resource governor mode=%s cpu=%s mem=%s gpu=%s gpu_mem=%s reasons=%s",
                           snapshot.mode, cpu_percent, memory_percent, gpu_util_percent, gpu_memory_percent, list(snapshot.reasons))
        return snapshot

    def _classify(
        self,
        cpu_percent: float | None,
        memory_percent: float | None,
        gpu_util_percent: float | None,
        gpu_memory_percent: float | None,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        critical = False
        constrained = False

        cpu_warn = float(get_health_config("cpu_warning_percent", 80.0))
        cpu_critical = float(get_health_config("cpu_critical_percent", 92.0))
        mem_warn = float(get_health_config("memory_warning_percent", 80.0))
        mem_critical = float(get_health_config("memory_critical_percent", 90.0))
        gpu_warn = float(get_health_config("gpu_warning_percent", 85.0))
        gpu_critical = float(get_health_config("gpu_critical_percent", 95.0))
        gpu_mem_warn = float(get_health_config("gpu_memory_warning_percent", 85.0))
        gpu_mem_critical = float(get_health_config("gpu_memory_critical_percent", 95.0))

        if cpu_percent is not None:
            if cpu_percent >= cpu_critical:
                critical = True
                reasons.append(f"cpu>={cpu_critical}")
            elif cpu_percent >= cpu_warn:
                constrained = True
                reasons.append(f"cpu>={cpu_warn}")
        if memory_percent is not None:
            if memory_percent >= mem_critical:
                critical = True
                reasons.append(f"mem>={mem_critical}")
            elif memory_percent >= mem_warn:
                constrained = True
                reasons.append(f"mem>={mem_warn}")
        if gpu_util_percent is not None:
            if gpu_util_percent >= gpu_critical:
                critical = True
                reasons.append(f"gpu>={gpu_critical}")
            elif gpu_util_percent >= gpu_warn:
                constrained = True
                reasons.append(f"gpu>={gpu_warn}")
        if gpu_memory_percent is not None:
            if gpu_memory_percent >= gpu_mem_critical:
                critical = True
                reasons.append(f"gpu_mem>={gpu_mem_critical}")
            elif gpu_memory_percent >= gpu_mem_warn:
                constrained = True
                reasons.append(f"gpu_mem>={gpu_mem_warn}")

        if critical:
            return "critical", reasons
        if constrained:
            return "constrained", reasons
        return "nominal", reasons

    def _read_process_resources(self) -> tuple[float | None, float | None, float | None]:
        try:
            import psutil

            process = psutil.Process(os.getpid())
            cpu_percent = psutil.cpu_percent(interval=None)
            memory_percent = psutil.virtual_memory().percent
            rss_mb = process.memory_info().rss / (1024.0 * 1024.0)
            return float(cpu_percent), float(memory_percent), float(rss_mb)
        except Exception:
            return None, None, None

    def _read_gpu_resources(self) -> tuple[float | None, float | None]:
        gpu = self._read_gpu_resources_pynvml()
        if gpu != (None, None):
            return gpu
        gpu = self._read_gpu_resources_nvidia_smi()
        if gpu != (None, None):
            return gpu
        return self._read_gpu_resources_torch()

    def _read_gpu_resources_pynvml(self) -> tuple[float | None, float | None]:
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return float(util.gpu), (float(mem.used) / float(mem.total) * 100.0) if mem.total else None
        except Exception:
            return None, None

    def _read_gpu_resources_nvidia_smi(self) -> tuple[float | None, float | None]:
        if shutil.which("nvidia-smi") is None:
            return None, None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=True,
                timeout=2.0,
            )
            first = (result.stdout or "").strip().splitlines()[0]
            gpu_str, used_str, total_str = [part.strip() for part in first.split(",")]
            total = float(total_str)
            used = float(used_str)
            return float(gpu_str), (used / total * 100.0) if total else None
        except Exception:
            return None, None

    def _read_gpu_resources_torch(self) -> tuple[float | None, float | None]:
        try:
            import torch

            if not torch.cuda.is_available():
                return None, None
            index = torch.cuda.current_device()
            props = torch.cuda.get_device_properties(index)
            total = float(getattr(props, "total_memory", 0.0) or 0.0)
            reserved = float(torch.cuda.memory_reserved(index))
            return None, (reserved / total * 100.0) if total else None
        except Exception:
            return None, None


_RESOURCE_GOVERNOR: ResourceGovernor | None = None


def get_resource_governor() -> ResourceGovernor:
    global _RESOURCE_GOVERNOR
    if _RESOURCE_GOVERNOR is None:
        _RESOURCE_GOVERNOR = ResourceGovernor()
    return _RESOURCE_GOVERNOR
