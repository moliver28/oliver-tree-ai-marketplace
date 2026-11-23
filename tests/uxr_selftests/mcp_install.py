"""Selftest for uxr-plugin/mcp-server/install.py (the install command).

Installs, replaces, uninstalls, and checks the uxr MCP server entry against
fixture config files inside temp directories. The machine's real harness
config files are never read, written, or modified: every flow runs with an
explicit fixture home, and the CLI layer is exercised through a redirected
USERPROFILE/HOME subprocess. The status checks speak a real initialize
handshake to the shipped server.py, spawned from the fixture entry.

Run: ``python3 -m tests.uxr_selftests.mcp_install`` or bare (also under the
smoke gate's ``--selftest`` flag). Exit 0 = every check passed.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "uxr-plugin"
INSTALLER = PLUGIN_ROOT / "mcp-server" / "install.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("uxr_install_selftest", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(callable_command, *args, **kwargs):
    """Run one installer function capturing its output; return (code, text)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = callable_command(*args, **kwargs)
    return code, buffer.getvalue()


def _seed_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def _seed_toml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[foreign_server]\ncommand = "keepme"\n\n[deep.other]\nkey = 1\n',
                    encoding="utf-8")


def _json_entry_at(path: Path, key_path: tuple[str, ...]) -> dict | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    node = data
    for key in key_path:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node.get("uxr") if isinstance(node, dict) else None


