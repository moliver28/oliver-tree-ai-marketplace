#!/usr/bin/env python3
"""Stdio MCP server for uxr-plugin (Phase 1).

Speaks newline-delimited JSON-RPC 2.0 over stdin/stdout so local CLI
harnesses (zcode, codex, claude-code, hermes-style runtimes) can drive the
plugin's deterministic scripts without importing any of them. Protocol
facts this server implements (verified against modelcontextprotocol.io on
2026-11-22):

- stdio transport: messages are single JSON-RPC objects delimited by
  newlines, UTF-8 encoded, with no embedded newlines; the server never
  writes anything to stdout that is not a protocol message and keeps all
  diagnostics on stderr.
- initialize handshake era (protocol versions ``2025-06-18`` and
  ``2025-11-25``; the client's requested version is echoed when supported,
  otherwise the newest supported one is returned). The 2026-07-28 revision
  moved to per-request versioning and is out of scope for this phase.
- ``instructions`` is a top-level field of the initialize result; it is
  mirrored inside ``serverInfo`` for hosts that read it there.

Binding laws inherited from docs/ARCHITECTURE.md: script stdout is passed
through verbatim (the caller never recomputes a number a script printed);
drafts never send (no tool publishes, posts, or mails anything); the
server shells out only and imports nothing from ``uxr-plugin/lib``.

Stdlib only; no network access. Exit 0 on stdin EOF.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
REFERENCES_DIR = PLUGIN_ROOT / "references"
PROMPTS_DIR = PLUGIN_ROOT / "prompts"
COMMANDS_DIR = PLUGIN_ROOT / "commands"
MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

#: Newest initialize-handshake revisions this server speaks. 2025-06-18 is
#: the seed revision the CLI harnesses negotiate today; 2025-11-25 is the
#: newest revision of the same era (verified 2026-11-22). The 2026-07-28
#: per-request era is intentionally out of scope for Phase 1.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")
FALLBACK_PROTOCOL_VERSION = "2025-11-25"

SERVER_NAME = "uxr-plugin"
SERVER_TITLE = "UXR plugin: research operations scripts"
SCRIPT_TIMEOUT_SECONDS = 60
STDERR_TAIL_CHARS = 2000

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = (
    "uxr-plugin turns your agent into a research operations assistant for UX "
    "research (UXR) work with product managers, designers, and engineers. "
    "Vocabulary: a study is one research project (one ticket, one spec, one "
    "workspace); the spec is a JSON file that is the source of truth and the "
    "ticket body is a rendering of it; a workspace is the local study folder; "
    "a roster is the recruit list with fixed statuses; a phase is a workflow "
    "status with a readiness gate; a gate is where the assistant stops and "
    "waits for the user. Principles: (1) the spec is the source of truth - "
    "content flows interview to spec to validated render to tracker, never "
    "hand-patched; (2) code owns rules, the model owns judgment - every tool "
    "here runs a deterministic script and its stdout is authoritative, so "
    "print script output verbatim and never recompute a number a script "
    "printed; (3) drafts, never sends - nothing in this server posts, "
    "publishes, or mails anything external; the user sends; (4) hooks fail "
    "open, exclusions fail closed - do-not-contact and participant-privacy "
    "checks block the action when they cannot run. Tools cover the study "
    "lifecycle: workspace scaffolding, spec-to-ticket-body rendering, edit "
    "shorthand parsing, roster updates, recruitment funnel tables, reply and "
    "method classification, HTML report rendering, deck generation, usage "
    "stats, and interview-script hard-rule checks. Resources expose the "
    "plugin's reference documents and prompt fragments; prompts expose the "
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


# ---------------------------------------------------------------------------
# tool registry: one tool per shipped script, schemas read from the scripts
# ---------------------------------------------------------------------------

_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer", "minimum": 1}
_STR_LIST = {"type": "array", "items": {"type": "string"}}

TOOLS = [
    {
        "name": "scaffold_workspace",
        "description": (
            "scaffold_workspace.py: derive a study slug, scaffold a workspace "
            "folder from the template, look up a workspace by ticket, render "
            "its overview, append outreach journal entries, or validate a "
            "recruitment table. Set 'subcommand' and only the flags that "
            "subcommand uses."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["subcommand"],
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["slug", "scaffold", "lookup-workspace",
                             "render-overview", "append-outreach-entry",
                             "validate-recruitment"],
                },
                "title": {**_STR, "description": "slug: study title"},
                "quarter": {**_STR, "description": "slug: quarter tag (example 2026-Q4)"},
                "max_body": {**_INT, "description": "slug: max overview body words (default 50)"},
                "template": {**_STR, "description": "scaffold: path to the workspace template"},
                "target": {**_STR, "description": "scaffold: target workspace folder"},
                "mapping": {**_STR, "description": "scaffold: JSON object of {{TOKEN}} fill values"},
                "readme": {**_STR, "description": "path to the research-root README index"},
                "spec": {**_STR, "description": "scaffold/render-overview: path to the spec JSON"},
                "no_commit": {**_BOOL, "description": "scaffold: skip the git commit step"},
                "ticket": {**_STR, "description": "lookup-workspace/render-overview: ticket key"},
                "log_path": {**_STR, "description": "append-outreach-entry: outreach log file"},
                "date": {**_STR, "description": "append-outreach-entry: entry date (YYYY-MM-DD)"},
                "name": {**_STR, "description": "append-outreach-entry: recruit name"},
                "slot": {**_STR_LIST, "description": "append-outreach-entry: slot rows (repeatable)"},
                "hold": {**_STR_LIST, "description": "append-outreach-entry: hold rows (repeatable)"},
                "channel": {**_STR, "description": "append-outreach-entry/validate-recruitment: channel"},
                "status_from": {**_STR, "description": "append-outreach-entry: status before"},
                "status_to": {**_STR, "description": "append-outreach-entry: status after"},
                "notes": {**_STR, "description": "append-outreach-entry: notes text"},
                "action": {**_STR, "description": "append-outreach-entry: action taken"},
                "path": {**_STR, "description": "validate-recruitment: recruitment table file"},
                "method": {**_STR, "description": "validate-recruitment: research method"},
            },
        },
    },
    {
        "name": "build_body",
        "description": (
            "build_body.py: render a study spec into the tracker ticket body. "
            "Pass the spec JSON in 'stdin'; the rendered body comes back on "
            "stdout (markdown, html, or ADF JSON). Exit 3 means the spec "
            "failed validation; a validation failure makes zero tracker calls."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["stdin"],
            "properties": {
                "stdin": {**_STR, "description": "the study spec JSON document"},
            },
        },
    },
    {
        "name": "parse_shorthand",
        "description": (
            "parse_shorthand.py: parse one edit-shorthand request into a JSON "
            "delta. Pass '{\"kind\": \"roster|hypotheses|assumptions|resources\", "
            "\"op\": \"+=|~=|=\", \"arg\": \"<pipe string>\"}' in 'stdin'."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["stdin"],
            "properties": {
                "stdin": {**_STR, "description": "the shorthand request JSON"},
            },
        },
    },
    {
        "name": "roster_apply",
        "description": (
            "roster_apply.py: apply recruitment ops to the study spec, "
            "validate, re-render the body, and write the spec and body files "
            "(or nothing on any failure). The only write path the recruit "
            "command uses against the spec."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["spec", "ops", "out"],
            "properties": {
                "spec": {**_STR, "description": "path to the study spec JSON"},
                "ops": {**_STR, "description": "ops JSON inline, or @path to an ops file"},
                "out": {**_STR, "description": "path to write the rendered body JSON"},
                "dry_run": {**_BOOL, "description": "apply nothing; report only"},
            },
        },
    },
    {
        "name": "recruit_funnel",
        "description": (
            "recruit_funnel.py: print the fixed nine-row recruitment funnel "
            "table, run the wave preflight (BLOCK lines for repeat recruits), "
            "draft nudge reminders, or check a V1 draft. Computes only; "
            "nothing is sent."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "spec": {**_STR, "description": "path to the study spec JSON (required unless check_draft)"},
                "wave": {**_STR, "description": "wave name for the this-wave columns"},
                "funnel_data": {**_STR, "description": "path to the funnel JSON export"},
                "check_draft": {**_STR, "description": "path to a V1 draft to check"},
                "today": {**_STR, "description": "today as YYYY-MM-DD (defaults to the real clock)"},
                "preflight": {**_BOOL, "description": "run the wave preflight"},
                "status": {**_BOOL, "description": "print the status summary"},
                "reminder": {**_BOOL, "description": "draft nudge reminders"},
            },
        },
    },
    {
        "name": "classify",
        "description": (
            "classify.py: deterministic classifiers. 'intent' routes a user "
            "request, 'reply' classes a recruit reply, 'method' picks the "
            "method shape from research questions, 'decision' checks the "
            "decision shape, 'route-finding' routes a review finding."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["subcommand"],
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["intent", "reply", "method", "decision", "route-finding"],
                },
                "text": {**_STR, "description": "intent/reply/decision: the plain input text"},
                "prefix": {**_STR, "description": "intent: prefix label for the verdict"},
                "rqs": {**_STR, "description": "method: research questions, semicolon or newline separated"},
                "category": {**_STR, "description": "route-finding: finding category"},
            },
        },
    },
    {
        "name": "report_html",
        "description": (
            "report_html.py render: turn a Markdown report deliverable plus "
            "front matter into one self-contained HTML file (no external "
            "assets, byte-identical on two runs)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["md", "html"],
            "properties": {
                "md": {**_STR, "description": "path to the report markdown"},
                "html": {**_STR, "description": "path to write the HTML file"},
            },
        },
    },
    {
        "name": "deck_render",
        "description": (
            "deck_render.py: outline JSON in, .pptx out. 'lint' prints one "
            "FAIL line per overflow or overlap; 'render' lints first and "
            "writes nothing on any FAIL. A deck is always regenerated from "
            "the outline; an existing file is never edited."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["subcommand", "outline"],
            "properties": {
                "subcommand": {"type": "string", "enum": ["lint", "render"]},
                "outline": {**_STR, "description": "path to the outline JSON"},
                "out": {**_STR, "description": "render: path for the .pptx output"},
            },
        },
    },
    {
        "name": "uxr_stats",
        "description": (
            "uxr_stats.py: read-only journal and analytics rollup. Reads the "
            "state directory from UXR_STATE_DIR or paths.state_dir in the "
            "plugin config; prints the table, or one JSON object with 'json'."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "json": {**_BOOL, "description": "print one JSON object"},
                "days": {**_INT, "description": "restrict the journal to the last N days"},
            },
        },
    },
    {
        "name": "review_checks",
        "description": (
            "review_checks.py check: run the interview-script hard-rule "
            "checker on one file. Exit 0 clean, 1 warnings, 2 unparseable, "
            "3 a hard rule is broken; findings print on stdout. The review "
            "loop saves nothing before this passes."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {
                "path": {**_STR, "description": "path to the interview script file"},
            },
        },
    },
]

_TOOL_NAMES = {tool["name"] for tool in TOOLS}


def _flag(name: str) -> str:
    """snake_case tool argument to the script's --dashed flag."""
    return "--" + name.replace("_", "-")


