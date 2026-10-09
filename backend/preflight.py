"""Read-only local demo diagnostics. Never makes an external provider request."""
import argparse
import json

import httpx

from backend.config import Settings
from reader_agent.connection import ConnectionSettings


def report(settings=None, *, transport=None):
    settings = settings or Settings()
    connection = ConnectionSettings(_env_file=None, host=settings.host, port=settings.port,
                                    local_api_token=settings.local_api_token)
    result = {"server_url": connection.base_url,
              "server_key_present_in_configuration": bool(settings.openai_api_key and settings.openai_api_key.get_secret_value().strip()),
              "configured_live_switch": settings.live_processing_enabled,
              "external_provider_requests": 0, "running_server": None}
    try:
        with httpx.Client(base_url=connection.base_url, headers={
                "X-Local-Token": connection.local_api_token.get_secret_value()},
                trust_env=False, follow_redirects=False, timeout=5, transport=transport) as client:
            response = client.get("/website/readiness")
            if response.status_code == 200:
                result["running_server"] = response.json()
            else:
                result["local_error"] = f"local_http_{response.status_code}"
    except (httpx.HTTPError, ValueError):
        result["local_error"] = "local_website_unavailable"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-live", action="store_true", help="Exit nonzero until the running local server is ready for a live demo")
    args = parser.parse_args()
    result = report()
    print(json.dumps(result, indent=2))
    if args.require_live and not (result["running_server"] or {}).get("ready_for_live_demo"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
