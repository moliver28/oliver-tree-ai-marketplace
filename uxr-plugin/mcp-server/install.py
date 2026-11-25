#!/usr/bin/env python3
"""Install, uninstall, or check the uxr MCP server entry for one CLI harness.

Usage (run inside the plugin checkout):

    python mcp-server/install.py install --harness auto|zcode|codex|claude-code|hermes [--force] [--dry-run]
    python mcp-server/install.py uninstall --harness <name>
    python mcp-server/install.py status --harness <name>

Harnesses and their config files (verified 2026-11-22):

    zcode        ~/.zcode/cli/config.json     JSON, entry under mcp.servers.uxr
    codex        ~/.codex/config.toml         TOML, [mcp_servers.uxr] table
    claude-code  ~/.claude.json               JSON, entry under mcpServers.uxr (user scope)
    hermes       not wired in this release    see the note printed by the command

Behavior: the config file is parsed, ONLY the ``uxr`` server entry is added
or replaced, and the file is written back in its original newline style.
Every other key is untouched. The original file is copied to
``<config>.uxr-backup`` before the first write (first backup wins; later
writes never overwrite it). An existing uxr entry is never clobbered
without ``--force``. A second install run is a no-op with exit 0.
``--dry-run`` prints the plan and writes nothing. ``auto`` picks the first
harness whose config file exists, in the order zcode, claude-code, codex.

claude-code scope note: this command writes the user scope (the top-level
``mcpServers`` object in ``~/.claude.json``), which applies to every
project. Project scope (a ``.mcp.json`` in one repository) is a different
file on purpose.

Exit codes, for every subcommand:

    0  success (install: written, or a no-op as described above;
       status: the config entry exists and answers a real handshake)
    1  not found (auto found no harness config; uninstall/status found no
       config file or no uxr entry; install with an explicit --harness
       creates a missing config instead, with a printed notice)
    2  status only: an entry exists but the handshake failed
    3  unsupported harness (hermes in this release)
    4  the config file exists but could not be parsed or written

Stdlib only; no network. All output is human-readable lines. This command
never prints config values other than the uxr entry it manages.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from pathlib import Path

SERVER_PATH = Path(__file__).resolve().parent / "server.py"
SERVER_NAME = "uxr"
HANDSHAKE_TIMEOUT_SECONDS = 15
HANDSHAKE_PROTOCOL_VERSION = "2025-06-18"

#: (display name, config path relative to home, storage kind)
HARNESSES = {
    "zcode": ("zcode", Path(".zcode") / "cli" / "config.json", "json-nested"),
    "codex": ("codex", Path(".codex") / "config.toml", "toml"),
    "claude-code": ("claude-code", Path(".claude.json"), "json-flat"),
    "hermes": ("hermes", None, None),
}
AUTO_ORDER = ("zcode", "claude-code", "codex")

HERMES_NOTE = (
    "hermes is not wired in this release. Grounding found that the public "
    "hermes-agent documentation points at a mcp_servers section in "
    "~/.hermes/config.yaml, but that layout could not be confirmed for this "
    "machine's runtime, and a wrong config path would silently do nothing. "
    "Install for zcode, codex, or claude-code instead."
)

EXIT_OK = 0
EXIT_MISSING = 1
EXIT_BROKEN = 2
EXIT_UNSUPPORTED = 3
EXIT_CONFIG_ERROR = 4


class _ConfigError(Exception):
    """The config file exists but cannot be parsed or written."""


# ---------------------------------------------------------------------------
# entry payloads per storage kind
# ---------------------------------------------------------------------------

def entry_payload() -> dict:
    """The JSON server entry: this interpreter plus the shipped server.py."""
    return {"command": sys.executable, "args": [str(SERVER_PATH)]}


def toml_entry_block() -> str:
    """The [mcp_servers.uxr] TOML table for the same entry.

    Values are emitted with JSON string escaping, which is valid TOML
    basic-string syntax, so Windows backslash paths survive intact.
    """
    entry = entry_payload()
    lines = [f"[mcp_servers.{SERVER_NAME}]"]
    lines.append(f"command = {json.dumps(entry['command'])}")
    args_text = ", ".join(json.dumps(arg) for arg in entry["args"])
    lines.append(f"args = [{args_text}]")
    return "\n".join(lines) + "\n"


def _json_key_path(kind: str) -> tuple[str, ...]:
    return ("mcp", "servers") if kind == "json-nested" else ("mcpServers",)


# ---------------------------------------------------------------------------
# JSON config handling (zcode, claude-code)
# ---------------------------------------------------------------------------

def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _ConfigError(f"cannot read {path}: {exc}") from exc


def _newline_of(raw: bytes) -> str:
    """CRLF only when it is the dominant newline, never for a stray one."""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    return "\r\n" if crlf and crlf * 2 > lf else "\n"


def _write_preserving(path: Path, text: str, raw: bytes) -> None:
    """Write text back in the file's original newline style, byte-safe."""
    newline = _newline_of(raw)
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    _ensure_parent(path)
    if raw:
        _backup(path, raw)
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise _ConfigError(f"cannot write {path}: {exc}") from exc


