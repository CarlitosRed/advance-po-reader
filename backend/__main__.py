"""Loopback server; no database migration or provider request on startup."""
import uvicorn
from backend.app import create_app
from backend.config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)
