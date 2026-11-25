#!/usr/bin/env python3
"""Researcher journal digest: the read side of the persistent hcd-researcher (issue 120).

One journal per study key holds the researcher's completed reviews across
sessions: ``<state_dir>/researcher/<KEY>.journal.jsonl``, append-only, one
JSON line per review. The study key is the existing law (the workspace
overview's ``Ticket:`` line match, else the workspace folder name), the
same key that names the spec and the review marker. The write side is the
SubagentStop branch of ``hooks/review_gate.py``; this script is the read
side the dispatch sites call before a review::

    python scripts/researcher_state.py digest --key <KEY> [--last <N>]

The digest is bounded: the last N reviews (default 3), one line each in
the form ``<date> <artifact_kind> <verdict> <summary sentence>``, then one
``open p0 items: <n>`` line counting the p0 entries in that printed window
(the next review re-tests prior findings, so an entry a later review stops
raising ages out of the window). A review whose transcript did not parse
(the hook's pointer-only fallback line) prints as ``unparsed``. An absent
or empty journal prints ``no prior reviews``. Exit codes: 0 digest
printed, 2 usage.

State dir: ``UXR_STATE_DIR`` wins, then ``paths.state_dir`` from config;
an unexpanded ``${VAR}`` placeholder resolves to nothing and the digest
prints ``no prior reviews``. Never raises.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.util import force_utf8_stdio as _force_utf8_stdio, load_config as _load_config  # noqa: E402

RESEARCHER_DIRNAME = "researcher"
JOURNAL_SUFFIX = ".journal.jsonl"
DIGEST_DEFAULT_LAST = 3
USAGE = "usage: python scripts/researcher_state.py digest --key <KEY> [--last <N>]"


def state_dir(config: dict | None, environ=None) -> Path | None:
    """``UXR_STATE_DIR`` wins, then ``paths.state_dir``; an unexpanded placeholder is None."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get("UXR_STATE_DIR") or "").strip()
    if not raw and isinstance(config, dict):
        paths = config.get("paths", {})
        if isinstance(paths, dict):
            raw = str(paths.get("state_dir") or "").strip()
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if "${" in expanded:
        return None
    return Path(expanded)


def journal_path(key: str, config: dict | None = None, environ=None) -> Path | None:
    """``<state_dir>/researcher/<KEY>.journal.jsonl``; None without a state dir or key."""
    base = state_dir(config, environ=environ)
    if base is None or not str(key).strip():
        return None
    return base / RESEARCHER_DIRNAME / f"{str(key).strip()}{JOURNAL_SUFFIX}"


def append_line(journal: Path | None, line: dict) -> bool:
    """Append one journal line under the provenance file lock; True when written.

    The lock is the same best-effort lock the eod journal rewrite uses
    (``hooks/provenance.py`` ``file_lock``): concurrent sessions append two
    ordered lines, never fork the stream. A lock timeout proceeds unlocked
    rather than losing the line.
    """
    if journal is None or not isinstance(line, dict) or not line:
        return False
    try:
        hooks_dir = PLUGIN_ROOT / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from provenance import file_lock  # noqa: E402  (hooks/ sibling, lazy like eod_journal)
    except Exception:
        return False
    try:
        journal.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(line, ensure_ascii=False) + "\n"
        with file_lock(journal.with_name(journal.name + ".lock")):
            with open(journal, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# digest (the read path)
# ---------------------------------------------------------------------------


def read_rows(journal: Path | None) -> list[dict]:
    """Every parseable journal line, oldest first; malformed lines stay out."""
    if journal is None or not journal.is_file():
        return []
    try:
        text = journal.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def is_pointer_row(row: dict) -> bool:
    """True for the pointer-only fallback line (the transcript parse found nothing)."""
    return "transcript_path" in row and "artifact_kind" not in row


def _first_sentence(text) -> str:
    """The first sentence of a summary section, bounded to 200 characters."""
    flat = " ".join(str(text or "").split())
    for cut in (". ", "! ", "? "):
        index = flat.find(cut)
        if index != -1:
            flat = flat[: index + 1]
            break
    return flat[:200]


def _verdict_word(row: dict) -> str:
    """The checklist-scoped verdict result word, or ``-`` when the line has none."""
    verdict = row.get("verdict")
    if isinstance(verdict, dict):
        result = str(verdict.get("result") or "").strip()
        if result:
            return result
    return "-"


def open_p0_count(rows: list[dict]) -> int:
    """The p0 entries in the printed window (a p0 verdict with an empty list counts one)."""
    count = 0
    for row in rows:
        verdict = row.get("verdict")
        if isinstance(verdict, dict) and str(verdict.get("result") or "") == "p0":
            items = verdict.get("p0")
            count += len(items) if isinstance(items, list) and items else 1
    return count


def digest_lines(rows: list[dict], last: int = DIGEST_DEFAULT_LAST) -> list[str]:
    """The bounded digest lines for ``last`` reviews (the exact print contract)."""
    if last < 1:
        last = 1
    window = rows[-last:]
    if not window:
        return ["no prior reviews"]
    lines = [f"prior reviews (last {len(window)} of {len(rows)}):"]
    for row in window:
        date = str(row.get("ran_at") or "")[:10] or "unknown"
        if is_pointer_row(row):
            lines.append(f"{date} unparsed - transcript-only record")
            continue
        kind = str(row.get("artifact_kind") or "review")
        line = f"{date} {kind} {_verdict_word(row)}"
        summary = _first_sentence(row.get("summary"))
        if summary:
            line += f" {summary}"
        lines.append(line)
    lines.append(f"open p0 items: {open_p0_count(window)}")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not args or args[0] != "digest":
        print(USAGE)
        return 2
    key = ""
    last = DIGEST_DEFAULT_LAST
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--key" and index + 1 < len(args):
            key = args[index + 1]
            index += 2
            continue
        if arg == "--last" and index + 1 < len(args):
            try:
                last = int(args[index + 1])
            except ValueError:
                print(f"digest: --last must be a number, got {args[index + 1]!r}", file=sys.stderr)
                return 2
            index += 2
            continue
        print(f"digest: unknown or incomplete argument {arg!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    if not key.strip():
        print(f"digest: --key is required\n\n{USAGE}", file=sys.stderr)
        return 2
    rows = read_rows(journal_path(key.strip(), _load_config()))
    for line in digest_lines(rows, last=last):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
