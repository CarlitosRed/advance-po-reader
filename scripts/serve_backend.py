"""Guarded entry point for the local website/backend (used by start-backend.ps1 and start-local-website.ps1).

Same server as the plain backend entry point. When live processing is enabled it additionally
refuses the published default API token and applies the same spend cap as the POC
(SpendGuard: at most PO_POC_MAX_LIVE_RUNS live runs, default 5, and the dollar cap when prices are set).
Free mode (live processing off) is unchanged. Nothing here prints a key or token.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import poc_live_support as live  # noqa: E402


def build_app(settings):
    """The backend app; with live processing on, only behind the private-token check and the spend cap."""
    from backend.app import create_app
    if not settings.live_processing_enabled:
        return create_app(settings)
    if settings.local_api_token.get_secret_value() == live.DEFAULT_TOKEN:
        raise live.LiveRefusal("Live processing needs a private local API token in this desk's ignored .env.backend "
                               "(PO_BACKEND_LOCAL_API_TOKEN, at least 16 characters, not the shared default). "
                               "Nothing was started.")
    from gate_a.database import create_db_engine
    engine = create_db_engine(settings.database_url.get_secret_value(), 5)
    app = create_app(settings, engine=engine)
    live.install_live_guard(app, live.SpendGuard(engine))
    return app


def main():
    from backend.config import Settings
    try:
        settings = Settings()
    except Exception:
        print("The server settings could not be loaded. Check this desk's .env.backend for typos "
              "(values are never printed). Nothing was started.", flush=True)
        sys.exit(2)
    try:
        app = build_app(settings)
    except live.LiveRefusal as refusal:
        print(refusal, flush=True)
        sys.exit(2)
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
