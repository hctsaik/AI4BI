"""Collect an exact wheel closure, install offline, and probe outside the checkout."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from email.parser import BytesParser

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def installed_closure() -> dict[str, str]:
    pending = [("ai4bi-web-api", frozenset())]
    seen = set()
    versions = {}
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        dist = metadata.distribution(name)
        versions[name] = dist.version
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in ("", *extras)):
                continue
            actual = metadata.version(requirement.name)
            if requirement.url or not requirement.specifier.contains(actual, prereleases=True):
                raise RuntimeError(f"Installed dependency does not satisfy {requirement.name}: {actual}")
            pending.append((requirement.name, frozenset(requirement.extras)))
    return dict(sorted(versions.items()))


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("Wheel must have one package metadata record")
        info = BytesParser().parsebytes(archive.read(names[0]))
        return canonicalize_name(info["Name"]), info["Version"]


def reuse_dependency_wheels(source: Path, destination: Path, versions: dict, local: dict):
    """Reuse a validated closure, never silently replace it with an online fetch."""
    source=source.resolve()
    receipt=json.loads((source/"evidence.json").read_text(encoding="utf-8"))
    if receipt.get("complete") is not True:
        raise ValueError("Dependency release has not passed installation validation")
    expected="\n".join(f"{name}=={version} --hash=sha256:{receipt['wheel_hashes'][name]}"
                         for name,version in sorted(receipt["packages"].items()))+"\n"
    if (source/"requirements.lock").read_text(encoding="utf-8")!=expected:
        raise ValueError("Dependency release lock differs from its evidence")
    wanted={name:version for name,version in versions.items() if name not in local}
    selected={}
    for path in sorted((source/"wheelhouse").glob("*.whl")):
        if not path.resolve().is_relative_to(source):
            raise ValueError("Dependency wheel escapes its release directory")
        name,version=wheel_identity(path)
        if name not in wanted:
            continue
        if name in selected or version!=wanted[name] or version!=receipt["packages"].get(name):
            raise ValueError("Dependency wheel version is missing, duplicated or incompatible")
        checksum=receipt["wheel_hashes"].get(name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
            raise ValueError("Dependency wheel hash differs from validated evidence")
        if (destination/path.name).exists():
            raise ValueError("Refusing to overwrite a supplied wheel")
        selected[name]=(path,checksum)
    if set(selected)!=set(wanted):
        raise ValueError("Validated dependency release does not contain the required closure")
    for path,checksum in selected.values():
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=checksum:
            raise ValueError("Dependency wheel changed while copying")
        (destination/path.name).write_bytes(raw)
    return {"packages":len(selected),"source_evidence_sha256":hashlib.sha256((source/"evidence.json").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--app-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dependency-release",type=Path,help="Reuse validated dependency wheels without downloading")
    parser.add_argument("--forbid-source", type=Path, action="append", default=[])
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / ".artifacts"):
        parser.error("output must be a new directory inside this project's .artifacts")
    versions = installed_closure()
    local = {}
    for path, expected in ((args.core_wheel, "ai4bi"), (args.app_wheel, "ai4bi-web-api")):
        path = path.resolve(strict=True)
        name, version = wheel_identity(path)
        if name != expected or versions.get(name) != version:
            parser.error("Local wheels must match the installed, tested package versions")
        local[name] = path
    output.mkdir(parents=True)
    wheels = output / "wheelhouse"
    wheels.mkdir()
    for path in local.values():
        shutil.copyfile(path, wheels / path.name)
    requirements = output / "download-requirements.txt"
    requirements.write_text("\n".join(f"{name}=={version}" for name, version in versions.items() if name not in local) + "\n", encoding="utf-8")
    evidence = {"python": sys.version, "machine": platform.machine(), "platform": platform.platform(),
                "packages": versions, "steps": {}, "complete": False}
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(name, None)
    env.update(LLM_MODE="mock", PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1")

    def save():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    def run(name, command, cwd, timeout=900):
        print(f"START {name}", flush=True)
        start = time.monotonic()
        try:
            with (output / (name + ".log")).open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            evidence["steps"][name] = {"exit_code": result.returncode, "seconds": round(time.monotonic() - start, 2)}
            save()
            if result.returncode:
                raise RuntimeError(f"{name} failed; inspect its log in the output directory")
        except subprocess.TimeoutExpired:
            evidence["steps"][name] = {"timeout": timeout}
            save()
            raise
        print(f"DONE {name}", flush=True)

    save()
    if args.dependency_release:
        evidence["dependency_reuse"]=reuse_dependency_wheels(args.dependency_release,wheels,versions,local)
        evidence["steps"]["dependency-reuse"]={"exit_code":0}
        save()
    else:
        run("download", [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
                         "--dest", str(wheels), "-r", str(requirements)], output)
    hashes = {}
    for path in wheels.glob("*.whl"):
        name, version = wheel_identity(path)
        if versions.get(name) != version or name in hashes:
            raise RuntimeError("Wheel closure has unexpected or duplicate distributions")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if hashes.keys() != versions.keys():
        raise RuntimeError("Missing dependency wheels")
    lock = output / "requirements.lock"
    lock.write_text("\n".join(f"{name}=={version} --hash=sha256:{hashes[name]}" for name, version in versions.items()) + "\n", encoding="utf-8")
    # Keep the installation outside every checkout and preserve it for diagnosis.
    installed = Path(tempfile.mkdtemp(prefix="ai4bi-release-"))
    evidence["installation_root"] = str(installed)
    evidence["wheel_hashes"] = hashes
    save()
    venv = installed / "venv"
    run("create-env", [sys.executable, "-m", "venv", str(venv)], installed)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run("offline-install", [str(python), "-I", "-m", "pip", "install", "--no-index", "--only-binary=:all:",
                            "--find-links", str(wheels), "--require-hashes", "-r", str(lock)], installed)
    run("pip-check", [str(python), "-I", "-m", "pip", "check"], installed)
    probe = installed / "probe_app_wheel.py"
    shutil.copyfile(ROOT / "scripts/probe_app_wheel.py", probe)
    command = [str(python), "-I", str(probe), "--expected-package-root", str(venv), "--output", str(installed / "probe.json"),
               "--forbid-source", str(ROOT)]
    for path in args.forbid_source:
        command.extend(["--forbid-source", str(path.resolve())])
    run("installed-http-probe", command, installed, timeout=180)
    evidence["probe"] = json.loads((installed / "probe.json").read_text(encoding="utf-8"))
    evidence["complete"] = True
    save()
    from collect_dependency_notices import collect
    notices=collect(output,ROOT,output/"third-party-notices")
    print(f"Collected notices for {len(notices['packages'])} packages; {len(notices['issues'])} packages need evidence review",flush=True)
    print(f"Verified offline installation: {output}", flush=True)


if __name__ == "__main__":
    main()