def _selftest() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append((name, detail))

    print("mcp-server/install.py selftest")
    install = _load_installer()
    install.HANDSHAKE_TIMEOUT_SECONDS = 3  # fail fast on a wedged fixture server
    server_path = str(PLUGIN_ROOT / "mcp-server" / "server.py")

    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "fixture-home"

        # --- zcode (nested JSON) ---
        cfg = home / ".zcode" / "cli" / "config.json"
        _seed_json(cfg, {"mcp": {"servers": {"foreign": {"command": "keepme"}}}})
        rc, out = _run(install.install, "zcode", home=home)
        entry = _json_entry_at(cfg, ("mcp", "servers"))
        check("zcode: install adds the uxr entry next to foreign entries",
              rc == 0 and isinstance(entry, dict) and entry.get("command")
              and entry.get("args") == [server_path], repr(entry)[:120])
        check("zcode: foreign entry untouched after install",
              json.loads(cfg.read_text(encoding="utf-8"))
              ["mcp"]["servers"]["foreign"] == {"command": "keepme"})
        rc, out = _run(install.install, "zcode", home=home)
        check("zcode: second install is an idempotent no-op with exit 0",
              rc == 0 and "no-op" in out, repr(out)[-120:])
        backup = Path(str(cfg) + ".uxr-backup")
        rc, _out = _run(install.install, "zcode", home=home, force=True)
        check("zcode: --force replaces the entry and a backup of the original exists",
              rc == 0 and backup.is_file()
              and json.loads(backup.read_text(encoding="utf-8"))
              ["mcp"]["servers"]["foreign"] == {"command": "keepme"},
              repr(backup.is_file()))
        rc, _out = _run(install.uninstall, "zcode", home=home)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        check("zcode: uninstall removes only the uxr entry",
              rc == 0 and "uxr" not in data["mcp"]["servers"]
              and data["mcp"]["servers"]["foreign"] == {"command": "keepme"}, repr(data))
        rc, _out = _run(install.status, "zcode", home=home)
        check("zcode: status after uninstall reports missing (exit 1)", rc == 1)
        _run(install.install, "zcode", home=home)
        rc, out = _run(install.status, "zcode", home=home)
        check("zcode: status against the live configured server is exit 0",
              rc == 0 and "handshake ok" in out, repr(out)[-160:])

        # --- codex (TOML) ---
        toml = home / ".codex" / "config.toml"
        _seed_toml(toml)
        rc, _out = _run(install.install, "codex", home=home)
        text = toml.read_text(encoding="utf-8")
        check("codex: install appends the uxr table and keeps foreign tables",
              rc == 0 and "[mcp_servers.uxr]" in text
              and "[foreign_server]" in text and "[deep.other]" in text, repr(text)[:160])
        rc, out = _run(install.install, "codex", home=home)
        check("codex: second install is an idempotent no-op with exit 0",
              rc == 0 and "no-op" in out, repr(out)[-120:])
        rc, _out = _run(install.install, "codex", home=home, force=True)
        text = toml.read_text(encoding="utf-8")
        check("codex: --force replaces the table including any stale sub-table",
              rc == 0 and "[mcp_servers.uxr.env]" not in text
              and "command =" in text and "[deep.other]" in text, repr(text)[:160])
        rc, _out = _run(install.uninstall, "codex", home=home)
        text = toml.read_text(encoding="utf-8")
        check("codex: uninstall removes only the uxr table",
              rc == 0 and "[mcp_servers.uxr]" not in text
              and "[foreign_server]" in text, repr(text)[:160])
        rc, _out = _run(install.status, "codex", home=home)
        check("codex: status after uninstall reports missing (exit 1)", rc == 1)

        # --- claude-code (flat JSON, user scope) ---
        cc = home / ".claude.json"
        _seed_json(cc, {"mcpServers": {"foreign": {"command": "keepme"}},
                        "projects": {"alpha": 1}})
        rc, _out = _run(install.install, "claude-code", home=home)
        data = json.loads(cc.read_text(encoding="utf-8"))
        check("claude-code: install writes the user-scope mcpServers entry",
              rc == 0 and data["mcpServers"]["uxr"].get("args") == [server_path],
              repr(data.get("mcpServers"))[:120])
        check("claude-code: sibling keys survive the write",
              data["mcpServers"]["foreign"] == {"command": "keepme"}
              and data["projects"] == {"alpha": 1}, repr(data)[:120])
        rc, _out = _run(install.install, "claude-code", home=home)
        check("claude-code: second install is an idempotent no-op with exit 0", rc == 0)
        rc, _out = _run(install.uninstall, "claude-code", home=home)
        data = json.loads(cc.read_text(encoding="utf-8"))
        check("claude-code: uninstall removes only the uxr entry",
              rc == 0 and "uxr" not in data["mcpServers"]
              and data["mcpServers"]["foreign"] == {"command": "keepme"}, repr(data))

        # --- hermes: clear refusal, nothing written ---
        rc, out = _run(install.install, "hermes", home=home)
        check("hermes: install refuses with exit 3 and names the runtime",
              rc == 3 and "hermes" in out, repr(out)[:120])
        rc, out = _run(install.status, "hermes", home=home)
        check("hermes: status reports UNKNOWN (exit 3) and creates no config",
              rc == 3 and not (home / ".hermes").exists(), repr(out)[:120])

        # --- dry-run writes nothing; missing config handled ---
        fresh = home / "fresh-home"
        rc, out = _run(install.install, "codex", dry_run=True, home=fresh)
        check("dry-run: exit 0, announces the plan, and writes no file",
              rc == 0 and "dry-run" in out
              and not (fresh / ".codex" / "config.toml").exists())
        rc, _out = _run(install.status, "zcode", home=fresh)
        check("status with no config file reports missing (exit 1)", rc == 1)

        # --- broken handshake surfaces exit 2 ---
        broken_home = Path(td) / "broken-home"
        broken_cfg = broken_home / ".zcode" / "cli" / "config.json"
        _seed_json(broken_cfg, {"mcp": {"servers": {"uxr": {
            "command": sys.executable,
            "args": ["-c", "import time; time.sleep(30)"]}}}})
        rc, _out = _run(install.status, "zcode", home=broken_home)
        check("status on a wedged server reports a broken handshake (exit 2)", rc == 2)

        # --- CLI layer through a redirected home (no real config touched) ---
        cli_home = home / "cli-home"
        env = {**os.environ, "USERPROFILE": str(cli_home), "HOME": str(cli_home)}
        run = subprocess.run(
            [sys.executable, "-I", str(INSTALLER), "install", "--harness", "zcode"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        cli_cfg = cli_home / ".zcode" / "cli" / "config.json"
        check("cli: install --harness zcode writes the fixture config with exit 0",
              run.returncode == 0 and cli_cfg.is_file()
              and _json_entry_at(cli_cfg, ("mcp", "servers")) is not None,
              (run.stdout + run.stderr)[-160:])
        rc, help_text = _run(install.main, ["--help"])
        check("cli: --help lists every harness, its config path, and the exit codes",
              rc == 0
              and all(name in help_text for name in ("zcode", "codex", "claude-code", "hermes"))
              and ".zcode/cli/config.json" in help_text
              and ".codex/config.toml" in help_text
              and ".claude.json" in help_text
              and "3" in help_text and "4" in help_text, help_text[:120])

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        for name, detail in failures:
            print("  - %s: %s" % (name, detail))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
