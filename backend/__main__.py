"""Loopback server; no database migration or provider request on startup.

Live processing is never started from here: the live entry points add the spend cap and
private-token checks that this generic launcher does not have.
"""
import sys

import uvicorn
from backend.app import create_app
from backend.config import Settings

LIVE_REFUSAL = ("Live processing is enabled, so this launcher will not start. Start live mode with "
                "scripts/serve_backend.py or scripts/start-poc-demo.ps1 -Live.")


def main(settings: Settings | None = None) -> int:
    settings = settings or Settings()
    if settings.live_processing_enabled:
        print(LIVE_REFUSAL, file=sys.stderr)
        return 2
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
