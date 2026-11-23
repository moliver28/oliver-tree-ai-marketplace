#!/usr/bin/env python3
"""Stdio MCP server for uxr-plugin (Phase 1).

Speaks newline-delimited JSON-RPC 2.0 over stdin/stdout so local CLI
harnesses (zcode, codex, claude-code, hermes-style runtimes) can drive the
plugin's deterministic scripts without importing any of them. Protocol
facts this server implements (verified against modelcontextprotocol.io on
2026-11-22):

- stdio transport, both eras. The 2026-07-28 revision keeps the same stdio
  binding (newline-delimited UTF-8 JSON-RPC, nothing but protocol messages
  on stdout, diagnostics on stderr) and replaces the handshake with
  per-request metadata: each request carries
  ``_meta["io.modelcontextprotocol/protocolVersion"]`` plus
  ``io.modelcontextprotocol/clientCapabilities``; an unsupported version is
  rejected with ``-32022`` carrying ``data.supported``; ``server/discover``
  answers a ``DiscoverResult`` with ``supportedVersions``. Legacy revisions
  ``2025-06-18`` and ``2025-11-25`` keep the ``initialize`` handshake; an
  ``initialize`` request selects legacy semantics for the process, per the
  spec's dual-era rule ("a request carrying modern per-request _meta is
  served statelessly; an initialize request selects legacy semantics").
- Tool schemas are DERIVED, not hand-maintained: every script ships a
  declarative ``MCP_SURFACE`` table (its own argument surface), and this
  server reads the table out of the script source via ``ast`` at first use,
  builds the JSON Schema for ``tools/list``, and builds argv from the same
  table for ``tools/call``. ``scripts/gen_mcp_docs.py`` renders docs from
  the same registry, so docs cannot drift from code. A selftest cross-
  checks each table against the parser's flag literals.
- ``instructions`` (a UXR/HCD domain summary) sits at the top level of the
  legacy initialize result (and inside ``serverInfo`` for hosts that read
  it there) and in the modern discover result.

Binding laws inherited from docs/ARCHITECTURE.md: script stdout is passed
through verbatim (the caller never recomputes a number a script printed);
drafts never send (no tool publishes, posts, or mails anything); the
server shells out only and imports nothing from ``uxr-plugin/lib``.

Stdlib only; no network access. Exit 0 on stdin EOF.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
REFERENCES_DIR = PLUGIN_ROOT / "references"
PROMPTS_DIR = PLUGIN_ROOT / "prompts"
COMMANDS_DIR = PLUGIN_ROOT / "commands"
MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

#: Curated tool set, in tools/list order: one tool per shipped script.
TOOL_ORDER = [
    "scaffold_workspace", "build_body", "parse_shorthand", "roster_apply",
    "recruit_funnel", "classify", "report_html", "deck_render", "uxr_stats",
    "review_checks",
]

#: Protocol eras (see module docstring). LEGACY_PROTOCOL_VERSIONS are the
#: initialize-handshake revisions; MODERN_PROTOCOL_VERSION is the per-request
#: era served statelessly.
LEGACY_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")
LEGACY_FALLBACK_VERSION = "2025-11-25"
MODERN_PROTOCOL_VERSION = "2026-07-28"

KEY_VERSION = "io.modelcontextprotocol/protocolVersion"
KEY_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
KEY_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

SERVER_NAME = "uxr-plugin"
SERVER_TITLE = "UXR plugin: research operations scripts"
SCRIPT_TIMEOUT_SECONDS = 60
STDERR_TAIL_CHARS = 2000
RESOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_PROTOCOL_VERSION = -32022

INSTRUCTIONS = (
    "uxr-plugin turns your agent into a research operations assistant for UX "
    "research (UXR) work with product managers, designers, and engineers. "
    "Vocabulary: a study is one research project (one ticket, one spec, one "
    "workspace); the spec is a JSON file that is the source of truth and the "
    "ticket body is a rendering of it; a workspace is the local study folder "
    "(the universal default root is ~/uxr-workspaces/<slug>/); a roster is "
    "the recruit list with fixed statuses; a phase is a workflow status with "
    "a readiness gate; a gate is where the assistant stops and waits for the "
    "user. Principles: (1) the spec is the source of truth - content flows "
    "interview to spec to validated render to tracker, never hand-patched; "
    "(2) code owns rules, the model owns judgment - every tool here runs a "
    "deterministic script and its stdout is authoritative, so print script "
    "output verbatim and never recompute a number a script printed; (3) "
    "drafts, never sends - nothing in this server posts, publishes, or mails "
    "anything external; the user sends; (4) hooks fail open, exclusions fail "
    "closed - do-not-contact and participant-privacy checks block the action "
    "when they cannot run. Tools cover the study lifecycle: workspace "
    "scaffolding, spec-to-ticket-body rendering, edit shorthand parsing, "
    "roster updates, recruitment funnel tables, reply and method "
    "classification, HTML report rendering, deck generation, usage stats, "
    "and interview-script hard-rule checks. Resources expose the plugin's "
    "reference documents and prompt fragments; prompts expose the "
    "slash-command templates. Paths passed to tools should be absolute; "
    "scripts resolve their own configuration from the plugin root."
)


def _log(message: str) -> None:
    """One diagnostic line to stderr; stdout carries protocol only."""
    print(f"uxr-mcp: {message}", file=sys.stderr, flush=True)


def plugin_version() -> str:
    """Version from the plugin manifest; '0.0.0' when unreadable."""
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


class _RpcError(Exception):
    """A JSON-RPC error to send back to the caller."""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _server_info() -> dict:
    return {
        "name": SERVER_NAME,
        "title": SERVER_TITLE,
        "version": plugin_version(),
        "instructions": INSTRUCTIONS,
    }


# ---------------------------------------------------------------------------
# derivation layer: tool schemas and argv come from the scripts' tables
# ---------------------------------------------------------------------------

def _tool_list() -> list[dict]:
    """tools/list entries: name, description, and the derived inputSchema."""
    return [{k: tool[k] for k in ("name", "description", "inputSchema")}
            for tool in get_registry().values()]


def script_surface(name: str) -> dict:
    """Read one script's MCP_SURFACE table out of its source via ast.

    The table is the script's own declaration of its argument surface; the
    script also self-reports it at runtime via
    ``python <script> --print-mcp-surface``. Reading the literal here keeps
    the derivation free of imports (a script's module imports load its
    dependencies) and free of subprocess cost.
    """
    path = SCRIPTS_DIR / f"{name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "MCP_SURFACE"
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise _RpcError(INTERNAL_ERROR, f"{name}.py declares no MCP_SURFACE table")


def _property_schema(entry: dict) -> dict:
    """JSON Schema for one declared argument."""
    kind = entry.get("type", "string")
    if entry.get("repeat"):
        return {"type": "array", "items": {"type": "string"}}
    if kind == "integer":
        return {"type": "integer", "minimum": 1}
    if kind == "boolean":
        return {"type": "boolean"}
    description = entry.get("help") or f"script argument {entry.get('flag', entry['name'])}"
    subs = entry.get("subs") or []
    if subs:
        description += f" (applies to: {', '.join(subs)})"
    return {"type": "string", "description": description}


def derive_schema(surface: dict) -> dict:
    """Build the tools/list inputSchema from one script's table."""
    properties: dict = {}
    required: list[str] = []
    sub = surface.get("subcommand")
    if sub:
        properties[sub["name"]] = {
            "type": "string",
            "enum": list(sub["values"]),
            "description": "the script subcommand to run",
        }
        if sub.get("required"):
            required.append(sub["name"])
    for entry in surface.get("flags", []):
        properties[entry["name"]] = _property_schema(entry)
        if entry.get("required") and not entry.get("subs"):
            required.append(entry["name"])
    for entry in surface.get("switches", []):
        properties[entry["name"]] = _property_schema(entry)
    stdin = surface.get("stdin")
    if stdin:
        properties[stdin["name"]] = {
            "type": "string",
            "description": stdin.get("help", "text piped to the script's stdin"),
        }
        if stdin.get("required"):
            required.append(stdin["name"])
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": required}


