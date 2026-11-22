#!/usr/bin/env python3
"""Checklist gate: mechanical per-item probes over search-grounded checklists (issue 53).

A checklist file is one markdown file per study type under
``references/checklists/`` (``qual-interviews.md``, ``quant-surveys.md``
when the confirmed content lands). Each item is ONE line and maps to
exactly ONE machine probe; the loader parses only this line shape and
never invents an item::

    - [ ] <id> <item>. Evidence: <probe>. (Source: <where the item came from>)

The probe vocabulary has three forms, all deterministic:

- ``spec:<predicate>`` - an existing ``lib/phase_gates.SPEC_CHECKS``
  predicate name (for example ``research_questions_nonempty``). The two
  standing-mandate predicates ``ask_verbatim_present`` and
  ``ask_source_present`` (the verbatim-capture mandate) live there too
  and are reachable only through checklist items, so the reference
  requirements table and every pinned gate output stay unchanged.
- ``path:<relative>`` - the workspace file exists and is non-empty.
- ``always`` - a standing mandate the plugin law itself satisfies;
  recorded as satisfied here, declared in this docstring, never invented
  at runtime. An unknown probe fails closed (the item reports missing).

CLI (exit codes copied from ``lib/phase_gates.py``: 0 pass, 1 not ready,
2 usage)::

    python lib/checklist_gate.py check --type <type> --spec <spec.json> --workspace <dir> [--json]

``check`` prints one JSON object ``{"type", "items", "ok", "missing"}``
with ``--json``; without it, one ``missing: <id> (evidence: <probe>)``
line per unsatisfied item and nothing on a full pass. A missing or empty
checklist for the type prints ``no checklist for type <type>`` and exits
0 - the harness-half-absent law (the gate works with the checklist
content absent; enforcement is a command-side decision via the
``checklists.enforcement`` config key, ``record`` by default).

``fix`` strings reuse the ``edit`` shorthand forms of
``lib/phase_gates.SPEC_FIX_HINTS``; ``path`` and ``always`` probes carry
no shorthand and an empty ``fix``. The checklist directory is a
parameter, so a different canonical location is a config change, not a
rewrite.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from . import phase_gates as _phase_gates  # package context: import lib.checklist_gate
except ImportError:  # direct execution: python lib/checklist_gate.py
    import phase_gates as _phase_gates  # type: ignore

try:
    from .util import force_utf8_stdio as _force_utf8_stdio, read_json_arg as _read_json_arg_util, JsonReadError as _JsonReadError  # package context
except ImportError:  # direct execution: python lib/checklist_gate.py
    from util import force_utf8_stdio as _force_utf8_stdio, read_json_arg as _read_json_arg_util, JsonReadError as _JsonReadError  # type: ignore

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

#: The canonical content location; W4 ships the machinery with no content
#: files, so every lookup prints the absent line until MO confirms the item set.
CHECKLIST_DIR = PLUGIN_ROOT / "references" / "checklists"

#: The one line shape a checklist item may take.
ITEM_RE = re.compile(
    r"^- \[ \] (\S+) (.+?)\. Evidence: (.+?)\. \(Source: (.+?)\)\s*$"
)

USAGE = """usage:
  python lib/checklist_gate.py check --type <type> --spec <spec.json> --workspace <dir> [--json]

