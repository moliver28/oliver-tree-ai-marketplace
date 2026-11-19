#!/usr/bin/env python3
"""Lazy-fragment prompt registry (W2).

``prompts/<id>/prompt.md``: JSON front matter + default body. Keys:
``id``/``version``; ``vars``; ``when`` variant rules
(``[{"if": "field op value", "use": "file.md"}]``, ops ``==`` and ``in`` -
the only ones the shipped assets use; JSON-literal values); ``fragments``
(``[{id, when?, file, budget?}]`` - loaded ONLY when the condition fires);
``budget`` (``{max_lines, max_vars}`` - over budget errors, never trims).
``dedupe`` (``{slot: anchor}`` - the slot renders empty when the anchor's
bound value already carries it: case/whitespace-normalized containment,
exact, never fuzzy).
A missing ``when`` always applies. Selection costs zero tokens; every
render logs ``<id>@<version> fragments=[...] est_tokens=N`` on stderr.
Usage: ``render <id> [--set k=v ...]`` | ``selftest``. Exit: 0 ok, 2 usage,
3 failure.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from string import Template

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PLUGIN_ROOT / "prompts"
FIXTURES_DIR = PLUGIN_ROOT / "tests" / "fixtures" / "prompts"

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
COND_RE = re.compile(r"^\s*([\w.]+)\s*(==|!=|>=|<=|>|<|\bin\b)\s*(.+?)\s*$")
_SLOT_RE = re.compile(r"\$([a-z_][a-z0-9_]*)")
_METER_RE = re.compile(r"[\w-]+@\d+ fragments=\[[^\]]*\] est_tokens=\d+")


class PromptError(Exception):
    """A prompt asset is missing, mis-declared, over budget, or under-bound."""


def _parse_asset(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise PromptError(f"{path}: missing JSON front matter block")
    try:
        meta = json.loads(match.group(1))
    except ValueError as exc:
        raise PromptError(f"{path}: front matter is not valid JSON: {exc}") from exc
    meta["dir"], meta["body"] = str(path.parent), text[match.end():]
    return meta


def load(name: str, prompts_dir: Path | None = None) -> dict:
    base = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
    path = base / name / "prompt.md"
    if not path.is_file():
        raise PromptError(f"no prompt asset named {name!r} under {base}")
    meta = _parse_asset(path)
    if meta.get("id") != name:
        raise PromptError(f"{path}: front matter id {meta.get('id')!r} != directory {name!r}")
    return meta


def _literal(raw: str):
    """JSON literal first (true/false/null, lists); then a Python literal;
    then the bare token stripped of quotes (verbatim binding keeps spaces)."""
    text = raw.strip()
    for parse in (json.loads, ast.literal_eval):
        try:
            return parse(text)
        except (ValueError, SyntaxError):
            pass
    return raw.strip("'\"")


def condition_passes(rule: str, fields: dict) -> bool:
    """Evaluate one ``field op value`` rule. No code execution: the left side
    is a field name, the right side a JSON literal (or bare token). Ops are
    ``==`` and ``in`` - the ones the shipped assets declare."""
    match = COND_RE.match(rule or "")
    if not match:
        raise PromptError(f"unparseable condition {rule!r} (ops: == in)")
    field, op, raw = match.group(1), match.group(2), match.group(3)
    actual, expected = fields.get(field), _literal(raw)
    if op == "==":
        return actual == expected
    if op == "in":
        if isinstance(expected, str):
            return isinstance(actual, str) and actual in expected
        return actual in expected if isinstance(expected, (list, tuple)) else False
    raise PromptError(f"unsupported op {op!r} in {rule!r} (ops: == in)")


def select_variant(meta: dict, fields: dict) -> str:
    for rule in meta.get("when") or []:
        if condition_passes(rule.get("if", ""), fields):
            return rule["use"]
    return meta.get("default") or "prompt.md"


def select_fragments(meta: dict, fields: dict) -> list[dict]:
    return [frag for frag in meta.get("fragments") or []
            if not frag.get("when") or condition_passes(frag["when"], fields)]


def _fragment_text(meta: dict, frag: dict) -> str:
    path = Path(meta["dir"]) / frag["file"]
    if not path.is_file():
        raise PromptError(f"fragment file missing: {path}")
    text = path.read_text(encoding="utf-8").rstrip()
    limit = frag.get("budget")
    if limit is not None and len(text.splitlines()) > limit:
        raise PromptError(f"fragment {frag.get('id')!r} over budget ({limit} lines)")
    return text


def _normalized(text: str) -> str:
    """Whitespace-collapsed, case-folded form for exact containment checks."""
    return " ".join(str(text).split()).casefold()


def render(name: str, fields: dict | None = None, prompts_dir: Path | None = None) -> str:
    """Select variant + lazy fragments, fill ``$slots`` with verbatim bound
    values, enforce the budget. Never paraphrases, never invents a value."""
    fields = dict(fields or {})
    meta = load(name, prompts_dir)
    body_path = Path(meta["dir"]) / select_variant(meta, fields)
    if not body_path.is_file():
        raise PromptError(f"{name}: variant file missing: {body_path}")
    body = body_path.read_text(encoding="utf-8")
    body_match = FRONT_MATTER_RE.match(body)
    if body_match:  # the default variant is the asset file itself
        body = body[body_match.end():]
    parts = [body.rstrip()] + [_fragment_text(meta, frag)
                               for frag in select_fragments(meta, fields)]
    text = "\n\n".join(parts)
    slots = set(_SLOT_RE.findall(text))
    missing = sorted(slots - set(fields))
    if missing:
        raise PromptError(f"{name}: unbound slots {missing} (bind every var verbatim)")
    conds = [rule.get("if", "") for rule in meta.get("when") or []] + \
            [frag.get("when", "") for frag in meta.get("fragments") or []]
    allowed = set(meta.get("vars") or []) | {
        match.group(1) for match in map(COND_RE.match, conds) if match}
    undeclared = sorted(set(fields) - allowed)
    if undeclared:
        raise PromptError(f"{name}: fields not declared in vars: {undeclared}")
    subs = {slot: str(fields[slot]) for slot in slots}
    for slot, anchor in (meta.get("dedupe") or {}).items():
        value, carried = subs.get(slot, ""), subs.get(anchor, "")
        if value and carried and _normalized(value) in _normalized(carried):
            subs[slot] = ""
    text = Template(text).substitute(subs)
    budget = meta.get("budget") or {}
    max_lines, max_vars = budget.get("max_lines"), budget.get("max_vars")
    if max_lines is not None and len(text.splitlines()) > max_lines:
        raise PromptError(f"{name}: over budget ({len(text.splitlines())} > {max_lines} lines)")
    if max_vars is not None and len(slots) > max_vars:
        raise PromptError(f"{name}: over budget ({len(slots)} > {max_vars} vars)")
    return text


def metering_line(name: str, fields: dict | None = None, text: str | None = None,
                  prompts_dir: Path | None = None) -> str:
    meta = load(name, prompts_dir)
    fired = [f.get("id") for f in select_fragments(meta, fields or {})]
    resolved = text if text is not None else render(name, fields, prompts_dir)
    return f"{meta['id']}@{meta['version']} fragments=[{', '.join(fired)}] est_tokens={max(1, len(resolved) // 4)}"


def _bind_fields(args: list[str]) -> dict:
    fields: dict = {}
    index = 0
    while index < len(args):
        if args[index] == "--set":
            key, _, value = (args[index + 1] if index + 1 < len(args) else "=").partition("=")
            fields[key.strip()] = _literal(value)
            index += 2
        else:
            raise PromptError(f"unknown argument {args[index]!r}")
    return fields


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if args and args[0] == "render" and len(args) > 1:
        try:
            fields = _bind_fields(args[2:])
            text = render(args[1], fields)
            print(text)
            print(metering_line(args[1], fields, text=text), file=sys.stderr)
            return 0
        except (PromptError, IndexError, OSError) as exc:
            print(f"prompts: {exc}", file=sys.stderr)
            return 3
    print(__doc__.strip())
    return 0


def _selftest() -> int:
    """Every asset renders under its fixture condition matrix; each fragment
    fires somewhere; the over-budget case fails; the metering line formats."""
    print("lib/prompts.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    assets = sorted(PROMPTS_DIR.glob("*/prompt.md"))
    check("assets exist", bool(assets))
    for path in assets:
        meta = _parse_asset(path)
        name = meta["id"]
        cases = sorted((FIXTURES_DIR / name).glob("case-*.json"))
        check(f"{name}: fixture cases", bool(cases))
        seen_fired: set[str] = set()
        for case_path in cases:
            case = json.loads(case_path.read_text(encoding="utf-8"))
            label = f"{name}:{case_path.stem}"
            try:
                text = render(name, case["fields"])
            except PromptError as exc:
                check(label, bool(case.get("expect_error")), str(exc))
                continue
            check(f"{label}: no error expected", not case.get("expect_error"))
            now = load(name)
            variant = select_variant(now, case["fields"])
            fired = [f.get("id") for f in select_fragments(now, case["fields"])]
            seen_fired.update(fired)
            check(f"{label}: variant", variant == case.get("variant", variant))
            check(f"{label}: fragments", fired == case.get("fragments", fired),
                  f"{fired} != {case.get('fragments')}")
            for line in case.get("expect_lines") or []:
                check(f"{label}: line", line in text, f"missing {line!r}")
        all_frags = {f.get("id") for f in meta.get("fragments") or []}
        check(f"{name}: condition matrix", all_frags <= seen_fired,
              f"never fired: {sorted(all_frags - seen_fired)}")
        over = FIXTURES_DIR / name / "over-budget.json"
        if over.is_file():
            try:
                render(name, json.loads(over.read_text(encoding="utf-8"))["fields"])
                check(f"{name}: over budget fails", False, "rendered anyway")
            except PromptError:
                check(f"{name}: over budget fails", True)
        try:
            probe = {v: "x" for v in meta.get("vars") or []}
            check(f"{name}: metering line",
                  bool(_METER_RE.fullmatch(metering_line(name, probe))))
        except PromptError as exc:
            check(f"{name}: metering line", False, str(exc))
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