def build_argv(surface: dict, arguments: dict) -> tuple[list[str], str | None]:
    """Translate tool arguments into ``[script, ...argv]`` plus stdin text.

    Derived from the same table as the schema; every mismatch between the
    caller's arguments and the declared surface raises ``ValueError`` with a
    caller-facing message (surfaced as ``-32602``).
    """
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    argv = list(surface.get("argv_prefix", []))
    sub_name = (surface.get("subcommand") or {}).get("name")
    sub_value = None
    if sub_name:
        sub_value = arguments.get(sub_name)
        if not isinstance(sub_value, str) or not sub_value:
            raise ValueError(f"{sub_name} is required and must be a string")
        if sub_value not in surface["subcommand"]["values"]:
            raise ValueError(
                f"{sub_name} must be one of: {', '.join(surface['subcommand']['values'])}")
        argv.append(sub_value)
    for entry in surface.get("flags", []):
        positional = entry.get("kind") == "positional"
        argv.extend(_flag_tokens(entry, arguments, sub_value, positional=positional))
    for entry in surface.get("switches", []):
        argv.extend(_flag_tokens(entry, arguments, sub_value, positional=False))
    stdin_text = None
    stdin = surface.get("stdin")
    if stdin:
        stdin_text = arguments.get(stdin["name"])
        if stdin.get("required") and not isinstance(stdin_text, str):
            raise ValueError(f"{stdin['name']} is required and must be a string")
    return argv, stdin_text


