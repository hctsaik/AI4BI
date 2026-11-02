"""Generate API types, build React and embed its assets in the Python package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify_wheel(path: Path, manifest: dict):
    """Reject stale, missing or changed application files before release install."""
    prefix = "ai4bi_web_api/"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Wheel contains duplicate members")
        packaged = json.loads(archive.read(prefix + "static/asset-manifest.json"))
        if packaged != manifest:
            raise ValueError("Wheel manifest differs from the requested build")
        expected = {prefix + name: digest for name, digest in manifest["backend_files"].items()}
        expected.update({prefix + "static/" + name: digest for name, digest in manifest["files"].items()})
        actual = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in names
                  if name.startswith(prefix) and not name.endswith("/")
                  and name != prefix + "static/asset-manifest.json"}
        if actual != expected:
            raise ValueError("Wheel contents differ from build manifest")


def build_wheel(project: Path, output: Path, manifest: dict):
    # Stage only maintained package inputs; setuptools' old build/lib may retain
    # removed hashed assets and removed Python modules across successive builds.
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="app-wheel-", dir=output.parent) as temporary:
        stage = Path(temporary)
        shutil.copyfile(project / "pyproject.toml", stage / "pyproject.toml")
        shutil.copytree(project / "src/ai4bi_web_api", stage / "src/ai4bi_web_api",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        built = stage / "wheels"
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", str(stage),
                        "--wheel-dir", str(built)], check=True)
        wheels = list(built.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one App wheel")
        verify_wheel(wheels[0], manifest)
        shutil.copyfile(wheels[0], output / wheels[0].name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--wheel", action="store_true")
    args = parser.parse_args()
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    from ai4bi_web_api.app import create_app
    schema = create_app(artifacts / "schema-unused").openapi()
    (artifacts / "openapi.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is needed to build maintained React sources")
    subprocess.run([npm, "run", "generate:api"], cwd=ROOT / "apps/web", check=True)
    if not args.skip_web:
        subprocess.run([npm, "run", "build"], cwd=ROOT / "apps/web", check=True)
    source = ROOT / "apps/web/dist"
    if not (source / "index.html").is_file():
        raise RuntimeError("React build did not produce index.html")
    target = ROOT / "services/api/src/ai4bi_web_api/static"
    # Only generated assets are replaced; all target paths remain in this package.
    target.mkdir(exist_ok=True)
    expected = ROOT.resolve() / "services/api/src/ai4bi_web_api/static"
    if target.resolve() != expected:
        raise RuntimeError("Refusing to modify a redirected generated static directory")
    source_files = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    stale = [p for p in target.rglob("*") if p.is_file() and p.relative_to(target) not in source_files]
    if any(not p.resolve().is_relative_to(expected) for p in stale):
        raise RuntimeError("Generated static output contains a path outside its package")
    for path in stale:
        path.unlink()
    for path in source.rglob("*"):
        if path.is_file():
            destination = target / path.relative_to(source)
            if not destination.resolve().is_relative_to(expected):
                raise RuntimeError("Refusing to copy assets outside the package")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    from ai4bi_web_api.static_assets import write_manifest
    manifest = write_manifest(target)
    if args.wheel:
        build_wheel(ROOT / "services/api", artifacts / "release/wheels", manifest)


if __name__ == "__main__":
    main()