def _backup(path: Path, raw: bytes) -> None:
    """Snapshot the original once; later writes never overwrite the backup."""
    backup = Path(str(path) + ".uxr-backup")
    if backup.exists():
        return
    try:
        backup.write_bytes(raw)
    except OSError as exc:
        raise _ConfigError(f"cannot write backup {backup}: {exc}") from exc


def _json_load(raw: bytes, path: Path) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _ConfigError(f"{path} must hold a JSON object")
    return data


def _json_get_entry(data: dict, kind: str) -> dict | None:
    node = data
    for key in _json_key_path(kind):
        if not isinstance(node, dict) or not isinstance(node.get(key), dict):
            return None
        node = node[key]
    return node.get(SERVER_NAME) if isinstance(node.get(SERVER_NAME), dict) else None


def _json_set_entry(data: dict, kind: str, entry: dict) -> None:
    node = data
    for key in _json_key_path(kind):
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise _ConfigError(f"config key {key!r} is not an object; refusing to restructure it")
        node = child
    node[SERVER_NAME] = entry


def _json_del_entry(data: dict, kind: str) -> bool:
    node = data
    for key in _json_key_path(kind):
        child = node.get(key) if isinstance(node, dict) else None
        if not isinstance(child, dict):
            return False
        node = child
    if isinstance(node, dict) and SERVER_NAME in node:
        del node[SERVER_NAME]
        return True
    return False


# ---------------------------------------------------------------------------
# TOML config handling (codex), without dependencies
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^\s*\[\[(?P<array>[^\]]+)\]\]\s*$|^\s*\[(?P<table>[^\]]+)\]\s*$")


def _table_span(raw_text: str, table: str) -> tuple[int, int] | None:
    """Line span (start, end-exclusive) of one TOML table plus its children.

    Children are deeper tables under the same prefix, such as
    ``[mcp_servers.uxr.env]``. Returns None when the table is absent.
    """
    family = table + "."
    start = None
    end = len(raw_text.splitlines())
    for index, line in enumerate(raw_text.splitlines()):
        match = _HEADER_RE.match(line)
        if not match:
            continue
        name = (match.group("array") or match.group("table")).strip()
        matched = name == table or (start is not None and name.startswith(family))
        if start is None and name == table:
            start = index
        elif start is not None and not matched:
            end = index
            break
    if start is None:
        return None
    return start, end


def _toml_block_text(raw_text: str, table: str) -> str | None:
    span = _table_span(raw_text, table)
    if span is None:
        return None
    lines = raw_text.splitlines()
    return "\n".join(lines[span[0]:span[1]]).strip()


def _toml_replace(raw_text: str, table: str, block: str) -> str:
    """Replace one table's span, or append the block when absent."""
    lines = raw_text.splitlines()
    span = _table_span(raw_text, table)
    if span is None:
        out = raw_text.rstrip("\n")
        joiner = "\n\n" if out.strip() else ""
        return out + joiner + block
    keep = lines[:span[0]] + block.strip("\n").split("\n") + lines[span[1]:]
    return "\n".join(keep) + "\n"


def _toml_remove(raw_text: str, table: str) -> str | None:
    """Drop one table's span; None when the table is absent."""
    span = _table_span(raw_text, table)
    if span is None:
        return None
    lines = raw_text.splitlines()
    kept = lines[:span[0]] + lines[span[1]:]
    return "\n".join(kept).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# engine shared by the subcommands
# ---------------------------------------------------------------------------

def _config_path(harness: str, home: Path | None) -> Path | None:
    spec = HARNESSES.get(harness)
    if spec is None or spec[1] is None:
        return None
    base = home if home is not None else Path.home()
    return base / spec[1]


