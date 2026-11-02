"""Collect distribution-supplied license evidence without assigning licenses."""
from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default as email_policy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def license_name(name):
    base=PurePosixPath(name).name.lower()
    return bool(re.search(r"(?:^|[._-])(licen[cs]e|copying|copyright|notice)(?:$|[._-])",base)) and not base.endswith((".py",".pyc"))


def safe_member(name):
    path=PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe distribution member path")


def collect(release:Path,npm_root:Path,output:Path):
    """Output is immutable evidence, not a redistribution approval or a new release."""
    release,npm_root,output=release.resolve(),npm_root.resolve(),output.resolve()
    if output.exists():
        raise ValueError("Output must not exist")
    receipt_raw=(release/"evidence.json").read_bytes()
    receipt=json.loads(receipt_raw)
    if receipt.get("complete") is not True:
        raise ValueError("Release installation evidence is incomplete")
    expected_lock="\n".join(f"{name}=={version} --hash=sha256:{receipt['wheel_hashes'][name]}"
                              for name,version in sorted(receipt["packages"].items()))+"\n"
    if (release/"requirements.lock").read_text(encoding="utf-8")!=expected_lock:
        raise ValueError("Release lock differs from validated wheel hashes")
    lock_raw=(npm_root/"package-lock.json").read_bytes()
    lock=json.loads(lock_raw)
    if lock.get("lockfileVersion")!=3:
        raise ValueError("Expected npm lockfile version 3")
    records=[]
    copies=[]

    def notice(record,origin,raw):
        if len(raw)>32_000_000:
            raise ValueError("Notice exceeds collection size limit")
        # A binary file is not silently treated as readable license evidence.
        try:raw.decode("utf-8-sig")
        except UnicodeError:
            record["issues"].append("notice_not_utf8: "+origin)
        destination=f"notices/{len(records)+1:03d}/{len(record['notices'])+1:03d}.txt"
        record["notices"].append({"origin":origin,"file":destination,"sha256":digest(raw),"bytes":len(raw)})
        copies.append((destination,raw))

    found=set()
    for wheel in sorted((release/"wheelhouse").glob("*.whl")):
        if not wheel.resolve().is_relative_to(release):
            raise ValueError("Wheel path escapes release")
        raw=wheel.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):
                raise ValueError("Duplicate wheel member")
            for name in names:safe_member(name)
            metadata_files=[name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_files)!=1:
                raise ValueError("Wheel must have one METADATA record")
            info=BytesParser(policy=email_policy).parsebytes(archive.read(metadata_files[0]))
            name,version=normalized(info["Name"]),info["Version"]
            if name in found or receipt["packages"].get(name)!=version or receipt["wheel_hashes"].get(name)!=digest(raw):
                raise ValueError("Wheel differs from validated release")
            found.add(name)
            record={"ecosystem":"python","name":name,"version":version,"artifact":wheel.name,"sha256":digest(raw),
                    "license_expression":info.get("License-Expression"),"license_metadata":info.get("License"),
                    "license_classifiers":[c for c in info.get_all("Classifier",[]) if c.startswith("License ::")],
                    "declared_license_files":info.get_all("License-File",[]),"notices":[],"issues":[]}
            prefix=metadata_files[0].rsplit("/",1)[0]
            declared=set()
            for entry in record["declared_license_files"]:
                safe_member(entry)
                candidates=[f"{prefix}/licenses/{entry}",f"{prefix}/{entry}",entry]
                matches=[candidate for candidate in candidates if candidate in names]
                if not matches:record["issues"].append("declared_notice_missing: "+entry)
                declared.update(matches)
            for member in sorted(set(n for n in names if not n.endswith("/") and (license_name(n) or n.startswith(prefix+"/licenses/")))|declared):
                notice(record,member,archive.read(member))
            if not record["notices"]:record["issues"].append("no_license_text")
            records.append(record)
    if found!=set(receipt["packages"]):
        raise ValueError("Wheel closure is incomplete")

    for location,item in sorted(lock["packages"].items()):
        if "node_modules/" not in location or item.get("dev") or item.get("link"):
            continue
        safe_member(location)
        package=(npm_root/location).resolve()
        if not package.is_relative_to(npm_root):
            raise ValueError("npm package escapes project")
        package_raw=(package/"package.json").read_bytes()
        metadata=json.loads(package_raw)
        expected_name=location.rsplit("node_modules/",1)[1]
        if metadata["name"]!=expected_name or metadata["version"]!=item.get("version"):
            raise ValueError("Installed npm package differs from lock")
        record={"ecosystem":"npm","name":metadata["name"],"version":metadata["version"],"location":location,
                "lock_integrity":item.get("integrity"),"lock_license":item.get("license"),"license_metadata":metadata.get("license"),
                "package_json_sha256":digest(package_raw),"files":{},"notices":[],"issues":[]}
        if item.get("license") is not None and item["license"]!=metadata.get("license"):
            record["issues"].append("license_metadata_differs_from_lock")
        for path in sorted(package.rglob("*")):
            if not path.is_file() or "node_modules" in path.relative_to(package).parts:
                continue
            if not path.resolve().is_relative_to(package):
                raise ValueError("npm file escapes package")
            content=path.read_bytes()
            member=path.relative_to(package).as_posix()
            record["files"][member]=digest(content)
            if license_name(member):notice(record,member,content)
        if not record["notices"]:record["issues"].append("no_license_text")
        records.append(record)
    result={"schema_version":1,"scope":"validated Python wheel closure plus current npm production lock entries",
            "release_evidence_sha256":digest(receipt_raw),"release_build_id":receipt.get("probe",{}).get("build_id"),
            "npm_lock_sha256":digest(lock_raw),"packages":records,
            "limitations":["Collected metadata is not a legal interpretation or redistribution approval.",
                           "npm file hashes identify installed content; lock integrity has not been checked against registry tarballs.",
                           "Embedded vendor code and external runtimes/fonts require a separate complete attribution audit."],
            "issues":[{"ecosystem":r["ecosystem"],"name":r["name"],"issues":r["issues"]} for r in records if r["issues"]]}
    # Validate all inputs before generating a new evidence directory.
    inventory_json=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    output.mkdir(parents=True)
    for destination,raw in copies:
        target=output/destination
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    (output/"inventory.json").write_text(inventory_json,encoding="utf-8")
    lines=["# Distribution notice inventory","","This is collected evidence, not an authorization to redistribute.","",
           "| Ecosystem | Package | Version | Notice files | Evidence issues |","|---|---|---|---:|---|"]
    for record in records:
        lines.append(f"| {record['ecosystem']} | {record['name']} | {record['version']} | {len(record['notices'])} | {'; '.join(record['issues']) or 'none detected'} |")
    (output/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT/".artifacts"):
        parser.error("Output must be a new directory within .artifacts")
    result=collect(args.release,ROOT,args.output)
    print(json.dumps({"packages":len(result["packages"]),"issues":result["issues"]},ensure_ascii=False))


if __name__=="__main__":main()
