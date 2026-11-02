"""Measure six governed queries; this is not browser end-to-end acceptance."""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def process_memory(handle):
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    function = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    function.restype = wintypes.BOOL
    if not function(wintypes.HANDLE(int(handle)), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"peak_working_bytes": counters.peak_working, "private_bytes": counters.private,
            "peak_commit_bytes": counters.peak_pagefile}


def fixture(folder, rows):
    import pandas as pd
    from ai4bi_web_api.core import template
    from ai4bi_web_api.jobs import make_snapshot
    from ai4bi_web_api.storage import Store
    report, contracts = template("fab")
    block = contracts["fab_process_move"]
    seed = pd.DataFrame(block.data_source.records)
    frame = pd.concat([seed] * math.ceil(rows / len(seed)), ignore_index=True).iloc[:rows].copy()
    frame["move_id"] = [f"BENCH-{i}" for i in range(rows)]
    original = report["pages"]["main"]["visuals"]
    visuals, expected = {}, {}
    for name, column in (("moves", None), ("queue", None), ("step", "step_name"),
                         ("tool", "tool_id"), ("product", "product_family"), ("priority", "priority")):
        visual = copy.deepcopy(original["kpi_moves" if name == "moves" else "kpi_qt" if name == "queue" else "bar_qt_step"])
        visual["component_id"] = name
        visual["query"]["spec_id"] = name
        visual["query"]["metrics"][0]["alias"] = "value"
        if column:
            visual["query"]["dimensions"][0].update(column_name=column, alias="group")
            expected[name] = {str(key): float(value) for key, value in frame.groupby(column)["queue_time_hr"].mean().items()}
        else:
            expected[name] = {"total": float(frame["move_count"].sum() if name == "moves" else frame["queue_time_hr"].mean())}
        visuals[name] = visual
    page = report["pages"]["main"]
    page["visuals"], page["visual_order"] = visuals, list(visuals)
    store = Store(folder / "data")
    ids = store.create_workspace("Six query benchmark", report, "benchmark", "fab")
    store.publish_dataset(ids["workspace_id"], block.model_dump(mode="json"), frame)
    snapshot = make_snapshot(store, ids["workspace_id"], ids["report_id"], 1, {})
    (folder / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (folder / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return {"rows": rows, "columns": len(frame.columns), "source_pattern_rows": len(seed),
            "parquet_bytes": sum(p.stat().st_size for p in (folder / "data").rglob("*.parquet")),
            "visuals": list(visuals), "dimensions": ["step_name", "tool_id", "product_family", "priority"]}


def check_result(result, expected):
    if set(result["visuals"]) != set(expected):
        raise ValueError("Benchmark did not execute all six visuals")
    for name, reference in expected.items():
        visual = result["visuals"][name]
        if visual["status"] != "ready" or visual["truncated"]:
            raise ValueError(f"Visual {name} failed or was truncated: {visual}")
        actual = {str(row.get("group", "total")): float(row["value"]) for row in visual["rows"]}
        if len(visual["rows"]) != len(reference) or actual.keys() != reference.keys():
            raise ValueError("Benchmark group coverage differs")
        if any(not math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9) for key, value in reference.items()):
            raise ValueError("Benchmark values differ from independent pandas reference")


def worker(folder, repeats, source_mode):
    # Windows venv python.exe is a launcher; its PID is not the interpreter PID.
    temporary = folder / "worker-pid.tmp"
    temporary.write_text(str(os.getpid()), encoding="ascii")
    temporary.replace(folder / "worker-pid.txt")
    started = time.perf_counter()
    from ai4bi_web_api.core import run_query, enable_worker_dataframe_sources
    if source_mode == "worker-dataframes":
        enable_worker_dataframe_sources()
    imports = (time.perf_counter() - started) * 1000
    snapshot = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    samples = []
    for index in range(repeats):
        started = time.perf_counter()
        result = run_query(folder / "data", snapshot)
        elapsed = (time.perf_counter() - started) * 1000
        check_result(result, expected)
        raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
        samples.append({"iteration": index, "elapsed_ms": round(elapsed, 2), "timings_ms": result["timings_ms"],
                        "response_bytes": len(raw), "response_rows": sum(v["row_count"] for v in result["visuals"].values())})
        (folder / "samples.json").write_text(json.dumps({"import_ms": imports, "samples": samples}, indent=2), encoding="utf-8")
        print(f"sample {index}: {elapsed:.2f} ms", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", nargs="+", type=int, default=[100000, 1000000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--source-mode", choices=["worker-dataframes", "inline"], default="worker-dataframes")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker:
        worker(output, args.repeats, args.source_mode)
        return
    if os.name != "nt" or output.exists() or not output.is_relative_to(ROOT / ".artifacts"):
        parser.error("Windows benchmark output must be new and inside .artifacts")
    if not 1 <= args.repeats <= 20 or any(n < 1 or n > 1000000 for n in args.rows) or len(set(args.rows)) != len(args.rows):
        parser.error("Use unique row counts up to one million and 1-20 repetitions")
    output.mkdir(parents=True)
    from ai4bi_web_api.static_assets import verify_manifest, PACKAGE
    evidence = {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "cases": [],
                "build": verify_manifest(PACKAGE / "static"),
                "source_mode": args.source_mode,
                "scope": "Backend run_query in the recorded source mode; first invocation and repeated same-process invocations with OS caches available. No application result cache assumed. Not HTTP, jobs, browser, end-to-end p95 or full performance acceptance."}
    for rows in args.rows:
        folder = output / str(rows)
        folder.mkdir()
        case = fixture(folder, rows)
        print(f"START {rows} rows", flush=True)
        started = time.monotonic()
        with (folder / "worker.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(folder),
                                        "--repeats", str(args.repeats), "--source-mode", args.source_mode], stdout=log, stderr=subprocess.STDOUT,
                                       env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=subprocess.CREATE_NO_WINDOW)
            peak, commit, handle = 0, 0, None
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            try:
                while process.poll() is None:
                    pid_file = folder / "worker-pid.txt"
                    if handle is None and pid_file.exists():
                        case["interpreter_pid"] = int(pid_file.read_text(encoding="ascii"))
                        handle = kernel.OpenProcess(0x0400 | 0x0010 | 0x0001, False, case["interpreter_pid"])
                        if not handle:
                            raise ctypes.WinError(ctypes.get_last_error())
                    memory = process_memory(handle or process._handle)
                    peak = max(peak, memory["peak_working_bytes"])
                    commit = max(commit, memory["peak_commit_bytes"])
                    if memory["private_bytes"] > 4 * 1024**3 or time.monotonic() - started > 180:
                        case["stopped"] = "benchmark diagnostic limit: 4 GiB private memory or 180 seconds per case"
                        if handle:
                            kernel.TerminateProcess(handle, 71)
                        process.terminate()
                        break
                    time.sleep(.1)
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    if handle:
                        kernel.TerminateProcess(handle, 71)
                    process.terminate()
                    process.wait(timeout=15)
                if handle:
                    kernel.CloseHandle(handle)
        case.update(exit_code=process.returncode, seconds=round(time.monotonic()-started, 2),
                    peak_working_bytes=peak, peak_commit_bytes=commit)
        if (folder / "samples.json").is_file():
            case.update(json.loads((folder / "samples.json").read_text(encoding="utf-8")))
        evidence["cases"].append(case)
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"DONE {rows}: exit {process.returncode}, peak working set {peak/1024**2:.1f} MiB", flush=True)
    if any(case["exit_code"] != 0 for case in evidence["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