def _read_config(harness: str, home: Path | None) -> tuple[Path, bytes, object] | None:
    """(path, raw bytes, parsed content) for the config file, or None when
    the file does not exist. JSON parses to a dict; TOML stays raw text
    (the stdlib has no TOML writer and the edit is line-scoped)."""
    path = _config_path(harness, home)
    if path is None:
        return None
    if not path.is_file():
        return None
    raw, parsed = _read_config_from_path(path)
    return path, raw, parsed


def _store(harness: str) -> tuple[str, str]:
    return HARNESSES[harness][1], HARNESSES[harness][2]


def _ensure_parent(path: Path) -> None:
    if path.parent.is_dir():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _ConfigError(f"cannot create {path.parent}: {exc}") from exc


def install(harness: str, force: bool = False, dry_run: bool = False,
            home: Path | None = None) -> int:
    """Add or replace only the uxr entry; idempotent; exit code per --help."""
    if harness == "hermes":
        print(HERMES_NOTE)
        return EXIT_UNSUPPORTED
    if harness not in HARNESSES:
        print(f"unknown harness: {harness}; known: {', '.join(HARNESSES)}")
        return EXIT_MISSING
    path = _config_path(harness, home)
    kind = _store(harness)[1]
    entry = entry_payload()
    print(f"harness: {harness}")
    print(f"config:  {path}")
    if kind == "toml":
        return _install_toml(path, entry, force, dry_run)
    return _install_json(path, entry, kind, force, dry_run)


def _install_json(path: Path, entry: dict, kind: str, force: bool, dry_run: bool) -> int:
    raw, data = _read_config_from_path(path)
    if not raw:
        print(f"notice: no {kind}-style config file found; creating a new one at {path}")
    current = _json_get_entry(data, kind)
    if current is not None and not force:
        if current == entry:
            print("no-op: the uxr entry is already installed with this exact configuration")
        else:
            print("no-op: an existing uxr entry is kept untouched; rerun with --force to replace it")
        return EXIT_OK
    _json_set_entry(data, kind, entry)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    verb = "replace" if current is not None else "add"
    if dry_run:
        print(f"dry-run: would {verb} the uxr entry ({entry['command']} {entry['args'][0]})")
        return EXIT_OK
    _write_preserving(path, text, raw)
    print(f"ok: {verb} uxr entry under {'.'.join(_json_key_path(kind))} in {path}")
    return EXIT_OK


def _install_toml(path: Path, entry: dict, force: bool, dry_run: bool) -> int:
    table = f"mcp_servers.{SERVER_NAME}"
    block = toml_entry_block()
    raw, text = _read_config_from_path(path)
    if not raw:
        print(f"notice: no codex config.toml found; creating a new one at {path}")
    existing = _toml_block_text(text, table)
    if existing is not None and not force:
        if existing == block.strip():
            print("no-op: the uxr table is already installed with this exact configuration")
        else:
            print("no-op: an existing [mcp_servers.uxr] table is kept untouched; rerun with --force to replace it")
        return EXIT_OK
    verb = "replace" if existing is not None else "add"
    if dry_run:
        print(f"dry-run: would {verb} the [mcp_servers.{SERVER_NAME}] table ({entry['command']} {entry['args'][0]})")
        return EXIT_OK
    updated = _toml_replace(text, table, block)
    _write_preserving(path, updated, raw)
    print(f"ok: {verb} [mcp_servers.{SERVER_NAME}] in {path}")
    return EXIT_OK


def _read_config_from_path(path: Path) -> tuple[bytes, object]:
    """Bytes plus parsed content for a config path.

    JSON configs parse to a dict (an empty dict for a missing file, so a
    first install can create the file); TOML configs keep their raw text
    because the stdlib has no TOML writer and the edit is line-scoped.
    """
    if path.is_file():
        raw = _read_bytes(path)
    else:
        raw = b""
    if path.suffix == ".json":
        return raw, (_json_load(raw, path) if raw else {})
    # TOML surgery runs on normalized LF text; the write re-expands to
    # the file's own newline style, so a CRLF file never gains a stray \r.
    return raw, (raw.decode("utf-8").replace("\r\n", "\n") if raw else "")


