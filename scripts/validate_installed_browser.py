"""Bind a Playwright run to an independently installed App release."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grep", required=True, help="Explicit Playwright test selection; recorded in evidence")
    args = parser.parse_args()
    release, output = args.release.resolve(), args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / ".artifacts"):
        parser.error("Output must be a new directory inside .artifacts")
    raw = (release / "evidence.json").read_bytes()
    receipt = json.loads(raw)
    if receipt.get("complete") is not True:
        parser.error("Release must have passed independent installation and HTTP validation")
    installed = Path(receipt["installation_root"]).resolve()
    environment = installed / "venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if installed.is_relative_to(ROOT) or not python.is_file():
        parser.error("An installed Python outside the source checkout is required")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        parser.error("npm is required for the maintained Playwright driver")
    command = [npm]
    if os.name == "nt":
        node = shutil.which("node.exe")
        cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if node is None or not cli.is_file():
            parser.error("Node and npm CLI are required; no shell command interpolation is used")
        command = [node, str(cli)]
    output.mkdir(parents=True)
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AI4BI_E2E_SESSION_COOKIES"):
        env.pop(name, None)
    env.update(AI4BI_E2E_PYTHON=str(python), AI4BI_E2E_DATA_ROOT=str(output / "data"),
               LLM_MODE="mock", PYTHONIOENCODING="utf-8")
    evidence = {"complete": False, "selection": args.grep, "build_id": receipt["probe"]["build_id"],
                "release_evidence_sha256": hashlib.sha256(raw).hexdigest(), "python": str(python),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "test_sha256": hashlib.sha256((ROOT / "tests/e2e/workspace.spec.ts").read_bytes()).hexdigest(),
                "limitation": "Browser driver and launch harness use checkout files; App and core use installed wheels. Not a NativeApp WebView test."}
    drivers = list((ROOT / "tests/e2e").glob("*.ts")) + [ROOT / name for name in
        ("apps/web/playwright.config.ts", "scripts/serve_dev.py", "scripts/validate_installed_browser.py",
         "package.json", "apps/web/package.json", "package-lock.json")]
    evidence["driver_hashes"] = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in drivers}

    def save():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    save()
    probe = (
        "import json,sys; from pathlib import Path; import ai4bi,ai4bi_web_api; "
        "from ai4bi_web_api.static_assets import verify_manifest; "
        "print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'core':str(Path(ai4bi.__file__).resolve()),'app':str(Path(ai4bi_web_api.__file__).resolve()),"
        "'build_id':verify_manifest(Path(ai4bi_web_api.__file__).parent/'static')['build_id']}))"
    )
    verified = subprocess.run([str(python), "-I", "-c", probe], cwd=installed, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
    (output / "origin-check.log").write_text(verified.stdout + verified.stderr, encoding="utf-8")
    verified.check_returncode()
    origins = json.loads(verified.stdout)
    if (Path(origins["prefix"]).resolve() != environment.resolve()
            or origins["prefix"] == origins["base_prefix"]
            or origins["build_id"] != evidence["build_id"]
            or any(not Path(origins[key]).is_relative_to(environment) for key in ("core", "app"))):
        raise ValueError("Installed origins or build differ from the validated release")
    evidence["origins"] = origins
    save()
    artifact_root = ROOT / ".artifacts"
    extensions = {".png", ".pdf", ".xlsx", ".zip"}

    def fingerprint(path):
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    before = {path.name: fingerprint(path) for path in artifact_root.iterdir()
              if path.is_file() and path.suffix.lower() in extensions}
    report_index = artifact_root / "playwright-report/index.html"
    previous_report = fingerprint(report_index) if report_index.exists() else None
    print("START installed browser: " + args.grep, flush=True)
    with (output / "run.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run([*command, "run", "test:e2e", "--workspace", "apps/web", "--", "--grep", args.grep],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    fresh_report = report_index.is_file() and fingerprint(report_index) != previous_report
    if fresh_report:
        for name in ("playwright-report", "playwright-results"):
            path = artifact_root / name
            if path.exists():
                shutil.copytree(path, output / name)
    downloads = {}
    for path in artifact_root.iterdir():
        if path.is_file() and path.suffix.lower() in extensions and before.get(path.name) != fingerprint(path):
            target = output / "downloads" / path.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, target)
            downloads[path.name] = {"bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    unchanged = all(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == evidence["driver_hashes"][path.relative_to(ROOT).as_posix()] for path in drivers)
    exit_code = completed.returncode or (0 if fresh_report and unchanged else 1)
    evidence.update(complete=True, exit_code=exit_code, runner_exit_code=completed.returncode,
                    fresh_report=fresh_report, drivers_unchanged=unchanged, downloads=downloads,
                    finished_at=datetime.now(timezone.utc).isoformat())
    save()
    print("DONE installed browser: exit " + str(exit_code), flush=True)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
