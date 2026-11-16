#!/usr/bin/env python3
"""Delivery gate adapter for the /voice plugin.

Contract (token economy):
- Deterministic scan only (regex tell scan from plugins/voice-gate/voice-tells.py). Zero LLM tokens to evaluate.
- PASS: emit {"status": "pass", "tokens_to_model": 0} and stop. The model is never re-engaged.
- FAIL: emit the violated pattern labels (one line each, max 5) with nearby context, plus one instruction
  block: patch in place, do not regenerate, do not re-emit the full text. One fix line per distinct pattern.
- ERROR (scan unavailable): fail-open, {"status": "error", "deliver": true}.

Usage: python3 gate.py < <text-file>; or point a pre-delivery hook at it.
Exit codes: 0 pass/error, 4 fail (instruction block on stdout), 2 usage.
"""
import json, os, importlib.util, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "voice_tells", os.path.join(_HERE, "..", "..", "voice-gate", "voice-tells.py"))
tells = importlib.util.module_from_spec(_spec)

MAX_PATTERNS = 5

FIX_HINT = (
    ("em dash", "Replace with comma, period, colon, or parentheses in place."),
    ("spaced double hyphen", "Same rewrite as an em dash."),
    ("negative parallelism", 'Delete the "not just X" frame; state the second half only.'),
    ("less about", "State the 'more about' half only."),
    ("copula", 'serves as/stands as/functions as -> "is" in place.'),
    ("testament", "Cut the inflation; state the concrete fact."),
    ("pivotal|landscape", "Cut the significance inflation; state the concrete fact."),
    ("not just", "See negative parallelism."),
)

def fix_line(hit):
    line = f"- {hit} -> "
    low = hit.lower()
    for needle, hint in FIX_HINT:
        if needle in low:
            return line + hint
    return line + "Rewrite that phrase plainly, in the profile's voice, same length intent."

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print("usage: pipe text to stdin", file=sys.stderr); return 2
    try:
        _spec.loader.exec_module(tells)
        hits = tells.find_regex_hits(raw)
    except Exception:
        print(json.dumps({"status": "error", "deliver": True, "tokens_to_model": 0})); return 0
    if not hits:
        print(json.dumps({"status": "pass", "tokens_to_model": 0})); return 0
    family = {}
    for h in hits:
        key = " ".join(h.split("(")[0].split()[:2])
        family.setdefault(key, h)
    reported = list(family.values())[:MAX_PATTERNS]
    lines = [fix_line(h) for h in reported]
    instruction = (
        "REPAIR, DO NOT REWRITE. Each line below names one tell with its nearby context. "
        "Patch that phrase in place; keep voice, length, and all other text identical. "
        "Do not paste the full text back unless the surface forces one final copy.\n"
        + "\n".join(lines))
    print(json.dumps({
        "status": "fail", "hit_count": len(hits), "reported": len(reported),
        "instruction_char_budget": 900, "instruction": instruction}))
    return 4

if __name__ == "__main__":
    sys.exit(main())