def uninstall(harness: str, dry_run: bool = False, home: Path | None = None) -> int:
    """Remove only the uxr entry; every other key stays."""
    if harness == "hermes":
        print(HERMES_NOTE)
        return EXIT_UNSUPPORTED
    if harness not in HARNESSES:
        print(f"unknown harness: {harness}; known: {', '.join(HARNESSES)}")
        return EXIT_MISSING
    path = _config_path(harness, home)
    kind = _store(harness)[1]
    print(f"harness: {harness}")
    print(f"config:  {path}")
    if not path.is_file():
        print("no-op: no config file, so there is no uxr entry to remove")
        return EXIT_MISSING
    raw = _read_bytes(path)
    if kind == "toml":
        updated = _toml_remove(raw.decode("utf-8"), f"mcp_servers.{SERVER_NAME}")
        if updated is None:
            print("no-op: no [mcp_servers.uxr] table in this config")
            return EXIT_MISSING
        if dry_run:
            print("dry-run: would remove the [mcp_servers.uxr] table")
            return EXIT_OK
        _write_preserving(path, updated, raw)
        print(f"ok: removed [mcp_servers.{SERVER_NAME}] from {path}")
        return EXIT_OK
    data = _json_load(raw, path)
    if not _json_del_entry(data, kind):
        print(f"no-op: no uxr entry under {'.'.join(_json_key_path(kind))}")
        return EXIT_MISSING
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if dry_run:
        print("dry-run: would remove the uxr entry")
        return EXIT_OK
    _write_preserving(path, text, raw)
    print(f"ok: removed uxr entry from {path}")
    return EXIT_OK


def resolve_auto(home: Path | None = None) -> str | None:
    """First harness whose config file exists, in AUTO_ORDER."""
    for harness in AUTO_ORDER:
        path = _config_path(harness, home)
        if path is not None and path.is_file():
            return harness
    return None


# ---------------------------------------------------------------------------
# status: entry exists and answers a real initialize handshake
# ---------------------------------------------------------------------------

