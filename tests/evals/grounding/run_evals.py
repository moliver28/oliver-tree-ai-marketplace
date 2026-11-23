#!/usr/bin/env python3
"""Grounding-adherence eval runner (build item 13). Operator-run only.

The suite verifies that the plugin's model RELIES on the source registry
whenever it runs in a uxr workspace (five cases in ``evals.json``: four
golden-path, one negative). This runner IMPORTS the hcd-researcher
runner (review F9 - no copy, so the #132 ground-truth upgrade lands once
for both suites) and reuses its mechanics: the normalized-containment
scorer, the sha256 instruction-asset hashing, and the baseline append
law (runs append; the newest PASS wins).

The suite's ONE new machinery dependency (review F9) lives here: the
tool-call-order parser behind assertion (b) - deterministic text parsing
over the saved transcript; a ``references/sources/`` read or an
entry-page fetch must precede every external web call (inverted for the
negative case G5: zero web calls and zero registry fetches).

This module is never run by the repo gates and is never imported by
them. Do not run the G-case dispatches as part of a build wave - the
acceptance pass dispatches them one at a time (the account concurrency
limit).

Usage::

    python tests/evals/grounding/run_evals.py prepare [--run-dir <name>]
    python tests/evals/grounding/run_evals.py score --run-dir <name> [--workspace <dir>]
    python tests/evals/grounding/run_evals.py record --run-dir <name>

Exit codes: 0 done, 2 usage, 3 missing inputs.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
RUNS = EVALS_DIR / "runs"
BASELINE = EVALS_DIR / "baseline.json"
EVALS_JSON = EVALS_DIR / "evals.json"

#: Import the hcd-researcher runner as the mechanics base - never a copy.
_BASE_PATH = EVALS_DIR.parent / "hcd-researcher" / "run_evals.py"
_spec = importlib.util.spec_from_file_location("grounding_base_runner", _BASE_PATH)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

# Reuse the base runner's rooted paths - no copies.
REPO_ROOT = base.REPO_ROOT
PLUGIN_ROOT = base.PLUGIN_ROOT

#: The exact gap wordings assertion (c) admits alongside served leaf text.
GAP_WORDINGS = (
    "no checklist ships for <method> yet",
    "insufficient external evidence",
)

#: Transcript tool-call markers the order parser accepts (one line each).
TOOL_CALL_RE = re.compile(
    r"(?:tool_use|→|Tool:)\s*([A-Za-z_]+)\((.*?)\)", re.DOTALL
)
WEB_TOOLS = {"WebSearch", "WebFetch", "web_search", "web_fetch"}
READ_TOOLS = {"Read", "Grep", "Glob", "Bash"}
STORE_HINTS = ("references/sources/", "research-sources.md")
FETCH_HINTS = ("https://", "http://")


def _tool_sequence(transcript: str) -> list[tuple[str, str]]:
    """The ordered (tool, argument) pairs the transcript records."""
    return [(m.group(1), m.group(2)) for m in TOOL_CALL_RE.finditer(transcript)]


def _store_urls() -> tuple[str, ...]:
    """The bookmarked page paths/URLs the shipped store holds (deterministic).

    Leaves carry either full URLs or site-relative paths (``/articles/...``);
    both forms count as entry-page evidence.
    """
    parts: list[str] = []
    sources = PLUGIN_ROOT / "references" / "sources"
    if sources.is_dir():
        for path in sorted(sources.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if not line.startswith("- "):
                    continue
                token = line[2:].split(" ")[0].split("—")[0].strip().rstrip("/")
                if token.startswith("http") or (token.startswith("/") and len(token) > 6):
                    parts.append(token)
    return tuple(dict.fromkeys(parts))


def registry_first_ok(transcript: str) -> bool:
    """Assertion (b): a store read or an entry-page fetch precedes every web call.

    A Read/Grep/Glob/Bash touch of ``references/sources/`` (or the central
    index) counts, and so does a web fetch whose target URL is one of the
    store's bookmarked pages (that IS the page-first lookup). Any other
    web call before either one fails the assertion.
    """
    urls = _store_urls()
    seen_store = False
    for tool, arg in _tool_sequence(transcript):
        arg_norm = base._normalized(arg)
        if tool in READ_TOOLS and any(h in arg_norm for h in STORE_HINTS):
            seen_store = True
            continue
        if tool in WEB_TOOLS:
            if any(base._normalized(u) in arg_norm for u in urls if len(u) > 12):
                seen_store = True
                continue
            if not seen_store:
                return False
    return True


def negative_order_ok(transcript: str) -> bool:
    """Assertion (b) inverted for G5: zero web calls, zero registry fetches."""
    for tool, arg in _tool_sequence(transcript):
        if tool in WEB_TOOLS:
            return False
        if tool in READ_TOOLS and any(h in arg for h in STORE_HINTS):
            return False
    return "WebSearch" not in transcript and "WebFetch" not in transcript


def _served_leaf_union() -> str:
    """The union of every shipped entry's leaf lines (assertion c corpus)."""
    parts: list[str] = []
    sources = PLUGIN_ROOT / "references" / "sources"
    if sources.is_dir():
        for path in sorted(sources.glob("*.md")):
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return base._normalized("\n".join(parts))


