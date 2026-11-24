#!/usr/bin/env python3
"""Serve the uxr MCP stdio server behind a local HTTP bridge with auth.

Goal (MO rulings, 2026-11-22/23): register the uxr server in the consumer
Gemini app (Connected Apps, Developer Mode) pointing at a public HTTPS URL
that tunnels to this bridge, which forwards every message to the stdio
server. Live Gemini testing rejected static bearer auth ("Gemini requires
standard OAuth for server connections"), so the bridge now embeds a minimal
OAuth 2.1 provider and accepts EITHER an OAuth-issued access token OR the
original static bearer token (back-compat for non-Gemini clients).

Usage (run from the repo root or the plugin root):

    python mcp-server/serve.py                    # tunnel if cloudflared exists
    python mcp-server/serve.py --no-tunnel        # loopback only, no tunnel
    python mcp-server/serve.py --port 8742        # fixed local port
    python mcp-server/serve.py --token-file PATH  # custom static token location

OAuth 2.1 provider (minimal, per MO spec):

- GET /.well-known/oauth-protected-resource and
  /.well-known/oauth-authorization-server: RFC 8414/9728 discovery
  documents, reachable without authentication (that is the point).
- POST /register: RFC 7591 dynamic client registration; any well-formed
  registration is accepted and returns a generated client_id +
  client_secret.
- GET /authorize: single-user local server, so the operator is
  auto-approved; answers 302 to the client's redirect_uri with a
  single-use authorization code (valid 10 minutes). PKCE S256 is honored
  when the client sends a code_challenge.
- POST /token: authorization_code exchange (client secret checked with a
  constant-time compare; PKCE verifier enforced when the code carried a
  challenge) and refresh_token grant (rotating). Tokens are short-lived
  and opaque; they live in memory only and disappear on restart.

Security bar:

- Auth is REQUIRED for MCP message POSTs, no exceptions, no localhost
  bypass: a missing or invalid token answers 401 with
  ``WWW-Authenticate: Bearer resource_metadata="<discovery URL>"`` (per
  the MCP auth spec - this header is what starts Gemini's OAuth dance).
  The comparison is constant-time. The static token is generated on first
  serve with ``secrets.token_urlsafe(32)`` and stored under the plugin's
  gitignored ``state/`` folder (never committed, never logged); issued
  codes and tokens are never logged either.
- The bridge binds 127.0.0.1 only: the loopback listener is reachable
  from this machine alone, and the only public exposure is the cloudflared
  quick tunnel, which authenticates every request the same way.
- POST carries one JSON-RPC message: requests (with an id) return the
  server's JSON-RPC response as ``application/json``; notifications and
  responses return 202. GET and DELETE outside discovery/authorize answer
  405 (the bridge never initiates messages, so there is no
  server-initiated stream to open).
- Stdlib only: ``http.server`` bridges stdio to HTTP; the only external
  binary is ``cloudflared`` (optional, shelled out, never required).

Exit 0 after Ctrl+C or when stdin closes. Diagnostics go to stderr; the
startup block (URL, token, registration steps) goes to stdout.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PLUGIN_ROOT / "mcp-server" / "server.py"
DEFAULT_TOKEN_PATH = PLUGIN_ROOT / "state" / "mcp-bridge-token"
MAX_BODY_BYTES = 10 * 1024 * 1024
RESPONSE_TIMEOUT_SECONDS = 60
TUNNEL_WAIT_SECONDS = 25
SCOPE = "mcp"
CODE_TTL_SECONDS = 600
ACCESS_TTL_SECONDS = 3600

INSTALL_HINTS = {
    "Windows": "winget install --id Cloudflare.cloudflared",
    "macOS": "brew install cloudflared",
    "Linux (deb)": ("curl -L --output cloudflared.deb https://github.com/"
                    "cloudflare/cloudflared/releases/latest/download/"
                    "cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb"),
}

GEMINI_STEPS = """Gemini Connected Apps registration (Developer Mode), OAuth flow:

  1. Open the Gemini app, enter Settings, and enable Developer mode.
  2. Open Connected apps -> Choose an app -> Create new.
  3. Server URL: paste the public URL printed above.
  4. Additional settings: paste the Client ID and Client secret from the
     registration block printed above (or leave them and let dynamic
     registration happen automatically), and use the "Copy redirect URI"
     button's value as the redirect URI when prompted.
  5. Connect: the consent screen auto-approves (single-user local server),
     Gemini exchanges the code, and every later request carries an OAuth
     access token this bridge validates.
  6. Confirm by asking for your open studies (tool uxr_stats).

