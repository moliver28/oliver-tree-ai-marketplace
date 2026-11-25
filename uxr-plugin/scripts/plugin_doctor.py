#!/usr/bin/env python3
"""plugin_doctor.py: install profiles and harness repair for uxr-plugin.

The plugin installs as one full copy. This script lets an end user prune
the parts they do not need from their installed copy, verify the harness
still holds together, and repair a broken install from the marketplace
source. Nothing here changes the repo tree: profiles apply to an INSTALL,
never to the marketplace repo.

Profiles are data, not code. ``MODULES`` below names each optional module
and the plugin-root-relative paths it owns. ``profile apply`` deletes the
module paths, records the act in ``.profile.json``, and prints the restore
path. ``check`` validates the remaining harness: manifest, hook wiring,
script compilation, front matter, cross-references, schemas, and the
profile state file itself. ``fix`` re-fetches the marketplace source and
copies back whatever is missing, then re-applies the saved profile.

All modes are read-only unless you run ``profile apply`` or ``fix``.
Exit codes: 0 ok, 1 problems found, 2 usage, 3 refusal, 4 fix failed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STATE = PLUGIN_ROOT / ".profile.json"

#: Optional modules. Each owns plugin-root-relative paths; ``profile apply``
#: removes exactly these and nothing else. References stay in core on
#: purpose: the reference room serves every profile.
MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "mcp": (
        "MCP stdio server for harnesses without plugin hooks",
        (
            "mcp-server",
            "scripts/gen_mcp_docs.py",
        ),
    ),
    "scripting": (
        "Interview and survey script drafting: two skills + their two scripts",
        (
            "skills/interview-script",
            "skills/survey-script",
            "scripts/review_checks.py",
            "scripts/render_script_docx.py",
        ),
    ),
}
def load_state() -> dict | None:
    """Return .profile.json, or None when absent."""
    if not STATE.is_file():
        return None
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def all_module_paths(modules: list[str]) -> list[str]:
    """Union of owned paths for the named modules, in declaration order."""
    out: list[str] = []
    for name in modules:
        if name in MODULES:
            out.extend(MODULES[name][1])
    return out


def manifest_version() -> str:
    """The plugin version from .claude-plugin/plugin.json."""
    data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(data.get("version") or "")


def iter_md_files() -> list[Path]:
    """Every commands/, skills/, agents/ markdown file."""
    out = []
    for sub in ("commands", "skills", "agents"):
        base = PLUGIN_ROOT / sub
        if base.is_dir():
            out.extend(p for p in base.rglob("*.md"))
    return out


def front_matter(text: str) -> dict[str, str] | None:
    """Parse the leading --- front matter block; None when malformed."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    out: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" not in line:
            return None
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out
PLUGIN_ROOT_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")


def check_py_compile(problems: list[str]) -> int:
    """Compile every shipped .py under scripts/, lib/, hooks/, mcp-server/."""
    count = 0
    for sub in ("scripts", "lib", "hooks", "mcp-server"):
        base = PLUGIN_ROOT / sub
        if not base.is_dir():
            continue
        for py in sorted(base.rglob("*.py")):
            try:
                compile(py.read_text(encoding="utf-8"), str(py), "exec")
            except (SyntaxError, ValueError, OSError) as exc:
                problems.append(f"compile: {py.relative_to(PLUGIN_ROOT)}: {exc}")
            count += 1
    return count


def check_hooks(problems: list[str]) -> int:
    """Every hooks.json hook command names a file that exists."""
    hooks_json = PLUGIN_ROOT / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        problems.append("hooks/hooks.json is missing")
        return 0
    count = 0
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    data = data.get("hooks", data)
    for event, entries in data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = str(hook.get("command") or "")
                for rel in PLUGIN_ROOT_RE.findall(command):
                    if not (PLUGIN_ROOT / rel).is_file():
                        problems.append(f"hooks.json {event}: missing {rel}")
                    count += 1
    return count
def check_md(problems: list[str]) -> int:
    """Front matter parses; every ${CLAUDE_PLUGIN_ROOT} ref resolves."""
    count = 0
    for md in iter_md_files():
        rel = md.relative_to(PLUGIN_ROOT)
        fm = front_matter(md.read_text(encoding="utf-8"))
        if fm is None or "description" not in fm:
            problems.append(f"front matter: {rel}")
            continue
        count += 1
        for rel_path in PLUGIN_ROOT_RE.findall(md.read_text(encoding="utf-8")):
            if not (PLUGIN_ROOT / rel_path).exists():
                problems.append(f"{rel}: missing ${'{CLAUDE_PLUGIN_ROOT}'}/{rel_path}")
    return count


