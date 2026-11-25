#!/usr/bin/env python3
"""Recruitment funnel table, wave preflight, nudges, and the V1 draft check (issue 10).

This script computes; the ``recruit`` command writes. Five jobs:

- default / ``--status``: print the fixed nine-row recruitment table
  (Fit, Looked at, Allowed, Not allowed, Sent, Bounced, Scheduled,
  Attempted % of fit, Recruited % of fit) across the five fixed columns
  (Internal users, In-product accounts, In-product users, Other accounts,
  Other users), under one caption line naming the target persona (issue
  51: ``funnel.fit.basis`` with its ``as_of``; ``not recorded yet``
  without). Every count cell reads ``all waves (this wave)`` and a
  this-wave value never exceeds its total. The suppress stage feeds the
  Not allowed row (issue 50: the suppressed rows join the excluded
  totals). Roster numbers are authoritative; sheet-derived numbers come
  from ``--funnel-data`` (the JSON export the command assembles after
  reading the live wave tabs).
- ``--preflight``: check the target wave's rows and exit 2 with
  ``BLOCK <account> / <first>: <reason>`` lines for anyone listed twice,
  already booked or declined, on an open-deal account, emailed in an
  earlier wave, on the do-not-contact tab, or whose booking link is not
  exactly one booking-page URL; ``BLOCK - / -: no rows ready`` when
  nothing is left. Success prints ``PREFLIGHT OK: <n> rows ready on
  <wave>``. The suppress stage (issue 50) runs first: rows matching one
  of its three checks leave the ready count without blocking, and the
  suppressed counts per check print with the result on both paths.
  Nothing is ever sent here.
- ``--pipeline-check``: print the resolved recruitment pipeline (the
  ordered stage list from config ``recruitment.pipeline``, default
  ``identify -> screen -> suppress -> invite -> schedule -> send``) and
  the configured suppression-list state. An unknown stage name or an
  unreadable configured suppression-list file is a usage error (exit 2,
  fail closed). Nothing is ever written here.
- ``--reminder``: list contacts whose send is older than
  ``recruit.nudge_after_days`` business days with no reply, plus one
  shorter follow-up draft (draft only; the link stays in the merge
  column, never in a mail draft body).
- ``--check-draft <file>``: the V1 check. Passes only when the draft body
  keeps ``{{First name}}`` and ``{{Booking link}}`` and contains no
  ``http`` (a mail tool that rewrites links would redirect the URL).

Output never contains an email address: every printed line is scrubbed as
a final safety net even though the funnel data itself carries emails.

Usage::

    python scripts/recruit_funnel.py --spec <path.spec.json>
        [--wave <tab>] [--preflight] [--status] [--reminder]
        [--funnel-data <json>] [--check-draft <file>] [--today <YYYY-MM-DD>]
    python scripts/recruit_funnel.py --pipeline-check

Exit codes: 0 clean (or V1 pass), 1 V1 draft check failed, 2 usage /
preflight blocked.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

if str(PLUGIN_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from scripts import source_contacts as _source  # noqa: E402
from lib.util import force_utf8_stdio as _force_utf8_stdio  # noqa: E402  (shared plumbing)
from lib import util as _util  # noqa: E402

EXIT_OK = 0
EXIT_V1 = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 2
EXIT_SELFTEST = 3

#: Roster statuses that count as Sent and as Scheduled (issue 10).
SENT_STATUSES: frozenset[str] = frozenset({"Outreach Sent", "Survey Sent", "Reminder Sent"})
SCHEDULED_STATUSES: frozenset[str] = frozenset(
    {"Scheduled", "Data Collected", "No Show", "Qualified (screener)"}
)

#: The workspace participants-table columns (issue 51; the approved
#: column law of 2026-11-22). One list per recruit-flow variant and the
#: order is the contract the template and the recruit command carry.
#: Checked by ``participant_header_issues`` and the repo-level recruit
#: enforcement module; the funnel table below is a different table.
PARTICIPANT_COLUMNS: dict[str, tuple[str, ...]] = {
    "internal": (
        "participant id",
        "name",
        "role/segment",
        "team/org area",
        "source (org-chart path)",
        "screener result",
        "status",
        "consent-to-record",
        "DM sent (date)",
        "notes",
    ),
    "external": (
        "participant id",
        "name/pseudonym",
        "contact",
        "source (panel/channel)",
        "screener result",
        "status",
        "consent-to-record",
        "incentive status",
        "DM sent (date)",
        "prep note",
        "notes",
    ),
}

#: The locked status vocabulary for the workspace participants table
#: (issue 51). ``withdrawn`` is reachable from any status.
PARTICIPANT_STATUSES: tuple[str, ...] = (
    "identified",
    "screened",
    "invited",
    "scheduled",
    "completed",
    "incentive-sent",
    "withdrawn",
)

#: Gate columns per variant and status (issue 51): a status may not
#: advance while its gate columns are empty on the row.
#: ``incentive-sent`` additionally requires the row to already sit at
#: ``completed``; ``withdrawn`` has no gate and is always allowed.
PARTICIPANT_STATUS_GATES: dict[str, dict[str, tuple[str, ...]]] = {
    "internal": {
        "screened": ("screener result",),
        "invited": ("source (org-chart path)",),
        "scheduled": ("DM sent (date)",),
        "completed": ("consent-to-record",),
    },
    "external": {
        "screened": ("screener result",),
        "invited": ("contact",),
        "scheduled": ("DM sent (date)",),
        "completed": ("consent-to-record",),
    },
}

#: The fixed table shape (issue 10). Order is part of the contract.
TABLE_COLUMNS: tuple[str, ...] = (
    "Internal users",
    "In-product accounts",
    "In-product users",
    "Other accounts",
    "Other users",
)
TABLE_ROWS: tuple[str, ...] = (
    "Fit",
    "Looked at",
    "Allowed",
    "Not allowed",
    "Sent",
    "Bounced",
    "Scheduled",
    "Attempted % of fit",
    "Recruited % of fit",
)

#: Wave-tab headers the command must match when building the sheet.
DEFAULT_WAVE_TAB_HEADERS: tuple[str, ...] = (
    "Account Name",
    "First name",
    "Last name",
    "Recipient",
    "Email Sent",
    "Booking link",
    "Email Source",
)

#: Booking-page URL match when config ``recruit.booking_url_regex`` is
#: empty. Organizations list their real booking domain in config. The
#: Google appointment-schedule shapes are the share link Google's
#: ``Copy link`` emits (``calendar.app.google/<id>``) and the underlying
#: booking page it resolves to; before the fix (issue 50) the pattern
#: carried a hyphenated shape that matches nothing Google emits, so a
#: real appointment link was refused and a redirect-wrapped URL could
#: end up in the send instead.
DEFAULT_BOOKING_URL_RE = (
    r"^https://(calendly\.com/|savvycal\.com/|cal\.com/|cal\.so/|"
    r"outlook\.office\.com/bookwithme/|bookings\.office\.com/|"
    r"calendar\.google\.com/calendar/u/\d+/appraisal/|"
    r"calendar\.google\.com/calendar/u/\d+/appointments/schedules/|"
    r"calendar\.app\.google/)"
)

#: The recruitment pipeline (issue 50): the ordered deterministic stages
#: the recruit flow moves a participant through. The config key
#: ``recruitment.pipeline`` carries the ordered list; the default is the
#: shipped flow below. Every stage name names a deterministic check or
#: action (no model call in the stage machinery itself); an unknown name
#: is a usage error (exit 2) through ``--pipeline-check`` and
#: :func:`resolve_pipeline`.
DEFAULT_PIPELINE: tuple[str, ...] = (
    "identify",
    "screen",
    "suppress",
    "invite",
    "schedule",
    "send",
)

#: The known stage names and the deterministic check/action each one
#: names (issue 50). One line each; ``--pipeline-check`` prints them.
KNOWN_STAGES: dict[str, str] = {
    "identify": (
        "identify: name the target rows (funnel.fit persona, roster adds "
        "through roster_apply.py; source_contacts.py on the external flow)"
    ),
    "screen": (
        "screen: the screener result records fit before a row may advance "
        "(the workspace screened gate; source_contacts.py filters)"
    ),
    "suppress": (
        "suppress: the three deterministic never-contact checks below run "
        "before any invite (recruit_funnel.py --preflight reports the counts)"
    ),
    "invite": (
        "invite: the merged draft block through the invited gate (drafts "
        "only; recruit_send.py merges one message per recipient)"
    ),
    "schedule": (
        "schedule: the booking or hold lands and the DM sent (date) stamp "
        "advances the row per the gate map (calendar_prep.py picks holds)"
    ),
    "send": (
        "send: the researcher's real send through the send script's real-send "
        "flag (one email per recipient; the agent itself never sends)"
    ),
}

#: The workspace and roster statuses the suppress stage never re-contacts
#: (issue 50). ``completed``, ``incentive-sent``, and ``withdrawn`` come
#: from the locked workspace participants vocabulary; ``cancelled`` is
#: the roster's declined status. Compared case-insensitively.
NEVER_RECONTACT_STATUSES: frozenset[str] = frozenset(
    {"completed", "incentive-sent", "withdrawn", "cancelled"}
)

#: The suppress-stage check names, in check order (issue 50). A row that
#: matches more than one check counts under the first, so the counts sum
#: to the suppressed total.
SUPPRESSION_CHECKS: tuple[str, ...] = ("status law", "bounce", "suppression list")

#: The skip reason the command marks into a suppressed wave row's Email
#: Sent cell (blank Recipient), per the existing skip law.
SUPPRESSION_SKIP_PREFIX = "skip: suppressed"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.\-]+", re.UNICODE)


def scrub(text: str) -> str:
    """Last-resort redaction: no email address ever reaches stdout."""
    return _EMAIL_RE.sub("[email]", text)


def _load_json(path_value: str, what: str) -> object:
    try:
        return _util.read_json_arg(path_value, what)
    except _util.JsonReadError as exc:
        if exc.kind == "notfound":
            raise _Usage(f"{what} not found: {exc.path}") from exc.exc
        raise _Usage(f"{what} cannot be read ({exc.path}): {exc.exc}") from exc.exc


class _Usage(Exception):
    pass


def _num(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cell(total: int, this_wave: int) -> str:
    return f"{max(total, 0)} ({min(max(this_wave, 0), max(total, 0))})"


def _pct_pair(total: int, this_wave: int, fit: int) -> str:
    if fit <= 0:
        return "- (-)"
    this = this_wave if this_wave <= total else total
    return f"{round(100.0 * total / fit)}% ({round(100.0 * this / fit)}%)"


def wave_name(spec: dict, funnel_data: dict | None, wave_flag: str) -> str:
    """The this-wave tab: the flag, else the last recorded tab, else the
    last tab present in the data, else ``Wave 1``."""
    if wave_flag:
        return wave_flag
    funnel = spec.get("funnel") if isinstance(spec.get("funnel"), dict) else {}
    tabs = [str(t) for t in (funnel.get("tabs") or []) if str(t).strip()]
    if not tabs and funnel_data:
        tabs = [str(t) for t in ((funnel_data.get("tabs") or {}).keys())]
    return tabs[-1] if tabs else "Wave 1"


def _rows_by_tab(funnel_data: dict) -> dict[str, list[dict]]:
    tabs = funnel_data.get("tabs")
    if not isinstance(tabs, dict):
        return {}
    return {
        str(name): [row for row in (payload or {}).get("rows", []) if isinstance(row, dict)]
        for name, payload in tabs.items()
    }


def _skips_by_tab(funnel_data: dict) -> dict[str, list[dict]]:
    tabs = funnel_data.get("tabs")
    if not isinstance(tabs, dict):
        return {}
    return {
        str(name): [row for row in (payload or {}).get("skips", []) if isinstance(row, dict)]
        for name, payload in tabs.items()
    }


def _row_email(row: dict) -> str:
    return str(row.get("email") or row.get("recipient") or "").strip().lower()


def _identity(row: dict) -> tuple[str, str]:
    return (str(row.get("account") or "").strip(), str(row.get("first_name") or "").strip())


def build_table(
    spec: dict,
    config: dict | None = None,
    funnel_data: dict | None = None,
    wave: str | None = None,
) -> tuple[str, dict]:
    """Render the fixed recruitment table under its persona caption; pure.

    The caption line names the target persona (``funnel.fit.basis`` with
    its ``as_of``; ``not recorded yet`` without; issue 51). The Not
    allowed row includes the suppress stage's counts (issue 50).
    Returns ``(markdown_table, numbers)``; ``numbers`` carries every
    computed total (plus the suppressed counts per check) so preflight
    and tests can assert on values without re-parsing the table.
    """
    config = config if isinstance(config, dict) else {}
    funnel = spec.get("funnel") if isinstance(spec.get("funnel"), dict) else {}
    fit = funnel.get("fit") if isinstance(funnel.get("fit"), dict) else {}
    roster = [row for row in (spec.get("roster") or []) if isinstance(row, dict)]
    internal = [row for row in roster if str(row.get("channel") or "internal") == "internal"]
    external = [row for row in roster if str(row.get("channel") or "internal") == "external"]

    data_tabs = _rows_by_tab(funnel_data or {})
    skip_tabs = _skips_by_tab(funnel_data or {})
    wave_tab = wave_name(spec, funnel_data, wave or "")
    wave_rows = data_tabs.get(wave_tab, [])
    wave_skips = skip_tabs.get(wave_tab, [])
    all_rows = [row for rows in data_tabs.values() for row in rows]

    excluded = (funnel_data or {}).get("excluded") if isinstance((funnel_data or {}).get("excluded"), dict) else {}
    not_allowed_sheet = sum(_num(v) for v in excluded.values())
    sheet_looked_override = (funnel_data or {}).get("looked_at")
    sheet_looked_override = sheet_looked_override if isinstance(sheet_looked_override, dict) else {}
    suppressed = {
        "all": suppression_counts(spec, funnel_data or {}, config=config),
        "wave": suppression_counts(spec, funnel_data or {}, config=config, wave_tab=wave_tab),
    }

    sent_rows = [row for row in all_rows if str(row.get("email_sent") or "").strip() and not str(row.get("email_sent") or "").strip().lower().startswith("skip")]
    wave_sent = [row for row in wave_rows if str(row.get("email_sent") or "").strip() and not str(row.get("email_sent") or "").strip().lower().startswith("skip")]
    wave_skip_sent = [row for row in wave_skips if str(row.get("reason") or "").strip()]
    bounced_all = [row for row in all_rows if " (bounced)" in str(row.get("email_sent") or "")]
    bounced_wave = [row for row in wave_rows if " (bounced)" in str(row.get("email_sent") or "")]
    booked_all = [row for row in all_rows if str(row.get("booked") or "").strip().lower() in ("true", "yes", "1")]
    booked_wave = [row for row in wave_rows if str(row.get("booked") or "").strip().lower() in ("true", "yes", "1")]

    def sent_status_count(rows: list[dict]) -> int:
        return sum(1 for row in rows if str(row.get("status") or "") in SENT_STATUSES)

    def scheduled_status_count(rows: list[dict]) -> int:
        return sum(1 for row in rows if str(row.get("status") or "") in SCHEDULED_STATUSES)

    internal_total = len(internal)
    external_total = len(external)
    other_accounts_total = len({str(row.get("company") or "").strip() for row in external if str(row.get("company") or "").strip()})
    fit_accounts = _num(fit.get("accounts"))
    fit_users = _num(fit.get("users"))

    sheet_looked = len(all_rows) + len(wave_skips) + not_allowed_sheet

    fit_numbers = (internal_total, fit_accounts, fit_users, other_accounts_total, external_total)
    looked = (
        internal_total,
        _num(sheet_looked_override.get("in_product_accounts")) or sheet_looked,
        _num(sheet_looked_override.get("in_product_users")) or sheet_looked,
        other_accounts_total,
        external_total,
    )
    # The suppress stage feeds Not allowed (issue 50 through issue 51):
    # the suppressed rows join the excluded totals.
    not_allowed = (
        0,
        _num(excluded.get("accounts")) + suppressed["all"]["accounts"],
        (_num(excluded.get("users")) or not_allowed_sheet) + suppressed["all"]["total"],
        0,
        0,
    )
    allowed = tuple(max(l - n, 0) for l, n in zip(looked, not_allowed))
    sent = (
        sent_status_count(internal),
        len({_identity(row)[0] for row in sent_rows if _identity(row)[0]}),
        len(sent_rows),
        0,
        sent_status_count(external),
    )
    sent_this = (
        0,
        len({_identity(row)[0] for row in wave_sent if _identity(row)[0]}),
        len(wave_sent) + len(wave_skip_sent),
        0,
        0,
    )
    bounced = (0, len({_identity(row)[0] for row in bounced_all if _identity(row)[0]}), len(bounced_all), 0, 0)
    bounced_this = (0, len({_identity(row)[0] for row in bounced_wave if _identity(row)[0]}), len(bounced_wave), 0, 0)
    scheduled = (
        scheduled_status_count(internal),
        len({_identity(row)[0] for row in booked_all if _identity(row)[0]}),
        len(booked_all),
        0,
        scheduled_status_count(external),
    )
    scheduled_this = (
        0,
        len({_identity(row)[0] for row in booked_wave if _identity(row)[0]}),
        len(booked_wave),
        0,
        0,
    )
    totals = {
        "Fit": fit_numbers,
        "Looked at": looked,
        "Allowed": allowed,
        "Not allowed": not_allowed,
        "Sent": sent,
        "Bounced": bounced,
        "Scheduled": scheduled,
    }
    this_wave = {
        "Fit": (0, 0, 0, 0, 0),
        "Looked at": (0, 0, len(wave_rows) + len(wave_skips), 0, 0),
        "Allowed": (0, 0, max(len(wave_rows) + len(wave_skips) - (len(wave_sent) + len(wave_skip_sent)), 0), 0, 0),
        "Not allowed": (0, 0, len(wave_skips) + suppressed["wave"]["total"], 0, 0),
        "Sent": sent_this,
        "Bounced": bounced_this,
        "Scheduled": scheduled_this,
    }

    basis = str(fit.get("basis") or "").strip()
    as_of = str(fit.get("as_of") or "").strip()
    if basis and as_of:
        persona_line = f"Target persona: {basis} (as of {as_of})"
    elif basis:
        persona_line = f"Target persona: {basis}"
    else:
        persona_line = "Target persona: not recorded yet"
    lines = [
        persona_line,
        "| Metric | " + " | ".join(TABLE_COLUMNS) + " |",
        "|---|---|---|---|---|---|",
    ]
    for row_name in ("Fit", "Looked at", "Allowed", "Not allowed", "Sent", "Bounced", "Scheduled"):
        cells = [_cell(t, this_wave[row_name][i]) for i, t in enumerate(totals[row_name])]
        lines.append(f"| {row_name} | " + " | ".join(cells) + " |")
    for row_name in ("Attempted % of fit", "Recruited % of fit"):
        source = sent if row_name.startswith("Attempted") else scheduled
        this_source = sent_this if row_name.startswith("Attempted") else scheduled_this
        cells = [
            _pct_pair(source[i], this_source[i], fit_numbers[i]) for i in range(len(TABLE_COLUMNS))
        ]
        lines.append(f"| {row_name} | " + " | ".join(cells) + " |")

    numbers = {
        "totals": {k: v for k, v in totals.items()},
        "this_wave": this_wave,
        "wave": wave_tab,
        "suppressed": suppressed,
    }
    table = "\n".join(lines)
    return table, numbers


def _booking_regex(config: dict | None) -> re.Pattern:
    config = config if isinstance(config, dict) else {}
    recruit = config.get("recruit") if isinstance(config.get("recruit"), dict) else {}
    pattern = str(recruit.get("booking_url_regex") or "").strip()
    if not pattern:
        return re.compile(DEFAULT_BOOKING_URL_RE)
    try:
        return re.compile(pattern)
    except re.error:
        return re.compile(DEFAULT_BOOKING_URL_RE)


def resolve_pipeline(config: dict | None = None) -> tuple[str, ...]:
    """The configured recruitment pipeline (issue 50); pure.

    Reads ``recruitment.pipeline`` (an ordered list of stage names; a
    comma-separated string is accepted too). Empty or absent returns
    :data:`DEFAULT_PIPELINE` (the shipped flow). An unknown stage name
    raises usage (exit 2 through ``main``), naming the first unknown and
    the known stages.
    """
    config = config if isinstance(config, dict) else {}
    recruitment = config.get("recruitment") if isinstance(config.get("recruitment"), dict) else {}
    stages = recruitment.get("pipeline") if isinstance(recruitment, dict) else None
    if isinstance(stages, str):
        names = [part.strip() for part in stages.split(",") if part.strip()]
    elif isinstance(stages, (list, tuple)):
        names = [str(part).strip() for part in stages if str(part).strip()]
    elif stages is None:
        names = []
    else:
        raise _Usage(f"recruitment.pipeline must be a list of stage names; got {stages!r}")
    if not names:
        return DEFAULT_PIPELINE
    unknown = [name for name in names if name not in KNOWN_STAGES]
    if unknown:
        raise _Usage(
            f"recruitment.pipeline: unknown stage {unknown[0]!r} "
            "(known stages: " + ", ".join(DEFAULT_PIPELINE) + ")"
        )
    return tuple(names)


def read_suppression_ids(path_value: str) -> list[str]:
    """The suppression-list identifiers, one per line; fail closed.

    The configured file (``recruitment.suppression_list``) must exist
    and read: a missing or unreadable file raises usage (exit 2), never
    an improvised empty list. One identifier per line (an email or an
    account id); blank lines are skipped. The plugin ships no list.
    """
    path = Path(str(path_value)).expanduser()
    if not path.is_file():
        raise _Usage(
            f"recruitment.suppression_list is configured but cannot be read: {path}"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _Usage(
            f"recruitment.suppression_list is configured but cannot be read ({path}): {exc}"
        ) from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split_ids(identifiers: list[str]) -> tuple[list[str], list[str]]:
    """Split identifiers into ``(emails, account ids)``; an ``@`` marks an email."""
    emails: list[str] = []
    accounts: list[str] = []
    for identifier in identifiers:
        raw = str(identifier).strip()
        if not raw:
            continue
        if "@" in raw:
            emails.append(raw.lower())
        else:
            accounts.append(raw)
    return emails, accounts


def _roster_hit(
    email: str, first: str, account: str, roster: list[dict], roster_emails: dict
) -> dict | None:
    """The roster row a wave row names, or None (the shared preflight match)."""
    hit = roster_emails.get(email) if email else None
    if hit is None and first:
        hit = next(
            (
                r
                for r in roster
                if str(r.get("name") or "").lower().startswith(first.lower())
                and account
                and _source.accounts_match(account, str(r.get("company") or ""))
            ),
            None,
        )
    return hit


def _suppression_context(
    spec: dict, funnel_data: dict, config: dict | None, wave_tab: str
) -> dict:
    """The precomputed match data the suppress-stage checks read; pure.

    Carries the roster (with its email index), the prior-wave bounce
    emails, the workspace-participants rows from the funnel data's
    optional ``participants`` export, and the suppression identifiers
    (the funnel data's optional ``suppression_list`` entries plus the
    configured file, which must read or the check fails closed).
    """
    roster = [row for row in (spec.get("roster") or []) if isinstance(row, dict)]
    roster_emails = {str(row.get("email") or "").strip().lower(): row for row in roster}
    prior_bounced: set[str] = set()
    for name, tab_rows in _rows_by_tab(funnel_data).items():
        if wave_tab and name == wave_tab:
            continue
        for row in tab_rows:
            email = _row_email(row)
            if email and " (bounced)" in str(row.get("email_sent") or ""):
                prior_bounced.add(email)
    raw_participants = funnel_data.get("participants")
    participants = (
        [row for row in raw_participants if isinstance(row, dict)]
        if isinstance(raw_participants, list)
        else []
    )
    raw_ids = funnel_data.get("suppression_list")
    raw_ids = [str(i) for i in raw_ids if str(i).strip()] if isinstance(raw_ids, list) else []
    config = config if isinstance(config, dict) else {}
    recruitment = config.get("recruitment") if isinstance(config.get("recruitment"), dict) else {}
    list_path = (
        str(recruitment.get("suppression_list") or "").strip()
        if isinstance(recruitment, dict)
        else ""
    )
    if list_path:
        raw_ids = raw_ids + read_suppression_ids(list_path)
    emails, accounts = _split_ids(raw_ids)
    return {
        "roster": roster,
        "roster_emails": roster_emails,
        "prior_bounced": prior_bounced,
        "participants": participants,
        "emails": emails,
        "accounts": accounts,
    }


def _suppression_hit(row: dict, email: str, context: dict) -> str | None:
    """The suppress-stage check that suppresses this wave row, or None.

    The stage guards queued rows: a row already carrying a send date is
    past the invite stage and is never a suppression candidate. For the
    remaining rows, first check wins, in :data:`SUPPRESSION_CHECKS`
    order: (1) status law: the matching roster or workspace-participants
    row sits at a never-recontact status (``completed``,
    ``incentive-sent``, ``withdrawn``, ``cancelled``; case-insensitive);
    (2) bounce: the email carries " (bounced)" on a prior wave tab;
    (3) suppression list: the email or the account id is on the
    configured list.
    """
    if str(row.get("email_sent") or "").strip():
        return None
    account, first = _identity(row)
    roster_hit = _roster_hit(email, first, account, context["roster"], context["roster_emails"])
    if (
        roster_hit is not None
        and str(roster_hit.get("status") or "").strip().lower() in NEVER_RECONTACT_STATUSES
    ):
        return "status law"
    for participant in context["participants"]:
        if str(participant.get("status") or "").strip().lower() not in NEVER_RECONTACT_STATUSES:
            continue
        contact_match = _EMAIL_RE.search(str(participant.get("contact") or ""))
        if email and contact_match and contact_match.group(0).strip().lower() == email:
            return "status law"
        name_words = str(
            participant.get("name") or participant.get("name/pseudonym") or ""
        ).strip().lower().split()
        if first and name_words and name_words[0] == first.lower():
            return "status law"
    if email and email in context["prior_bounced"]:
        return "bounce"
    if email and email in context["emails"]:
        return "suppression list"
    if account and any(_source.accounts_match(account, item) for item in context["accounts"]):
        return "suppression list"
    return None


def suppression_counts(
    spec: dict,
    funnel_data: dict,
    config: dict | None = None,
    wave_tab: str | None = None,
) -> dict:
    """The suppress-stage counts (issue 50); pure.

    Classifies every non-skip row of ``wave_tab`` (every tab when it is
    empty) against the three checks and returns one count per check plus
    ``total`` and ``accounts`` (the distinct suppressed accounts). A row
    matching more than one check counts under the first, so the counts
    sum to the total. Rows already carrying a skip reason stay out (the
    command's suppression marks among them are already sheet skips).
    Raises usage when the configured suppression-list file cannot be
    read (fail closed).
    """
    data_tabs = _rows_by_tab(funnel_data)
    skip_tabs = _skips_by_tab(funnel_data)
    context = _suppression_context(spec, funnel_data, config, wave_tab or "")
    tabs = [wave_tab] if wave_tab else list(data_tabs.keys())
    counts = {check: 0 for check in SUPPRESSION_CHECKS}
    accounts: set[str] = set()
    total = 0
    for tab in tabs:
        skips = skip_tabs.get(tab, [])
        for row in data_tabs.get(tab, []):
            account, first = _identity(row)
            already_skip = any(
                _identity(s) == (account, first) and str(s.get("reason") or "").strip()
                for s in skips
            )
            if already_skip:
                continue
            hit = _suppression_hit(row, _row_email(row), context)
            if hit:
                counts[hit] += 1
                total += 1
                if account:
                    accounts.add(account)
    return {**counts, "total": total, "accounts": len(accounts)}


def preflight(
    spec: dict,
    funnel_data: dict,
    config: dict | None = None,
    wave: str | None = None,
) -> tuple[int, list[str]]:
    """Check the target wave; pure. Returns ``(exit_code, output_lines)``.

    The suppress stage (issue 50) runs first: a row matching one of its
    three checks leaves the ready count, never blocks, and counts under
    its check. The remaining reasons (issue 10): listed twice (on more
    than one wave tab), already booked or declined, open deal, emailed
    in an earlier wave, on the do-not-contact tab, booking link not one
    value or not a booking-page URL, no rows ready. The suppressed
    counts per check print with the result on both paths; when nothing
    is left ready the gate exits 2 exactly as before.
    """
    config = config if isinstance(config, dict) else {}
    booking_re = _booking_regex(config)

    data_tabs = _rows_by_tab(funnel_data)
    skip_tabs = _skips_by_tab(funnel_data)
    wave_tab = wave_name(spec, funnel_data, wave or "")
    rows = data_tabs.get(wave_tab)
    if rows is None:
        return EXIT_BLOCKED, [
            f"BLOCK - / -: wave tab {wave_tab!r} is not in the funnel data; "
            "save the wave export first"
        ]
    context = _suppression_context(spec, funnel_data, config, wave_tab)

    deal_accounts = [str(a) for a in (funnel_data.get("open_deal_accounts") or [])]
    dnc_emails = {str(e).strip().lower() for e in (funnel_data.get("dnc_emails") or [])}
    dnc_accounts = [str(a) for a in (funnel_data.get("dnc_accounts") or [])]

    all_tabs = {name: {_row_email(row) for row in tab_rows} for name, tab_rows in data_tabs.items()}
    listing_counts: dict[str, int] = {}
    for emails in all_tabs.values():
        for email in emails:
            if email:
                listing_counts[email] = listing_counts.get(email, 0) + 1

    lines: list[str] = []
    suppressed_counts = {check: 0 for check in SUPPRESSION_CHECKS}
    ready = 0
    skips = skip_tabs.get(wave_tab, [])
    for row in rows:
        account, first = _identity(row)
        label = f"{account or '-'} / {first or '-'}"
        email = _row_email(row)
        is_skip = any(
            _identity(s) == (account, first) and str(s.get("reason") or "").strip()
            for s in skips
        )
        if is_skip:
            continue

        hit = _suppression_hit(row, email, context)
        if hit is not None:
            suppressed_counts[hit] += 1
            continue

        problems: list[str] = []
        if email and listing_counts.get(email, 0) > 1:
            problems.append("listed twice (on more than one wave tab)")
        roster_hit = _roster_hit(email, first, account, context["roster"], context["roster_emails"])
        if roster_hit is not None and (
            str(roster_hit.get("status") or "") in SCHEDULED_STATUSES
            or str(roster_hit.get("status") or "") == "Cancelled"
        ):
            problems.append("already booked or declined on the roster")
        if any(_source.accounts_match(account, deal) for deal in deal_accounts):
            problems.append("open deal account")
        if email and any(email in emails for name, emails in all_tabs.items() if name != wave_tab):
            problems.append("already emailed in an earlier wave")
        if (email and email in dnc_emails) or any(
            _source.accounts_match(account, dnc_account) for dnc_account in dnc_accounts
        ):
            problems.append("on the do-not-contact tab")

        link = str(row.get("booking_link") or "").strip()
        if not link:
            problems.append("booking link is missing")
        elif re.search(r"(;|\||,)\s*https?://", link) or len(re.findall(r"https?://", link)) > 1:
            problems.append("booking link is not one value")
        elif not booking_re.match(link):
            problems.append("booking link is not a booking-page URL")

        if problems:
            for problem in problems:
                lines.append(f"BLOCK {label}: {problem}")
        else:
            ready += 1

    counts_line = (
        f"suppressed on {wave_tab}: {suppressed_counts['status law']} status-law, "
        f"{suppressed_counts['bounce']} bounce, "
        f"{suppressed_counts['suppression list']} suppression-list"
    )
    if not any(row for row in rows):
        lines.append("BLOCK - / -: no rows ready")
    if lines:
        # Any blocked row stops the send: the gate is all-or-nothing.
        if ready == 0 and not any(line.endswith("no rows ready") for line in lines):
            lines.append("BLOCK - / -: no rows ready")
        return EXIT_BLOCKED, lines + [counts_line]
    if ready == 0:
        # Nothing blocked and nothing ready: every row was suppressed.
        return EXIT_BLOCKED, ["BLOCK - / -: no rows ready", counts_line]
    return EXIT_OK, [f"PREFLIGHT OK: {ready} rows ready on {wave_tab}", counts_line]


def business_days_between(start: date, end: date) -> int:
    """Business days (Mon-Fri) strictly after ``start`` up to ``end``."""
    if end <= start:
        return 0
    days = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def reminders(
    funnel_data: dict,
    config: dict | None = None,
    today: date | None = None,
    wave: str | None = None,
) -> list[str]:
    """Draft-only nudge list for sends with no reply after the nudge window."""
    config = config if isinstance(config, dict) else {}
    recruit = config.get("recruit") if isinstance(config.get("recruit"), dict) else {}
    nudge_after = _num(recruit.get("nudge_after_days")) or 2
    today = today or date.today()
    data_tabs = _rows_by_tab(funnel_data)
    lines: list[str] = []
    for tab, rows in data_tabs.items():
        if wave and tab != wave:
            continue
        for row in rows:
            sent_raw = str(row.get("email_sent") or "").strip()
            if not sent_raw or sent_raw.lower().startswith("skip") or " (bounced)" in sent_raw:
                continue
            try:
                sent = date.fromisoformat(sent_raw.split(" ")[0])
            except ValueError:
                continue
            waited = business_days_between(sent, today)
            if waited >= nudge_after:
                lines.append(
                    f"NUDGE {tab}: {_identity(row)[0] or '-'} / {_identity(row)[1] or '-'} "
                    f"- sent {sent.isoformat()}, {waited} business days with no reply"
                )
    if lines:
        lines.append("")
        lines.append(
            "One shorter follow-up per person (draft only; never send). Keep the "
            "booking link in the merge column: "
            '"Hey <first name>, following up once on my note about <study title>. '
            'If none of the times work, send a few that do."'
        )
    else:
        lines.append(f"No nudges due (window: {nudge_after} business days).")
    return lines


def check_draft_v1(path_value: str) -> tuple[int, list[str]]:
    """V1: the draft keeps the merge tokens and holds no ``http``."""
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise _Usage(f"check-draft file not found: {path}")
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    if "{{First name}}" not in text:
        problems.append("missing the {{First name}} merge token")
    if "{{Booking link}}" not in text:
        problems.append("missing the {{Booking link}} merge token")
    if "http" in text.lower():
        problems.append(
            "draft body contains http; mail tools that rewrite links would "
            "redirect it - keep the link in the merge column only"
        )
    if problems:
        return EXIT_V1, ["V1 FAIL: " + p for p in problems]
    return EXIT_OK, ["V1 OK: draft keeps {{First name}} and {{Booking link}}, no http"]


# ---------------------------------------------------------------------------
# workspace participants-table enforcement (issue 51): additive checks.
# Pure helpers for the recruit flow and the repo-level enforcement module;
# nothing in run(), build_table(), preflight(), or reminders() calls them,
# so every existing output stays byte-identical.
# ---------------------------------------------------------------------------


def participant_header_issues(header: list, variant: str) -> list[str]:
    """Compare a participants-table header against the approved columns.

    ``header`` holds the header row's cell values (raw; compared
    stripped and case-insensitively) and ``variant`` is ``internal`` or
    ``external``. Returns one line per problem: a missing approved
    column, a duplicated approved column, an approved column out of
    order, an unrecognized extra column, or an unknown variant. An
    empty list means the header matches the approved set.
    """
    approved = PARTICIPANT_COLUMNS.get(str(variant).strip().lower())
    if approved is None:
        return [f"participant columns: unknown variant {variant!r} (use internal or external)"]
    approved_lower = [name.lower() for name in approved]
    cells = [str(cell).strip().lower() for cell in header if str(cell).strip()]
    problems: list[str] = []
    for name, low in zip(approved, approved_lower):
        if low not in cells:
            problems.append(f"participant columns: missing {name!r} ({variant})")
    counts: dict[str, int] = {}
    for cell in cells:
        if cell in approved_lower:
            counts[cell] = counts.get(cell, 0) + 1
    for name in sorted(name for name, count in counts.items() if count > 1):
        problems.append(f"participant columns: duplicate column {name!r} ({variant})")
    present = [low for low in approved_lower if low in cells]
    deduped = []
    for cell in cells:
        if cell in approved_lower and cell not in deduped:
            deduped.append(cell)
    if present != deduped:
        problems.append(f"participant columns: approved columns out of order ({variant})")
    for name in (cell for cell in cells if cell not in approved_lower):
        problems.append(f"participant columns: unrecognized extra column {name!r} ({variant})")
    return problems


def participant_status_issue(status: str) -> str:
    """One line when ``status`` is outside the locked vocabulary, else ``\"\"``."""
    if str(status).strip().lower() in PARTICIPANT_STATUSES:
        return ""
    return f"participant status: {status!r} is outside the locked vocabulary"


