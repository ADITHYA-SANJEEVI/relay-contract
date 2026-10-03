"""Local-only BFF launcher. Pairing material lives in an ignored local file."""

import argparse
import os
import secrets
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from relay.browser.app import Config, create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--origin", help="Exact browser origin; defaults to this listener")
    parser.add_argument("--assets", default=str(ROOT / "frontend/dist"))
    parser.add_argument("--pairing-file", default=str(ROOT / ".cache/board-pairing/code"))
    args = parser.parse_args()
    try:
        config = Config.from_file(args.env_file, args.backend,
            args.origin or f"http://127.0.0.1:{args.port}", args.assets)
        if not 1 <= args.port <= 65535:
            raise ValueError("invalid_listener")
        # Restrict pairing material to an ignored workspace child; never a public asset.
        pairing = Path(args.pairing_file).resolve()
        cache = (ROOT / ".cache").resolve()
        if not pairing.is_relative_to(cache) or pairing.is_relative_to(config.assets):
            raise ValueError("pairing_file_must_be_private_cache")
        pairing.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: refuse overwrites/symlinks or accidental concurrent launch.
        code = secrets.token_urlsafe(32)
        fd = os.open(pairing, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(code)
        app = create_app(config, code)
        del code
        print("Local pairing file created; valid for 120 seconds. Open /board-connect at the configured origin.", flush=True)
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False,
                        log_level="warning", proxy_headers=False)
        finally:
            pairing.unlink(missing_ok=True)
    except (ValueError, OSError):
        # Do not echo server configuration, exception text or credentials.
        print("Local BFF configuration/startup rejected.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
