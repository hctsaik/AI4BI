"""Private subprocess entry. Reads a fixed job; never mutates metadata."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import threading
import re
import errno


_phase = "startup"
_job_id = None
_sequence = 0
_PHASES = {"startup", "parent-watch", "imports", "ready", "assignment-read", "assignment-remove",
           "workspace-check", "job-read", "job-decode", "job-execute", "result-encode", "result-write",
           "result-publish", "reuse-check", "reuse-ready"}


def _owned_folder(root, folder):
    folder, root = Path(folder), Path(root).resolve()
    return (re.fullmatch(r"[a-f0-9]{32}", folder.name) is not None
            and folder.parent in (root / "staging" / "jobs", root / "staging" / "workers")
            and folder.absolute() == folder.resolve())


def read_failure(root, folder):
    """Only accept a bounded, field-validated diagnostic from an owned folder."""
    try:
        if not _owned_folder(root, folder):
            return None
        path = Path(folder) / "fatal.json"
        if path.is_symlink():
            return None
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        data = json.loads(raw)
        fields = {"version", "phase", "exception", "module", "line", "pid", "job_id", "sequence", "errno", "winerror"}
        if not isinstance(data, dict) or set(data) != fields or type(data["version"]) is not int or data["version"] != 1:
            return None
        if not isinstance(data["phase"], str) or data["phase"] not in _PHASES:
            return None
        if not isinstance(data["exception"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", data["exception"]):
            return None
        if data["module"] is not None and (not isinstance(data["module"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}\.py", data["module"])):
            return None
        if data["job_id"] is not None and (not isinstance(data["job_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", data["job_id"])):
            return None
        for field, low, high in (("pid", 1, 2**32-1), ("line", 0, 10**7), ("sequence", 0, 8)):
            if type(data[field]) is not int or not low <= data[field] <= high:
                return None
        if any(data[field] is not None and (type(data[field]) is not int or not -2**31 <= data[field] < 2**31) for field in ("errno", "winerror")):
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


def record_failure(root, folder, exc):
    """Best effort: never copy exception messages, arguments, source paths or data."""
    try:
        if not _owned_folder(root, folder) or not Path(folder).is_dir():
            return
        module, line = None, 0
        trace = exc.__traceback__
        package = Path(__file__).resolve().parent
        while trace:
            filename = Path(trace.tb_frame.f_code.co_filename)
            if filename.resolve().parent == package:
                module, line = filename.name, trace.tb_lineno
            trace = trace.tb_next
        exception = type(exc).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception):
            exception = "Exception"
        def error_number(field):
            value = getattr(exc, field, None)
            return value if type(value) is int and -2**31 <= value < 2**31 else None
        data = {"version": 1, "phase": _phase, "exception": exception, "module": module, "line": line,
                "pid": os.getpid(), "job_id": _job_id, "sequence": _sequence,
                "errno": error_number("errno"), "winerror": error_number("winerror")}
        raw = json.dumps(data, ensure_ascii=True).encode("ascii")
        if len(raw) > 4096:
            return
        pending, final = Path(folder) / "fatal.tmp", Path(folder) / "fatal.json"
        if pending.is_symlink() or final.is_symlink():
            return
        pending.write_bytes(raw)
        pending.replace(final)
    except Exception:
        # Diagnostics must never turn a successful task or retirement into a failure.
        pass


def entrypoint():
    root = folder = None
    try:
        root = Path(sys.argv[1]).resolve()
        selector = sys.argv[2]
        folder = root / "staging" / ("workers" if selector == "--standby" else "jobs") / (sys.argv[3] if selector == "--standby" else selector)
        main()
        return 0
    except Exception as exc:
        if root is not None and folder is not None:
            record_failure(root, folder, exc)
        return 1


def watch_coordinator():
    """The coordinator owns the only writer; EOF also detects forced parent exit."""
    descriptor = sys.stdin.fileno()
    if os.name == "nt":
        import ctypes
        import msvcrt

        # Never block a CRT read on stdin: it can interfere with extension loading
        # and interpreter shutdown. This pipe has no other reader or I/O requests.
        handle = msvcrt.get_osfhandle(descriptor)
        peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        peek.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        peek.restype = ctypes.c_int

    def wait_for_eof():
        try:
            if os.name == "nt":
                while peek(handle, None, 0, None, None, None):
                    time.sleep(.1)
            else:
                while os.read(descriptor, 1):
                    pass
        finally:
            # No metadata/artifact publishing after the coordinator disappears.
            os._exit(70)
    threading.Thread(target=wait_for_eof, name="ai4bi-parent-watch", daemon=True).start()


def within_reuse_memory_limit():
    """Retire after any large job; the core dataframe store has no eviction API."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.WinDLL("kernel32").GetCurrentProcess
    current.restype = ctypes.c_void_p
    get_memory = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    return bool(get_memory(current(), ctypes.byref(counters), counters.cb)) and max(
        counters.peak_working, counters.peak_pagefile) < 768 * 1024 * 1024


