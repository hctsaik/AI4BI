"""Build identity and integrity of the packaged UI and API sources."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re

from . import __version__
from .errors import AppError
from .migrations import CURRENT_SCHEMA

MANIFEST = "asset-manifest.json"
PACKAGE = Path(__file__).resolve().parent


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_id(body: dict) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def identity() -> dict:
    return {"manifest_version": 1, "app_id": "ai4bi-web", "app_version": __version__,
            "api_version": 1, "schema_version": CURRENT_SCHEMA, "core_version": version("ai4bi")}


def file_map(root: Path, *, backend=False) -> dict[str, str]:
    paths = root.rglob("*.py" if backend else "*")
    result = {}
    for path in paths:
        if not path.is_file() or path.name in (MANIFEST, MANIFEST + ".tmp"):
            continue
        if backend and "static" in path.relative_to(root).parts:
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Asset escapes package")
        result[path.relative_to(root).as_posix()] = checksum(path)
    return result


def write_manifest(static: Path) -> dict:
    files = file_map(static)
    if "index.html" not in files or not any(name.endswith(".js") for name in files):
        raise ValueError("UI build is incomplete")
    body = {**identity(), "files": files, "backend_files": file_map(PACKAGE, backend=True)}
    manifest = {**body, "build_id": build_id(body)}
    temporary = static / (MANIFEST + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(static / MANIFEST)
    return manifest


def verify_manifest(static: Path) -> dict:
    """Readiness is evidence of this installed build, not merely index.html."""
    try:
        manifest_path = static / MANIFEST
        if not manifest_path.resolve().is_relative_to(static.resolve()):
            raise ValueError("Manifest escapes static root")
        with manifest_path.open("rb") as stream:
            raw = stream.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Manifest too large")
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError("Invalid manifest")
        expected = identity()
        if set(manifest) != set(expected) | {"files", "backend_files", "build_id"}:
            raise ValueError("Invalid manifest fields")
        if any(manifest[key] != value for key, value in expected.items()):
            raise ValueError("Incompatible build")
        body = {key: value for key, value in manifest.items() if key != "build_id"}
        if manifest["build_id"] != build_id(body):
            raise ValueError("Invalid build identity")
        files = file_map(static)
        if "index.html" not in files or not any(name.endswith(".js") for name in files):
            raise ValueError("Incomplete UI")
        if manifest["files"] != files or manifest["backend_files"] != file_map(PACKAGE, backend=True):
            raise ValueError("Build contents differ")
        return {**expected, "build_id": manifest["build_id"]}
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise AppError("BUILD_INTEGRITY_FAILED", "應用程式建置不完整或版本不一致，請重新建置或安裝。", 503) from exc


def validate_launch_identity(static: Path, instance_id: str | None, expected_build_id: str | None):
    """Reject an invalid launch without importing the HTTP or analysis runtime."""
    if instance_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", instance_id):
        raise ValueError("Invalid instance ID")
    if expected_build_id is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_build_id):
            raise ValueError("Invalid expected build ID")
        if verify_manifest(static)["build_id"] != expected_build_id:
            raise AppError("BUILD_ID_MISMATCH", "啟動要求的建置與已安裝版本不符。", 409)