def participant_gate_lines(row: dict, target_status: str, variant: str) -> list[str]:
    """Status-gate check for one participants-table row; pure.

    ``row`` maps the approved column names to their cell values,
    ``target_status`` is the status the row wants to advance to, and
    ``variant`` is ``internal`` or ``external``. A status may not
    advance while its gate columns are empty on the row;
    ``completed`` needs ``consent-to-record`` = yes and
    ``incentive-sent`` needs the row already ``completed``.
    Withdrawn is checked first: it returns an empty list before the
    variant check, and the variant is checked for gated statuses;
    statuses outside the vocabulary pass through unchecked, and an
    unknown variant is reported for gated statuses, never silently
    passed. Returns one ``GATE`` line per violated gate; an empty list
    means the advance is allowed.
    """
    target = str(target_status).strip().lower()
    if target == "withdrawn" or target not in PARTICIPANT_STATUSES:
        return []
    gates = PARTICIPANT_STATUS_GATES.get(str(variant).strip().lower())
    if gates is None:
        return [f"participant gates: unknown variant {variant!r} (use internal or external)"]
    problems: list[str] = []
    if target == "incentive-sent" and str(row.get("status") or "").strip().lower() != "completed":
        problems.append("GATE incentive-sent: the row is not at completed")
    for column in gates.get(target, ()):
        value = str(row.get(column) or "").strip()
        if not value:
            problems.append(f"GATE {target}: {column} is empty")
        elif column == "consent-to-record" and value.lower() != "yes":
            problems.append(f"GATE {target}: consent-to-record is not yes")
    return problems


