#!/usr/bin/env python3
"""Serve the uxr MCP stdio server behind a local HTTP bridge with bearer auth.

Goal (MO ruling 2026-11-22): register the uxr server in the consumer Gemini
app (Connected Apps, Developer Mode) pointing at a public HTTPS URL that
tunnels to this bridge, which forwards every message to the stdio server.

Usage (run from the repo root or the plugin root):

    python mcp-server/serve.py                    # tunnel if cloudflared exists
    python mcp-server/serve.py --no-tunnel        # loopback only, no tunnel
    python mcp-server/serve.py --port 8742        # fixed local port
    python mcp-server/serve.py --token-file PATH  # custom token location

Behavior and security bar:

- Bearer-token auth is REQUIRED on every request, no exceptions, no
  localhost bypass: a missing or wrong token answers 401. The comparison
  is constant-time (``hmac.compare_digest``). The token is generated on
  first serve with ``secrets.token_urlsafe(32)``, stored under the
  plugin's gitignored ``state/`` folder (never committed), and printed to
  the terminal so it can be pasted into the Gemini registration form; it
  is never written to any log line.
- The bridge binds 127.0.0.1 only: the loopback listener is reachable
  from this machine alone, and the only public exposure is the cloudflared
  quick tunnel, which authenticates every request the same way.
- POST carries one JSON-RPC message: requests (with an id) return the
  server's JSON-RPC response as ``application/json``; notifications and
  responses return 202. GET and DELETE answer 405 (the bridge never
  initiates messages, so there is no server-initiated stream to open).
- Stdlib only: ``http.server`` bridges stdio to HTTP; the only external
  binary is ``cloudflared`` (optional, shelled out, never required).

Exit 0 after Ctrl+C or when stdin closes. Diagnostics go to stderr; the
startup block (URL, token, registration steps) goes to stdout.
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PLUGIN_ROOT / "mcp-server" / "server.py"
DEFAULT_TOKEN_PATH = PLUGIN_ROOT / "state" / "mcp-bridge-token"
MAX_BODY_BYTES = 10 * 1024 * 1024
RESPONSE_TIMEOUT_SECONDS = 60
TUNNEL_WAIT_SECONDS = 25

INSTALL_HINTS = {
    "Windows": "winget install --id Cloudflare.cloudflared",
    "macOS": "brew install cloudflared",
    "Linux (deb)": ("curl -L --output cloudflared.deb https://github.com/"
                    "cloudflare/cloudflared/releases/latest/download/"
                    "cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb"),
}

GEMINI_STEPS = """Gemini Connected Apps registration (Developer Mode):

  1. Open the Gemini app, enter Settings, and enable Developer mode.
  2. Open Connected apps and choose to add a custom app (MCP).
  3. Name: uxr-plugin research operations (any name works).
  4. Server URL: paste the public URL printed above.
  5. Authentication: choose bearer/API key style auth and set the header
     Authorization to: Bearer <the token printed above>
  6. Transport: HTTP (this bridge speaks JSON over HTTP POST).
  7. Save, then start a chat and ask for your open studies (tool uxr_stats
     or the /uxr-stats equivalent) to confirm the connection.

Menu labels can shift between Gemini versions; the constant part is the
URL plus the Authorization header carrying this bridge's bearer token.
"""


def _log(message: str) -> None:
    print(f"uxr-serve: {message}", file=sys.stderr, flush=True)


def load_or_create_token(path: Path) -> tuple[str, bool]:
    """The bearer token plus whether it was freshly generated."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text, False
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8", newline="\n")
    return token, True


class StdioBridge:
    """One persistent stdio server subprocess behind a lock; one JSON-RPC
    message in, one response line out (notifications get no read)."""

    def __init__(self, server_path: Path):
        self.proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace",
        )
        self.lock = threading.Lock()

    def send(self, message: dict) -> str | None:
        """Forward one message; return the response line for a request."""
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.lock:
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise BridgeError(f"the stdio server is unreachable ({exc})") from exc
            if "id" not in message:
                return None  # notification or response; no reply comes back
            reader_line = self.proc.stdout.readline()
            if not reader_line:
                raise BridgeError("the stdio server closed its output")
            return reader_line.strip()

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class BridgeError(Exception):
    pass


def make_handler(bridge: StdioBridge, token: str):
    """The request handler bound to one bridge and one expected token."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "uxr-mcp-bridge/0.4"

        def _deny(self):
            body = b'{"error":"unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            return hmac.compare_digest(header.encode("utf-8"), expected.encode("utf-8"))

        def do_GET(self):
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_DELETE = do_GET
        do_PUT = do_GET
        do_PATCH = do_GET

        def do_POST(self):
            if not self._authorized():
                self._deny()
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self.send_response(413)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            raw = self.rfile.read(length) if length else b""
            try:
                message = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = b'{"error":"body must be one JSON-RPC message"}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not isinstance(message, dict):
                self._reject_body()
                return
            try:
                reply = bridge.send(message)
            except BridgeError as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if reply is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = reply.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reject_body(self):
            body = b'{"error":"body must be one JSON-RPC message"}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            _log("request handled (token never logged)")

    return Handler


def tunnel_url(port: int) -> str | None:
    """Start a cloudflared quick tunnel; return its public URL, or None."""
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return None
    marker = ".trycloudflare.com"
    deadline = threading.Event()
    result: list[str] = []

    def _read():
        for line in proc.stdout or []:
            if marker in line and not result:
                start = line.find("https://")
                if start != -1:
                    end = line.find(marker, start) + len(marker)
                    result.append(line[start:end].strip())
                    deadline.set()
                    return
        deadline.set()

    threading.Thread(target=_read, daemon=True).start()
    if not deadline.wait(timeout=TUNNEL_WAIT_SECONDS):
        proc.kill()
        return None
    if not result:
        proc.kill()
        return None
    return result[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve.py",
        description="Serve the uxr MCP stdio server over HTTP with required "
                    "bearer auth, plus an optional cloudflared quick tunnel.")
    parser.add_argument("--port", type=int, default=0,
                        help="local port (default: an ephemeral free port)")
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH),
                        help=f"bearer token location (default: {DEFAULT_TOKEN_PATH})")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="loopback only; never start a cloudflared tunnel")
    opts = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    token, fresh = load_or_create_token(Path(opts.token_file))
    bridge = StdioBridge(SERVER_PATH)
    server = ThreadingHTTPServer(("127.0.0.1", opts.port), make_handler(bridge, token))
    port = server.server_address[1]
    print(f"bearer token ({'generated now' if fresh else 'loaded'}; stored at "
          f"{opts.token_file}, never committed, never logged):")
    print(f"  {token}")
    print(f"bridge: http://127.0.0.1:{port}/ (loopback only; POST, auth required)")
    public = None
    if not opts.no_tunnel:
        public = tunnel_url(port)
        if public is None:
            print("no cloudflared quick tunnel is available; install it to get a "
                  "public HTTPS URL:")
            for label, command in INSTALL_HINTS.items():
                print(f"  {label}: {command}")
            print("rerun after installing, or use --no-tunnel for loopback-only serving.")
        else:
            print(f"public URL: {public}")
    if public is not None:
        print()
        print(GEMINI_STEPS, end="")
    print("Ctrl+C stops the bridge.")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
