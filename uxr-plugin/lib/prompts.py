#!/usr/bin/env python3
"""Lazy-fragment prompt registry (W2 efficiency pass).

Prompt assets live under ``prompts/<id>/prompt.md``: a JSON front matter
block (``---`` fenced) plus the default body. Front matter keys:

- ``id`` / ``version``: identity used in metering lines and doc references
  (``prompt: <id>@<version>``).
- ``vars``: the slot names the body may reference; ``vars_source`` names
  where callers bind them from (``spec``, ``config``, or ``state``). The
  engine never invents values: every ``$slot`` must be bound verbatim.
- ``when``: ``[{"if": "<field> <op> <value>", "use": "<file>.md"}]`` variant
  selection against the bound fields (ops ``== != > < >= <= in``; values are
  JSON literals). First match wins; otherwise ``default``.
- ``fragments``: ``[{"id", "when", "file", "budget"}]``. A fragment loads
  ONLY when its condition fires against the bound fields (lazy). Complex
  rarely-used logic therefore costs nothing until it applies.
- ``budget``: ``{"max_lines", "max_vars"}``. Over budget is an error, never
  a trim.

Selection and condition evaluation cost zero tokens: the model sees only
the resolved text. Every render emits a metering line
``<id>@<version> fragments=[...] est_tokens=N`` on stderr.

Usage::

    python lib/prompts.py render <id> [--set key=value ...] [--spec file]
        [--config]
    python lib/prompts.py list
    python lib/prompts.py selftest

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
    meta["dir"] = str(path.parent)
    meta["body"] = text[match.end():]
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
    """JSON literal first (true/false/null, lists); fall back to a Python
    literal, then to the bare token stripped of quotes."""
    text = raw.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return raw.strip("'\"")  # verbatim binding keeps inner whitespace


def condition_field(rule: str) -> str:
    match = COND_RE.match(rule or "")
    return match.group(1) if match else ""


def condition_passes(rule: str, fields: dict) -> bool:
    """Evaluate one ``field op value`` rule. No code execution: the left side
    is a field name, the right side a JSON literal (or bare token)."""
    match = COND_RE.match(rule or "")
    if not match:
        raise PromptError(f"unparseable condition {rule!r} (ops: == != > < >= <= in)")
    field, op, raw = match.group(1), match.group(2), match.group(3)
    actual = fields.get(field)
    if op == "in":
        candidates = _literal(raw)
        if isinstance(candidates, str):
            return isinstance(actual, str) and actual in candidates
        if isinstance(candidates, (list, tuple)):
            return actual in candidates
        return False
    expected = _literal(raw)
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
    """Resolve one prompt: select variant + lazy fragments, fill ``$slots``
    with verbatim bound values, enforce the budget. Never paraphrases."""
    fields = dict(fields or {})
    meta = load(name, prompts_dir)
    variant = select_variant(meta, fields)
    body_path = Path(meta["dir"]) / variant
    if not body_path.is_file():
        raise PromptError(f"{name}: variant file missing: {body_path}")
    body = body_path.read_text(encoding="utf-8")
    body_match = FRONT_MATTER_RE.match(body)
    if body_match:  # the default variant is the asset file itself
        body = body[body_match.end():]
    parts = [body.rstrip()]
    for frag in select_fragments(meta, fields):
        parts.append(_fragment_text(meta, frag))
    text = "\n\n".join(parts)
    slots = set(_SLOT_RE.findall(text))
    missing = sorted(slots - set(fields))
    if missing:
        raise PromptError(f"{name}: unbound slots {missing} (bind every var verbatim)")
    allowed = set(meta.get("vars") or [])
    for rule in meta.get("when") or []:
        allowed.add(condition_field(rule.get("if", "")))
    for frag in meta.get("fragments") or []:
        allowed.add(condition_field(frag.get("when", "")))
    undeclared = sorted(set(fields) - allowed)
    if undeclared:
        raise PromptError(f"{name}: fields not declared in vars: {undeclared}")
    text = Template(text).substitute({s: str(fields[s]) for s in slots})
    budget = meta.get("budget") or {}
    max_lines = budget.get("max_lines")
    if max_lines is not None and len(text.splitlines()) > max_lines:
        raise PromptError(f"{name}: over budget ({len(text.splitlines())} > {max_lines} lines)")
    max_vars = budget.get("max_vars")
    if max_vars is not None and len(slots) > max_vars:
        raise PromptError(f"{name}: over budget ({len(slots)} > {max_vars} vars)")
    return text


def metering_line(name: str, fields: dict | None = None, text: str | None = None,
                  prompts_dir: Path | None = None) -> str:
    meta = load(name, prompts_dir)
    fired = [f.get("id") for f in select_fragments(meta, fields or {})]
    resolved = text if text is not None else render(name, fields, prompts_dir)
    est = max(1, len(resolved) // 4)
    return f"{meta['id']}@{meta['version']} fragments=[{', '.join(fired)}] est_tokens={est}"


def _bind_fields(args: list[str]) -> dict:
    fields: dict = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--set":
            if index + 1 >= len(args):
                raise PromptError("--set needs key=value")
            key, _, value = args[index + 1].partition("=")
            fields[key.strip()] = _literal(value)
            index += 2
        elif token == "--spec":
            if index + 1 >= len(args):
                raise PromptError("--spec needs a file path")
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
    if args and args[0] == "render":
        try:
            name = args[1]
            fields = _bind_fields(args[2:])
            text = render(name, fields)
            print(text)
            print(metering_line(name, fields, text=text), file=sys.stderr)
            return 0
        except (PromptError, IndexError) as exc:
            print(f"prompts: {exc}", file=sys.stderr)
            return 3
    print(__doc__.strip())
    return 0


def _selftest() -> int:
    print("lib/prompts.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    assets = sorted(PROMPTS_DIR.glob("*/prompt.md"))
    check("assets exist", bool(assets), "no prompts/*/prompt.md found")
    for path in assets:
        meta = _parse_asset(path)
        name = meta["id"]
        cases = sorted((FIXTURES_DIR / name).glob("case-*.json"))
        check(f"{name}: fixture cases exist", bool(cases), "no tests/fixtures/prompts cases")
        seen_fired: set[str] = set()
        for case_path in cases:
            case = json.loads(case_path.read_text(encoding="utf-8"))
            label = f"{name}:{case_path.stem}"
            try:
                text = render(name, case["fields"])
            except PromptError as exc:
                check(label, bool(case.get("expect_error")), str(exc))
                continue
            check(f"{label}: no error expected", not case.get("expect_error"),
                  "rendered although the case expects a failure")
            meta_now = load(name)
            variant = select_variant(meta_now, case["fields"])
            fired = [f.get("id") for f in select_fragments(meta_now, case["fields"])]
            seen_fired.update(fired)
            check(f"{label}: variant", variant == case.get("variant", variant),
                  f"{variant} != {case.get('variant')}")
            check(f"{label}: fragments", fired == case.get("fragments", fired),
                  f"{fired} != {case.get('fragments')}")
            for line in case.get("expect_lines") or []:
                check(f"{label}: line present", line in text, f"missing {line!r}")
        all_frags = {f.get("id") for f in meta.get("fragments") or []}
        check(f"{name}: condition matrix covers every fragment",
              all_frags <= seen_fired, f"never fired: {sorted(all_frags - seen_fired)}")
        over = FIXTURES_DIR / name / "over-budget.json"
        if over.is_file():
            case = json.loads(over.read_text(encoding="utf-8"))
            try:
                render(name, case["fields"])
                check(f"{name}: over budget fails", False, "rendered anyway")
            except PromptError:
                check(f"{name}: over budget fails", True)
        probe = {v: "x" for v in meta.get("vars") or []}
        try:
            meter = metering_line(name, probe)
            check(f"{name}: metering line", bool(_METER_RE.fullmatch(meter)), meter)
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
