"""Container entry point: mark readiness false as soon as a stop signal arrives."""
from time import monotonic

import uvicorn

from app.main import app
from app.config import Settings


class ExtractorServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        app.state.shutting_down = True
        app.state.shutdown_started = monotonic()
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    graceful_timeout = Settings.from_env().graceful_shutdown_timeout_seconds
    ExtractorServer(uvicorn.Config(app, host="0.0.0.0", port=8000,
                                   timeout_graceful_shutdown=max(1, int(graceful_timeout)))).run()
