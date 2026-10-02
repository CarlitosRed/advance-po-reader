"""Bounded decoded uploads and opaque private storage. Filenames are ignored."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from backend.errors import BackendError
from backend.config import ROOT


def private_directory(directory: Path):
    if not directory.resolve().is_relative_to((ROOT / "data").resolve()):
        raise BackendError("invalid_storage_directory", 503)


def validate_file(data: bytes, settings) -> dict:
    if not data:
        raise BackendError("empty_upload", 422)
    if len(data) > settings.max_upload_bytes:
        raise BackendError("upload_too_large", 413)
    args = [sys.executable, "-m", "backend.file_validator", str(settings.max_pages),
            str(settings.max_image_dimension), str(settings.max_image_pixels)]
    try:
        result = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=settings.validation_timeout_seconds,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        metadata = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        raise BackendError("file_decode_failed_or_timed_out", 422) from None
    if result.returncode or "error" in metadata:
        raise BackendError(metadata.get("error", "file_decode_failed"), 422)
    return metadata


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_source(directory: Path, data: bytes) -> str:
    private_directory(directory)
    directory.mkdir(parents=True, exist_ok=True)
    reference = uuid4().hex
    path = directory / reference
    with path.open("xb") as target:
        target.write(data)
    return reference


def read_source(directory: Path, reference: str, expected_hash: str) -> bytes:
    private_directory(directory)
    if not re.fullmatch(r"[a-f0-9]{32}", reference):
        raise BackendError("invalid_storage_reference", 503)
    path = directory / reference
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise BackendError("invalid_storage_reference", 503)
    try:
        data = path.read_bytes()
    except OSError:
        raise BackendError("source_storage_unavailable", 503) from None
    if digest(data) != expected_hash:
        raise BackendError("source_integrity_failed", 409)
    return data
