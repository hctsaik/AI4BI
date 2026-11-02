"""Exercise a released Kit's HTTP lifecycle in a new isolated Store."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import time
import zipfile
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

ROOT = Path(__file__).resolve().parents[1]


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:
                return False
            raise ctypes.WinError(error)
        try:
            status = kernel.WaitForSingleObject(handle, 0)
            if status not in (0, 258):
                raise ctypes.WinError(ctypes.get_last_error())
            return status == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def verify_stopped(pid, port, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        alive, listening = process_alive(pid), port_open(port)
        if not alive and not listening:
            return {"launcher_exited": True, "endpoint_closed": True}
        if time.monotonic() >= deadline:
            raise ValueError(f"Host stop left resources alive: process={alive}, endpoint={listening}")
        time.sleep(.05)


def cli_result(raw: bytes) -> dict:
    """create-environment emits pip progress before its final public JSON object."""
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.startswith("{"):
            try:
                result, end = decoder.raw_decode(text, offset)
                if isinstance(result, dict) and not text[end:].strip():
                    return result
            except ValueError:
                pass
        offset += len(line)
    raise ValueError("Kit did not emit a final JSON result")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("kit", "package", "release", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--provision-python", type=Path, help="Create a new environment from the archive using this base Python")
    args = parser.parse_args()
    kit, package, release, output = (getattr(args, name).resolve() for name in ("kit", "package", "release", "output"))
    if output.exists() or not output.is_relative_to(ROOT / ".artifacts"):
        parser.error("Output must be a new directory inside .artifacts")
    receipt = (release / "evidence.json").read_bytes()
    installed = json.loads(receipt)
    packaged = json.loads((package / "evidence.json").read_bytes())
    if (installed.get("complete") is not True or packaged.get("pack") != "passed"
            or packaged.get("release_evidence_sha256") != hashlib.sha256(receipt).hexdigest()):
        parser.error("Package must match the validated installation")
    from build_nativeapp_package import verify_package
    archive = package / packaged["package"]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != packaged["sha256"]:
        parser.error("Package changed after validation")
    verify_package(archive, package / "application", package / "integration")
    python = (args.provision_python.resolve() if args.provision_python else
              Path(installed["installation_root"]) / "venv/Scripts/python.exe")
    kit_python = kit / "python-runtime/python.exe"
    if not python.is_file() or not kit_python.is_file():
        parser.error("Validated App environment and released Kit runtime are required")
    output.mkdir(parents=True)
    store = output / "store"
    results = {"complete": False, "build_id": packaged["build_id"], "steps": {},
               "execution_contract": installed["probe"]["execution_contract"],
               "package_sha256": packaged["sha256"], "release_evidence_sha256": packaged["release_evidence_sha256"]}

    def save():
        (output / "evidence.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    def run(name, options, timeout=180):
        print("START " + name, flush=True)
        start = time.monotonic()
        proc = subprocess.run([str(kit_python), "-m", "nativeapp_platform", "--store", str(store), *options],
                              cwd=kit, capture_output=True, timeout=timeout,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        (output / (name + ".stdout.log")).write_bytes(proc.stdout)
        (output / (name + ".stderr.log")).write_bytes(proc.stderr)
        results["steps"][name] = {"exit_code": proc.returncode, "seconds": round(time.monotonic() - start, 2)}
        save()
        proc.check_returncode()
        parsed = cli_result(proc.stdout)
        (output / (name + ".json")).write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        return parsed

    save()
    integration, application = package / "integration", package / "application"
    if args.provision_python:
        imported = run("import-package", ["import-package", "--zip", str(archive), "--no-activate"])
        if imported.get("activated") is not False or imported.get("app_id") != "ai4bi-web":
            raise ValueError("Kit did not stage the expected inactive App")
        # The archive has already passed exact source-set/hash validation above.
        # Extraction stays separate from the Kit-managed Store and its layout.
        extracted = output / "archive-inputs"
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not (extracted / name).resolve().is_relative_to(extracted.resolve()):
                    raise ValueError("Archive entry escapes staging")
            bundle.extractall(extracted)
        integration, application = extracted / "integration", extracted / "app"
        environment = run("create-environment", ["create-environment", "--python", str(python), "--lock-file",
                          str(integration / "runtime/requirements.lock"), "--wheelhouse",
                          str(integration / "runtime/wheelhouse")], timeout=900)
        if environment.get("attached") is not False or environment.get("complete") is not True:
            raise ValueError("Kit did not create a complete independent environment")
        created_python = Path(environment["python"]["executable"]).resolve()
        if not created_python.is_relative_to(store.resolve()):
            raise ValueError("Provisioned environment is outside the isolated Store")
        results["provisioned_python"] = str(created_python)
    else:
        environment = run("register-environment", ["register-environment", "--python", str(python), "--lock-file",
                          str(integration / "runtime/requirements.lock"), "--attach"])
    run("prepare", ["prepare", "--integration-root", str(integration), "--source-root",
                    str(application), "--environment-id", environment["environment_id"]])
    resolved = run("resolve", ["resolve", "--app-id", "ai4bi-web"])
    if args.provision_python and Path(resolved["python_exe"]).resolve() != created_python:
        raise ValueError("App is not bound to its newly provisioned environment")
    # Launch/stop must share the public Host API process: separate CLI calls
    # cannot share the Kit's in-memory process registry.
    host_log = output / "host-api.stdout.log"
    opener = build_opener(ProxyHandler({}))
    with host_log.open("wb") as stdout, (output / "host-api.stderr.log").open("wb") as stderr:
        host = subprocess.Popen([str(kit_python), "-m", "nativeapp_platform", "--store", str(store),
                                 "serve", "--host", "127.0.0.1", "--port", "0"], cwd=kit,
                                stdout=stdout, stderr=stderr,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def api(name, path, body=None):
        print("START Host API " + name, flush=True)
        started = time.monotonic()
        request = Request(host_url + path, data=None if body is None else json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=60) as response:
            value = json.loads(response.read())
        results["steps"][name] = {"exit_code": 0, "transport": "persistent-host-api",
                                  "seconds": round(time.monotonic() - started, 2)}
        (output / (name + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")
        save()
        return value

    launch = None
    try:
        deadline = time.monotonic() + 20
        while not host_log.stat().st_size:
            if host.poll() is not None or time.monotonic() >= deadline:
                raise ValueError("Host API did not announce readiness")
            time.sleep(.05)
        announced = json.loads(host_log.read_text(encoding="utf-8").splitlines()[0])
        host_url = announced["url"]
        host_address = urlsplit(host_url)
        if host_address.scheme != "http" or host_address.hostname != "127.0.0.1" or host_address.username or host_address.password:
            raise ValueError("Unexpected Host API address")
        if Path(announced["store"]).resolve() != store.resolve() or host.poll() is not None:
            raise ValueError("Host API identity does not match the isolated Store")
        launch = api("launch", "/launch", {"app_id": "ai4bi-web"})
        url = urlsplit(launch["url"])
        if url.scheme != "http" or url.hostname != "127.0.0.1" or url.username or url.password:
            raise ValueError("Kit returned an unexpected URL")
        with opener.open(launch["url"].rstrip("/") + "/ready", timeout=15) as response:
            ready = json.loads(response.read())
        if ready["app_id"] != "ai4bi-web" or ready["build_id"] != packaged["build_id"]:
            raise ValueError("Running App does not match package build")
        (output / "ready.json").write_text(json.dumps(ready, indent=2), encoding="utf-8")
        database = store / "data/ai4bi-web/workspace/metadata.sqlite"
        if not database.is_file():
            raise ValueError("App database was not created in isolated Store data")
        results["data_path"] = str(database)
        active = api("running-before-stop", "/running")
        if not any(item.get("pid") == launch["pid"] for item in active.get("instances", [])):
            raise ValueError("Host did not retain the launched App in its live registry")
        if not process_alive(launch["pid"]) or not port_open(url.port):
            raise ValueError("App process or listener disappeared before stop")
        stopped = api("stop", "/stop", {"app_id": "ai4bi-web"})
        if stopped.get("ok") is not True:
            raise ValueError("Kit did not confirm stop")
        results["stop_verification"] = verify_stopped(launch["pid"], url.port)
        running = api("running", "/running")
        if running.get("instances") != []:
            raise ValueError("Kit still reports running applications")
    finally:
        try:
            if launch is not None and not results.get("stop_verification"):
                api("cleanup-stop", "/stop", {"app_id": "ai4bi-web"})
        finally:
            host.terminate()
            host.wait(timeout=10)
    results.update(complete=True, provisioned_from_archive=bool(args.provision_python), limitations=[
                   "Archive provisioning requires an existing compatible base Python and released Kit; their offline delivery is not covered." if args.provision_python else
                   "Public prepare attaches an already installed environment; this is not single-archive provisioning.",
                   "No Tauri WebView, host launch identity binding, secure session bootstrap or cooperative shutdown acceptance."])
    save()
    print("Verified Kit HTTP lifecycle: " + str(output), flush=True)


if __name__ == "__main__":
    main()
