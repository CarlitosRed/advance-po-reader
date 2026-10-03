"""Run the foundation on the validated local bind address."""

import uvicorn

from gate_a.app import create_app
from gate_a.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