def _flag_tokens(entry: dict, arguments: dict, sub_value: str | None,
                 positional: bool) -> list[str]:
    """argv tokens for one declared argument, validated against its table."""
    name = entry["name"]
    subs = entry.get("subs") or []
    if subs and sub_value is not None and sub_value not in subs:
        return []  # declared for other subcommands; ignore silently
    value = arguments.get(name)
    required = entry.get("required", False)
    if positional:
        if not isinstance(value, str) or not value.strip():
            if required:
                raise ValueError(f"{name} is required and must be a string")
            return []
        return [value]
    kind = entry.get("type", "string")
    if kind == "boolean":
        if value is None or value is False:
            if required:
                raise ValueError(f"{name} is required")
            return []
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        return [entry["flag"]]
    if kind == "integer":
        if value is None:
            if required:
                raise ValueError(f"{name} is required")
            return []
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < 1:
            raise ValueError(f"{name} must be a positive integer")
        return [entry["flag"], str(value)]
    if entry.get("repeat"):
        if value is None:
            if required:
                raise ValueError(f"{name} is required")
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{name} must be an array of strings")
        tokens: list[str] = []
        for item in value:
            tokens += [entry["flag"], item]
        return tokens
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{name} is required and must be a string")
        return []
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return [entry["flag"], value]


_REGISTRY: dict | None = None


def get_registry() -> dict:
    """The derived tool registry, built once per process (lazy)."""
    global _REGISTRY
    if _REGISTRY is None:
        registry = {}
        for name in TOOL_ORDER:
            surface = script_surface(name)
            registry[name] = {
                "name": name,
                "description": surface.get("description", name),
                "inputSchema": derive_schema(surface),
                "surface": surface,
            }
        _REGISTRY = registry
    return _REGISTRY


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------