def execute_assignment(root, jid, *, imports_ms, standby, sequence, wait_ms):
    global _phase, _job_id
    from .core import run_query, run_assistant, clean, enable_worker_dataframe_sources
    from .storage import encode
    assigned = time.perf_counter()
    if len(jid) != 32 or not all(c in "0123456789abcdef" for c in jid):
        raise ValueError("Invalid job ID")
    _job_id = jid
    _phase = "job-read"
    with closing(sqlite3.connect(root / "metadata.sqlite")) as db:
        row = db.execute("SELECT kind,input FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise ValueError("Unknown job")
    _phase = "job-decode"
    payload = json.loads(row[1])
    enable_worker_dataframe_sources()
    try:
        _phase = "job-execute"
        if row[0] == "query":
            result = run_query(root, payload)
        elif row[0] == "assistant":
            result = run_assistant(root, payload)
        elif row[0] == "spc":
            from .spc import run_spc
            result = run_spc(root, payload)
        elif row[0] == "change":
            from .change_analysis import run_change
            result = run_change(root, payload)
        elif row[0] == "rfm":
            from .rfm import run_rfm
            result = run_rfm(root, payload)
        elif row[0] == "summary":
            from .business_summary import run_summary
            result = run_summary(root, payload)
        elif row[0] == "alerts":
            from .alerts import run_alerts
            result = run_alerts(root, payload)
        elif row[0] == "crossfact":
            from .crossfact import run_crossfact
            result = run_crossfact(root, payload)
        elif row[0] == "commonality":
            from .commonality import run_commonality
            result = run_commonality(root, payload)
        elif row[0] == "export":
            from .exports import export_snapshot
            result = export_snapshot(root, payload, root / "staging" / "jobs" / jid)
        elif row[0] == "publish":
            from .publications import check_publication
            result = check_publication(root, payload)
        else:
            raise ValueError("Unsupported job kind")
        result.setdefault("timings_ms", {}).update({"worker_imports": round(imports_ms, 2),
            "worker_standby": standby,
            "worker_sequence": sequence,
            "worker_standby_wait": round(wait_ms, 2),
            "worker_execution": round((time.perf_counter()-assigned)*1000, 2),
            "worker_total": round(imports_ms+(time.perf_counter()-assigned)*1000, 2)})
        output = {"result": clean(result)}
    except Exception as exc:
        output = {"error": {"code": getattr(exc, "code", "ANALYSIS_FAILED"),
                            "message": getattr(exc, "message", "分析未完成；請確認欄位、來源與查詢設定。")}}
    directory = root / "staging" / "jobs" / jid
    temp = directory / "result.tmp"
    _phase = "result-encode"
    encoded = encode(output)
    _phase = "result-write"
    temp.write_text(encoded, encoding="utf-8")
    _phase = "result-publish"
    temp.replace(directory / "result.json")
    return "error" not in output


def read_assignment(assignment):
    """Windows CRT reads can report a sharing denial as errno 13 without winerror."""
    deadline = time.monotonic() + 1.0
    while True:
        try:
            return assignment.read_text(encoding="ascii")
        except PermissionError as exc:
            if os.name != "nt" or exc.errno != errno.EACCES:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(.025, remaining))


def remove_assignment(assignment):
    """Tolerate a brief Windows sharing violation before executing the job."""
    deadline = time.monotonic() + 1.0
    while True:
        try:
            assignment.unlink()
            return
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != 32:
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(.025, remaining))


def main():
    global _phase, _sequence, _job_id
    started = time.perf_counter()
    if os.environ.get("AI4BI_WORKER_PARENT_PIPE") == "1":
        _phase = "parent-watch"
        watch_coordinator()
    _phase = "imports"
    from . import core, storage  # Import once before announcing readiness.
    loaded = time.perf_counter()
    root, jid = Path(sys.argv[1]).resolve(), sys.argv[2]
    imports_ms = (loaded-started)*1000
    if jid != "--standby":
        _sequence = 1
        execute_assignment(root, jid, imports_ms=imports_ms, standby=False, sequence=1, wait_ms=0)
        return
    token = sys.argv[3]
    if len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
        raise ValueError("Invalid standby ID")
    directory = root / "staging" / "workers" / token
    _phase = "ready"
    (directory / "ready").write_text("ready", encoding="ascii")
    assignment = directory / "assignment"
    owner = None
    for sequence in range(1, 9):
        _sequence = sequence
        _job_id = None
        _phase = "assignment-read"
        waiting = time.perf_counter()
        while not assignment.is_file():
            time.sleep(.025)
        jid = read_assignment(assignment)
        if re.fullmatch(r"[a-f0-9]{32}", jid):
            _job_id = jid
        _phase = "assignment-remove"
        remove_assignment(assignment)
        # Bind independently in the child as well as in the coordinator.
        _phase = "workspace-check"
        with closing(sqlite3.connect(root / "metadata.sqlite")) as db:
            row = db.execute("SELECT wid FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row or owner is not None and row[0] != owner:
            raise ValueError("Worker workspace changed")
        owner = row[0]
        succeeded = execute_assignment(root, jid, imports_ms=imports_ms if sequence == 1 else 0,
            standby=True, sequence=sequence, wait_ms=(time.perf_counter()-waiting)*1000)
        if not succeeded or sequence == 8:
            return
        # A matching marker means all job files are closed and this worker is
        # quiescent. No further writes until the coordinator assigns another job.
        try:
            _phase = "reuse-check"
            if not within_reuse_memory_limit():
                return
            pending = directory / "ready.tmp"
            _phase = "reuse-ready"
            pending.write_text(jid, encoding="ascii")
            pending.replace(directory / "ready")
        except OSError:
            # The result is already durable. Fall back to normal one-job exit
            # if the optional reuse handshake cannot be completed.
            return


if __name__ == "__main__":
    raise SystemExit(entrypoint())