Menu labels can shift between Gemini versions; the constant parts are the
URL, the client credentials, and the OAuth redirect this bridge serves.
"""


def _log(message: str) -> None:
    print(f"uxr-serve: {message}", file=sys.stderr, flush=True)


def load_or_create_token(path: Path) -> tuple[str, bool]:
    """The static bearer token plus whether it was freshly generated."""
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


def _constant(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthStore:
    """In-memory single-user OAuth 2.1 state (clients, codes, tokens).

    Everything is opaque and short-lived; a restart invalidates all of it,
    and clients simply re-register and re-authorize.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._clients: dict[str, dict] = {}
        self._codes: dict[str, dict] = {}
        self._access: dict[str, dict] = {}
        self._refresh: dict[str, dict] = {}

    def register(self, redirect_uris: list[str]) -> dict:
        client_id = "uxr-" + secrets.token_hex(8)
        client_secret = secrets.token_urlsafe(32)
        with self._lock:
            self._clients[client_id] = {"secret": client_secret,
                                       "redirect_uris": list(redirect_uris)}
        return {"client_id": client_id, "client_secret": client_secret,
                "redirect_uris": list(redirect_uris),
                "token_endpoint_auth_method": "client_secret_basic",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"]}

    def has_client(self, client_id: str) -> bool:
        with self._lock:
            return client_id in self._clients

    def client_ok(self, client_id: str, client_secret: str | None) -> bool:
        with self._lock:
            client = self._clients.get(client_id)
        if client is None or not isinstance(client_secret, str):
            return False
        return _constant(client_secret, client["secret"])

    def redirect_ok(self, client_id: str, redirect_uri: str) -> bool:
        with self._lock:
            client = self._clients.get(client_id)
        if client is None:
            return False
        registered = client["redirect_uris"]
        if not registered:
            return True  # registered without constraints; any https URI is fine
        return redirect_uri in registered

    def issue_code(self, client_id: str, redirect_uri: str,
                   code_challenge: str | None) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri,
                                "challenge": code_challenge,
                                "expires": time.time() + CODE_TTL_SECONDS}
        return code

    def exchange_code(self, code: str, client_id: str, verifier: str | None) -> dict | None:
        """Consume one authorization code; None when invalid/expired/reused."""
        with self._lock:
            entry = self._codes.pop(code, None)
        now = time.time()
        if entry is None or entry["expires"] < now or entry["client_id"] != client_id:
            return None
        if entry["challenge"]:
            if not verifier or not _constant(_pkce_s256(verifier), entry["challenge"]):
                return None
        return self._issue_tokens(client_id)

    def refresh(self, refresh_token: str, client_id: str) -> dict | None:
        """Rotate one refresh token; None when unknown or foreign."""
        with self._lock:
            entry = self._refresh.pop(refresh_token, None)
        if entry is None or entry["client_id"] != client_id:
            return None
        return self._issue_tokens(client_id)

    def _issue_tokens(self, client_id: str) -> dict:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        with self._lock:
            self._access[access] = {"client_id": client_id,
                                   "expires": time.time() + ACCESS_TTL_SECONDS}
            self._refresh[refresh] = {"client_id": client_id}
        return {"access_token": access, "token_type": "Bearer",
                "expires_in": ACCESS_TTL_SECONDS, "refresh_token": refresh,
                "scope": SCOPE}

    def access_ok(self, token: str) -> bool:
        with self._lock:
            entry = self._access.get(token)
        return entry is not None and entry["expires"] >= time.time()


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


