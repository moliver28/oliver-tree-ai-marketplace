#!/usr/bin/env python3
"""Lazy-fragment prompt registry (W2 efficiency pass).

Assets live at ``prompts/<id>/prompt.md``: JSON front matter (``---``
fenced) plus the default body. Keys: ``id``/``version`` (metering and
``prompt: <id>@<version>`` doc references); ``vars`` + ``vars_source``
(``spec|config|state``) naming the slots callers bind verbatim; ``when``
(``[{"if": "field op value", "use": "file.md"}]`` variant rules, ops
``== != > < >= <= in``, JSON-literal values); ``fragments``
(``[{id, when?, file, budget?}]`` - a fragment loads ONLY when its
condition fires, so rarely-used logic costs nothing until it applies);
``budget`` (``{max_lines, max_vars}`` - over budget is an error, never a
trim). A fragment/variant without ``when`` always applies. Selection
costs zero tokens: the model sees only the resolved text, and every
render logs ``<id>@<version> fragments=[...] est_tokens=N`` on stderr.

Usage::

    python lib/prompts.py render <id> [--set key=value ...] [--spec file] [--config]
    python lib/prompts.py list | selftest

Exit codes: 0 ok, 2 usage, 3 render or selftest failure.
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
    is a field name, the right side a JSON literal (or bare token)."""
    match = COND_RE.match(rule or "")
    if not match:
        raise PromptError(f"unparseable condition {rule!r} (ops: == != > < >= <= in)")
    field, op, raw = match.group(1), match.group(2), match.group(3)
    actual, expected = fields.get(field), _literal(raw)
    if op == "in":
        if isinstance(expected, str):
            return isinstance(actual, str) and actual in expected
        return actual in expected if isinstance(expected, (list, tuple)) else False
    if op == "==":
        return actual == expected
    if op == "!=":
        return actual != expected
    if actual is None or expected is None:
        return False
    try:
        if op == ">":
            return actual > expected
        if op == "<":
            return actual < expected
        if op == ">=":
            return actual >= expected
        return actual <= expected  # <=
    except TypeError:
        return False


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
    allowed = set(meta.get("vars") or [])
    for rule in meta.get("when") or []:
        allowed.add(COND_RE.match(rule.get("if", "")).group(1) if COND_RE.match(rule.get("if", "")) else "")
    for frag in meta.get("fragments") or []:
        match = COND_RE.match(frag.get("when", ""))
        if match:
            allowed.add(match.group(1))
    undeclared = sorted(set(fields) - allowed)
    if undeclared:
        raise PromptError(f"{name}: fields not declared in vars: {undeclared}")
    text = Template(text).substitute({s: str(fields[s]) for s in slots})
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
        token = args[index]
        if token == "--set":
            key, _, value = (args[index + 1] if index + 1 < len(args) else "=").partition("=")
            fields[key.strip()] = _literal(value)
            index += 2
        elif token == "--spec":
            data = json.loads(Path(args[index + 1]).read_text(encoding="utf-8"))
            fields.update(data if isinstance(data, dict) else {})
            index += 2
        elif token == "--config":
            from lib.config import load_config
            fields.update(load_config())
            index += 1
        else:
            raise PromptError(f"unknown argument {token!r}")
    return fields


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if args and args[0] == "list":
        for path in sorted(PROMPTS_DIR.glob("*/prompt.md")):
            meta = _parse_asset(path)
            print(f"{meta.get('id')}@{meta.get('version')} vars={meta.get('vars')}")
        return 0
    if args and args[0] == "render" and len(args) > 1:
        try:
            fields = _bind_fields(args[2:])
            print(render(args[1], fields))
            print(metering_line(args[1], fields), file=sys.stderr)
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