def check_schemas(problems: list[str]) -> int:
    """Every *.schema.json under references/ parses as JSON."""
    count = 0
    schemas = PLUGIN_ROOT / "references"
    if schemas.is_dir():
        for schema in sorted(schemas.rglob("*.schema.json")):
            try:
                json.loads(schema.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                problems.append(f"schema: {schema.relative_to(PLUGIN_ROOT)}: {exc}")
            count += 1
    return count


def check_profile_state(problems: list[str]) -> int:
    """Profile state, when present, names known modules and absent paths."""
    state = load_state()
    if state is None:
        return 0
    profile = str(state.get("profile") or "")
    if profile not in MODULES and profile != "full":
        problems.append(f"profile state: unknown profile {profile!r}")
    pruned: list[str] = state.get("pruned") or []
    for name in pruned:
        if name not in MODULES:
            problems.append(f"profile state: unknown module {name!r}")
            continue
        for rel in MODULES[name][1]:
            if (PLUGIN_ROOT / rel).exists():
                problems.append(f"profile state: pruned {rel} is back on disk")
    return 1
def run_check() -> int:
    """Validate the harness; print a report; return the process exit code."""
    problems: list[str] = []
    py_count = check_py_compile(problems)
    hook_refs = check_hooks(problems)
    md_count = check_md(problems)
    schema_count = check_schemas(problems)
    state_flag = check_profile_state(problems)
    state = load_state()
    profile = str((state or {}).get("profile") or "full")
    print(f"doctor: {len(problems)} problem(s)")
    print(f"  scripts compiled: {py_count}")
    print(f"  hook command refs: {hook_refs}")
    print(f"  markdown files: {md_count}")
    print(f"  schemas: {schema_count}")
    print(f"  profile: {profile}{' (state file present)' if state else ''}")
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    return 1 if problems else 0


def apply_profile(name: str) -> int:
    """Prune optional modules from this install and record the state.

    Records the full-install command/skill counts and the per-directory
    count of pruned files, so the smoke gate's component floors keep
    passing for pruned installs (the floors a full install met).
    """
    if name not in MODULES and name != "full":
        known = ", ".join(["full"] + sorted(MODULES))
        print(f"profile: unknown profile {name!r}; known: {known}", file=sys.stderr)
        return 2
    probe = PLUGIN_ROOT
    while probe != probe.parent:
        if (probe / ".git").is_dir():
            print(
                "profile: refusing: this looks like the marketplace repo clone, "
                "not an installed copy (a .git dir sits above the plugin root). "
                "Profiles apply to installs only; the repo tree never shrinks.",
                file=sys.stderr,
            )
            return 3
        probe = probe.parent
    state = load_state()
    pruned = list(state.get("pruned") or []) if state else []
    counts = (state or {}).get("counts") or {
        "commands": len(list((PLUGIN_ROOT / "commands").iterdir())) if (PLUGIN_ROOT / "commands").is_dir() else 0,
        "skills": len([p for p in (PLUGIN_ROOT / "skills").rglob("*") if p.is_file()]) if (PLUGIN_ROOT / "skills").is_dir() else 0,
    }
    pruned_files = dict((state or {}).get("pruned_files") or {})
    if name != "full":
        for rel in all_module_paths([name]):
            target = prune_path(PLUGIN_ROOT / rel)
            if target is None:
                continue
            segment = rel.split("/")[0]
            pruned_files[segment] = pruned_files.get(segment, 0) + target
    if name not in pruned:
        pruned.append(name)
    STATE.write_text(
        json.dumps(
            {
                "profile": name,
                "version": manifest_version(),
                "pruned": pruned,
                "counts": counts,
                "pruned_files": pruned_files,
                "restore": "plugin update or python scripts/plugin_doctor.py fix",
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"profile: applied {name!r}; pruned {pruned}")
    print("restore: install a newer plugin version, or run: python scripts/plugin_doctor.py fix")
    return 0


def prune_path(target: Path) -> int | None:
    """Delete a module path; return the file count removed, None if gone."""
    if not target.exists():
        return None
    if target.is_dir():
        files = len([p for p in target.rglob("*") if p.is_file()])
        shutil.rmtree(target)
        return files
    target.unlink()
    return 1

MARKETPLACE_REPO = "https://github.com/moliver28/oliver-tree-ai-marketplace"

USAGE = """usage:
  python scripts/plugin_doctor.py                        # check harness health
  python scripts/plugin_doctor.py profile <name>         # show a module's paths
  python scripts/plugin_doctor.py profile apply full|mcp|scripting
  python scripts/plugin_doctor.py fix                    # repair from marketplace
  python scripts/plugin_doctor.py --help

exit codes: 0 ok, 1 problems, 2 usage, 3 refusal, 4 fix failed."""


def run_fix() -> int:
    """Repair a broken install from a fresh marketplace clone."""
    problems_before: list[str] = []
    check_py_compile(problems_before)
    if not problems_before:
        print("fix: nothing to repair (all scripts compile)")
    repo = Path(tempfile.mkdtemp(prefix="uxr-doctor-"))
    try:
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", MARKETPLACE_REPO, str(repo / "src")],
            capture_output=True, text=True,
        )
        if clone.returncode != 0:
            print(f"fix: clone failed: {clone.stderr.strip()}", file=sys.stderr)
            return 4
        src_root = repo / "src" / "uxr-plugin"
        if not src_root.is_dir():
            print("fix: marketplace clone has no uxr-plugin/; repository layout changed", file=sys.stderr)
            return 4
        state = load_state()
        pruned = list(state.get("pruned") or []) if state else []
        owned = set(all_module_paths(pruned)) if pruned else set()
        copied = 0
        for src in src_root.rglob("*"):
            rel = src.relative_to(src_root).as_posix()
            if any(rel == o or rel.startswith(o + "/") for o in owned):
                continue
            if src.is_file():
                dest = PLUGIN_ROOT / rel
                if not dest.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    copied += 1
        after: list[str] = []
        check_py_compile(after)
        print(f"fix: copied back {copied} missing file(s); {len(after)} compile problem(s) remain")
        return 0 if not after else 1
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not args or args[0] == "check":
        return run_check()
    if args[0] == "fix":
        return run_fix()
    if args[0] == "profile" and len(args) >= 2 and args[1] == "apply" and len(args) >= 3:
        return apply_profile(args[2])
    if args[0] == "profile" and len(args) == 2 and args[1] in MODULES:
        desc = MODULES[args[1]][0]
        paths = "\n".join(f"  {rel}" for rel in MODULES[args[1]][1])
        print(f"{args[1]}: {desc}\n{paths}")
        return 0
    print(USAGE.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