def _trace_or_gap(output: str, corpus: str) -> bool:
    """Assertion (c): every method-law line traces to served text or a gap wording."""
    for line in output.splitlines():
        low = base._normalized(line)
        if not low or ("law" not in low and "rule" not in low and "method" not in low):
            continue
        if low in corpus:
            continue
        if any(base._normalized(g) in low for g in GAP_WORDINGS):
            continue
        return False
    return True


def prepare(run_dir: str | None = None) -> int:
    """Write each case's dispatch prompt; print it (the base runner's law)."""
    cases = json.loads(EVALS_JSON.read_text(encoding="utf-8"))["cases"]
    if run_dir is None:
        from datetime import datetime
        run_dir = datetime.now().strftime("%Y-%m-%dT%H%M%S") + "-grounding"
    target = RUNS / run_dir
    (target / "outputs").mkdir(parents=True, exist_ok=True)
    for case in cases:
        prompt = (
            f"{base.DISPATCH_PREFIX}\n\nCase {case['id']} on surface {case['surface']}.\n"
            f"Fixture: {json.dumps(case['fixture'], ensure_ascii=False)}\n"
            f"Steps:\n- " + "\n- ".join(case["steps"]) + "\n"
            "Follow the grounding law: consult registered sources page-first; "
            "cite the URL with the claim. Workspace-artifact-only steps run no search."
        )
        (target / "outputs" / f"case-{case['id']}.dispatch.txt").write_text(
            prompt + "\n", encoding="utf-8"
        )
        print(f"=== {case['id']} ===\n{prompt}")
    print(f"run dir: {target}")
    return 0


def score(run_dir: str, workspace: str | None = None) -> int:
    """Mechanical scoring of the saved replies + transcripts (never self-report)."""
    target = RUNS / run_dir
    out_dir = target / "outputs"
    failures: list[str] = []
    corpus = _served_leaf_union()
    cases = json.loads(EVALS_JSON.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        cid = case["id"]
        reply = out_dir / f"case-{cid}.txt"
        transcript = out_dir / f"case-{cid}.transcript.txt"
        if not reply.is_file() or not transcript.is_file():
            failures.append(f"{cid}: missing reply or transcript (exit-3 condition)")
            continue
        text = reply.read_text(encoding="utf-8", errors="replace")
        tr = transcript.read_text(encoding="utf-8", errors="replace")
        if cid == "G5-negative-record-keeping":
            if not negative_order_ok(tr):
                failures.append(f"{cid}: external web call or registry fetch in a record-keeping turn")
            continue
        if not registry_first_ok(tr):
            failures.append(f"{cid}: a web call preceded the registry read/fetch")
        if not _trace_or_gap(text, corpus):
            failures.append(f"{cid}: a method-law line traces to neither served text nor a gap wording")
    if workspace:
        import subprocess
        gate = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "lib" / "checklist_gate.py"),
             "citations", "--workspace", workspace],
            capture_output=True, text=True, timeout=60,
        )
        if gate.returncode != 0:
            failures.append(f"gate citation check exit {gate.returncode}: {(gate.stderr or gate.stdout).strip()[:200]}")
    verdict = "PASS" if not failures else "FAIL"
    (target / "scores.json").write_text(
        json.dumps({"failures": failures, "verdict": verdict}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"verdict: {verdict}")
    for item in failures:
        print(f"  [FAIL] {item}")
    return 0 if not failures else 1


def record(run_dir: str) -> int:
    """Append the run to baseline.json with carrier-file hashes (base's law)."""
    target = RUNS / run_dir
    scores_path = target / "scores.json"
    if not scores_path.is_file():
        print("record: run has no scores.json (score first)", file=sys.stderr)
        return 3
    carriers = {
        "uxr-plugin/references/research-sources.md": None,
        "uxr-plugin/templates/workspace/CLAUDE.md": None,
    }
    assets = {}
    for rel in carriers:
        path = REPO_ROOT / rel
        if path.is_file():
            assets[rel] = base._eol_sha256(path)
    data = json.loads(scores_path.read_text(encoding="utf-8"))
    entry = {
        "date": base._entry_date(run_dir),
        "dir": f"runs/{run_dir}",
        "verdict": data.get("verdict", "FAIL"),
        "instruction_assets": assets,
    }
    baseline = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {"runs": []}
    )
    baseline.setdefault("runs", []).append(entry)
    BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"recorded: {entry['verdict']} ({len(assets)} carrier hashes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    command = args[0]
    if command == "prepare":
        run_dir = None
        if "--run-dir" in args:
            run_dir = args[args.index("--run-dir") + 1]
        return prepare(run_dir)
    if command == "score":
        if "--run-dir" not in args:
            print("score: --run-dir is required", file=sys.stderr)
            return 2
        run_dir = args[args.index("--run-dir") + 1]
        workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
        return score(run_dir, workspace)
    if command == "record":
        if "--run-dir" not in args:
            print("record: --run-dir is required", file=sys.stderr)
            return 2
        return record(args[args.index("--run-dir") + 1])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
