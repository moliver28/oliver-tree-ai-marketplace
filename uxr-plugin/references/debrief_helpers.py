#!/usr/bin/env python3
"""Deterministic helpers for ``debrief`` and ``notebook`` (issue 04).

Every printout here is computed, never drafted; the commands show helper
output verbatim and add the writing work on top. All checks run offline:
no calendar, no mail, no tracker, no network.

Subcommands:

- ``render-appendix --key <participant-key.md> [--arr-file <json>]``
  Prints one ``Name, Role (Account, ARR)`` line per participant-key row,
  reading columns by header name and leaving absent parts out. An
  ``--arr-file`` (``{"<Account or Name>": "$1.2M"}``) fills an empty ARR
  cell: Account is tried first, then Name.

- ``check-stale-transcripts --events-json <file> --research-dirs <root>
  [--cache-path <file>] [--window-days 7] [--today <YYYY-MM-DD>]
  [--internal-domain <dns>]``
  Flags interview-shaped calendar events that have no filed
  ``interviews/*-<date>-summary.md`` under any research dir, and writes
  the SessionStart cache ``{"checked_at", "stale": [{title, date}]}``.
  ``--today`` pins the clock so tests do not age out. Pass one
  ``--internal-domain`` per trusted domain (from ``org.internal_domains``).

- ``pick-transcript --candidates <json-or-@file>``
  Applies the dedupe priority (speaker-labeled with a summary, then
  speaker-labeled, then raw text) and returns ``{"chosen",
  "named_not_copied"}``; the caller copies exactly the chosen source and
  names the others in the recap.

- ``check-recap --file <draft.md> [--date <YYYY-MM-DD>] [--footer <md>]``
  Gates the ticket-comment draft: ``[uxr-debrief <date>]`` first line,
  under 200 words, no bare ``RQ<digit>``/``H<digit>`` token, both
  ``What landed:`` and ``Not covered:`` present, footer last (when
  given). Exit 0 clean, 1 on any failure (one ``[FAIL]`` line each).

- ``check-summary --file <summary.md>``
  Gates the session summary's ``Insights -> Research Alignment`` block
  at write time: every ``- H<n> (...)`` line must start with a
  hypothesis stance (``Supports`` / ``Challenges`` / ``Mixed``) and
  every ``- A<n> (...)`` line with an assumption stance (``Holds`` /
  ``Breaks`` / ``Untested``) -- the frozen contract the report parser
  reads; a missing block fails too. One ``WARN`` line per violation
  (stderr), exit 0 clean, 1 on any violation (rewrite before
  continuing), 2 usage.

- ``upload-plan --workspace <dir> [--slug <slug>]``
  Builds the NotebookLM upload set as JSON: ``00-overview.md`` as
  ``Research-Plan-<slug>`` and each ``interviews/*-summary.md`` as
  ``T-<name-slug>``. ``interviews/participant-key.md`` and anything under
  ``interviews/raw-transcripts/`` are listed as excluded reasons and can
  never appear in ``uploads``.


Exit codes: 0 ok, 1 a check failed or input unreadable, 2 usage, 4
self-test failure.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

#: Titles that are never interview-shaped, whatever the attendee list.
EXCLUDE_TITLE_RE = re.compile(
    r"standup|stand-up|sync|1:1|1-1|weekly|retro|planning|coffee|team meeting",
    re.IGNORECASE,
)

#: A summary file ends ``-<YYYY-MM-DD>-summary.md``; capture the date.
SUMMARY_DATE_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})-summary\.md$")

#: Bare research codes are banned in the recap draft.
BARE_CODE_RE = re.compile(r"\b(?:RQ|H)\d")

#: The frozen alignment contract (commands/uxr-debrief.md, "Summary and
#: alignment block"; the report-side parser is references/report_helpers.py).
#: Change these vocabularies together with the parser, or not at all.
HYPOTHESIS_STANCES = ("Supports", "Challenges", "Mixed")
ASSUMPTION_STANCES = ("Holds", "Breaks", "Untested")

#: The alignment block starts under a heading carrying both tokens and ends
#: at the next heading, the same enter and leave rules the report parser uses.
ALIGN_ENTER_TOKENS = ("insights", "research alignment")

#: ``- H1 (label): stance - why`` / ``- A1 (label): stance this session - why``.
STANCE_LINE_RE = re.compile(r"^-\s+((?:H|A)\d+)\s*\(([^)]*)\)\s*:\s*(.*)$", re.IGNORECASE)

TRANSCRIPT_RANKS = (
    ("speaker-labeled with a summary", 0),
    ("speaker-labeled", 1),
    ("raw text", 2),
)


# ---------------------------------------------------------------------------
# check-stale-transcripts
# ---------------------------------------------------------------------------


def _attendee_emails(event: dict) -> list[str]:
    """Attendee email addresses; accepts ``["a@x"]`` or ``[{"email": "a@x"}]``."""
    emails: list[str] = []
    for entry in event.get("attendees") or []:
        if isinstance(entry, str):
            emails.append(entry.strip())
        elif isinstance(entry, dict):
            value = entry.get("email") or ""
            if isinstance(value, str):
                emails.append(value.strip())
    return [email for email in emails if email]


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower()


def is_interview_shaped(event: dict, internal_domains: tuple[str, ...] = ()) -> bool:
    """True when the event looks like a research session.

    First exclusion: any title matching the banned-word regex (standup,
    sync, weekly, retro, planning, coffee, team meeting, ...) is never
    interview-shaped. Then the shape needs an external attendee (an email
    domain outside ``internal_domains``) or 2 to 3 attendees.
    """
    title = str(event.get("title") or event.get("summary") or "")
    if EXCLUDE_TITLE_RE.search(title):
        return False
    emails = _attendee_emails(event)
    known = {domain.strip().lower() for domain in internal_domains if domain}
    for email in emails:
        if _email_domain(email) not in known:
            return True
    return 2 <= len(emails) <= 3


def _event_date(event: dict) -> str:
    """The ``YYYY-MM-DD`` the event starts, or ``""`` when unusable."""
    raw = event.get("start")
    if isinstance(raw, dict):
        raw = raw.get("dateTime") or raw.get("date") or ""
    text = str(raw or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""


def _parse_day(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def _summary_dates(research_dirs: list[Path]) -> set[str]:
    """Dates of filed summaries under ``<root>/<workspace>/interviews/``.

    A research dir may be the root that holds workspaces or a workspace
    itself; both ``*/interviews/*-summary.md`` and ``interviews/*-summary.md``
    are scanned.
    """
    found: set[str] = set()
    for root in research_dirs:
        if not root.is_dir():
            continue
        for path in root.glob("*/interviews/*-summary.md"):
            match = SUMMARY_DATE_RE.search(path.name)
            if match:
                found.add(match.group(1))
        for path in root.glob("interviews/*-summary.md"):
            match = SUMMARY_DATE_RE.search(path.name)
            if match:
                found.add(match.group(1))
    return found


def check_stale_transcripts(
    events: list[dict],
    research_dirs: list[Path],
    window_days: int,
    today: date,
    internal_domains: tuple[str, ...] = (),
) -> list[dict]:
    """Return ``[{title, date}]`` for shaped events with no filed summary."""
    window_start = today - timedelta(days=max(window_days, 1) - 1)
    filed = _summary_dates(research_dirs)
    stale: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict) or not is_interview_shaped(event, internal_domains):
            continue
        day = _event_date(event)
        if not day:
            continue
        parsed = _parse_day(day)
        if parsed is None or parsed < window_start or parsed > today:
            continue
        if day in filed:
            continue
        title = str(event.get("title") or event.get("summary") or "(untitled event)")
        key = (title, day)
        if key not in seen:
            seen.add(key)
            stale.append({"title": title, "date": day})
    return stale


def _write_cache(cache_path: Path, stale: list[dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale": stale,
    }
    cache_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _split_dirs(value: str) -> list[Path]:
    parts: list[str] = []
    for chunk in re.split(r"[,;]", value):
        chunk = chunk.strip()
        if chunk:
            parts.extend(part for part in chunk.split(os.pathsep) if part.strip())
    return [Path(part.strip()).expanduser() for part in parts if part.strip()]


def cmd_check_stale(args: dict[str, str]) -> int:
    events_value = args.get("--events-json") or ""
    dirs_value = args.get("--research-dirs") or ""
    if not events_value or not dirs_value:
        print(
            "debrief_helpers: check-stale-transcripts needs --events-json and --research-dirs",
            file=sys.stderr,
        )
        return EXIT_USAGE
    events_path = Path(events_value).expanduser()
    try:
        raw = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"debrief_helpers: cannot read events JSON: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if isinstance(raw, dict):
        raw = raw.get("events") or []
    if not isinstance(raw, list):
        print("debrief_helpers: events JSON must be a list of events", file=sys.stderr)
        return EXIT_FAIL
    window_days = 7
    if args.get("--window-days"):
        try:
            window_days = int(args["--window-days"])
        except ValueError:
            print("debrief_helpers: --window-days needs an integer", file=sys.stderr)
            return EXIT_USAGE
    today = date.today()
    if args.get("--today"):
        today = _parse_day(args["--today"]) or today
    domains = tuple(
        domain.strip()
        for domain in re.split(r"[,;]", args.get("--internal-domain") or "")
        if domain.strip()
    )
    research_dirs = _split_dirs(dirs_value)
    stale = check_stale_transcripts(raw, research_dirs, window_days, today, domains)
    for item in stale:
        print(f"STALE {item['date']} {item['title']}")
    if not stale:
        print(f"no stale transcripts in the past {window_days} day(s)")
    cache_value = args.get("--cache-path")
    if cache_value:
        try:
            _write_cache(Path(cache_value).expanduser(), stale)
        except OSError as exc:
            print(f"debrief_helpers: cannot write cache: {exc}", file=sys.stderr)
            return EXIT_FAIL
    return EXIT_OK


# ---------------------------------------------------------------------------
# render-appendix
# ---------------------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def read_participant_key(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read the participant-key markdown table as (headers, row dicts)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = _split_row(line)
        if _is_separator(cells):
            continue
        if not headers:
            headers = cells
            continue
        row = {header: cells[i] if i < len(cells) else "" for i, header in enumerate(headers)}
        if any(cell for cell in row.values()):
            rows.append(row)
    return headers, rows


def _load_arr_file(arr_value: str) -> dict[str, str]:
    if not arr_value:
        return {}
    try:
        data = json.loads(Path(arr_value).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"debrief_helpers: cannot read arr file: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)
    if not isinstance(data, dict):
        print("debrief_helpers: arr file must be a JSON object", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)
    return {str(key): str(value) for key, value in data.items()}


def render_appendix_lines(
    headers: list[str], rows: list[dict[str, str]], arr: dict[str, str]
) -> list[str]:
    """``Name, Role (Account, ARR)`` per row; absent parts stay out."""
    lines: list[str] = []
    for row in rows:
        name = row.get("Name", "")
        if not name:
            continue
        role = row.get("Role", "")
        account = row.get("Account", "")
        arr_value = row.get("ARR", "")
        if not arr_value and arr:
            arr_value = arr.get(account, "") or arr.get(name, "")
        left = name + (f", {role}" if role else "")
        parts = [part for part in (account, arr_value) if part]
        if parts:
            left += f" ({', '.join(parts)})"
        lines.append(left)
    return lines


def cmd_render_appendix(args: dict[str, str]) -> int:
    key_value = args.get("--key") or ""
    if not key_value:
        print("debrief_helpers: render-appendix needs --key <participant-key.md>", file=sys.stderr)
        return EXIT_USAGE
    key_path = Path(key_value).expanduser()
    if not key_path.is_file():
        print(f"debrief_helpers: participant key not found: {key_path}", file=sys.stderr)
        return EXIT_FAIL
    arr = _load_arr_file(args.get("--arr-file") or "")
    try:
        headers, rows = read_participant_key(key_path)
    except OSError as exc:
        print(f"debrief_helpers: cannot read participant key: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not headers:
        print("debrief_helpers: no markdown table found in the participant key", file=sys.stderr)
        return EXIT_FAIL
    lines = render_appendix_lines(headers, rows, arr)
    if not lines:
        print("no participant rows")
    for line in lines:
        print(line)
    return EXIT_OK


# ---------------------------------------------------------------------------
# pick-transcript
# ---------------------------------------------------------------------------


def _transcript_rank(kind: str) -> int:
    normalized = str(kind or "").strip().lower().replace("_", "-")
    if normalized in ("speaker-labeled with a summary", "speaker-labeled-summary",
                      "speaker-labeled+summary", "labeled-summary", "summary"):
        return 0
    if normalized in ("speaker-labeled", "labeled"):
        return 1
    if normalized in ("raw text", "raw-text", "raw"):
        return 2
    return len(TRANSCRIPT_RANKS)  # unknown kinds rank last


def pick_transcript(candidates: list[dict]) -> dict:
    """Pick one candidate by the dedupe priority; name the others.

    Priority: speaker-labeled with a summary, then speaker-labeled, then
    raw text; ties keep the first. ``named_not_copied`` carries the
    identifying fields of every candidate that is not copied.
    """
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (_transcript_rank(pair[1].get("kind")), pair[0]),
    )
    if not ranked:
        return {"chosen": None, "named_not_copied": []}
    _chosen_index, chosen = ranked[0]

    def identified(item: dict) -> dict:
        return {
            key: value
            for key, value in item.items()
            if key in ("source", "kind", "url", "path", "title") and value
        }

    others = [identified(item) for _index, item in ranked[1:]]
    return {"chosen": chosen, "named_not_copied": others}


def _read_candidates(value: str) -> list[dict]:
    text = value
    if value.startswith("@"):
        text = Path(value[1:]).expanduser().read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("candidates must be a JSON list")
    return [item for item in data if isinstance(item, dict)]


def cmd_pick_transcript(args: dict[str, str]) -> int:
    value = args.get("--candidates") or ""
    if not value:
        print("debrief_helpers: pick-transcript needs --candidates <json-or-@file>", file=sys.stderr)
        return EXIT_USAGE
    try:
        candidates = _read_candidates(value)
    except (OSError, ValueError) as exc:
        print(f"debrief_helpers: cannot read candidates: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not candidates:
        print("debrief_helpers: no candidates given", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(pick_transcript(candidates), indent=2, ensure_ascii=False))
    return EXIT_OK


# ---------------------------------------------------------------------------
# check-recap
# ---------------------------------------------------------------------------

RECAP_WORD_CAP = 200


def check_recap(text: str, expected_date: str = "", footer: str = "") -> list[str]:
    """Return one ``[FAIL] ...`` line per broken rule; empty means clean."""
    failures: list[str] = []
    stripped = text.strip()
    first_line = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    if expected_date:
        wanted = f"[uxr-debrief {expected_date}]"
        if first_line != wanted:
            failures.append(f"[FAIL] first line must be exactly {wanted!r} (found {first_line!r})")
    else:
        if not re.fullmatch(r"\[uxr-debrief \d{4}-\d{2}-\d{2}\]", first_line):
            failures.append(
                "[FAIL] first line must be the [uxr-debrief <YYYY-MM-DD>] heading"
            )
    words = len(stripped.split())
    if words >= RECAP_WORD_CAP:
        failures.append(f"[FAIL] recap is {words} words; it must stay under {RECAP_WORD_CAP}")
    hit = BARE_CODE_RE.search(stripped)
    if hit:
        failures.append(f"[FAIL] bare research code {hit.group(0)!r} found; spell it out in words")
    if "What landed:" not in stripped:
        failures.append("[FAIL] the 'What landed:' section is missing")
    if "Not covered:" not in stripped:
        failures.append("[FAIL] the 'Not covered:' section is missing")
    if footer and not stripped.endswith(footer.strip()):
        failures.append("[FAIL] the draft must end with the comments.footer text")
    return failures


def _check_recap_path(draft_path: Path, expected_date: str, footer: str) -> int:
    try:
        text = draft_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"debrief_helpers: cannot read draft: {exc}", file=sys.stderr)
        return EXIT_FAIL
    failures = check_recap(text, expected_date, footer)
    if failures:
        for line in failures:
            print(line)
        print(f"recap FAILED ({len(failures)} rule(s)); rewrite before showing it")
        return EXIT_FAIL
    words = len(text.strip().split())
    print(f"recap ok: {words} words, heading and sections present, no bare codes")
    return EXIT_OK


def cmd_check_recap(args: dict[str, str]) -> int:
    file_value = args.get("--file") or ""
    if not file_value:
        print("debrief_helpers: check-recap needs --file <draft.md>", file=sys.stderr)
        return EXIT_USAGE
    return _check_recap_path(Path(file_value).expanduser(),
                             args.get("--date") or "", args.get("--footer") or "")


# ---------------------------------------------------------------------------
# check-summary
# ---------------------------------------------------------------------------


def check_summary_stances(text: str) -> list[str]:
    """One ``WARN`` line per off-contract stance; empty means clean.

    The report parser drops any alignment line whose stance is not one
    of the frozen vocabulary words, which let an off-contract stance
    flow through ``evidence-weight`` as silently empty verdicts (F2).
    This check runs at write time so the block is rewritten instead.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        lowered = line.lower()
        if ALIGN_ENTER_TOKENS[0] in lowered and ALIGN_ENTER_TOKENS[1] in lowered:
            start = index + 1
            break
    if start is None:
        return [
            "WARN no Insights -> Research Alignment block found; write the "
            "alignment block so the report can compute verdicts"
        ]
    warnings: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("## ") and "insights" not in stripped.lower():
            break
        match = STANCE_LINE_RE.match(stripped)
        if not match:
            continue
        entry_id = match.group(1).upper()
        label = match.group(2).strip() or entry_id
        stance_text = match.group(3).strip()
        allowed = ASSUMPTION_STANCES if entry_id.startswith("A") else HYPOTHESIS_STANCES
        if any(stance_text.upper().startswith(stance.upper()) for stance in allowed):
            continue
        warnings.append(
            f"WARN stance on {entry_id} ({label}) is outside the contract "
            f"({' / '.join(allowed)}); rewrite the alignment block in the summary"
        )
    return warnings


def _check_summary_path(summary_path: Path) -> int:
    try:
        text = summary_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"debrief_helpers: cannot read summary: {exc}", file=sys.stderr)
        return EXIT_FAIL
    warnings = check_summary_stances(text)
    if warnings:
        for line in warnings:
            print(line, file=sys.stderr)
        print(
            f"summary FAILED ({len(warnings)} stance warning(s)); "
            "rewrite the alignment block before continuing"
        )
        return EXIT_FAIL
    print("summary ok: alignment block stances within the contract")
    return EXIT_OK


def cmd_check_summary(args: dict[str, str]) -> int:
    file_value = args.get("--file") or ""
    if not file_value:
        print("debrief_helpers: check-summary needs --file <summary.md>", file=sys.stderr)
        return EXIT_USAGE
    return _check_summary_path(Path(file_value).expanduser())


# ---------------------------------------------------------------------------
# assemble-summary / render-recap (W2: the debrief call is ONE structured
# JSON; the frozen block and the recap shape are assembled mechanically)
# ---------------------------------------------------------------------------

_ALIGN_HEADING = "## Insights → Research Alignment"


def assemble_summary_text(payload: dict) -> str:
    """The committed summary markdown from the debrief call's JSON: a
    one-paragraph session summary, speaker-labeled quotes, then the frozen
    alignment block (every spec entry gets a line; unanswered items keep
    the exact contract wording)."""
    session = payload.get("session") or {}
    alignment = payload.get("alignment") or {}
    parts: list[str] = [str(session.get("paragraph") or "").strip(), "",
                        "Notable quotes"]
    for quote in payload.get("quotes") or []:
        parts.append(f"- **{quote.get('speaker', '')}**: {quote.get('text', '')}")
    parts += ["", _ALIGN_HEADING, "**Research Questions**"]
    for entry in alignment.get("rq") or []:
        finding = str(entry.get("finding") or "").strip()
        parts.append(f"- {entry.get('id', '')} ({entry.get('short') or entry.get('id', '')}): "
                     + (finding or "No direct evidence this session."))
    for heading, group, suffix in (("**Hypotheses**", "hypotheses", ""),
                                   ("**Assumptions**", "assumptions", " this session")):
        parts.append(heading)
        for entry in alignment.get(group) or []:
            parts.append(f"- {entry.get('id', '')} ({entry.get('label', '')}): "
                         f"{entry.get('stance', '')}{suffix} - {entry.get('why', '')}")
    return "\n".join(parts).rstrip() + "\n"


def _write_payload_doc(args: dict[str, str], required: tuple[str, ...], usage: str,
                       render_fn) -> int:
    """Shared writer for the payload-driven commands: check the required
    flags, load the payload JSON, render, write (parents created), print the
    path. Exit: 0 ok, 2 usage, 1 unreadable payload."""
    values = {flag: (args.get(flag) or "") for flag in set(required) | {"--file", "--payload"}}
    if any(not values[flag] for flag in required):
        print(f"debrief_helpers: {usage}", file=sys.stderr)
        return EXIT_USAGE
    try:
        payload = json.loads(Path(values["--payload"]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"debrief_helpers: unreadable payload: {exc}", file=sys.stderr)
        return EXIT_FAIL
    path = Path(values["--file"]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_fn(payload if isinstance(payload, dict) else {}, args),
                    encoding="utf-8")
    print(path)
    return EXIT_OK


def cmd_assemble_summary(args: dict[str, str]) -> int:
    code = _write_payload_doc(
        args, ("--file", "--payload"),
        "assemble-summary needs --file <summary.md> --payload <json>",
        lambda payload, _args: assemble_summary_text(payload))
    if code == EXIT_OK and args.get("--gate"):
        return _check_summary_path(Path(args.get("--file") or "").expanduser())
    return code


def _prose_clause(topics: list[str]) -> str:
    """The ``Not covered:`` topics as one prose clause: comma-and joined,
    one closing period. A topic's own trailing period never doubles."""
    trimmed = [topic[:-1] if topic.endswith(".") else topic for topic in topics]
    if not trimmed:
        return ""
    if len(trimmed) == 1:
        return trimmed[0] + "."
    return ", ".join(trimmed[:-1]) + ", and " + trimmed[-1] + "."


def render_recap_text(payload: dict, expected_date: str, footer: str) -> str:
    """The recap comment from the debrief call's JSON: the fixed heading,
    the one-paragraph session intro, the transcript link and the summary's
    relative path, ``What landed:`` with its sentences joined as one prose
    line, ``Not covered:`` with the topics as one prose clause, blank line,
    footer."""
    lines = [f"[uxr-debrief {expected_date}]", "",
             str(payload.get("paragraph") or "").strip()]
    if payload.get("link"):
        lines.append(str(payload["link"]))
    if payload.get("summary_path"):
        lines.append(str(payload["summary_path"]))
    landing = " ".join(str(s).strip() for s in payload.get("landing") or []
                       if str(s).strip())
    lines += ["", ("What landed: " + landing) if landing else "What landed:"]
    covered = _prose_clause([str(t).strip() for t in payload.get("not_covered") or []
                             if str(t).strip()])
    lines += ["", ("Not covered: " + covered) if covered else "Not covered:"]
    if footer.strip():
        lines.extend(["", footer.strip()])
    return "\n".join(lines).rstrip() + "\n"


def cmd_render_recap(args: dict[str, str]) -> int:
    code = _write_payload_doc(
        args, ("--file", "--payload", "--date"),
        "render-recap needs --file <draft.md> --payload <json> --date <YYYY-MM-DD> [--footer <md>]",
        lambda payload, a: render_recap_text(payload, a.get("--date") or "", a.get("--footer") or ""))
    if code == EXIT_OK and args.get("--gate"):
        return _check_recap_path(Path(args.get("--file") or "").expanduser(),
                                 args.get("--date") or "", args.get("--footer") or "")
    return code


# ---------------------------------------------------------------------------
# upload-plan
# ---------------------------------------------------------------------------

OVERVIEW_MARKER = "00-overview.md"
FORBIDDEN_PARTS = ("participant-key.md", "raw-transcripts")


def upload_plan(workspace: Path, slug: str = "") -> dict:
    """The NotebookLM upload set for one workspace, forbidden paths filtered.

    ``uploads`` holds ``00-overview.md`` as ``Research-Plan-<slug>`` and
    every ``interviews/*-summary.md`` as ``T-<name-slug>``.
    ``participant-key.md`` and anything under ``raw-transcripts/`` are
    reported under ``excluded`` and can never appear in ``uploads``.
    """
    slug = slug or workspace.name
    uploads: list[dict] = []
    excluded: list[dict] = []
    overview = workspace / OVERVIEW_MARKER
    if overview.is_file():
        uploads.append(
            {"path": str(overview), "source_name": f"Research-Plan-{slug}"}
        )
    else:
        excluded.append(
            {"path": str(overview), "reason": "00-overview.md is missing; resolve the workspace first"}
        )
    interviews = workspace / "interviews"
    if interviews.is_dir():
        for path in sorted(interviews.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(workspace).as_posix()
            if any(part in rel for part in FORBIDDEN_PARTS):
                excluded.append(
                    {"path": rel, "reason": "participant data never uploads to NotebookLM"}
                )
                continue
            if SUMMARY_DATE_RE.search(path.name):
                stem = path.name[: -len("-summary.md")]
                uploads.append({"path": rel, "source_name": f"T-{stem}"})
            elif path.name != "README.md":
                excluded.append({"path": rel, "reason": "not a session summary"})
    return {"workspace": str(workspace), "slug": slug, "uploads": uploads, "excluded": excluded}


def cmd_upload_plan(args: dict[str, str]) -> int:
    ws_value = args.get("--workspace") or ""
    if not ws_value:
        print("debrief_helpers: upload-plan needs --workspace <dir>", file=sys.stderr)
        return EXIT_USAGE
    workspace = Path(ws_value).expanduser()
    if not workspace.is_dir():
        print(f"debrief_helpers: workspace not found: {workspace}", file=sys.stderr)
        return EXIT_FAIL
    overview = workspace / OVERVIEW_MARKER
    if not overview.is_file():
        print(f"debrief_helpers: {overview} does not exist", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(upload_plan(workspace, args.get("--slug") or ""), indent=2, ensure_ascii=False))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    command = args[0]
    if command not in (
        "render-appendix",
        "check-stale-transcripts",
        "pick-transcript",
        "check-recap",
        "check-summary",
        "assemble-summary",
        "render-recap",
        "upload-plan",
    ):
        print(f"debrief_helpers: unknown subcommand {command!r}", file=sys.stderr)
        return EXIT_USAGE
    parsed: dict[str, str] = {}
    index = 1
    while index < len(args):
        token = args[index]
        if token.startswith("--") and "=" in token:
            flag, value = token.split("=", 1)
            parsed[flag] = value
        elif token == "--gate":
            parsed[token] = "1"
        elif token.startswith("--"):
            if index + 1 >= len(args):
                print(f"debrief_helpers: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            parsed[token] = args[index + 1]
            index += 1
        else:
            print(f"debrief_helpers: unexpected argument {token!r}", file=sys.stderr)
            return EXIT_USAGE
        index += 1
    handlers = {
        "render-appendix": cmd_render_appendix,
        "check-stale-transcripts": cmd_check_stale,
        "pick-transcript": cmd_pick_transcript,
        "check-recap": cmd_check_recap,
        "check-summary": cmd_check_summary,
        "assemble-summary": cmd_assemble_summary,
        "render-recap": cmd_render_recap,
        "upload-plan": cmd_upload_plan,
    }
    return handlers[command](parsed)


if __name__ == "__main__":
    raise SystemExit(main())
