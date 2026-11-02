"""Freeze a tracked AI4BI commit and collect P00 evidence without editing it.

Run with the source project's Python 3.11 interpreter. Output must be a new
directory beneath this project's ignored .artifacts directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".artifacts") or output.exists():
        parser.error("output must be a NEW directory inside .artifacts")
    output.mkdir(parents=True)
    evidence: dict = {"started_at": datetime.now(timezone.utc).isoformat(),
                      "python": sys.version, "machine": platform.machine(),
                      "platform": platform.platform(), "steps": {}}
    env = os.environ.copy()
    env.update(LLM_MODE="mock", PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    for name in ("ANTHROPIC_API_KEY", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)

    def run(name: str, command: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
        start = time.monotonic()
        print(f"START {name}", flush=True)
        log_path = output / f"{name}.log"
        with log_path.open("w", encoding="utf-8") as log:
            try:
                proc = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired:
                evidence["steps"][name] = {"status": "timeout", "seconds": timeout}
                save()
                raise
        evidence["steps"][name] = {"exit_code": proc.returncode,
                                   "seconds": round(time.monotonic() - start, 3),
                                   "log": log_path.name}
        save()
        print(f"DONE {name}: exit={proc.returncode}", flush=True)
        return proc

    def git(*command: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(source), *command])

    def save() -> None:
        (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False,
                                                       indent=2), encoding="utf-8")

    evidence["source_commit"] = git("rev-parse", "HEAD").decode().strip()
    evidence["source_status_before"] = git("status", "--porcelain=v1").decode("utf-8")
    diff = git("diff", "HEAD", "--binary")
    evidence["tracked_diff_sha256"] = hashlib.sha256(diff).hexdigest()
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    evidence["excluded_untracked"] = [
        {"path": name, "sha256": hashlib.sha256((source / name).read_bytes()).hexdigest()}
        for name in untracked if name and (source / name).is_file()]
    evidence["dependencies"] = {}
    for name in ("pytest", "setuptools", "wheel", "duckdb", "pandas", "pydantic",
                 "pyarrow", "streamlit", "plotly", "scipy", "anthropic"):
        try:
            evidence["dependencies"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            evidence["dependencies"][name] = None
    (output / "tracked-files.txt").write_bytes(git("ls-tree", "-r", "--name-only", "HEAD"))
    archive = output / "source.tar"
    subprocess.run(["git", "-C", str(source), "archive", "--format=tar",
                    f"--output={archive}", evidence["source_commit"]], check=True)
    evidence["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    snapshot = output / "source"
    snapshot.mkdir()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            dest = (snapshot / member.name).resolve()
            if not dest.is_relative_to(snapshot) or member.issym() or member.islnk():
                raise ValueError(f"Unsafe source archive member: {member.name}")
        tar.extractall(snapshot, filter="data")
    save()
    # Working directory guarantees normal imports resolve the frozen checkout.
    run("regression", [sys.executable, "-m", "pytest", "tests", "-q",
                       "--ignore=tests/e2e", "-p", "no:cacheprovider",
                       "--basetemp", str(output / "pytest-tmp"),
                       "--junitxml", str(output / "regression.xml")], snapshot, 1200)
    wheel_dir = output / "wheels"
    wheel_dir.mkdir()
    built = run("build-wheel", [sys.executable, "-m", "pip", "wheel", str(snapshot),
                                "--no-deps", "--wheel-dir", str(wheel_dir)], output)
    if built.returncode == 0:
        wheels = list(wheel_dir.glob("ai4bi-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one AI4BI wheel")
        evidence["wheel_sha256"] = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        import zipfile
        with zipfile.ZipFile(wheels[0]) as wheel:
            members = wheel.namelist()
        (output / "wheel-members.txt").write_text("\n".join(members), encoding="utf-8")
        evidence["wheel_contains_demo_data"] = any("semiconductor_demo/" in p for p in members)
        evidence["wheel_contains_test_fixtures"] = any("tests/fixtures/" in p for p in members)
        wheel_env = output / "wheel-env"
        created = run("create-wheel-env", [sys.executable, "-m", "venv",
                                           "--system-site-packages", str(wheel_env)], output)
        if created.returncode == 0:
            python = wheel_env / "Scripts" / "python.exe"
            installed = run("install-wheel", [str(python), "-m", "pip", "install",
                                               "--no-deps", "--ignore-installed", str(wheels[0])], output)
            if installed.returncode == 0:
                run("headless-wheel", [str(python), "-I", str(ROOT / "scripts" / "probe_core_wheel.py"),
                                       "--expected-package-root", str(wheel_env),
                                       "--forbid-source", str(source),
                                       "--forbid-source", str(snapshot)], output)
    evidence["source_status_after"] = git("status", "--porcelain=v1").decode("utf-8")
    evidence["source_unchanged"] = (
        evidence["source_status_before"] == evidence["source_status_after"]
        and evidence["tracked_diff_sha256"] == hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest()
        and all(hashlib.sha256((source / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
                for entry in evidence["excluded_untracked"]))
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    evidence["limitations"] = ["Wheel probe shares existing third-party dependencies; not a clean offline install.",
                              "No browser, NativeApp or live LLM acceptance is performed."]
    save()
    return 0 if evidence["source_unchanged"] and all(
        value.get("exit_code") == 0 for value in evidence["steps"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