def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(name: str, arguments: dict) -> dict:
    """Run one shipped script; returns the MCP tools/call result object.

    Script stdout is passed through verbatim. A nonzero exit is reported
    with ``isError: true`` and the stderr tail; a timeout is reported the
    same way. No shell interpolation: the script always runs as
    ``[sys.executable, script, ...argv]`` with ``PYTHONIOENCODING=utf-8``
    pinned so non-ASCII output survives any platform locale.
    """
    tool = get_registry().get(name)
    if tool is None:
        raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
    if arguments is None:
        arguments = {}
    script = SCRIPTS_DIR / f"{name}.py"
    if not script.is_file():
        raise _RpcError(INTERNAL_ERROR, f"script missing on disk: {script.name}")
    try:
        argv, stdin_text = build_argv(tool["surface"], arguments)
    except ValueError as exc:
        raise _RpcError(INVALID_PARAMS, str(exc)) from exc
    command = [sys.executable, str(script), *argv]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            input=stdin_text or "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SCRIPT_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        tail = ""
        if exc.stderr:
            tail = _as_text(exc.stderr)[-STDERR_TAIL_CHARS:]
        message = f"{name}: timed out after {SCRIPT_TIMEOUT_SECONDS}s"
        if tail:
            message += "\n" + tail
        return _error_result(message)
    except OSError as exc:
        return _error_result(f"{name}: failed to start: {exc}")
    if completed.returncode == 0:
        return {"content": [{"type": "text", "text": completed.stdout}], "isError": False}
    tail = (completed.stderr or completed.stdout or "")[-STDERR_TAIL_CHARS:]
    message = tail or f"{name}: exited {completed.returncode} with no output"
    return _error_result(message)


# ---------------------------------------------------------------------------
# resources and prompts
# ---------------------------------------------------------------------------

def _first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
        if stripped:
            return stripped
    return fallback


def _fragment_paths() -> dict:
    """Map each flat fragment resource name to its file on disk.

    Fragment names carry their prompt directory so same-named fragments in
    different directories stay distinct (drafts-feedback-gap vs
    signals-feedback-gap). Directory names and stems both contain hyphens,
    so read resolves through this registry instead of re-parsing the name.
    """
    if not PROMPTS_DIR.is_dir():
        return {}
    return {f"{path.parent.parent.name}-{path.stem}": path
            for path in sorted(PROMPTS_DIR.glob("*/fragments/*.md"))}


def list_resources() -> list[dict]:
    """references/*.md plus prompts/*/fragments/*.md, read-only text/markdown."""
    resources: list[dict] = []
    if REFERENCES_DIR.is_dir():
        for path in sorted(REFERENCES_DIR.glob("*.md")):
            stem = path.stem
            resources.append({
                "uri": f"uxr://references/{stem}",
                "name": stem,
                "description": _first_heading(path.read_text(encoding="utf-8"), stem),
                "mimeType": "text/markdown",
            })
    for name, path in _fragment_paths().items():
        resources.append({
            "uri": f"uxr://fragments/{name}",
            "name": name,
            "description": _first_heading(path.read_text(encoding="utf-8"), name),
            "mimeType": "text/markdown",
        })
    return resources


def read_resource(uri: str) -> dict:
    """One resource document; raises _RpcError(-32602) on unknown URIs.

    The name segment must match ``^[A-Za-z0-9_-]+$``: no separators, no
    traversal, no drive-relative forms like ``C:foo``.
    """
    if not isinstance(uri, str) or not uri.startswith("uxr://"):
        raise _RpcError(INVALID_PARAMS, f"unsupported uri: {uri!r}")
    kind, _, name = uri[len("uxr://"):].partition("/")
    if kind not in ("references", "fragments") or not name \
            or not RESOURCE_NAME_RE.match(name):
        raise _RpcError(INVALID_PARAMS, f"unknown resource uri: {uri}")
    if kind == "references":
        path = REFERENCES_DIR / f"{name}.md"
    else:
        known = _fragment_paths().get(name)
        path = known if known is not None else None
    if path is None or not path.is_file():
        raise _RpcError(INVALID_PARAMS, f"unknown resource uri: {uri}")
    return {
        "uri": uri,
        "mimeType": "text/markdown",
        "text": path.read_text(encoding="utf-8"),
    }


