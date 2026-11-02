"""Start the same-origin App using locally built assets; no Vite dev server."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    from ai4bi_web_api.app import create_app
    import uvicorn
    code = os.environ.get("AI4BI_PAIRING_CODE") or secrets.token_urlsafe(18)
    port = int(os.environ.get("AI4BI_PORT", "8765"))
    app = create_app(Path(os.environ.get("AI4BI_DATA_ROOT", str(root / ".artifacts/dev-data"))), code)
    # The code is shown to the local interactive caller, never put in URLs or files.
    print(f"AI4BI Web http://127.0.0.1:{port} | local pairing code: {code}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    main()
