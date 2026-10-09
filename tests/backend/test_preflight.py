"""Key presence cannot trigger a provider call, even in diagnostic mode."""
import httpx
from pydantic import SecretStr

from backend.config import Settings
from backend.preflight import report


def test_preflight_reads_only_loopback_and_hides_key_and_local_token():
    calls=[]
    settings=Settings(_env_file=None,openai_api_key=SecretStr("fake-provider-secret-marker"),
        local_api_token=SecretStr("fake-local-token-marker"),live_processing_enabled=False)
    def handler(request):
        calls.append(request)
        assert request.url.host=="127.0.0.1" and request.url.path=="/website/readiness"
        return httpx.Response(200,json={"ready_for_live_demo":False,"provider_configured":False})
    value=report(settings,transport=httpx.MockTransport(handler))
    assert len(calls)==1 and value["external_provider_requests"]==0
    assert value["server_key_present_in_configuration"] is True
    assert "fake-provider-secret-marker" not in str(value) and "fake-local-token-marker" not in str(value)


def test_preflight_connection_failure_is_safe():
    def handler(request): raise httpx.ConnectError("fake-secret-error-marker",request=request)
    value=report(Settings(_env_file=None,openai_api_key=None),transport=httpx.MockTransport(handler))
    assert value["local_error"]=="local_website_unavailable"
    assert "fake-secret-error-marker" not in str(value)
