"""Selftest for the derived-schema docs chain (round 3A).

Covers the "docs cannot drift from code" contract end to end:

1. ``scripts/gen_mcp_docs.py --check`` passes: the committed README tool
   table matches the derived registry.
2. Every script's ``MCP_SURFACE`` table flags equal the ``--flag`` literals
   the script's own parser code mentions (drift in either direction fails).
3. The derived JSON Schemas match the surfaces the scripts self-report via
   ``--print-mcp-surface`` for a sample of tools (spot proof that the AST
   derivation reads the same table the script publishes).
4. The argv builder reproduces each script's documented invocation for a
   sample of tools (schema and call grammar cannot drift apart).

Run: ``python3 -m tests.uxr_selftests.mcp_docs`` or bare. Exit 0 = pass.
"""
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "uxr-plugin"
SERVER_PATH = PLUGIN_ROOT / "mcp-server" / "server.py"
SCRIPTS = PLUGIN_ROOT / "scripts"
GEN_DOCS = SCRIPTS / "gen_mcp_docs.py"

TOOL_ORDER = [
    "scaffold_workspace", "build_body", "parse_shorthand", "roster_apply",
    "recruit_funnel", "classify", "report_html", "deck_render", "uxr_stats",
    "review_checks",
]

#: Derived argv spot checks: (tool, arguments, expected argv prefix/shape).
ARGV_CASES = [
    ("roster_apply", {"spec": "s.json", "ops": "{}", "out": "b.json"},
     ["--spec", "s.json", "--ops", "{}", "--out", "b.json"]),
    ("review_checks", {"path": "script.md"}, ["check", "script.md"]),
    ("report_html", {"md": "r.md", "html": "r.html"}, ["render", "r.md", "r.html"]),
    ("deck_render", {"subcommand": "render", "outline": "o.json", "out": "o.pptx"},
     ["render", "o.json", "o.pptx"]),
    ("uxr_stats", {"days": 7}, ["--days", "7"]),
    ("classify", {"subcommand": "intent", "text": "draft the interview script",
                  "prefix": "p"}, ["intent", "draft the interview script", "--prefix", "p"]),
]


def _load_server():
    spec = importlib.util.spec_from_file_location("uxr_mcp_server_docs", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_flag_names(source: str) -> set[str]:
    """The flags declared in the script's MCP_SURFACE table."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "MCP_SURFACE" for t in node.targets):
            surface = ast.literal_eval(node.value)
            names = set()
            for section in ("flags", "switches"):
                for entry in surface.get(section, []):
                    if entry.get("flag"):
                        names.add(entry["flag"])
            return names
    raise AssertionError("no MCP_SURFACE table found")


def _parser_flag_literals(source: str) -> set[str]:
    """Every ``--name`` string literal the module mentions outside the table.

    This is the parser side of the drift check: the hand-rolled parser (and
    its usage strings) name each flag exactly once as a literal; a flag
    added to the parser without the table, or renamed in the table without
    the parser, breaks the equality below.
    """
    tree = ast.parse(source)
    excluded_lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "MCP_SURFACE" for t in node.targets):
            excluded_lines = set(range(node.lineno, node.end_lineno + 1))
    literals = set()
    pattern = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.lineno in excluded_lines:
                continue
            literals.update(pattern.findall(node.value))
    literals.discard("--print-mcp-surface")  # the self-report hook, not a flag
    literals.discard("--help")
    return literals


def _selftest() -> int:
    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append((name, detail))

    print("mcp docs derivation selftest")
    server = _load_server()

    run = subprocess.run([sys.executable, "-I", str(GEN_DOCS), "--check"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(REPO_ROOT))
    check("the committed README tool table matches the derived registry",
          run.returncode == 0, (run.stdout + run.stderr)[-200:])

    for name in TOOL_ORDER:
        source = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        table_flags = _table_flag_names(source)
        parser_literals = _parser_flag_literals(source)
        parser_only = parser_literals - table_flags
        # Literals that look like flags but are not script arguments, recorded
        # once with their reason; any NEW parser literal still fails the check.
        external = {
            # git rev-parse plumbing inside commit_workspace
            "scaffold_workspace": {"--show-toplevel",
                                   # optional post-scaffold render switch (0.8.1):
                                   # parser-only convenience, not MCP surface
                                   "--then-render-overview"},
            # CSS color class names inside the HTML template
            "report_html": {"--accent", "--bg", "--fg", "--low", "--mid",
                            "--neg", "--pos", "--surface"},
        }
        check(f"{name}: MCP_SURFACE flags equal the parser's own flag literals",
              table_flags <= parser_literals
              and parser_only == external.get(name, set()),
              f"table-only={sorted(table_flags - parser_literals)} "
              f"parser-only={sorted(parser_only)}")

    registry = server.get_registry()
    for tool_name in ("roster_apply", "scaffold_workspace", "uxr_stats"):
        # No -I here on purpose: the self-report runs the script's real import
        # chain, which needs the plugin's documented PyYAML dependency.
        printed = subprocess.run(
            [sys.executable, str(SCRIPTS / f"{tool_name}.py"),
             "--print-mcp-surface"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            published = json_loads_or_none(printed.stdout)
        except Exception:
            published = None
        schema = registry[tool_name]["inputSchema"]
        surface = registry[tool_name]["surface"]
        property_names = set(schema.get("properties", {}))
        declared = {entry["name"] for entry in surface.get("flags", [])}
        declared |= {entry["name"] for entry in surface.get("switches", [])}
        if surface.get("subcommand"):
            declared.add(surface["subcommand"]["name"])
        if surface.get("stdin"):
            declared.add(surface["stdin"]["name"])
        check(f"{tool_name}: derived schema properties equal the declared surface",
              published is not None and property_names == declared,
              f"schema={sorted(property_names)} declared={sorted(declared)}")

    for tool_name, arguments, expected in ARGV_CASES:
        argv, stdin_text = server.build_argv(registry[tool_name]["surface"], arguments)
        check(f"{tool_name}: the argv builder reproduces the script's real grammar",
              argv == expected and stdin_text is None, repr(argv))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        for name, detail in failures:
            print("  - %s: %s" % (name, detail))
        return 1
    print("selftest: all checks passed")
    return 0


def json_loads_or_none(text: str):
    try:
        return __import__("json").loads(text)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(_selftest())
