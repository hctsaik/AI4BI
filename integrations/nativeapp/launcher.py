"""Adapt the public NativeApp HTTP launch arguments to the installed App CLI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    value = os.environ.get("AI4BI_DATA_ROOT", "")
    if not value or not Path(value).is_absolute():
        parser.error("NativeApp must supply an absolute AI4BI_DATA_ROOT through managed_env")
    data = Path(value).resolve()
    if data.is_relative_to(args.root.resolve()):
        parser.error("Persistent data must be outside the installed application directory")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid HTTP port")
    from ai4bi_web_api.__main__ import main as serve
    sys.argv = [sys.argv[0], "--host", args.host, "--port", str(args.port), "--data-root", str(data),
                "--session-cookie-mode", "partitioned"]
    for name, flag in (("AI4BI_INSTANCE_ID", "--instance-id"),
                       ("AI4BI_EXPECTED_BUILD_ID", "--expected-build-id")):
        if name in os.environ:
            sys.argv.extend([flag, os.environ[name]])
    serve()


if __name__ == "__main__":
    main()