def _handshake(command: list[str]) -> tuple[bool, str]:
    """Speak initialize, notifications/initialized, tools/list once.

    Returns ``(healthy, report_line)``. The reader runs on a thread with a
    timeout so a silent or wedged server cannot hang the command.
    """
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return False, f"cannot start the configured server ({exc})"
    lines: list[str] = []
    reader_done = threading.Event()

    def _read() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if len(lines) >= 2:
                break
        reader_done.set()

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    try:
        assert proc.stdin is not None
        init_request = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": HANDSHAKE_PROTOCOL_VERSION,
                                   "capabilities": {},
                                   "clientInfo": {"name": "uxr-install-status", "version": "1"}}}
        try:
            proc.stdin.write(json.dumps(init_request) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            proc.kill()
            return False, f"cannot speak to the configured server ({exc})"
        if not reader_done.wait(timeout=HANDSHAKE_TIMEOUT_SECONDS):
            proc.kill()
            return False, f"no response within {HANDSHAKE_TIMEOUT_SECONDS}s"
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if len(lines) < 2:
        return False, f"incomplete handshake ({len(lines)} response line(s))"
    try:
        init = json.loads(lines[0])
        tools = json.loads(lines[1])
    except ValueError as exc:
        return False, f"handshake lines are not JSON ({exc})"
    result = init.get("result") if isinstance(init, dict) else None
    if not isinstance(result, dict) or "protocolVersion" not in result \
            or not isinstance(result.get("serverInfo"), dict):
        return False, "initialize response missing protocolVersion or serverInfo"
    version = result.get("serverInfo", {}).get("version", "unknown")
    tool_names = []
    if isinstance(tools, dict) and isinstance(tools.get("result"), dict):
        entries = tools["result"].get("tools", [])
        tool_names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    return True, (f"handshake ok: server {result.get('serverInfo', {}).get('name', 'server')} "
                  f"version {version}, protocol {result.get('protocolVersion')}, "
                  f"{len(tool_names)} tools")


def status(harness: str, home: Path | None = None) -> int:
    """Check the entry exists and the configured server answers a handshake."""
    if harness == "hermes":
        print(HERMES_NOTE)
        print("status: UNKNOWN for hermes in this release")
        return EXIT_UNSUPPORTED
    if harness not in HARNESSES:
        print(f"unknown harness: {harness}; known: {', '.join(HARNESSES)}")
        return EXIT_MISSING
    kind = _store(harness)[1]
    path = _config_path(harness, home)
    print(f"harness: {harness}")
    print(f"config:  {path}")
    triple = None
    try:
        triple = _read_config(harness, home)
    except _ConfigError as exc:
        print(f"status: cannot read the config ({exc})")
        return EXIT_CONFIG_ERROR
    if triple is None:
        print("status: MISSING (no config file)")
        return EXIT_MISSING
    _raw, parsed = triple[1], triple[2]
    command: list[str] | None = None
    if kind == "toml":
        text = parsed if isinstance(parsed, str) else ""
        block = _toml_block_text(text, f"mcp_servers.{SERVER_NAME}")
        if block is None:
            print("status: MISSING (no uxr table in the config)")
            return EXIT_MISSING
        command = _toml_command(block)
        if command is None:
            print("status: present, but the uxr table has no parsable command/args")
            return EXIT_BROKEN
    else:
        entry = _json_get_entry(parsed, kind)
        if entry is None:
            print("status: MISSING (no uxr entry in the config)")
            return EXIT_MISSING
        cmd = entry.get("command")
        args = entry.get("args", [])
        if not isinstance(cmd, str) or not isinstance(args, list) \
                or not all(isinstance(a, str) for a in args):
            print("status: present, but command/args are not strings")
            return EXIT_BROKEN
        command = [cmd, *args]
    healthy, report = _handshake(command)
    print(report)
    if healthy:
        return EXIT_OK
    return EXIT_BROKEN


def _toml_command(block: str) -> list[str] | None:
    """Minimal command/args extraction from one [mcp_servers.uxr] table.

    Tolerates a hand-edited multi-line args array: the value is whatever
    follows ``args = [`` until the accumulated text parses as JSON.
    """
    command = None
    args: list[str] | None = None
    collecting: list[str] | None = None
    for line in block.splitlines():
        if collecting is not None:
            collecting.append(line)
            candidate = "\n".join(collecting).split("=", 1)[1].strip()
            try:
                args = json.loads(candidate)
                collecting = None
            except ValueError:
                continue
            continue
        match = re.match(r"^\s*command\s*=\s*(.+?)\s*$", line)
        if match:
            try:
                command = json.loads(match.group(1))
            except ValueError:
                return None
            continue
        match = re.match(r"^\s*args\s*=\s*(\[.*\])\s*$", line)
        if match:
            try:
                args = json.loads(match.group(1))
            except ValueError:
                return None
            continue
        if re.match(r"^\s*args\s*=\s*\[", line):
            collecting = [line]
    if not isinstance(command, str) or not isinstance(args, list) \
            or not all(isinstance(a, str) for a in args):
        return None
    return [command, *args]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_argv(argv: list[str]) -> tuple[str, str, bool, bool, bool]:
    """Return (subcommand, harness, force, dry_run, help_wanted)."""
    subcommand = ""
    harness = ""
    force = dry_run = help_wanted = False
    tokens = list(argv)
    if tokens and tokens[0] in ("install", "uninstall", "status", "--help", "-h", "help"):
        if tokens[0] in ("--help", "-h", "help"):
            help_wanted = True
        else:
            subcommand = tokens[0]
        tokens = tokens[1:]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in ("--help", "-h"):
            help_wanted = True
        elif token == "--force":
            force = True
        elif token == "--dry-run":
            dry_run = True
        elif token == "--harness":
            if index + 1 < len(tokens):
                harness = tokens[index + 1]
                index += 1
        elif token.startswith("--harness="):
            harness = token.split("=", 1)[1]
        index += 1
    return subcommand, harness, force, dry_run, help_wanted


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    subcommand, harness, force, dry_run, help_wanted = _parse_argv(argv_list)
    if help_wanted or not subcommand:
        print(__doc__.strip())
        return EXIT_OK if help_wanted else EXIT_MISSING
    if harness in ("", "auto"):
        if subcommand == "install" and harness == "auto":
            detected = resolve_auto()
            if detected is None:
                print("auto found no harness config; pass --harness explicitly")
                print("checked: " + ", ".join(
                    f"{name} ({_config_path(name, None)})" for name in AUTO_ORDER))
                return EXIT_MISSING
            harness = detected
            print(f"auto detected: {harness}")
        elif harness == "auto":
            print("auto detection applies to install only; pass --harness for uninstall/status")
            return EXIT_MISSING
        else:
            print("pass --harness with one of: auto, zcode, codex, claude-code, hermes")
            return EXIT_MISSING
    try:
        if subcommand == "install":
            return install(harness, force=force, dry_run=dry_run)
        if subcommand == "uninstall":
            return uninstall(harness, dry_run=dry_run)
        if subcommand == "status":
            return status(harness)
        print(f"unknown subcommand: {subcommand}; expected install, uninstall, or status")
        return EXIT_MISSING
    except _ConfigError as exc:
        print(f"error: {exc}")
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
