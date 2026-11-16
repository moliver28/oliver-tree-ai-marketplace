#!/usr/bin/env python3
"""voice-check.py: standalone zero-AI-tells scanner feeding the render gate.

Usage: python3 voice-check.py <file> [more files...]
- Exits 0 clean: writes <stem>.voice-pass marker next to the source.
- Exits 1 with the offending lines when banned patterns hit.
Rules live in voice-gate.py (same BANNED_PATTERNS) so the hook and the
standalone scanner can never drift apart.
"""
import importlib.util, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "voice_gate_mod", Path(__file__).resolve().parent / "voice-gate.py")
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
_find_banned = _m._find_banned

def main():
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not files:
        print("usage: voice-check.py <file> ...")
        return 2
    total_bad = 0
    for f in files:
        p = Path(f).expanduser()
        if not p.exists():
            print(f"MISSING: {p}")
            total_bad += 1
            continue
        text = p.read_text(errors="replace")
        hits = _find_banned(text)
        marker = p.with_name(p.stem + ".voice-pass")
        if hits:
            total_bad += len(hits)
            print(f"FAIL {p}: {len(hits)} banned pattern(s)")
            for h in hits:
                print(f"  - {h}")
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
        else:
            marker.write_text(datetime.now(timezone.utc).isoformat() + "\n")
            print(f"PASS {p} (marker {marker.name})")
    return 1 if total_bad else 0

if __name__ == "__main__":
    sys.exit(main())
