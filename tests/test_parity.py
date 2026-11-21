#!/usr/bin/env python3
"""Golden parity gates for the W2 efficiency pass.

Parametrized over the fixture cases under ``tests/fixtures/``: every
deterministic artifact (mine table, show card, evidence synthesis block,
classifier verdicts, prompt renders, eod grouping, RQ map, slot picks,
recap draft, blocked-move line) is regenerated through the same functions
the commands call and compared against its committed expected output; the
expected outputs and the baseline goldens in ``tests/goldens/`` are
hash-pinned in ``tests/goldens/hashes.json`` so the parity targets cannot
drift silently. The baseline goldens carry ``<!-- DIFFERS: Fid -->``
markers on the four sections W1 changed (plus ``D1``/``D2`` on the two
by-design deltas ratified separately); everything outside a DIFFERS pair
is the byte-parity target.

Run: ``python tests/test_parity.py`` (also wired into the repo-level
``scripts/verify.py``). Exit 0 = all parity gates green.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

#: repo root (this tree lives at <repo>/tests, outside the installed plugin)
REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "uxr-plugin"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
GOLDENS = REPO_ROOT / "tests" / "goldens"
HASHES = GOLDENS / "hashes.json"

#: fixture expected-output files, each pinned by hash (the parity targets)
EXPECTED_GLOBS = ["render/*.expected.txt", "evidence/*.json", "spec/*.json",
                  "calendar/window.json", "eod/*.jsonl", "classify/*.json",
                  "prompts/*/*.json", "debrief/*.expected.txt",
                  "gates/*.expected.txt"]

#: the fixture-driven modules whose selftests regenerate every artifact
#: above. Each is a repo-level tests/uxr_selftests/ module, run bare in a
#: subprocess (its __main__ guard raises SystemExit(_selftest())); a
#: standalone install ships no selftest code, so these live outside the
#: plugin payload.
SELFTESTS = [
    "prompts.py", "render.py", "phase_gates.py",
    "classify.py", "evidence_sweep.py", "eod_journal.py",
    "backfill_spec.py", "calendar_prep.py", "trace_prompts.py",
    "debrief_helpers.py",
]


def _sha256(path: Path) -> str:
    """Content hash of a pinned file, EOL-normalized so a pin survives any
    checkout (git autocrlf converts text on clone; content, not line
    endings, is what the pin guards)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _pinned(path: Path, hashes: dict) -> str | None:
    """One failure line when the file's hash is pinned and has moved."""
    key = path.relative_to(REPO_ROOT).as_posix().replace("\\", "/")
    want = hashes.get(key)
    if want is None:
        return None
    got = _sha256(path)
    return None if got == want else f"{key}: sha256 {got[:12]} != pinned {want[:12]}"


def _run_module(argv: list[str], label: str) -> list[str]:
    """Run one selftest module in a subprocess (10s timeout); return failures."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              cwd=str(PLUGIN_ROOT), timeout=10)
    except subprocess.TimeoutExpired:
        return [f"{label}: selftest timed out after 10s"]
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return [f"{label}: selftest exit {proc.returncode}: {tail[-1] if tail else ''}"]
    return []


def main() -> int:
    failures: list[str] = []
    hashes = json.loads(HASHES.read_text(encoding="utf-8")) if HASHES.is_file() else {}

    for name in SELFTESTS:
        failures.extend(_run_module(
            [sys.executable, str(REPO_ROOT / "tests" / "uxr_selftests" / name)], name))

    if not GOLDENS.is_dir() or not list(GOLDENS.glob("uc-*.md")):
        failures.append("tests/goldens: no baseline goldens committed")
    for marker_file in sorted(GOLDENS.glob("uc-*.md")):
        problem = _pinned(marker_file, hashes)
        if problem:
            failures.append(problem)
        text = marker_file.read_text(encoding="utf-8")
        for fid in ("F1", "F2", "F3", "F4", "D1", "D2"):
            opens, closes = text.count(f"<!-- DIFFERS: {fid}"), text.count(f"<!-- /DIFFERS: {fid} -->")
            if opens and opens != closes:
                failures.append(f"{marker_file.name}: unbalanced DIFFERS markers for {fid}")
    for pattern in EXPECTED_GLOBS:
        for path in sorted(FIXTURES.glob(pattern)):
            problem = _pinned(path, hashes)
            if problem:
                failures.append(problem)

    if failures:
        print(f"parity FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 1
    print(f"parity: all gates green ({len(SELFTESTS)} module selftests, "
          f"{len(list(GOLDENS.glob('uc-*.md')))} goldens hash-pinned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
