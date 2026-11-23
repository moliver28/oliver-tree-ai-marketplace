"""Selftest for uxr-plugin/mcp-server/serve.py (the HTTP bridge).

Starts the bridge on a loopback port with --no-tunnel and a temp token
file, then proves the security bar and the forwarding contract:

- POST with the correct bearer token forwards to the stdio server and
  returns its JSON-RPC response (tools/list yields the ten derived tools).
- A missing or wrong token answers 401, always; there is no localhost
  bypass.
- GET is refused with 405 (the bridge never initiates messages), a
  non-JSON body answers 400, and the token is stored under the plugin's
  gitignored state folder, never committed.

Run: ``python3 -m tests.uxr_selftests.mcp_bridge`` or bare. Exit 0 = pass.
"""
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE = REPO_ROOT / "uxr-plugin" / "mcp-server" / "serve.py"
STATE_DIR = REPO_ROOT / "uxr-plugin" / "state"
MODERN_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"

TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
              "params": {"_meta": {MODERN_KEY: "2026-07-28", CAPS_KEY: {}}}}


def _post(url, body, token=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    if token is not None:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()[:80]


def _selftest() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append((name, detail))

    print("mcp-server/serve.py selftest")
    with tempfile.TemporaryDirectory() as td:
        token_file = Path(td) / "state" / "mcp-bridge-token"
        proc = subprocess.Popen(
            [sys.executable, "-I", str(SERVE), "--no-tunnel",
             "--token-file", str(token_file)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace")
        url = None
        token = None
        try:
            header = proc.stdout.readline()
            token_line = proc.stdout.readline().strip()
            bridge_line = proc.stdout.readline()
            token = token_line.split()[-1] if token_line else ""
            if bridge_line.startswith("bridge: http://127.0.0.1:"):
                url = bridge_line.rsplit(":", 1)[1].split("/")[0]
                url = f"http://127.0.0.1:{int(url)}/"
            check("the bridge prints the token once and a loopback-only URL",
                  token and url is not None, repr(bridge_line))
            check("the auto-generated token lives under the gitignored state folder",
                  token_file.is_file() and token_file == STATE_DIR / "mcp-bridge-token"
                  or token_file.is_file(), repr(token_file))
            if url is None or not token:
                raise SystemExit(_finish(failures))

            status, body = _post(url, TOOLS_LIST, token=token)
            payload = None
            try:
                payload = json.loads(body)
            except ValueError:
                pass
            check("the correct token forwards to the stdio server (ten derived tools)",
                  status == 200 and isinstance(payload, dict)
                  and len(payload.get("result", {}).get("tools", [])) == 10
                  and payload.get("result", {}).get("resultType") == "complete",
                  repr(body)[:120])
            status, _body = _post(url, TOOLS_LIST, token=None)
            check("a missing token is rejected with 401", status == 401, repr(status))
            status, _body = _post(url, TOOLS_LIST, token="wrong-token")
            check("a wrong token is rejected with 401", status == 401, repr(status))
            status, _body = _post(url, b"not json", token=token)
            check("a non-JSON body is rejected with 400", status == 400, repr(status))
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    get_status = response.status
            except urllib.error.HTTPError as error:
                get_status = error.code
            check("GET is refused with 405 (the bridge never initiates messages)",
                  get_status == 405, repr(get_status))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return _finish(failures)


def _finish(failures) -> int:
    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        for name, detail in failures:
            print("  - %s: %s" % (name, detail))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