def _front_matter(text: str) -> tuple[dict, str]:
    """Split one command file into (front matter mapping, body text)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    mapping: dict = {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body = "\n".join(lines[index + 1:]).strip("\n")
            return mapping, body
        line = lines[index]
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        mapping[key.strip()] = value
    return mapping, text


def list_prompts() -> list[dict]:
    """commands/*.md as prompts: name, front-matter description, no args."""
    prompts: list[dict] = []
    if not COMMANDS_DIR.is_dir():
        return prompts
    for path in sorted(COMMANDS_DIR.glob("*.md")):
        mapping, _body = _front_matter(path.read_text(encoding="utf-8"))
        prompts.append({
            "name": path.stem,
            "description": str(mapping.get("description") or path.stem),
            "arguments": [],
        })
    return prompts


def get_prompt(name: str) -> dict:
    """One prompt: description plus the command body as the template."""
    if not isinstance(name, str) or "/" in name or "\\" in name or name in ("", ".", ".."):
        raise _RpcError(INVALID_PARAMS, f"unknown prompt: {name!r}")
    path = COMMANDS_DIR / f"{name}.md"
    if not path.is_file():
        raise _RpcError(INVALID_PARAMS, f"unknown prompt: {name!r}")
    mapping, body = _front_matter(path.read_text(encoding="utf-8"))
    description = str(mapping.get("description") or name)
    return {
        "description": description,
        "messages": [{"role": "user", "content": {"type": "text", "text": body}}],
    }


# ---------------------------------------------------------------------------
# JSON-RPC dispatch, both eras
# ---------------------------------------------------------------------------

def _capabilities() -> dict:
    return {
        "tools": {"listChanged": False},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
    }


def initialize_result(requested_version) -> dict:
    """Legacy initialize result: echo the client's supported version, else
    the newest legacy revision this server speaks."""
    version = requested_version if requested_version in LEGACY_PROTOCOL_VERSIONS \
        else LEGACY_FALLBACK_VERSION
    return {
        "protocolVersion": version,
        "capabilities": _capabilities(),
        "serverInfo": _server_info(),
        "instructions": INSTRUCTIONS,
    }


def discover_result() -> dict:
    """Modern server/discover result (2026-07-28 DiscoverResult)."""
    return {
        "resultType": "complete",
        "supportedVersions": [MODERN_PROTOCOL_VERSION],
        "capabilities": _capabilities(),
        "_meta": {KEY_SERVER_INFO: {k: v for k, v in _server_info().items()
                                    if k != "instructions"}},
        "instructions": INSTRUCTIONS,
    }


def _modern_result(payload: dict) -> dict:
    """Wrap one legacy-shaped result payload for the modern era: every
    result carries ``resultType: "complete"`` plus the serverInfo ``_meta``."""
    wrapped = {"resultType": "complete"}
    wrapped.update(payload)
    return wrapped


def _modern_version_of(params: dict) -> str | None:
    """The per-request protocol version, or None when the request carries no
    modern metadata (a legacy-era request)."""
    meta = params.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get(KEY_VERSION), str):
        return meta[KEY_VERSION]
    return None


def handle_request(method: str, params, era: dict) -> dict:
    """Dispatch one JSON-RPC request; returns the result object or raises.

    ``era`` is the per-connection session state (``era["mode"]`` is None,
    "legacy", or "modern"). Era selection follows the spec's dual-era rule:
    an ``initialize`` request selects legacy semantics for the process; a
    request carrying a modern per-request version is served statelessly.
    """
    params = params or {}
    if not isinstance(params, dict):
        raise _RpcError(INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        era["mode"] = "legacy"
        return initialize_result(params.get("protocolVersion"))
    requested = _modern_version_of(params)
    if method == "server/discover" and requested is None and era["mode"] is None:
        raise _RpcError(INVALID_PARAMS,
                        "server/discover requires the modern per-request "
                        f"_meta {KEY_VERSION} field (or send initialize first "
                        "for a legacy session)")
    if requested is not None:
        meta = params.get("_meta") or {}
        if not isinstance(meta.get(KEY_CLIENT_CAPABILITIES), dict):
            raise _RpcError(
                INVALID_PARAMS,
                f"modern requests must carry _meta {KEY_CLIENT_CAPABILITIES}")
        if requested != MODERN_PROTOCOL_VERSION:
            raise _RpcError(
                UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                data={"supported": [MODERN_PROTOCOL_VERSION], "requested": requested})
        return _handle_modern(method, params)
    if era["mode"] == "legacy":
        return _handle_legacy(method, params)
    if method == "ping":
        return {}
    raise _RpcError(
        INVALID_PARAMS,
        "no session: send initialize (legacy) or a per-request "
        f"_meta {KEY_VERSION} (modern) before {method}")


def _handle_modern(method: str, params: dict) -> dict:
    if method == "server/discover":
        return discover_result()
    if method == "ping":
        return {"resultType": "complete"}
    if method == "tools/list":
        return _modern_result({"tools": _tool_list()})
    if method == "tools/call":
        tool = params.get("name")
        if not isinstance(tool, str) or not tool:
            raise _RpcError(INVALID_PARAMS, "tools/call needs a tool name")
        return _modern_result(call_tool(tool, params.get("arguments")))
    if method == "resources/list":
        return _modern_result({"resources": list_resources()})
    if method == "resources/read":
        uri = params.get("uri")
        return _modern_result({"contents": [read_resource(uri)]})
    if method == "prompts/list":
        return _modern_result({"prompts": list_prompts()})
    if method == "prompts/get":
        return _modern_result(get_prompt(params.get("name")))
    raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")


def _handle_legacy(method: str, params: dict) -> dict:
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _tool_list()}
    if method == "tools/call":
        tool = params.get("name")
        if not isinstance(tool, str) or not tool:
            raise _RpcError(INVALID_PARAMS, "tools/call needs a tool name")
        return call_tool(tool, params.get("arguments"))
    if method == "resources/list":
        return {"resources": list_resources()}
    if method == "resources/read":
        uri = params.get("uri")
        return {"contents": [read_resource(uri)]}
    if method == "prompts/list":
        return {"prompts": list_prompts()}
    if method == "prompts/get":
        return get_prompt(params.get("name"))
    raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")


def dispatch(message, era: dict | None = None) -> dict | None:
    """One inbound JSON-RPC message to its outbound response, or None.

    Notifications (no id) never get a response; unknown methods with an id
    get -32601; responses to server requests (we send none) are ignored.
    """
    if era is None:
        era = {"mode": None}
    if not isinstance(message, dict):
        return _error_response(None, INVALID_REQUEST, "Invalid Request")
    method = message.get("method")
    has_id = "id" in message
    if method is None:
        if (has_id and "result" in message) or (has_id and "error" in message):
            return None  # a response to a server request; none are sent
        return _error_response(message.get("id"), INVALID_REQUEST, "Invalid Request")
    if not has_id:
        return None  # a notification; never answered
    request_id = message["id"]
    try:
        result = handle_request(method, message.get("params"), era)
    except _RpcError as exc:
        error = {"code": exc.code, "message": exc.message}
        if exc.data is not None:
            error["data"] = exc.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    except Exception as exc:  # keep serving no matter what one request does
        _log(f"{method} failed: {exc!r}")
        return _error_response(request_id, INTERNAL_ERROR, "Internal error")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _write(message: dict) -> None:
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def serve(read_stream=None) -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF; always serving.

    A malformed line answers -32700 and the loop continues; nothing a
    client sends can take the server down between messages.
    """
    stream = read_stream if read_stream is not None else sys.stdin
    _log(f"starting ({plugin_version()}); scripts at {SCRIPTS_DIR}")
    era = {"mode": None}
    for raw in stream:
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError as exc:
            _log(f"parse error: {exc}")
            _write(_error_response(None, PARSE_ERROR, "Parse error"))
            continue
        response = dispatch(message, era)
        if response is not None:
            _write(response)
    return 0


def main() -> int:
    """Force UTF-8 protocol on both stdio streams, then serve."""
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n" if stream is sys.stdout else None)
        except (AttributeError, ValueError, OSError):
            pass
    try:
        return serve()
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
