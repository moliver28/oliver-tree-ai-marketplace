"""Selftest for uxr-plugin/mcp-server/server.py (stdio MCP surface).

Speaks the real newline-delimited JSON-RPC protocol to a spawned server
process, exactly as a host harness would, across BOTH protocol eras:
legacy initialize handshake (version echo, fallback, capabilities,
instructions, tools, calls, resources, prompts, error codes) and the
2026-07-28 modern per-request era (server/discover, resultType-complete
results, -32022 version rejection, required clientCapabilities). Also
covers the derived-schema layer, the UTF-8 output pinning, and the
resource name validation.

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
MODERN_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"

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


def _modern_params(extra=None):
    meta = {MODERN_KEY: "2026-07-28", CAPS_KEY: {}}
    if extra:
        meta.update(extra)
    return {"_meta": meta}


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
            # --- legacy era: initialize handshake ---
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
            check("initialize names the universal uxr-workspaces default",
                  "uxr-workspaces" in str(result.get("instructions", "")),
                  repr(result.get("instructions", ""))[:80])
            client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            # legacy negotiation: an unsupported requested version falls back
            reply = client.request({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                                    "params": {"protocolVersion": "2024-11-05"}})
            check("initialize with an unsupported version answers the newest "
                  "supported legacy revision (2025-11-25)",
                  reply.get("result", {}).get("protocolVersion") == "2025-11-25",
                  repr(reply)[:120])

            # ping (legacy shape)
            reply = client.request({"jsonrpc": "2.0", "id": 3, "method": "ping"})
            check("ping returns an empty result object",
                  reply.get("id") == 3 and reply.get("result") == {}, repr(reply))

            # tools/list: exactly the ten curated tools, derived object schemas
            reply = client.request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
            tools = reply.get("result", {}).get("tools", [])
            names = [t.get("name") for t in tools]
            check("tools/list returns exactly the ten curated tools in order",
                  names == EXPECTED_TOOLS, repr(names))
            check("every tool carries an object inputSchema and a description",
                  all(isinstance(t.get("inputSchema"), dict)
                      and t["inputSchema"].get("type") == "object"
                      and isinstance(t.get("description"), str) and t["description"]
                      for t in tools), repr(tools)[:120])
            schemas = {t["name"]: t["inputSchema"] for t in tools}
            check("roster_apply derives its required path trio from the script table",
                  schemas["roster_apply"]["properties"].get("spec", {}).get("type") == "string"
                  and set(schemas["roster_apply"]["required"]) == {"spec", "ops", "out"},
                  repr(schemas["roster_apply"])[:160])
            check("uxr_stats derives --json as a boolean switch and --days as an integer",
                  schemas["uxr_stats"]["properties"].get("json", {}).get("type") == "boolean"
                  and schemas["uxr_stats"]["properties"].get("days", {}).get("type") == "integer",
                  repr(schemas["uxr_stats"])[:120])
            check("scaffold_workspace derives the subcommand enum from the script table",
                  set(schemas["scaffold_workspace"]["properties"]["subcommand"]["enum"])
                  == {"slug", "scaffold", "lookup-workspace", "render-overview",
                      "append-outreach-entry", "validate-recruitment"},
                  repr(schemas["scaffold_workspace"])[:120])

            # tools/call: script stdout arrives verbatim from the fixture state
            reply = client.request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
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

            # UTF-8 pinning: non-ASCII survives the child process round trip
            shorthand = ('{"kind":"roster","op":"+=",'
                         '"arg":"Ame\\u0301lie Example|a@x.io|||Scheduled|"}')
            reply = client.request({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                    "params": {"name": "parse_shorthand",
                                               "arguments": {"stdin": shorthand}}})
            call = reply.get("result", {})
            text = (call.get("content") or [{}])[0].get("text", "")
            check("tools/call round-trips non-ASCII output verbatim",
                  call.get("isError") is False and "Ame\u0301lie" in text
                  or "Amélie" in text, repr(text)[:120])

            # derived argv validation answers -32602 (never -32603/KeyError)
            reply = client.request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                    "params": {"name": "review_checks", "arguments": {}}})
            check("tools/call with missing required arguments is a -32602 error",
                  reply.get("error", {}).get("code") == -32602, repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                                    "params": {"name": "scaffold_workspace",
                                               "arguments": {}}})
            check("scaffold_workspace without a subcommand is -32602, not a KeyError",
                  reply.get("error", {}).get("code") == -32602, repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                    "params": {"name": "scaffold_workspace",
                                               "arguments": {"subcommand": "slug",
                                                             "title": "T", "quarter": "Q",
                                                             "max_body": True}}})
            check("an integer argument rejects a boolean (true) as -32602",
                  reply.get("error", {}).get("code") == -32602, repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                                    "params": {"name": "scaffold_workspace",
                                               "arguments": {"subcommand": "bogus"}}})
            check("an unknown subcommand value is -32602 with the valid set named",
                  reply.get("error", {}).get("code") == -32602
                  and "slug" in reply.get("error", {}).get("message", ""), repr(reply)[:160])

            # resources: list, one reference, one hyphenated-group fragment
            reply = client.request({"jsonrpc": "2.0", "id": 11, "method": "resources/list"})
            resources = reply.get("result", {}).get("resources", [])
            uris = [r.get("uri") for r in resources]
            check("resources/list covers references and prompt fragments",
                  "uxr://references/tracker" in uris
                  and "uxr://fragments/hcd-gate-verdict-contract" in uris
                  and all(r.get("mimeType") == "text/markdown" for r in resources),
                  repr(uris)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 12, "method": "resources/read",
                                    "params": {"uri": "uxr://references/tracker"}})
            ref = (reply.get("result", {}).get("contents") or [{}])[0]
            check("resources/read returns the reference text",
                  "Tracker adapter" in ref.get("text", ""), repr(ref)[:80])
            reply = client.request({"jsonrpc": "2.0", "id": 13, "method": "resources/read",
                                    "params": {"uri": "uxr://fragments/hcd-gate-verdict-contract"}})
            frag = (reply.get("result", {}).get("contents") or [{}])[0]
            check("resources/read resolves a fragment under a hyphenated group",
                  bool(frag.get("text")) and frag.get("uri") == "uxr://fragments/hcd-gate-verdict-contract",
                  repr(reply)[:120])
            for bad_uri in ("uxr://references/../../../etc/passwd",
                            "uxr://references/C:foo",
                            "uxr://fragments/../secrets/x"):
                reply = client.request({"jsonrpc": "2.0", "id": 14,
                                        "method": "resources/read",
                                        "params": {"uri": bad_uri}})
                check(f"resources/read rejects {bad_uri.rsplit('/', 1)[-1]!r} with -32602",
                      reply.get("error", {}).get("code") == -32602, repr(reply)[:120])

            # prompts: list and get one command template
            reply = client.request({"jsonrpc": "2.0", "id": 15, "method": "prompts/list"})
            prompts = reply.get("result", {}).get("prompts", [])
            prompt_names = [p.get("name") for p in prompts]
            check("prompts/list covers the shipped commands with descriptions",
                  "uxr-stats" in prompt_names
                  and all(isinstance(p.get("description"), str) and p["description"]
                          for p in prompts), repr(prompt_names)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 16, "method": "prompts/get",
                                    "params": {"name": "uxr-stats"}})
            got = reply.get("result", {})
            message = (got.get("messages") or [{}])[0]
            template = (message.get("content") or {}).get("text", "")
            check("prompts/get returns the command body as the template",
                  message.get("role") == "user" and "uxr_stats.py" in template
                  and bool(got.get("description")), repr(template)[:80])

            # unknown method and malformed line: error codes, still serving
            reply = client.request({"jsonrpc": "2.0", "id": 17, "method": "no/such/method"})
            check("unknown method answers -32601",
                  reply.get("error", {}).get("code") == -32601, repr(reply))
            client.send("this is not json")
            broken = client.recv()
            check("a malformed line answers -32700 with id null",
                  broken.get("id") is None and broken.get("error", {}).get("code") == -32700,
                  repr(broken))

            # --- modern era (2026-07-28): stateless per-request metadata ---
            reply = client.request({"jsonrpc": "2.0", "id": 18,
                                    "method": "server/discover",
                                    "params": _modern_params()})
            discovered = reply.get("result", {})
            check("server/discover returns a modern DiscoverResult",
                  discovered.get("resultType") == "complete"
                  and discovered.get("supportedVersions") == ["2026-07-28"]
                  and isinstance(discovered.get("capabilities"), dict)
                  and len(str(discovered.get("instructions", ""))) > 200,
                  repr(discovered)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 19,
                                    "method": "tools/list", "params": _modern_params()})
            modern_tools = reply.get("result", {})
            check("modern tools/list wraps the derived tools with resultType complete",
                  modern_tools.get("resultType") == "complete"
                  and [t.get("name") for t in modern_tools.get("tools", [])] == EXPECTED_TOOLS,
                  repr(modern_tools)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 20,
                                    "method": "tools/call",
                                    "params": {**_modern_params(), "name": "uxr_stats",
                                               "arguments": {"json": True}}})
            check("modern tools/call returns resultType complete with the script output",
                  reply.get("result", {}).get("resultType") == "complete"
                  and reply["result"].get("isError") is False, repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 21,
                                    "method": "tools/list",
                                    "params": _modern_params({MODERN_KEY: "2026-01-01"})})
            error = reply.get("error", {})
            check("an unsupported modern version is rejected with -32022 and the "
                  "supported list in data",
                  error.get("code") == -32022
                  and error.get("data", {}).get("supported") == ["2026-07-28"]
                  and error.get("data", {}).get("requested") == "2026-01-01",
                  repr(reply)[:160])
            reply = client.request({"jsonrpc": "2.0", "id": 22, "method": "tools/list",
                                    "params": {"_meta": {MODERN_KEY: "2026-07-28"}}})
            check("a modern request without clientCapabilities is -32602",
                  reply.get("error", {}).get("code") == -32602, repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 23,
                                    "method": "resources/read",
                                    "params": {**_modern_params(),
                                               "uri": "uxr://references/tracker"}})
            check("modern resources/read wraps the document with resultType complete",
                  reply.get("result", {}).get("resultType") == "complete"
                  and bool(reply["result"]["contents"][0]["text"]), repr(reply)[:120])
            reply = client.request({"jsonrpc": "2.0", "id": 24, "method": "ping"})
            check("the server keeps serving across era switches",
                  reply.get("result") == {}, repr(reply))
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
