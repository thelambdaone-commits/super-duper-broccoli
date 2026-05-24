import asyncio
import logging
import time
import json

try:
    import uvicorn
except ModuleNotFoundError:
    uvicorn = None

try:
    from fastapi import FastAPI, Response, status
except ModuleNotFoundError:
    FastAPI = None
    Response = None

    class _Status:
        HTTP_503_SERVICE_UNAVAILABLE = 503

    status = _Status()

    class _FallbackResponse:
        def __init__(self, content: str, media_type: str, status_code: int) -> None:
            self.content = content
            self.media_type = media_type
            self.status_code = status_code
            self.body = content.encode("utf-8")

logger = logging.getLogger("HealthMonitor")

if FastAPI is not None:
    app = FastAPI(title="LOBSTAR Diagnostic Health Check Probe")
else:
    app = None

_orchestrator = None
_runner = None


def get_liveness():
    global _orchestrator, _runner

    orchestrator_status = "UP"
    if not _orchestrator or not _orchestrator._queue_worker_task or _orchestrator._queue_worker_task.done():
        orchestrator_status = "DOWN"

    runner_status = "UP"
    if not _runner or not _runner._is_running:
        runner_status = "DOWN"

    status_dict = {
        "status": "UP" if (orchestrator_status == "UP" and runner_status == "UP") else "DOWN",
        "timestamp": time.time(),
        "components": {
            "orchestrator": orchestrator_status,
            "quantum_runner": runner_status,
        },
        "runtime": {
            "runner_jobs": _runner.get_job_stats() if _runner and hasattr(_runner, "get_job_stats") else {},
        },
    }

    if status_dict["status"] == "DOWN":
        if Response is not None:
            return Response(
                content=json.dumps(status_dict),
                media_type="application/json",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        return _FallbackResponse(
            content=json.dumps(status_dict),
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return status_dict


if app is not None:
    app.get("/health")(get_liveness)
    app.get("/liveness")(get_liveness)


class LobstarHealthMonitor:
    def __init__(self, orchestrator, runner, port: int = 8080) -> None:
        self.orchestrator = orchestrator
        self.runner = runner
        self.port = port
        self._server = None
        self._server_task = None

    def start(self) -> None:
        if uvicorn is None or app is None:
            logger.warning("Health monitor disabled: web health dependencies are not installed.")
            return
        global _orchestrator, _runner
        _orchestrator = self.orchestrator
        _runner = self.runner

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
            loop="asyncio"
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        logger.info(f"🏥 [HEALTH MONITOR] Diagnostic liveness probe listening on HTTP port {self.port}")

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
            self._server.force_exit = True
        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            logger.info("🏥 [HEALTH MONITOR] Diagnostic web service stopped.")
