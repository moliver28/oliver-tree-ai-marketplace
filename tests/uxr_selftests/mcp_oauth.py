"""Selftest for the OAuth 2.1 provider in mcp-server/serve.py (round 4).

Drives a live loopback bridge through the full dance Gemini performs:

1. unauthenticated discovery (both RFC 8414/9728 documents),
2. dynamic client registration (RFC 7591),
3. auto-approved /authorize with a 302 code redirect (PKCE S256),
4. authorization_code token exchange (bad codes and secrets rejected),
5. authenticated MCP POST carrying ONLY the OAuth access token,
6. 401 with a WWW-Authenticate resource_metadata pointer without a token,
7. the static bearer token still works (back-compat),
8. the refresh_token grant rotates to a fresh working token.

Run: ``python3 -m tests.uxr_selftests.mcp_oauth`` or bare. Exit 0 = pass.
"""
import base64
import hashlib
import http.client
import json
import secrets
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE = REPO_ROOT / "uxr-plugin" / "mcp-server" / "serve.py"
MODERN_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"


class NoRedirectConnection:
    """Raw HTTP/1.1 calls to one loopback port; redirects are NOT followed.

    One fresh connection per request: responses are short-lived and the
    bridge closes idle connections, so keep-alive reuse would be flaky.
    """

    def __init__(self, port: int):
        self.port = port

    def request(self, method, path, body=None, headers=None):
        payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
        self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        self.conn.request(method, path, body=payload, headers=headers or {})

    def response(self):
        response = self.conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        self.conn.close()
        return result