def _tool_argv(tool: str, args: dict) -> tuple[list[str], str | None]:
    """Translate tool arguments into [script, ...argv] plus stdin text.

    Derived from each script's hand-rolled argument parser; returns
    ``(argv, stdin_text)``. Raises ``ValueError`` with a caller-facing
    message when an argument has the wrong type.
    """
    if tool == "scaffold_workspace":
        argv = [str(args["subcommand"])]
        text_flags = ("title", "quarter", "max_body", "template", "target",
                      "mapping", "readme", "spec", "ticket", "log_path",
                      "date", "name", "channel", "status_from", "status_to",
                      "notes", "action", "path", "method")
        for flag in text_flags:
            value = args.get(flag)
            if value in (None, ""):
                continue
            if flag == "max_body":
                if not isinstance(value, int):
                    raise ValueError("max_body must be an integer")
                argv += [_flag(flag), str(value)]
            else:
                if not isinstance(value, str):
                    raise ValueError(f"{flag} must be a string")
                argv += [_flag(flag), value]
        if args.get("no_commit"):
            argv.append("--no-commit")
        for flag in ("slot", "hold"):
            value = args.get(flag) or []
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{flag} must be an array of strings")
            for item in value:
                argv += [_flag(flag), item]
        return argv, None

    if tool in ("build_body", "parse_shorthand"):
        text = args.get("stdin")
        if not isinstance(text, str):
            raise ValueError("stdin must be a string")
        return [], text

    if tool == "roster_apply":
        for flag in ("spec", "ops", "out"):
            value = args.get(flag)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{flag} is required and must be a string")
        argv = ["--spec", args["spec"], "--ops", args["ops"], "--out", args["out"]]
        if args.get("dry_run"):
            argv.append("--dry-run")
        return argv, None

    if tool == "recruit_funnel":
        argv = []
        for flag in ("spec", "wave", "funnel_data", "check_draft", "today"):
            value = args.get(flag)
            if value in (None, ""):
                continue
            if not isinstance(value, str):
                raise ValueError(f"{flag} must be a string")
            argv += [f"--{flag.replace('_', '-')}", value]
        for flag in ("preflight", "status", "reminder"):
            if args.get(flag):
                argv.append(f"--{flag}")
        return argv, None

    if tool == "classify":
        sub = args.get("subcommand")
        argv = [str(sub)]
        if sub in ("intent", "reply", "decision"):
            text = args.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{sub} needs text")
            argv += [text]
            if sub == "intent" and args.get("prefix"):
                if not isinstance(args["prefix"], str):
                    raise ValueError("prefix must be a string")
                argv += ["--prefix", args["prefix"]]
        elif sub == "method":
            rqs = args.get("rqs")
            if not isinstance(rqs, str) or not rqs.strip():
                raise ValueError("method needs rqs")
            argv += ["--rqs", rqs]
        elif sub == "route-finding":
            category = args.get("category")
            if not isinstance(category, str) or not category.strip():
                raise ValueError("route-finding needs category")
            argv += ["--category", category]
        else:
            raise ValueError("subcommand must be intent, reply, method, decision, or route-finding")
        return argv, None

    if tool == "report_html":
        for flag in ("md", "html"):
            value = args.get(flag)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{flag} is required and must be a string")
        return ["render", args["md"], args["html"]], None

    if tool == "deck_render":
        sub = args.get("subcommand")
        outline = args.get("outline")
        if sub not in ("lint", "render"):
            raise ValueError("subcommand must be lint or render")
        if not isinstance(outline, str) or not outline.strip():
            raise ValueError("outline is required and must be a string")
        if sub == "lint":
            return ["lint", outline], None
        out = args.get("out")
        if not isinstance(out, str) or not out.strip():
            raise ValueError("render needs out")
        return ["render", outline, out], None

    if tool == "uxr_stats":
        argv = []
        if args.get("json"):
            argv.append("--json")
        days = args.get("days")
        if days is not None:
            if not isinstance(days, int) or isinstance(days, bool) or days < 1:
                raise ValueError("days must be a positive integer")
            argv += ["--days", str(days)]
        return argv, None

    if tool == "review_checks":
        path = args.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path is required and must be a string")
        return ["check", path], None

    raise ValueError(f"unknown tool: {tool}")


