"""Selftest for uxr-plugin/mcp-server/server.py (stdio MCP surface).

Speaks the real newline-delimited JSON-RPC protocol to a spawned server
process, exactly as a host harness would: initialize handshake (version
echo, capabilities, instructions), the ten-tool tools/list, one tools/call
against a fixture state directory (stdout verbatim), unknown method and
malformed-line handling (the server keeps serving), resources and prompts.

Fixture configs live only in a temp directory; the machine's real harness
config files are never read or written.

Run: ``python3 -m tests.uxr_selftests.mcp_server`` or bare (also under the
smoke gate's ``--selftest`` flag). Exit 0 = every check passed.
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "uxr-plugin" / "mcp-server" / "server.py"

EXPECTED_TOOLS = [
    "scaffold_workspace", "build_body", "parse_shorthand", "roster_apply",
    "recruit_funnel", "classify", "report_html", "deck_render", "uxr_stats",
    "review_checks",
]

READ_TIMEOUT_SECONDS = 6


class Client:
    """One server process plus a request/response line channel."""

    def __init__(self, env=None):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", env=env,
        )
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)

    def send(self, message) -> None:
        text = message if isinstance(message, str) else json.dumps(message)
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout=READ_TIMEOUT_SECONDS):
        return json.loads(self.lines.get(timeout=timeout))

    def request(self, message):
        self.send(message)
        return self.recv()

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _selftest() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append((name, detail))

    print("mcp-server/server.py selftest")
    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "state"
        state.mkdir()
        journal = state / "work-log-2026-11-08.jsonl"
        journal.write_text(json.dumps(
            {"session_id": "s1", "ended_at": "2026-11-08T09:00:00-05:00",
             "commands_used": ["/uxr-new"], "files_edited_count": 2,
             "tracker_tool_calls": 1, "processed": False}) + "\n", encoding="utf-8")
        env = {**os.environ, "UXR_STATE_DIR": str(state)}
        client = Client(env=env)
        try:
            # initialize handshake: version echo, capabilities, instructions
            reply = client.request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"protocolVersion": "2025-06-18",
                                               "capabilities": {},
                                               "clientInfo": {"name": "selftest", "version": "0"}}})
            result = reply.get("result", {})
            check("initialize echoes the requested protocolVersion",
                  result.get("protocolVersion") == "2025-06-18", repr(result)[:120])
            caps = result.get("capabilities", {})
            check("initialize advertises tools, resources, and prompts",
                  all(k in caps for k in ("tools", "resources", "prompts")), repr(caps))
            info = result.get("serverInfo", {})
            check("serverInfo carries name, version, and instructions",
                  info.get("name") == "uxr-plugin" and bool(info.get("version"))
                  and len(str(info.get("instructions", ""))) > 200, repr(info)[:120])
            check("instructions also sits at the result top level",
                  len(str(result.get("instructions", ""))) > 200, repr(result)[:80])
            client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            # ping
            reply = client.request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            check("ping returns an empty result object",
                  reply.get("id") == 2 and reply.get("result") == {}, repr(reply))

            # tools/list: exactly the ten curated tools, object schemas
            reply = client.request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
            tools = reply.get("result", {}).get("tools", [])
            names = [t.get("name") for t in tools]
            check("tools/list returns exactly the ten curated tools in order",
                  names == EXPECTED_TOOLS, repr(names))
            check("every tool carries an object inputSchema and a description",
                  all(isinstance(t.get("inputSchema"), dict)
                      and t["inputSchema"].get("type") == "object"
                      and isinstance(t.get("description"), str) and t["description"]
                      for t in tools), repr(tools)[:120])

            # tools/call: script stdout arrives verbatim from the fixture state
            reply = client.request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                    "params": {"name": "uxr_stats",
                                               "arguments": {"json": True}}})
            call = reply.get("result", {})
            text = (call.get("content") or [{}])[0].get("text", "")
            payload = None
            try:
                payload = json.loads(text)
            except ValueError:
                pass
            check("tools/call uxr_stats is exit-0 and the stdout parses as JSON",
                  call.get("isError") is False and isinstance(payload, dict)
                  and payload.get("journal", {}).get("distinct_sessions") == 1,
                  repr(text)[:120])

            # invalid tool arguments are rejected without spawning a script
            reply = client.request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                    "params": {"name": "review_checks", "arguments": {}}})
            check("tools/call with missing required arguments is a -32602 error",
                  reply.get("error", {}).get("code") == -32602, repr(reply)[:120])

            # resources: one reference and one hyphenated-group fragment
            reply = client.request({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
            resources = reply.get("result", {}).get("resources", [])
            uris = [r.get("uri") for r in resources]
            check("resources/list covers references and prompt fragments",
                  "uxr://references/tracker" in uris
                  and "uxr://fragments/hcd-gate-verdict-contract" in uris
                  and all(r.get("mimeType") == "text/markdown" for r in resources),
                  repr(uris)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                                    "params": {"uri": "uxr://references/tracker"}})
            ref = (reply.get("result", {}).get("contents") or [{}])[0]
            check("resources/read returns the reference text",
                  "Tracker adapter" in ref.get("text", ""), repr(ref)[:80])
            reply = client.request({"jsonrpc": "2.0", "id": 8, "method": "resources/read",
                                    "params": {"uri": "uxr://fragments/hcd-gate-verdict-contract"}})
            frag = (reply.get("result", {}).get("contents") or [{}])[0]
            check("resources/read resolves a fragment under a hyphenated group",
                  bool(frag.get("text")) and frag.get("uri") == "uxr://fragments/hcd-gate-verdict-contract",
                  repr(reply)[:120])

            # prompts: list and get one command template
            reply = client.request({"jsonrpc": "2.0", "id": 9, "method": "prompts/list"})
            prompts = reply.get("result", {}).get("prompts", [])
            prompt_names = [p.get("name") for p in prompts]
            check("prompts/list covers the shipped commands with descriptions",
                  "uxr-stats" in prompt_names
                  and all(isinstance(p.get("description"), str) and p["description"]
                          for p in prompts), repr(prompt_names)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 10, "method": "prompts/get",
                                    "params": {"name": "uxr-stats"}})
            got = reply.get("result", {})
            message = (got.get("messages") or [{}])[0]
            template = (message.get("content") or {}).get("text", "")
            check("prompts/get returns the command body as the template",
                  message.get("role") == "user" and "uxr_stats.py" in template
                  and bool(got.get("description")), repr(template)[:80])

            # unknown method and malformed line: error codes, still serving
            reply = client.request({"jsonrpc": "2.0", "id": 11, "method": "no/such/method"})
            check("unknown method answers -32601",
                  reply.get("error", {}).get("code") == -32601, repr(reply))
            client.send("this is not json")
            broken = client.recv()
            check("a malformed line answers -32700 with id null",
                  broken.get("id") is None and broken.get("error", {}).get("code") == -32700,
                  repr(broken))
            reply = client.request({"jsonrpc": "2.0", "id": 12, "method": "ping"})
            check("the server keeps serving after a malformed line",
                  reply.get("id") == 12 and reply.get("result") == {}, repr(reply))
        finally:
            client.close()
        check("the server exits 0 when stdin closes", client.proc.returncode == 0,
              repr(client.proc.returncode))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        for name, detail in failures:
            print("  - %s: %s" % (name, detail))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