def _selftest() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append((name, detail))

    print("mcp-server/serve.py OAuth selftest")
    with tempfile.TemporaryDirectory() as td:
        token_file = Path(td) / "state" / "mcp-bridge-token"
        proc = subprocess.Popen(
            [sys.executable, "-I", str(SERVE), "--no-tunnel",
             "--token-file", str(token_file)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace")
        try:
            proc.stdout.readline()
            static_token = proc.stdout.readline().strip().split()[-1]
            bridge_line = proc.stdout.readline()
            port = int(bridge_line.rsplit(":", 1)[1].split("/")[0])
            base = f"http://127.0.0.1:{port}"
            conn = NoRedirectConnection(port)

            # discovery, unauthenticated
            conn.request("GET", "/.well-known/oauth-protected-resource")
            status, headers, body = conn.response()
            protected = json.loads(body)
            check("protected-resource metadata is public and names this server",
                  status == 200 and base in protected.get("resource", "")
                  and base in protected.get("authorization_servers", [])[0],
                  repr(body)[:120])
            conn.request("GET", "/.well-known/oauth-authorization-server")
            status, _h, body = conn.response()
            server_meta = json.loads(body)
            check("authorization-server metadata advertises the full endpoint set",
                  status == 200
                  and server_meta.get("authorization_endpoint") == base + "/authorize"
                  and server_meta.get("token_endpoint") == base + "/token"
                  and server_meta.get("registration_endpoint") == base + "/register"
                  and "authorization_code" in server_meta.get("grant_types_supported", []),
                  repr(body)[:160])

            # dynamic client registration
            redirect_uri = "https://gemini.example/redirect"
            conn.request("POST", "/register",
                         body=json.dumps({"redirect_uris": [redirect_uri]}),
                         headers={"Content-Type": "application/json"})
            status, _h, body = conn.response()
            registration = json.loads(body)
            check("DCR accepts a registration and returns client credentials",
                  status == 201 and registration.get("client_id", "").startswith("uxr-")
                  and bool(registration.get("client_secret")),
                  repr(body)[:120])
            client_id = registration["client_id"]
            client_secret = registration["client_secret"]

            # authorize: auto-approved 302 with code + state, PKCE S256
            verifier = secrets.token_urlsafe(40)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            authorize_query = urllib.parse.urlencode({
                "response_type": "code", "client_id": client_id,
                "redirect_uri": redirect_uri, "state": "st4te",
                "code_challenge": challenge, "code_challenge_method": "S256",
                "scope": "mcp"})
            conn.request("GET", "/authorize?" + authorize_query)
            status, headers, body = conn.response()
            location = headers.get("Location", "")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            code = (query.get("code") or [""])[0]
            check("authorize auto-approves the operator with a 302 code redirect",
                  status == 302 and location.startswith(redirect_uri + "?")
                  and bool(code) and (query.get("state") or [""])[0] == "st4te",
                  repr((status, location))[:160])
            bad_client = urllib.parse.urlencode({
                "response_type": "code", "client_id": "uxr-unknown",
                "redirect_uri": redirect_uri})
            conn.request("GET", "/authorize?" + bad_client)
            status, _h, body = conn.response()
            check("authorize rejects an unregistered client with 400",
                  status == 400 and json.loads(body).get("error") == "unauthorized_client",
                  repr(body)[:120])

            # token exchange: wrong secret first, then the real one with PKCE
            conn.request("POST", "/token",
                         body=urllib.parse.urlencode({
                             "grant_type": "authorization_code", "code": code,
                             "client_id": client_id, "client_secret": "wrong",
                             "redirect_uri": redirect_uri, "code_verifier": verifier}),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            status, _h, body = conn.response()
            check("token exchange with a wrong client secret is 401 invalid_client",
                  status == 401 and json.loads(body).get("error") == "invalid_client",
                  repr(body)[:120])
            conn.request("POST", "/token",
                         body=urllib.parse.urlencode({
                             "grant_type": "authorization_code", "code": code,
                             "client_id": client_id, "client_secret": client_secret,
                             "redirect_uri": redirect_uri, "code_verifier": verifier}),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            status, _h, body = conn.response()
            tokens = json.loads(body)
            check("token exchange issues an opaque access token and a refresh token",
                  status == 200 and tokens.get("token_type") == "Bearer"
                  and tokens.get("access_token") and tokens.get("refresh_token")
                  and tokens.get("scope") == "mcp", repr(body)[:160])
            access_token = tokens["access_token"]
            refresh_token = tokens["refresh_token"]
            conn.request("POST", "/token",
                         body=urllib.parse.urlencode({
                             "grant_type": "authorization_code", "code": code,
                             "client_id": client_id, "client_secret": client_secret,
                             "redirect_uri": redirect_uri, "code_verifier": verifier}),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            status, _h, body = conn.response()
            check("an authorization code is single-use (replay is invalid_grant)",
                  status == 400 and json.loads(body).get("error") == "invalid_grant",
                  repr(body)[:120])

            # authenticated MCP POST with ONLY the OAuth token
            tools_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                             "params": {"_meta": {MODERN_KEY: "2026-07-28",
                                                  CAPS_KEY: {}}}}
            conn.request("POST", "/", body=json.dumps(tools_request),
                         headers={"Content-Type": "application/json",
                                  "Authorization": "Bearer " + access_token})
            status, _h, body = conn.response()
            payload = json.loads(body)
            check("tools/list authenticated with the OAuth access token",
                  status == 200 and len(payload.get("result", {}).get("tools", [])) == 10,
                  repr(body)[:120])

            # unauthenticated: 401 + WWW-Authenticate pointing at the metadata
            conn.request("POST", "/", body=json.dumps(tools_request),
                         headers={"Content-Type": "application/json"})
            status, headers, _body = conn.response()
            www = headers.get("WWW-Authenticate", "")
            check("an unauthenticated POST is 401 with the resource_metadata pointer",
                  status == 401
                  and "Bearer" in www
                  and "/.well-known/oauth-protected-resource" in www,
                  repr((status, www))[:160])

            # static bearer back-compat
            conn.request("POST", "/", body=json.dumps(tools_request),
                         headers={"Content-Type": "application/json",
                                  "Authorization": "Bearer " + static_token})
            status, _h, body = conn.response()
            check("the static bearer token still authenticates (back-compat)",
                  status == 200 and json.loads(body).get("result") is not None,
                  repr(body)[:120])

            # refresh grant: rotation issues a fresh working token
            conn.request("POST", "/token",
                         body=urllib.parse.urlencode({
                             "grant_type": "refresh_token", "refresh_token": refresh_token,
                             "client_id": client_id, "client_secret": client_secret}),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            status, _h, body = conn.response()
            rotated = json.loads(body)
            check("the refresh grant rotates to a fresh access token",
                  status == 200 and rotated.get("access_token")
                  and rotated["access_token"] != access_token
                  and rotated.get("refresh_token") not in (None, refresh_token),
                  repr(body)[:120])
            conn.request("POST", "/", body=json.dumps(tools_request),
                         headers={"Content-Type": "application/json",
                                  "Authorization": "Bearer " + rotated["access_token"]})
            status, _h, body = conn.response()
            check("the rotated access token authenticates",
                  status == 200 and json.loads(body).get("result") is not None,
                  repr(body)[:120])
            conn.request("POST", "/token",
                         body=urllib.parse.urlencode({
                             "grant_type": "refresh_token", "refresh_token": refresh_token,
                             "client_id": client_id, "client_secret": client_secret}),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            status, _h, body = conn.response()
            check("a consumed refresh token cannot be replayed",
                  status == 400 and json.loads(body).get("error") == "invalid_grant",
                  repr(body)[:120])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        for name, detail in failures:
            print("  - %s: %s" % (name, detail))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
