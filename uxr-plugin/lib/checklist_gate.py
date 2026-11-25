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

The citation check (build item 12) is the second, standalone-invocable
CLI form: ``citations --workspace <dir>`` loads every shipped checklist
item, treats an item as outside-knowledge iff its Source field names an
``R-``/``A-`` registry id, and requires that item's ``path:`` evidence
artifact to carry a source line (a URL or a registry id). Registry ids
resolve against the ``references/sources/`` DIRECTORY; an unresolved id
prints a WARNING and never fails the check (promotion never renames).
Additive to the probe vocabulary - ``check`` behavior is unchanged.
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

#: The source-registry store (design decision 7): one entry file per id.
#: Every scripted lookup targets this DIRECTORY, never one big file.
SOURCES_DIR = PLUGIN_ROOT / "references" / "sources"

#: The one line shape a checklist item may take.
ITEM_RE = re.compile(
    r"^- \[ \] (\S+) (.+?)\. Evidence: (.+?)\. \(Source: (.+?)\)\s*$"
)

#: The group heading (the loader reads it for the output-only hierarchy
#: attachment; the line itself never parses as an item).
H3_RE = re.compile(r"^###\s+(.+)$")

#: The group default executor line (``Executor: llm``); an explicit item
#: tag always wins.
EXECUTOR_RE = re.compile(r"^Executor:\s*(llm|draft|human)\s*$")

#: The executor tag inside the item text (``[llm] `` prefix).
ITEM_TAG_RE = re.compile(r"^\[(llm|draft|human)\]\s")

#: The two autonomy values of the ``checklists.autonomy`` config key.
AUTONOMY_VALUES = ("execute", "approve")

#: Gate citation predicate (review F5): an item is outside-knowledge if and
#: only if its Source field names a registry id (an ``R-`` or ``A-`` token).
#: Grep-checkable, zero classifier variance.
REGISTRY_ID_RE = re.compile(r"\b[RA]-\d{1,3}\b")

#: A source line in an evidence artifact: a URL or a registry id.
SOURCE_LINE_RE = re.compile(r"(https?://|\b[RA]-\d{1,3}\b)")

USAGE = """usage:
  python lib/checklist_gate.py check --type <type> --spec <spec.json> --workspace <dir> [--json]
  python lib/checklist_gate.py citations --workspace <dir> [--json]
  python lib/checklist_gate.py pauses --type <type> [--autonomy execute|approve] [--json]

A missing spec file counts as an empty spec (spec probes fail closed).
``pauses`` prints the pause plan for the ``checklists.autonomy`` switch
(default ``execute``): one line per [human]/[draft] item in both modes,
plus one line per group boundary in ``approve``. Exit codes: 0 pass (or
no checklist for the type), 1 not ready, 2 usage."""


# ---------------------------------------------------------------------------
# load and probe
# ---------------------------------------------------------------------------