def pipeline_report(config: dict | None = None) -> tuple[int, str]:
    """``--pipeline-check`` output (issue 50); pure. Never writes.

    Prints the resolved stage list, one deterministic action line per
    stage, and the suppression-list state. An unknown stage name or an
    unreadable configured suppression-list file raises usage (exit 2
    through ``main``), fail closed.
    """
    stages = resolve_pipeline(config)
    lines = ["pipeline: " + " -> ".join(stages)]
    lines.extend(f"- {KNOWN_STAGES[stage]}" for stage in stages)
    config = config if isinstance(config, dict) else {}
    recruitment = config.get("recruitment") if isinstance(config.get("recruitment"), dict) else {}
    list_path = (
        str(recruitment.get("suppression_list") or "").strip()
        if isinstance(recruitment, dict)
        else ""
    )
    if list_path:
        identifiers = read_suppression_ids(list_path)
        emails, accounts = _split_ids(identifiers)
        lines.append(
            f"suppression list: {len(identifiers)} identifiers from {list_path} "
            f"({len(emails)} email, {len(accounts)} account id)"
        )
    else:
        lines.append("suppression list: none configured")
    return EXIT_OK, "\n".join(lines) + "\n"


def run(args: dict[str, str], config: dict | None = None) -> tuple[int, str]:
    """One CLI invocation; returns ``(exit_code, stdout_text)``. Never writes."""
    check_draft = str(args.get("check_draft") or "").strip()
    if check_draft:
        v1_code, v1_lines = check_draft_v1(check_draft)
        return v1_code, "\n".join(v1_lines) + "\n"

    if args.get("pipeline_check"):
        return pipeline_report(config)

    spec_value = str(args.get("spec") or "").strip()
    if not spec_value:
        raise _Usage("--spec <path.spec.json> is required")
    spec = _load_json(spec_value, "spec")
    if not isinstance(spec, dict):
        raise _Usage("spec must be a JSON object")

    funnel_data = None
    if str(args.get("funnel_data") or "").strip():
        funnel_data = _load_json(str(args["funnel_data"]), "funnel data")
        if not isinstance(funnel_data, dict):
            raise _Usage("funnel data must be a JSON object")

    wave = str(args.get("wave") or "").strip()
    out_lines: list[str] = []
    table, _numbers = build_table(spec, config=config, funnel_data=funnel_data, wave=wave)
    out_lines.append(table)

    code = EXIT_OK
    if args.get("preflight"):
        if funnel_data is None:
            out_lines.append("")
            out_lines.append(
                "BLOCK - / -: preflight needs the funnel data; save the wave export "
                "to JSON and pass --funnel-data"
            )
            code = EXIT_BLOCKED
        else:
            pre_code, pre_lines = preflight(spec, funnel_data, config=config, wave=wave)
            out_lines.append("")
            out_lines.extend(pre_lines)
            code = pre_code
    elif args.get("reminder"):
        today_value = str(args.get("today") or "").strip()
        today = date.fromisoformat(today_value) if today_value else None
        out_lines.append("")
        out_lines.extend(reminders(funnel_data, config=config, today=today, wave=wave))
    else:
        funnel = spec.get("funnel") if isinstance(spec.get("funnel"), dict) else {}
        tabs = [str(t) for t in (funnel.get("tabs") or []) if str(t).strip()]
        out_lines.append("")
        out_lines.append(
            f"wave: {wave_name(spec, funnel_data, wave)}; recorded tabs: "
            + (", ".join(tabs) if tabs else "none yet")
        )
    return code, scrub("\n".join(out_lines)) + "\n"


