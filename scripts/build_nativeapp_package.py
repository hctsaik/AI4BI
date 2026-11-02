"""Build the external NativeApp integration using a released Kit's public CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def notice_inputs(release: Path, receipt: bytes) -> dict[str, bytes]:
    """Capture validated bytes so later copies cannot race a changed inventory."""
    evidence = json.loads(receipt)
    root = release / "third-party-notices"
    raw = (root / "inventory.json").read_bytes()
    inventory = json.loads(raw)
    if (inventory.get("schema_version") != 1 or evidence.get("complete") is not True
            or inventory.get("release_evidence_sha256") != hashlib.sha256(receipt).hexdigest()
            or inventory.get("release_build_id") != evidence["probe"]["build_id"]):
        raise ValueError("Notice inventory does not match the validated release")
    records = [r for r in inventory["packages"] if r["ecosystem"] == "python"]
    if (len(records) != len(evidence["packages"])
            or {r["name"]: r["version"] for r in records} != evidence["packages"]
            or {r["name"]: r["sha256"] for r in records} != evidence["wheel_hashes"]):
        raise ValueError("Notice inventory Python closure differs from the release")
    result = {"inventory.json": raw, "README.md": (root / "README.md").read_bytes()}
    for record in inventory["packages"]:
        for notice in record["notices"]:
            name = notice["file"]
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or path.as_posix() != name or not name.startswith("notices/") or name in result):
                raise ValueError("Unsafe or duplicate notice path")
            source = root / name
            if not source.resolve().is_relative_to(root.resolve()):
                raise ValueError("Notice file escapes inventory root")
            data = source.read_bytes()
            if len(data) != notice["bytes"] or hashlib.sha256(data).hexdigest() != notice["sha256"]:
                raise ValueError("Notice file differs from inventory")
            result[name] = data
    return result


def verify_package(package: Path, application: Path, integration: Path) -> dict:
    """Check both source completeness and Kit's own per-file integrity records."""
    expected = {}
    for prefix, root in (("app", application), ("integration", integration)):
        for path in root.rglob("*"):
            if path.is_file():
                raw = path.read_bytes()
                expected[prefix + "/" + path.relative_to(root).as_posix()] = (len(raw), hashlib.sha256(raw).hexdigest())
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected) | {"package.json"}:
            raise ValueError("Kit package omitted, duplicated or added source files")
        content = json.loads(archive.read("package.json"))
        items = content["contents"]["files"]
        if len(items) != len(expected) or {item["path"] for item in items} != set(expected):
            raise ValueError("Kit content manifest does not cover all source files")
        app = json.loads(archive.read("integration/app.json"))
        if "app/" + app["ui"]["entry"] not in expected:
            raise ValueError("Kit package omitted the declared application entry")
        for item in items:
            raw = archive.read(item["path"])
            actual = (len(raw), hashlib.sha256(raw).hexdigest())
            if actual != expected[item["path"]] or actual != (item["size"], item["sha256"]):
                raise ValueError("Packaged content integrity failure")
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    kit, release, output = args.kit.resolve(), args.release.resolve(), args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / ".artifacts"):
        parser.error("output must be a new directory inside .artifacts")
    receipt = (release / "evidence.json").read_bytes()
    evidence = json.loads(receipt)
    if evidence.get("complete") is not True:
        parser.error("Release must have passed its independent installation probe")
    expected_lock = "\n".join(f"{name}=={version} --hash=sha256:{evidence['wheel_hashes'][name]}"
                              for name, version in sorted(evidence["packages"].items())) + "\n"
    if (release / "requirements.lock").read_text(encoding="utf-8") != expected_lock:
        parser.error("Release lock differs from its validated wheel hashes")
    python = kit / "python-runtime/python.exe"
    if not python.is_file():
        parser.error("A released Integration Kit with its Python runtime is required")
    source = ROOT / "integrations/nativeapp"
    app_manifest = json.loads((source / "app.json").read_text(encoding="utf-8"))
    if app_manifest["version"] != evidence["packages"]["ai4bi-web-api"]:
        parser.error("Integration version must match the validated App wheel")
    notices = notice_inputs(release, receipt)
    output.mkdir(parents=True)
    integration, application = output / "integration", output / "application"
    integration.mkdir()
    application.mkdir()
    for name in ("app.json", "launch.json", "sheet.json"):
        shutil.copyfile(source / name, integration / name)
    # The published Kit's public pack command includes scripts/, not arbitrary root files.
    (application / "scripts").mkdir()
    shutil.copyfile(source / "launcher.py", application / "scripts/launcher.py")
    runtime = integration / "runtime"
    runtime.mkdir()
    (runtime / "release-evidence.json").write_bytes(receipt)
    for name, raw in notices.items():
        target = runtime / "third-party-notices" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    shutil.copyfile(release / "requirements.lock", runtime / "requirements.lock")
    wheelhouse = runtime / "wheelhouse"
    wheelhouse.mkdir()
    from validate_app_release import wheel_identity
    found = set()
    for wheel in (release / "wheelhouse").glob("*.whl"):
        name, version = wheel_identity(wheel)
        raw = wheel.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if evidence["packages"].get(name) != version or evidence["wheel_hashes"].get(name) != checksum or name in found:
            raise ValueError("Release wheel contents changed after validation")
        found.add(name)
        (wheelhouse / wheel.name).write_bytes(raw)
    if found != set(evidence["packages"]):
        raise ValueError("Release is missing a dependency wheel")
    package = output / f"{app_manifest['app_id']}-{app_manifest['version']}.napkg.zip"
    results = {}
    for name, options in (("validate", ["validate-manifest", "--integration-root", str(integration)]),
                          ("pack", ["pack", "--integration-root", str(integration), "--source-root", str(application), "--out", str(package)])):
        print(f"START Kit {name}", flush=True)
        with (output / (name + ".json")).open("w", encoding="utf-8") as log:
            subprocess.run([str(python), "-m", "nativeapp_platform", "--store", str(output / "store"), *options],
                           cwd=kit, stdout=log, stderr=subprocess.STDOUT, check=True)
        results[name] = "passed"
    content = verify_package(package, application, integration)
    results.update(package=package.name, sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
                   files=len(content["contents"]["files"]), build_id=evidence["probe"]["build_id"],
                   notice_inventory_sha256=hashlib.sha256(notices["inventory.json"]).hexdigest(),
                   release_evidence_sha256=hashlib.sha256(receipt).hexdigest(),
                   limitation="Environment provisioning, host identity validation and WebView bootstrap remain separate gates")
    (output / "evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