def load_items(path: Path | None) -> list[dict]:
    """The checklist items of one file; only the documented line shape parses.

    Output-only hierarchy attachment (issue 53 build item 1): the nearest
    ``###`` group heading and the last ``Executor:`` default ride on each
    item as ``group`` and ``executor_default``. The parse itself is
    unchanged - ``ITEM_RE`` matches the same lines, and heading, ``Pipeline:``,
    ``Executor:``, and ``Summary:`` lines stay invisible to the loader.
    """
    if path is None or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    items: list[dict] = []
    group: str | None = None
    executor_default: str | None = None
    for line in text.splitlines():
        heading = H3_RE.match(line.strip())
        if heading:
            group = heading.group(1).strip()
            continue
        executor = EXECUTOR_RE.match(line.strip())
        if executor:
            executor_default = executor.group(1).strip()
            continue
        match = ITEM_RE.match(line.strip())
        if match:
            items.append(
                {
                    "id": match.group(1),
                    "item": match.group(2),
                    "evidence": match.group(3).strip(),
                    "source": match.group(4).strip(),
                    "group": group,
                    "executor_default": executor_default,
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
# the gate citation check (build item 12; standalone-invocable)
# ---------------------------------------------------------------------------


def check_citations(
    workspace: Path | None,
    checklists_dir: Path | None = None,
) -> dict:
    """The citation check over every shipped checklist item.

    An item is outside-knowledge iff its Source field names a registry id
    (``REGISTRY_ID_RE``). For each outside-knowledge item whose evidence
    is a ``path:`` probe, the workspace artifact must carry a source line
    (a URL or a registry id token) - decision 7's "source line (URL) on
    outside-knowledge items". The check targets the ``references/sources/``
    DIRECTORY: every registry id the items or the checked artifacts name
    is resolved against ``SOURCES_DIR``; an id the store does not hold is
    a WARNING, never a failure (review F8; promotion never renames - a
    promoted A-entry becomes a new ``R-`` id and its A-file is removed, so
    recorded artifacts keep resolving). Additive to design decision 4:
    the probe vocabulary and the evidence-presence law are unchanged.

    Returns ``{"items", "ok", "missing", "warnings"}``; never raises.
    """
    result: dict = {"items": [], "ok": True, "missing": [], "warnings": []}
    try:
        base = checklists_dir if checklists_dir is not None else CHECKLIST_DIR
        if not base.is_dir():
            return result
        items: list[dict] = []
        for path in sorted(base.glob("*.md")):
            items.extend(load_items(path))
        result["items"] = items
        if not items:
            return result
        named_ids: set[str] = set()
        missing: list[dict] = []
        for item in items:
            named_ids.update(REGISTRY_ID_RE.findall(item["source"]))
            if not REGISTRY_ID_RE.search(item["source"]):
                continue
            evidence = item["evidence"].strip()
            kind, _, name = evidence.partition(":")
            if kind != "path" or not name.strip() or workspace is None:
                continue  # no artifact target; grounding rides the preamble law
            try:
                target = workspace / name.strip()
                if not (target.is_file() and target.stat().st_size > 0):
                    missing.append({"item": item["id"], "evidence": evidence, "fix": ""})
                    continue
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                missing.append({"item": item["id"], "evidence": evidence, "fix": ""})
                continue
            named_ids.update(REGISTRY_ID_RE.findall(text))
            if not SOURCE_LINE_RE.search(text):
                missing.append(
                    {
                        "item": item["id"],
                        "evidence": evidence,
                        "fix": "add a source line: a URL or a registry id",
                    }
                )
        store_ids = {p.stem for p in SOURCES_DIR.glob("*.md")} if SOURCES_DIR.is_dir() else set()
        warnings = sorted(i for i in named_ids if i not in store_ids)
        result["missing"] = missing
        result["warnings"] = warnings
        result["ok"] = not missing
        return result
    except Exception as exc:  # a gate never crashes a command
        result["ok"] = False
        result["missing"] = [{"item": "gate", "evidence": f"crashed: {exc}", "fix": ""}]
        return result


def _cli_citations(rest: list[str]) -> int:
    workspace_arg: str | None = None
    as_json = False
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--workspace" and index + 1 < len(rest):
            workspace_arg = rest[index + 1]
            index += 2
            continue
        if arg == "--json":
            as_json = True
            index += 1
            continue
        print(f"citations: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not workspace_arg:
        print(f"citations: --workspace is required\n\n{USAGE}", file=sys.stderr)
        return 2
    workspace = Path(workspace_arg).expanduser()
    result = check_citations(workspace)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for warning in result["warnings"]:
            print(f"warning: {warning} not in references/sources/")
        for entry in result["missing"]:
            print(f"missing: {entry['item']} (evidence: {entry['evidence']})")
        if not result["missing"]:
            print("citations OK")
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------------------
# the pause plan (the autonomy switch; the runner-side half of the gate loop)
# ---------------------------------------------------------------------------


def item_tag(item: dict) -> str | None:
    """The item's executor tag: the explicit ``[llm]/[draft]/[human]``
    token in the item text wins; the group ``Executor:`` default is the
    fallback; ``None`` when neither carries one."""
    match = ITEM_TAG_RE.match(item.get("item", ""))
    if match:
        return match.group(1)
    default = item.get("executor_default")
    return default.strip() if isinstance(default, str) and default.strip() else None


def pause_plan(items: list[dict], autonomy: str = "execute") -> list[dict]:
    """The pause points of one checklist, in execution order (issue 53).

    The autonomy switch is the ``checklists.autonomy`` config key
    (``execute | approve``, default ``execute``). ``[human]`` items always
    pause (human-only: the harness tracks, records, and nudges, never
    performs). ``[draft]`` items always pause (the harness drafts when the
    context it needs is available, the human decides; missing context =
    record the gap and ask, never invent). ``approve`` additionally pauses
    at every group boundary, where the runner presents the group summary,
    the artifact links, and the missing list, and waits for one go-ahead
    word. Every pause is a dict ``{"kind", "item"?, "tag"?, "group"?,
    "next_group"?}``; ``kind`` is ``human``, ``draft``, or ``boundary``.
    Mechanical output for the runner - never chat advice.
    """
    if autonomy not in AUTONOMY_VALUES:
        raise ValueError(f"autonomy must be one of {', '.join(AUTONOMY_VALUES)}")
    pauses: list[dict] = []
    previous_group: str | None = None
    for item in items:
        group = item.get("group")
        if (
            autonomy == "approve"
            and previous_group is not None
            and group != previous_group
        ):
            pauses.append(
                {"kind": "boundary", "group": previous_group, "next_group": group}
            )
        previous_group = group
        tag = item_tag(item)
        if tag == "human":
            pauses.append({"kind": "human", "item": item["id"], "tag": tag})
        elif tag == "draft":
            pauses.append({"kind": "draft", "item": item["id"], "tag": tag})
    if autonomy == "approve" and previous_group is not None:
        pauses.append({"kind": "boundary", "group": previous_group, "next_group": None})
    return pauses


def _cli_pauses(rest: list[str]) -> int:
    type_name = ""
    autonomy = "execute"
    as_json = False
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--type" and index + 1 < len(rest):
            type_name = rest[index + 1]
            index += 2
            continue
        if arg == "--autonomy" and index + 1 < len(rest):
            autonomy = rest[index + 1]
            index += 2
            continue
        if arg == "--json":
            as_json = True
            index += 1
            continue
        print(f"pauses: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not type_name:
        print(f"pauses: --type is required\n\n{USAGE}", file=sys.stderr)
        return 2
    if autonomy not in AUTONOMY_VALUES:
        print(
            f"pauses: --autonomy must be one of {', '.join(AUTONOMY_VALUES)}\n\n{USAGE}",
            file=sys.stderr,
        )
        return 2
    path = CHECKLIST_DIR / f"{type_name}.md"
    items = load_items(path)
    if not items:
        print(f"no checklist for type {type_name}")
        return 0
    pauses = pause_plan(items, autonomy)
    if as_json:
        print(json.dumps({"type": type_name, "autonomy": autonomy, "pauses": pauses},
                         ensure_ascii=False, indent=2))
    else:
        for pause in pauses:
            if pause["kind"] == "boundary":
                tail = f" before {pause['next_group']}" if pause.get("next_group") else ""
                print(f"pause: group boundary {pause['group']}{tail} (autonomy: {autonomy})")
            else:
                reason = "human-only" if pause["kind"] == "human" \
                    else "harness drafts, human decides"
                print(f"pause: {pause['item']} [{pause['tag']}] {reason}")
    return 0


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
    if args and args[0] == "citations":
        try:
            return _cli_citations(args[1:])
        except OSError as exc:
            print(f"citations: {exc}", file=sys.stderr)
            return 2
    if args and args[0] == "pauses":
        return _cli_pauses(args[1:])
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