def make_handler(bridge: StdioBridge, static_token: str, oauth: OAuthStore,
                 base_url_holder: dict):
    """The request handler bound to one bridge, the static token, the OAuth
    store, and a holder carrying the externally reachable base URL (set
    once the tunnel URL is known, before serving)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "uxr-mcp-bridge/0.4"

        def _base(self) -> str:
            return base_url_holder.get("url") or f"http://127.0.0.1:{self.server.server_port}"

        def _send(self, status: int, body: bytes, content_type: str = "application/json",
                  extra_headers: list[tuple[str, str]] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers or []:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict,
                  extra_headers: list[tuple[str, str]] | None = None):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json",
                       extra_headers)

        def _deny(self):
            metadata = self._base() + "/.well-known/oauth-protected-resource"
            self._send(401, b'{"error":"unauthorized"}', "application/json",
                       [("WWW-Authenticate", f'Bearer resource_metadata="{metadata}"')])

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return False
            presented = header[len("Bearer "):]
            if _constant(presented, static_token):
                return True
            return oauth.access_ok(presented)

        def _read_body(self) -> bytes | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._send(413, b'{"error":"body too large"}')
                return None
            return self.rfile.read(length) if length else b""

        # --- OAuth endpoints (public; discovery must work pre-auth) ---

        def _discovery_documents(self) -> dict[str, dict]:
            base = self._base()
            return {
                "/.well-known/oauth-protected-resource": {
                    "resource": base + "/",
                    "authorization_servers": [base],
                    "scopes_supported": [SCOPE],
                    "bearer_methods_supported": ["header"],
                },
                "/.well-known/oauth-authorization-server": {
                    "issuer": base,
                    "authorization_endpoint": base + "/authorize",
                    "token_endpoint": base + "/token",
                    "registration_endpoint": base + "/register",
                    "scopes_supported": [SCOPE],
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["client_secret_basic",
                                                              "client_secret_post"],
                },
            }

        def do_GET(self):
            path = urlparse(self.path).path
            docs = self._discovery_documents()
            if path in docs:
                self._json(200, docs[path])
                return
            if path == "/authorize":
                self._authorize()
                return
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _authorize(self):
            query = parse_qs(urlparse(self.path).query)
            pick = lambda name: (query.get(name) or [""])[0]  # noqa: E731
            response_type = pick("response_type")
            client_id = pick("client_id")
            redirect_uri = pick("redirect_uri")
            state = pick("state")
            challenge = pick("code_challenge")
            if response_type != "code":
                self._json(400, {"error": "unsupported_response_type"})
                return
            if not oauth.has_client(client_id):
                self._json(400, {"error": "unauthorized_client",
                                 "hint": "register first via POST /register"})
                return
            if not redirect_uri or not oauth.redirect_ok(client_id, redirect_uri):
                self._json(400, {"error": "invalid_request",
                                 "hint": "redirect_uri does not match the registration"})
                return
            code = oauth.issue_code(client_id, redirect_uri, challenge or None)
            params = {"code": code}
            if state:
                params["state"] = state
            separator = "&" if "?" in redirect_uri else "?"
            self.send_response(302)
            self.send_header("Location", redirect_uri + separator + urlencode(params))
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_DELETE = do_GET
        do_PUT = do_GET
        do_PATCH = do_GET

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/register":
                self._register()
                return
            if path == "/token":
                self._token()
                return
            if not self._authorized():
                self._deny()
                return
            self._forward_message()

        def _register(self):
            raw = self._read_body()
            if raw is None:
                return
            try:
                request = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                request = {}
            if not isinstance(request, dict):
                request = {}
            redirect_uris = request.get("redirect_uris") or []
            if not isinstance(redirect_uris, list) \
                    or not all(isinstance(u, str) and u for u in redirect_uris):
                redirect_uris = []
            self._json(201, oauth.register(redirect_uris))

        def _token(self):
            raw = self._read_body()
            if raw is None:
                return
            # Accept both form-encoded and JSON bodies; OAuth clients send
            # application/x-www-form-urlencoded, stdlib tests may send JSON.
            try:
                form = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                form = None
            if not isinstance(form, dict):
                form = {k: v[0] for k, v in
                        parse_qs(raw.decode("utf-8", "replace")).items()}
            grant = str(form.get("grant_type") or "")
            client_id = str(form.get("client_id") or "")
            client_secret = form.get("client_secret")
            if not isinstance(client_secret, str):
                # client_secret_basic: credentials on the Authorization header
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Basic "):
                    import base64 as _b64
                    try:
                        decoded = _b64.b64decode(auth[6:]).decode("utf-8")
                        client_id, client_secret = decoded.split(":", 1)
                    except (ValueError, UnicodeDecodeError):
                        client_id, client_secret = client_id, None
            if not oauth.client_ok(client_id, client_secret if isinstance(client_secret, str) else None):
                self._json(401, {"error": "invalid_client"})
                return
            if grant == "authorization_code":
                tokens = oauth.exchange_code(str(form.get("code") or ""), client_id,
                                             form.get("code_verifier"))
            elif grant == "refresh_token":
                tokens = oauth.refresh(str(form.get("refresh_token") or ""), client_id)
            else:
                self._json(400, {"error": "unsupported_grant_type"})
                return
            if tokens is None:
                self._json(400, {"error": "invalid_grant"})
                return
            self._json(200, tokens)

        def _forward_message(self):
            raw = self._read_body()
            if raw is None:
                return
            try:
                message = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"error": "body must be one JSON-RPC message"})
                return
            if not isinstance(message, dict):
                self._json(400, {"error": "body must be one JSON-RPC message"})
                return
            try:
                reply = bridge.send(message)
            except BridgeError as exc:
                self._json(502, {"error": str(exc)})
                return
            if reply is None:
                self._send(202, b"")
                return
            self._send(200, reply.encode("utf-8"))

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            _log("request handled (tokens and codes never logged)")

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
    done = threading.Event()
    result: list[str] = []

    def _read():
        for line in proc.stdout or []:
            if marker in line and not result:
                start = line.find("https://")
                if start != -1:
                    end = line.find(marker, start) + len(marker)
                    result.append(line[start:end].strip())
                    done.set()
                    return
        done.set()

    threading.Thread(target=_read, daemon=True).start()
    if not done.wait(timeout=TUNNEL_WAIT_SECONDS):
        proc.kill()
        return None
    if not result:
        proc.kill()
        return None
    return result[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve.py",
        description="Serve the uxr MCP stdio server over HTTP with OAuth 2.1 "
                    "(plus static bearer back-compat) and an optional "
                    "cloudflared quick tunnel.")
    parser.add_argument("--port", type=int, default=0,
                        help="local port (default: an ephemeral free port)")
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN_PATH),
                        help=f"static bearer token location (default: {DEFAULT_TOKEN_PATH})")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="loopback only; never start a cloudflared tunnel")
    opts = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    static_token, fresh = load_or_create_token(Path(opts.token_file))
    oauth = OAuthStore()
    bridge = StdioBridge(SERVER_PATH)
    base_url_holder: dict = {"url": None}
    server = ThreadingHTTPServer(("127.0.0.1", opts.port),
                                 make_handler(bridge, static_token, oauth, base_url_holder))
    port = server.server_address[1]

    print(f"static bearer token ({'generated now' if fresh else 'loaded'}; stored at "
          f"{opts.token_file}, never committed, never logged; non-Gemini clients only):")
    print(f"  {static_token}")
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
        base_url_holder["url"] = public
        # A pre-registered client so the operator can paste credentials even
        # when Gemini's dialog asks before any dynamic registration runs.
        registration = oauth.register([public + "/authorize",
                                       "https://gemini.google.com/redirect"])
        print(f"OAuth client registration (also available dynamically via "
              f"POST {public}/register):")
        print(f"  client_id: {registration['client_id']}")
        print(f"  client_secret: {registration['client_secret']}")
        print(f"  discovery: {public}/.well-known/oauth-authorization-server")
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
