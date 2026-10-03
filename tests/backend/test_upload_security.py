"""Decode the actual content and enforce privacy boundaries without a DB/key."""
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
import pymupdf
import pytest
from pydantic import SecretStr, ValidationError

from backend.app import create_app
from backend.config import Settings, ROOT
from backend.errors import BackendError
from backend.synthetic import generate_fixture
from backend.uploads import validate_file, write_source, read_source, digest


@pytest.fixture
def settings():
    folder = ROOT / "data" / "root-tests" / uuid4().hex
    cfg = Settings(_env_file=None, local_api_token=SecretStr("test-token-long-enough"), storage_directory=folder)
    yield cfg
    if folder.exists():
        shutil.rmtree(folder)


@pytest.mark.parametrize("media", ["application/pdf", "image/png"])
def test_real_content_decodes_and_storage_verifies_hash(settings, media):
    content = generate_fixture(media_type=media)
    result = validate_file(content, settings)
    assert result["media_type"] == media and result["page_count"] == 1
    reference = write_source(settings.storage_directory, content)
    assert len(reference) == 32 and "." not in reference
    assert read_source(settings.storage_directory, reference, digest(content)) == content
    (settings.storage_directory / reference).write_bytes(b"changed")
    with pytest.raises(BackendError, match="source_integrity_failed"):
        read_source(settings.storage_directory, reference, digest(content))


@pytest.mark.parametrize("content", [b"", b"arbitrary text", b"%PDF-1.7\n%%EOF", b"\x89PNG\r\n\x1a\ninvalid"])
def test_malformed_actual_content_rejected(settings, content):
    with pytest.raises(BackendError):
        validate_file(content, settings)


def test_size_limit_checks_before_decode(settings):
    with pytest.raises(BackendError, match="upload_too_large"):
        validate_file(b"x" * (settings.max_upload_bytes + 1), settings)


def test_pdf_page_limit_encryption_and_malformed_trailer(settings):
    with pymupdf.open() as pdf:
        for _ in range(2):
            pdf.new_page()
        content = pdf.tobytes()
        encrypted = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    small = settings.model_copy(update={"max_pages": 1})
    with pytest.raises(BackendError, match="pdf_page_limit"):
        validate_file(content, small)
    with pytest.raises(BackendError, match="encrypted_pdf"):
        validate_file(encrypted, settings)
    with pytest.raises(BackendError, match="malformed_pdf"):
        validate_file(content.split(b"%%EOF")[0], settings)


def test_image_dimension_limits_and_unsupported_gif(settings):
    with BytesIO() as stream:
        Image.new("RGB", (101, 50), "white").save(stream, format="PNG")
        data = stream.getvalue()
    with pytest.raises(BackendError, match="image_dimension_limit"):
        validate_file(data, settings.model_copy(update={"max_image_dimension": 100}))
    with BytesIO() as stream:
        Image.new("RGB", (10, 10)).save(stream, format="GIF")
        with pytest.raises(BackendError, match="unsupported_media_type"):
            validate_file(stream.getvalue(), settings)


def test_decode_timeout_is_sanitized(settings, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private-source secret", 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(BackendError) as caught:
        validate_file(b"private-source", settings)
    assert caught.value.code == "file_decode_failed_or_timed_out"


@pytest.mark.parametrize("reference", ["../../escape", "filename.pdf", "a" * 31, "A" * 32])
def test_opaque_storage_references_only(settings, reference):
    with pytest.raises(BackendError, match="invalid_storage_reference"):
        read_source(settings.storage_directory, reference, "a" * 64)


@pytest.mark.parametrize("database", ["gate_a_service", "gate_a", "production"])
def test_database_config_cannot_target_gate_a_or_unrelated_database(database):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr(f"postgresql+psycopg://user:private@127.0.0.1:5432/{database}"))


def test_nonloopback_and_public_storage_refused(tmp_path):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr("postgresql+psycopg://user:secret@remote/gate_a_backend_dev"))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_directory=tmp_path)


def test_browser_token_host_origin_and_streaming_request_limits(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8012") as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/configuration").json()["provider_configured"] is False
        assert client.post("/tenants", json={"name": "Example"}).status_code == 401
        headers = {"X-Local-Token": "test-token-long-enough", "Origin": "https://evil.example"}
        assert client.post("/tenants", headers=headers, json={"name": "Example"}).status_code == 403
        headers["Origin"] = "http://127.0.0.1:8013"
        assert client.post("/tenants", headers=headers, json={"name": "Example"}).status_code == 403
        del headers["Origin"]
        headers["Sec-Fetch-Site"] = "cross-site"
        assert client.post("/tenants", headers=headers, json={"name": "Example"}).status_code == 403
        assert client.get("/health/live", headers={"Host": "rebinding.example"}).status_code == 403
        headers.pop("Sec-Fetch-Site")
        body = (b"x" * 65536 for _ in range(162))
        assert client.post("/documents", headers=headers, content=body).status_code == 413


def test_validation_does_not_echo_private_input(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8012") as client:
        response = client.post("/tenants", headers={"X-Local-Token": "test-token-long-enough"},
                               json={"name": "", "private_data": "secret-source-value"})
        assert response.status_code == 422
        assert "secret-source-value" not in response.text
        response = client.post("/tenants", headers={"X-Local-Token": "test-token-long-enough"},
                               json={"name": "", "sk-proj-SENTINEL": "private source"})
        assert response.status_code == 422
        assert "sk-proj-SENTINEL" not in response.text and "private source" not in response.text
