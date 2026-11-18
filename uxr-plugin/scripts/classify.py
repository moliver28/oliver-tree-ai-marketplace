#!/usr/bin/env python3
"""Deterministic classifiers for the W2 efficiency pass: steps the commands
used to hand to the model even though their output shape is fully specified.
Keyword tables and rule data live under ``prompts/classify/``; this script
only loads and applies them. No network, no tracker access, nothing written.

Each subcommand prints one JSON object and exits 0:

    intent "<message>" [--prefix <KEY>]     router intent pick (ux-research-tickets)
    reply "<reply text>"                    recruit reply classification (phases F/H)
    method --rqs "<RQ1; RQ2; ...>"          dominant RQ shape + method table row (new ph7)
    decision "<one sentence>"               decision shape gate (new ph4)
    route-finding --category "<category>"   review-finding routing (report review)
    selftest

Exit codes: 0 ok, 2 usage, 3 selftest failed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PLUGIN_ROOT / "prompts" / "classify"
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures" / "classify"


def _spec(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


class ClassifyError(Exception):
    """No rule matched; the caller decides the fallback."""


def _hits(text: str, needles: list[str]) -> list[str]:
    """Case-insensitive keyword hits; single words match on word boundaries,
    multi-word phrases as substrings."""
    found = []
    lowered = text.lower()
    for needle in needles:
        if " " in needle.strip():
            if needle.strip().lower() in lowered:
                found.append(needle)
        elif re.search(r"\b" + re.escape(needle.strip().lower()) + r"\b", lowered):
            found.append(needle)
    return found


def _first_rule_hit(rules: list[dict], text: str) -> dict | None:
    for rule in rules:
        found = _hits(text, rule.get("any") or [])
        if found:
            lowered = text.lower()
            earliest = min(found, key=lambda needle: lowered.index(needle.lower()))
            return {**rule, "matched": earliest}
        pattern = rule.get("regex")
        if pattern and re.search(pattern, text, re.IGNORECASE):
            return {**rule, "matched": pattern}
    return None


def classify_intent(text: str, prefix: str = "") -> dict:
    spec = _spec("intents")
    lowered = text.strip().lower()
    rule = _first_rule_hit(spec["rules"], lowered)
    if rule:
        key = _extract_key(text, prefix)
        return {"command": rule["command"],
                "args": f"{key} {rule.get('args') or ''}".strip() if key and rule["command"] != "mine" and rule["command"] != "eod" else (rule.get("args") or ""),
                "signal": rule.get("matched", "")}
    key = _extract_key(text, prefix)
    if key:  # a bare key, or a key with read intent, routes to show
        return {"command": "show", "args": key, "signal": "ticket key"}
    raise ClassifyError(f"no intent rule matches {text!r}")


def _extract_key(text: str, prefix: str) -> str:
    for token in re.split(r"[\s,;!?()\"\']+", text):
        match = re.fullmatch(r"(?:([A-Za-z][A-Za-z0-9]*)-)?(\d{1,7})", token)
        if not match:
            continue
        if match.group(1):
            return token
        if prefix:
            return f"{prefix}-{token}"
    return ""


def classify_reply(text: str) -> dict:
    spec = _spec("replies")
    rule = _first_rule_hit(spec["classes"], text)
    if rule is None:  # defensive: the table always ends in free-text
        rule = spec["classes"][-1]
    return {"class": rule["class"], "action": rule.get("action", ""),
            "matched": rule.get("matched", ""), "lane": "exception" if rule["class"] == "free-text" else "deterministic"}


def classify_method(rqs: list[str]) -> dict:
    spec = _spec("methods")
    text = " ; ".join(rqs)
    lowered = text.lower()
    why_question = bool(re.search(r"\b(why|what makes|what does)\b", lowered))
    scored = []
    for rule in spec["rules"]:
        if why_question and rule["method"] == "Survey":
            continue  # hard rule: never default to a survey for a why question
        found = _hits(text, rule["keywords"])
        if found:
            scored.append((len(found), rule, found))
    if not scored:
        raise ClassifyError("no method row matches these RQs")
    scored.sort(key=lambda entry: -entry[0])
    best_count, best, found = scored[0]
    runner_up = scored[1][1]["method"] if len(scored) > 1 and scored[1][0] == best_count else ""
    return {"shape": best["shape"], "method": best["method"], "sample": best["sample"],
            "length": best["length"], "investment": best["investment"],
            "matched_on": found[:3], "alternative": runner_up,
            "rules": "qualitative leads; never a survey for a why question; a tie picks the lighter method"}


def classify_decision(text: str) -> dict:
    spec = _spec("decisions")
    body = re.sub(r"[.;]?\s*\b(?:owner|decision owner|sponsor)\b\s*[:].*$", "", text,
                  flags=re.IGNORECASE | re.DOTALL).strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    has_owner = any(marker in text.lower() for marker in spec["owner_markers"])
    for rule in spec["bad_shapes"]:
        if _hits(text, rule["any"]):
            return {"shape": rule["shape"], "good": False, "has_owner": has_owner,
                    "sentences": len(sentences)}
    if len(sentences) > 1:  # the craft bar: anything two sentences long is a bad shape
        return {"shape": "two-sentences", "good": False, "has_owner": has_owner,
                "sentences": len(sentences)}
    if not has_owner:
        return {"shape": "no-owner", "good": False, "has_owner": False,
                "sentences": len(sentences)}
    for rule in spec["good_shapes"]:
        if _hits(text, rule["any"]):
            return {"shape": rule["shape"], "good": True, "has_owner": has_owner,
                    "sentences": len(sentences)}
    return {"shape": "other-good", "good": True, "has_owner": has_owner,
            "sentences": len(sentences)}


def route_finding(category: str) -> dict:
    spec = _spec("findings")
    lowered = category.strip().lower()
    for target, categories in (("renderer", spec["render"]), ("markdown", spec["content"])):
        for name in categories:
            if name.lower() in lowered or lowered in name.lower():
                return {"target": target, "category": category}
    return {"target": "markdown", "category": category, "note": "unknown category routed to the Markdown"}


def _usage(message: str) -> str:
    return f"classify: {message}\nusage: classify.py intent|reply|method|decision|route-finding|selftest"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if not args:
        print(_usage("a subcommand is required"), file=sys.stderr)
        return 2
    sub, rest = args[0], args[1:]

    def value_of(name: str) -> str:
        return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else ""

    if sub == "intent" and rest:
        text = " ".join(t for t in rest if not t.startswith("--"))
    elif sub == "reply" and rest:
        text = " ".join(rest)
    elif sub == "method" and "--rqs" in rest:
        text = None
    elif sub == "decision" and rest:
        text = " ".join(t for t in rest if not t.startswith("--"))
    elif sub == "route-finding" and "--category" in rest:
        text = None
    else:
        print(_usage(f"unknown subcommand or missing input: {sub}"), file=sys.stderr)
        return 2
    try:
        if sub == "intent":
            result = classify_intent(text, value_of("--prefix"))
        elif sub == "reply":
            result = classify_reply(text)
        elif sub == "method":
            result = classify_method([rq for rq in re.split(r"[;\n]", value_of("--rqs")) if rq.strip()])
        elif sub == "decision":
            result = classify_decision(text)
        else:
            result = route_finding(value_of("--category"))
    except ClassifyError as exc:
        print(_usage(str(exc)), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _selftest() -> int:
    print("scripts/classify.py selftest")
    failures: list[str] = []
    cases = sorted(FIXTURES.glob("*.json"))
    if not cases:
        failures.append("no fixtures under tests/fixtures/classify")
    for case_path in cases:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        try:
            if case["subcommand"] == "intent":
                got = classify_intent(case["input"], case.get("prefix", ""))
            elif case["subcommand"] == "reply":
                got = classify_reply(case["input"])
            elif case["subcommand"] == "method":
                got = classify_method(case["input"])
            elif case["subcommand"] == "decision":
                got = classify_decision(case["input"])
            else:
                got = route_finding(case["input"])
        except ClassifyError as exc:
            got = {"error": str(exc)}
        if got == case["expect"]:
            print(f"  [ok] {case_path.stem}")
        else:
            failures.append(f"{case_path.stem}: {got} != {case['expect']}")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
