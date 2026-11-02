from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import socket


def main():
    parser = argparse.ArgumentParser(description="AI4BI Web local server")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-root", type=Path,
                        default=Path(os.environ.get("AI4BI_DATA_ROOT", str(Path.home() / ".ai4bi-web"))))
    parser.add_argument("--static-root", type=Path)
    parser.add_argument("--instance-id", help="Host-generated unique ID for this launch (not a secret)")
    parser.add_argument("--expected-build-id", help="Expected installed build SHA-256")
    parser.add_argument("--session-cookie-mode", choices=["strict", "partitioned"], default="strict",
                        help="Use secure partitioned cookies for supported embedded desktop hosts")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument("--backup-to", type=Path)
    maintenance.add_argument("--restore-from", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid HTTP port")
    if args.backup_to or args.restore_from:
        from .errors import AppError
        from .storage import Store
        from .recovery import restore_backup
        try:
            if args.restore_from:
                output = restore_backup(args.restore_from, args.data_root)
            else:
                if not (args.data_root / "metadata.sqlite").is_file():
                    raise AppError("NOT_FOUND", "找不到要備份的資料庫。", 404)
                store = Store(args.data_root)
                try:
                    store.backup(args.backup_to)
                    output = args.backup_to.resolve()
                finally:
                    store.close()
        except AppError as exc:
            parser.exit(1, f"{exc.code}: {exc.message}\n")
        print(output)
        return
    # Hold the same socket through startup: a failed bind must not open/migrate data.
    host = "127.0.0.1" if args.host == "localhost" else args.host
    with socket.socket(socket.AF_INET6 if host == "::1" else socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((host, args.port))
        except OSError:
            parser.exit(1, "HTTP_BIND_FAILED: Cannot acquire the requested loopback port.\n")
        from .errors import AppError
        from .static_assets import PACKAGE, validate_launch_identity
        try:
            validate_launch_identity(args.static_root or PACKAGE / "static", args.instance_id, args.expected_build_id)
            from .app import create_app
            import uvicorn
            code = secrets.token_urlsafe(18)
            app = create_app(args.data_root, code, args.static_root,
                             instance_id=args.instance_id, expected_build_id=args.expected_build_id,
                             session_cookie_mode=args.session_cookie_mode)
        except (AppError, ValueError) as exc:
            parser.exit(1, f"{exc.code}: {exc.message}\n" if isinstance(exc, AppError) else f"{exc}\n")
        display_host = f"[{host}]" if host == "::1" else host
        print(f"AI4BI Web: http://{display_host}:{args.port}", flush=True)
        print(f"本次啟動配對碼（僅供本機使用）：{code}", flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=args.port, access_log=False))
        server.run(sockets=[listener])
        if not server.started:
            parser.exit(1, "HTTP_START_FAILED: Application startup did not complete.\n")


if __name__ == "__main__":
    main()