A missing spec file counts as an empty spec (spec probes fail closed).
Exit codes: 0 pass (or no checklist for the type), 1 not ready, 2 usage."""


# ---------------------------------------------------------------------------
# load and probe
# ---------------------------------------------------------------------------


def load_items(path: Path | None) -> list[dict]:
    """The checklist items of one file; only the documented line shape parses."""
    if path is None or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    items: list[dict] = []
    for line in text.splitlines():
        match = ITEM_RE.match(line.strip())
        if match:
            items.append(
                {
                    "id": match.group(1),
                    "item": match.group(2),
                    "evidence": match.group(3).strip(),
                    "source": match.group(4).strip(),
                }
            )
    return items


def probe_ok(evidence: str, spec: dict, workspace: Path | None) -> bool:
    """One probe, evaluated. Unknown probes fail closed."""
    evidence = str(evidence or "").strip()
    if evidence == "always":
        return True
    kind, _, name = evidence.partition(":")
    if kind == "spec":
        predicate = _phase_gates.SPEC_CHECKS.get(name.strip())
        try:
            return bool(predicate(spec if isinstance(spec, dict) else {}))
        except Exception:
            return False
    if kind == "path" and name.strip() and workspace is not None:
        try:
            target = workspace / name.strip()
            return target.is_file() and target.stat().st_size > 0
        except OSError:
            return False
    return False


def check_type(
    check_type_name: str,
    spec: Any,
    workspace: Path | None,
    checklists_dir: Path | None = None,
) -> dict:
    """The gate result for one type: ``{"type", "items", "ok", "missing"}``.

    A missing or empty checklist yields zero items and no missing list
    (the absent line is the caller's to print). Never raises.
    """
    result: dict = {"type": check_type_name, "items": [], "ok": True, "missing": []}
    try:
        base = checklists_dir if checklists_dir is not None else CHECKLIST_DIR
        path = base / f"{check_type_name}.md"
        items = load_items(path)
        result["items"] = items
        if not items:
            return result
        source = spec if isinstance(spec, dict) else {}
        missing: list[dict] = []
        for item in items:
            if not probe_ok(item["evidence"], source, workspace):
                missing.append(
                    {
                        "item": item["id"],
                        "evidence": item["evidence"],
                        "fix": _fix_hint(item["evidence"]),
                    }
                )
        result["missing"] = missing
        result["ok"] = not missing
        return result
    except Exception as exc:  # a gate never crashes a command
        result["ok"] = False
        result["missing"] = [{"item": "gate", "evidence": f"crashed: {exc}", "fix": ""}]
        return result


def _fix_hint(evidence: str) -> str:
    """The edit shorthand for a spec probe; path and always probes carry none."""
    kind, _, name = str(evidence or "").strip().partition(":")
    if kind == "spec":
        return _phase_gates.SPEC_FIX_HINTS.get(name.strip(), "")
    return ""


def absent_line(check_type_name: str, result: dict | None = None) -> bool:
    """True when the checklist for the type is absent or has no parsable items."""
    if result is None:
        return False
    return not result.get("items")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_check(rest: list[str]) -> int:
    type_name = ""
    spec_arg: str | None = None
    workspace_arg: str | None = None
    as_json = False
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--type" and index + 1 < len(rest):
            type_name = rest[index + 1]
            index += 2
            continue
        if arg == "--spec" and index + 1 < len(rest):
            spec_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--workspace" and index + 1 < len(rest):
            workspace_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--json":
            as_json = True
            index += 1
            continue
        print(f"check: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not type_name or not spec_arg or not workspace_arg:
        print(f"check: --type, --spec, and --workspace are required\n\n{USAGE}", file=sys.stderr)
        return 2
    try:
        spec = _read_json_arg_util(spec_arg, "--spec file", missing="empty", expanduser=False)
    except _JsonReadError as exc:
        if exc.kind == "invalid":
            raise ValueError(f"--spec file {exc.path} is not valid JSON: {exc.exc}") from None
        raise exc.exc
    workspace = Path(workspace_arg).expanduser()
    result = check_type(type_name, spec, workspace)
    if absent_line(type_name, result):
        print(f"no checklist for type {type_name}")
        return 0
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for entry in result["missing"]:
            print(f"missing: {entry['item']} (evidence: {entry['evidence']})")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if args and args[0] == "check":
        try:
            return _cli_check(args[1:])
        except ValueError as exc:
            print(f"check: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"check: {exc}", file=sys.stderr)
            return 2
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
