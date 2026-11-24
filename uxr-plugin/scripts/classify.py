#!/usr/bin/env python3
"""Deterministic classifiers (W2): steps the commands handed to the model
even though the output shape is fully specified. Keyword tables live in
``prompts/classify/``. Each subcommand prints one JSON object: ``intent
"<msg>" [--prefix <KEY>]`` (router), ``reply "<text>"`` (recruit), ``method
--rqs "<RQ1; ...>"`` (new ph7), ``decision "<sentence>"`` (new ph4),
``route-finding --category "<c>"`` (report review). Exit:
0 ok, 2 usage/no match.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PLUGIN_ROOT / "prompts" / "classify"
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
    best, found = scored[0][1], scored[0][2]
    # The contract promises one alternative: the highest other row that
    # scored at least one keyword (a tie picks the lighter method = the best).
    runner_up = scored[1][1]["method"] if len(scored) > 1 else ""
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
    return f"classify: {message}\nusage: classify.py intent|reply|method|decision|route-finding"


MCP_SURFACE = {
    "description": (
        "classify.py: deterministic classifiers. 'intent' routes a user "
        "request, 'reply' classes a recruit reply, 'method' picks the method "
        "shape from research questions, 'decision' checks the decision shape, "
        "'route-finding' routes a review finding."),
    "subcommand": {
        "name": "subcommand", "required": True,
        "values": ["intent", "reply", "method", "decision", "route-finding"]},
    "flags": [
        {"name": "text", "kind": "positional", "type": "string", "required": True,
         "subs": ["intent", "reply", "decision"],
         "help": "the plain input text"},
        {"name": "prefix", "flag": "--prefix", "type": "string", "subs": ["intent"],
         "help": "prefix label for the verdict"},
        {"name": "rqs", "flag": "--rqs", "type": "string", "subs": ["method"],
         "help": "research questions, semicolon or newline separated"},
        {"name": "category", "flag": "--category", "type": "string", "subs": ["route-finding"],
         "help": "finding category"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--print-mcp-surface":
        print(json.dumps(MCP_SURFACE))
        return 0
    if not args:
        print(_usage("a subcommand is required"), file=sys.stderr)
        return 2
    sub, rest = args[0], args[1:]

    def value_of(name: str) -> str:
        return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else ""

    plain = " ".join(t for t in rest if not t.startswith("--"))
    try:
        if sub == "intent" and rest:
            result = classify_intent(plain, value_of("--prefix"))
        elif sub == "reply" and rest:
            result = classify_reply(" ".join(rest))  # a reply is never flag-parsed
        elif sub == "method" and "--rqs" in rest:
            result = classify_method([rq for rq in re.split(r"[;\n]", value_of("--rqs")) if rq.strip()])
        elif sub == "decision" and rest:
            result = classify_decision(plain)
        elif sub == "route-finding" and "--category" in rest:
            result = route_finding(value_of("--category"))
        else:
            print(_usage(f"unknown subcommand or missing input: {sub}"), file=sys.stderr)
            return 2
    except ClassifyError as exc:
        print(_usage(str(exc)), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