MCP_SURFACE = {
    "description": (
        "recruit_funnel.py: print the fixed nine-row recruitment funnel table, "
        "run the wave preflight (BLOCK lines for repeat recruits, suppressed "
        "counts per suppress-stage check), draft nudge reminders, check a V1 "
        "draft, or resolve the configured recruitment pipeline. Computes "
        "only; nothing is sent."),
    "flags": [
        {"name": "spec", "flag": "--spec", "type": "string",
         "help": "path to the study spec JSON (required unless check_draft)"},
        {"name": "wave", "flag": "--wave", "type": "string",
         "help": "wave name for the this-wave columns"},
        {"name": "funnel_data", "flag": "--funnel-data", "type": "string",
         "help": "path to the funnel JSON export"},
        {"name": "check_draft", "flag": "--check-draft", "type": "string",
         "help": "path to a V1 draft to check"},
        {"name": "today", "flag": "--today", "type": "string",
         "help": "today as YYYY-MM-DD (defaults to the real clock)"},
    ],
    "switches": [
        {"name": "preflight", "flag": "--preflight", "type": "boolean"},
        {"name": "status", "flag": "--status", "type": "boolean"},
        {"name": "reminder", "flag": "--reminder", "type": "boolean"},
        {"name": "pipeline_check", "flag": "--pipeline-check", "type": "boolean"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--print-mcp-surface":
        print(json.dumps(MCP_SURFACE))
        return EXIT_OK
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK

    flags: dict[str, str] = {}
    index = 0
    flag_names = {
        "--spec": "spec",
        "--wave": "wave",
        "--funnel-data": "funnel_data",
        "--check-draft": "check_draft",
        "--today": "today",
    }
    switches = {
        "--preflight": "preflight",
        "--status": "status",
        "--reminder": "reminder",
        "--pipeline-check": "pipeline_check",
    }
    while index < len(args):
        token = args[index]
        if token in flag_names:
            if index + 1 >= len(args):
                print(f"recruit_funnel: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            flags[flag_names[token]] = args[index + 1]
            index += 2
            continue
        if token in switches:
            flags[switches[token]] = "1"
            index += 1
            continue
        print(f"recruit_funnel: unknown argument {token!r}", file=sys.stderr)
        return EXIT_USAGE

    config = None
    if flags.get("pipeline_check"):
        # The one CLI path that reads the org config (issue 50): the
        # pipeline stage list and the suppression-list path live there.
        try:
            from lib.config import load_config  # PyYAML: the documented exception

            config = load_config()
        except Exception as exc:
            print(
                f"recruit_funnel: the org config cannot load for --pipeline-check: {exc}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    try:
        code, output = run(flags, config=config)
    except _Usage as exc:
        print(f"recruit_funnel: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return code


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

TABLE_SPEC: dict = {
    "history": "Churn interviews follow the Q3 renewal miss.",
    "decision": "Which renewal play do we fix first?",
    "hypotheses": [{"label": "H1", "text": "Renewal admins never see the usage page."}],
    "research_questions": ["When do renewal admins check usage?"],
    "study_title": "Renewal admin interviews",
    "method_key": "interview",
    "channel": "external",
    "roster": [
        {"name": "Ada Example", "email": "ada@example.com", "status": "Outreach Sent", "channel": "internal"},
        {"name": "Rook Example", "email": "rook@example.com", "status": "Scheduled", "channel": "internal"},
        {"name": "Sol Store", "email": "sol@example-retail.example.com", "status": "Outreach Sent",
         "channel": "external", "company": "Example Retail"},
        {"name": "Kit Store", "email": "kit@example-retail.example.com", "status": "Data Collected",
         "channel": "external", "company": "Example Retail"},
    ],
    "funnel": {
        "sheet": "sheet-123",
        "tabs": ["Wave 1", "Wave 2"],
        "fit": {"users": 120, "accounts": 30, "as_of": "2026-11-01", "basis": "product analytics cohort"},
    },
}

FUNNEL_DATA: dict = {
    "tabs": {
        "Wave 1": {
            "rows": [
                {"account": "Box", "first_name": "Ada", "email": "ada-w1@box.example.com",
                 "email_sent": "2026-11-02", "booking_link": "https://calendly.com/team/renewal-60"},
                {"account": "Dropbox", "first_name": "Dee", "email": "dee@dropbox.example.com",
                 "email_sent": "2026-11-03 (bounced)", "booking_link": "https://calendly.com/team/renewal-60"},
                {"account": "Okta", "first_name": "Rae", "email": "rae@okta.example.com",
                 "email_sent": "2026-11-04", "booking_link": "https://calendly.com/team/renewal-60",
                 "booked": "true"},
            ],
            "skips": [
                {"account": "Gadget", "first_name": "No", "reason": "skip: no email key"},
            ],
        },
        "Wave 2": {
            "rows": [
                {"account": "Box", "first_name": "Bo", "email": "bo@box.example.com",
                 "email_sent": "2026-11-06", "booking_link": "https://calendly.com/team/renewal-60"},
            ],
            "skips": [],
        },
    },
    "excluded": {"accounts": 4, "users": 9},
    "open_deal_accounts": ["Retail Giant"],
    "dnc_emails": ["ghost@example.com"],
    "dnc_accounts": ["Do Not Call Corp"],
}


if __name__ == "__main__":
    raise SystemExit(main())
