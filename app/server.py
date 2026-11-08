"""Container entry point: mark readiness false as soon as a stop signal arrives."""
from time import monotonic
import sys

import uvicorn

from app.main import app
from app.config import Settings


class ExtractorServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        app.state.shutting_down = True
        app.state.shutdown_started = monotonic()
        super().handle_exit(sig, frame)


def run_server() -> int:
    graceful_timeout = Settings.from_env().graceful_shutdown_timeout_seconds
    server = ExtractorServer(uvicorn.Config(app, host="0.0.0.0", port=8000,
                                   timeout_graceful_shutdown=max(1, int(graceful_timeout))))
    app.state.server = server
    server.run()
    return 70 if getattr(app.state, "worker_broken", False) else 0


if __name__ == "__main__":
    sys.exit(run_server())