def call_tool(name: str, arguments: dict) -> dict:
    """Run one shipped script; returns the MCP tools/call result object.

    Script stdout is passed through verbatim. A nonzero exit is reported
    with ``isError: true`` and the stderr tail; a timeout is reported the
    same way. No shell interpolation: the script always runs as
    ``[sys.executable, script, ...argv]``.
    """
    if name not in _TOOL_NAMES:
        raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise _RpcError(INVALID_PARAMS, "arguments must be an object")
    script = SCRIPTS_DIR / f"{name}.py"
    if not script.is_file():
        raise _RpcError(INTERNAL_ERROR, f"script missing on disk: {script.name}")
    try:
        argv, stdin_text = _tool_argv(name, arguments)
    except ValueError as exc:
        raise _RpcError(INVALID_PARAMS, str(exc)) from exc
    command = [sys.executable, str(script), *argv]
    try:
        completed = subprocess.run(
            command,
            input=stdin_text or "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SCRIPT_TIMEOUT_SECONDS,
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


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


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
    """One resource document; raises _RpcError(-32602) on unknown URIs."""
    if not isinstance(uri, str) or not uri.startswith("uxr://"):
        raise _RpcError(INVALID_PARAMS, f"unsupported uri: {uri!r}")
    kind, _, name = uri[len("uxr://"):].partition("/")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise _RpcError(INVALID_PARAMS, f"unknown resource uri: {uri}")
    if kind == "references":
        path = REFERENCES_DIR / f"{name}.md"
    elif kind == "fragments":
        known = _fragment_paths().get(name)
        path = known if known is not None else None
    else:
        path = None
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
        key, _, value = line.partition(":")
        if not _:
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
# JSON-RPC dispatch
# ---------------------------------------------------------------------------

class _RpcError(Exception):
    """A JSON-RPC error to send back to the caller."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _capabilities() -> dict:
    return {
        "tools": {"listChanged": False},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
    }


def initialize_result(requested_version) -> dict:
    """The initialize result: echo the client's supported version, else the
    newest supported one."""
    version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS \
        else FALLBACK_PROTOCOL_VERSION
    server_info = {
        "name": SERVER_NAME,
        "title": SERVER_TITLE,
        "version": plugin_version(),
        "instructions": INSTRUCTIONS,
    }
    return {
        "protocolVersion": version,
        "capabilities": _capabilities(),
        "serverInfo": server_info,
        "instructions": INSTRUCTIONS,
    }


def handle_request(method: str, params) -> dict:
    """Dispatch one JSON-RPC request; returns the result object or raises."""
    params = params or {}
    if not isinstance(params, dict):
        raise _RpcError(INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        return initialize_result(params.get("protocolVersion"))
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
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


def dispatch(message: dict) -> dict | None:
    """One inbound JSON-RPC message to its outbound response, or None.

    Notifications (no id) never get a response; unknown methods with an id
    get -32601; responses to server requests (we send none) are ignored.
    """
    if not isinstance(message, dict):
        return _error_response(None, INVALID_REQUEST, "Invalid Request")
    method = message.get("method")
    has_id = "id" in message
    if method is None:
        if has_id and "result" in message or has_id and "error" in message:
            return None  # a response to a server request; none are sent
        return _error_response(message.get("id"), INVALID_REQUEST, "Invalid Request")
    if not has_id:
        return None  # a notification; never answered
    request_id = message["id"]
    try:
        result = handle_request(method, message.get("params"))
    except _RpcError as exc:
        return _error_response(request_id, exc.code, exc.message)
    except Exception as exc:  # keep serving no matter what one request does
        _log(f"{method} failed: {exc!r}")
        return _error_response(request_id, INTERNAL_ERROR, "Internal error")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id, code: int, message: str) -> dict:
    response = {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": message}}
    return response


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
        response = dispatch(message)
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
