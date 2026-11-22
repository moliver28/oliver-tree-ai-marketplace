#!/usr/bin/env python3
"""MVP recruitment email send from the workspace participants table (W5).

Reads the approved participants table (the
``templates/workspace/recruitment/participants.md`` shape), merges one
message per recipient from a workspace merge template, and sends it
through stdlib ``smtplib``. The default mode is a dry run: the merged
messages print and nothing changes -- no send, no stamp, no write. A
real send needs the explicit ``--send`` flag plus a configured SMTP
account (org config ``recruit.email.*`` in the user's gitignored
``config/org.yaml``, or the ``UXR_RECRUIT_*`` env fallbacks).

State machine (recorded in the W5 decision note): a row is sendable when
it sits at ``invited`` in the external table, its outreach gate column
(``contact``) is non-empty, its ``DM sent (date)`` cell is empty (never
double-send), and the ``contact`` cell carries an email address. On send
success the row's ``DM sent (date)`` is stamped and the status advances
to ``scheduled`` -- legal per the shipped gate map, because the stamp
satisfies the ``scheduled`` gate. A failed row gets no stamp and stays
at ``invited``. Rows at other statuses are reported as skipped, with the
reason named; a row whose gate columns are empty is never emailed.

One email per recipient: every message carries exactly one ``To`` header
and never a ``Cc`` or ``Bcc``; a duplicate recipient address sends once
and every later row with that address is reported as a duplicate skip.
Per-row report lines carry id, status, and outcome; contact values are
masked by default and shown only with ``--show-contacts``.

The gate and column law is imported from ``scripts/recruit_funnel.py``
(the same approved column sets, the locked seven-value status
vocabulary, and the per-variant gate map). Internal-flow rows carry no
approved address column, so the MVP send serves the external table and
reports internal rows in one summary line.

Merge template: a workspace-local file. Its first non-empty line must
start with ``Subject: ``; everything after it is the body. A ``{{token}}``
names an approved column: lowercased, with every run of non-alphanumeric
characters read as one underscore (``name/pseudonym`` becomes
``{{name_pseudonym}}``). A token matching no approved column stops the
run before anything is sent.

Exit codes: 0 full success (a dry run, or a real send with no failed
rows), 1 a real send failed for at least one row, 2 usage or unreadable
input (missing files, drifted table header, unknown template token, no
SMTP account configured for ``--send``).

Usage::

    python scripts/recruit_send.py --participants <participants.md>
        --template <merge-template.md> [--send] [--show-contacts]
        [--today <YYYY-MM-DD>]
"""

from __future__ import annotations

import os
import re
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

if str(PLUGIN_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from scripts.recruit_funnel import (  # noqa: E402  (the shared recruit law)
    PARTICIPANT_COLUMNS,
    participant_gate_lines,
    participant_header_issues,
    participant_status_issue,
    scrub as _scrub,
    _EMAIL_RE,
)
from lib.util import force_utf8_stdio as _force_utf8_stdio  # noqa: E402  (shared plumbing)

EXIT_OK = 0
EXIT_SEND_FAIL = 1
EXIT_USAGE = 2

SEND_FROM_STATUS = "invited"   # the only status the send advances
SEND_TO_STATUS = "scheduled"   # the gate map: scheduled needs DM sent (date)
SEND_VARIANT = "external"      # the MVP send path serves the external table

_SMTP_TIMEOUT_SECONDS = 30

_TOKEN_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")

#: ``recruit.email`` config keys and their env fallback names. Values
#: never live in a repo file; the shipped example carries placeholders only.
#: Each env name is computed as the prefix plus the config key uppercased,
#: except two keys with short names.
_ENV_PREFIX = "UXR_RECRUIT_"
_ENV_SHORT_NAMES = {
    "from_address": "FROM",
    "template_path": "TEMPLATE",
}
ENV_FALLBACKS: dict[str, str] = {
    key: _ENV_PREFIX + _ENV_SHORT_NAMES.get(key, key.upper())
    for key in (
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "from_address",
        "use_tls",
        "template_path",
    )
}


class _Usage(Exception):
    """Usage or unreadable-input error; the caller prints it and exits 2."""


def column_token(name: str) -> str:
    """The merge token for one approved column name."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def load_send_settings(environ: dict | None = None) -> tuple[dict, str]:
    """SMTP settings: org config first (``recruit.email.*``), env as fallback.

    Returns ``(values, source)``. The config layer reads through
    ``lib.config.load_config`` (the documented PyYAML exception); when the
    config is absent, unreadable, or PyYAML is missing, the env fallbacks
    carry the account. Values never come from a repo file.
    """
    env = os.environ if environ is None else environ
    values: dict[str, str | None] = {key: None for key in ENV_FALLBACKS}
    from_config = False
    try:
        from lib.config import load_config  # PyYAML: the documented exception

        recruit = load_config().get("recruit")
        email = recruit.get("email") if isinstance(recruit, dict) else None
        if isinstance(email, dict):
            for key in values:
                raw = email.get(key)
                if raw is not None and str(raw).strip() != "":
                    values[key] = str(raw).strip()
                    from_config = True
    except Exception:  # config absent or unreadable: the env fallbacks apply
        pass
    from_env = False
    for key, name in ENV_FALLBACKS.items():
        if values[key] is None:
            raw = env.get(name)
            if raw is not None and raw.strip() != "":
                values[key] = raw.strip()
                from_env = True
    if from_config and from_env:
        source = "config recruit.email.* + env"
    elif from_config:
        source = "config recruit.email.*"
    elif from_env:
        source = "env"
    else:
        source = "none"
    return values, source


def split_cells(line: str) -> list[str]:
    """Split one Markdown table row into cells; ``\\|`` stays inside a cell."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_delimiter(line: str) -> bool:
    body = line.strip().replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
    return line.lstrip().startswith("|") and body == ""


def parse_tables(text: str) -> list[dict]:
    """Parse every Markdown table block; one entry per block.

    Each entry carries ``header`` (split cells), ``rows`` (one dict per
    data row: ``cells`` and the ``line`` index into ``text.splitlines()``),
    and ``header_line``. A block starts at the first ``|`` line and ends
    at the first following non-``|`` line.
    """
    lines = text.splitlines()
    tables: list[dict] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        header = split_cells(lines[index])
        cursor = index + 1
        if cursor < len(lines) and _is_delimiter(lines[cursor]):
            cursor += 1  # the GFM delimiter row; data rows start after it
        rows = []
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            rows.append({"cells": split_cells(lines[cursor]), "line": cursor})
            cursor += 1
        tables.append({"header": header, "rows": rows, "header_line": index})
        index = cursor
    return tables


def detect_variant(header: list[str]) -> tuple[str | None, list[str]]:
    """Match a header against the approved column sets.

    Returns ``(variant, issues)``: the variant whose approved set matches
    exactly, or ``None`` with the checker's drift lines for both variants.
    """
    for variant in ("external", "internal"):
        issues = participant_header_issues(header, variant)
        if not issues:
            return variant, []
    issues = participant_header_issues(header, "external")
    issues += participant_header_issues(header, "internal")
    return None, issues


def row_map(header: list[str], cells: list[str], variant: str = SEND_VARIANT) -> tuple[dict, bool]:
    """Map one row's cells onto the approved column names; pure.

    Keys are the canonical approved names (``DM sent (date)`` keeps its
    capitals), so a row dict reads exactly like the ones the recruit gate
    helpers take. Returns ``(row, has_extra_cells)``. Short rows pad to
    the header width with empty cells; a row with more non-empty cells
    than the header is flagged (the caller never sends it).
    """
    width = len(header)
    padded = list(cells[:width]) + [""] * (width - len(cells))
    extras = [cell for cell in cells[width:] if cell]
    approved_lower = [name.lower() for name in PARTICIPANT_COLUMNS[variant]]
    keys = [
        next(
            (PARTICIPANT_COLUMNS[variant][i] for i, low in enumerate(approved_lower)
             if low == cell.strip().lower()),
            cell.strip().lower(),
        )
        for cell in header
    ]
    row = {keys[i]: padded[i] for i in range(min(len(keys), width))}
    return row, bool(extras)


def evaluate_row(row: dict) -> dict:
    """One external row's send decision; pure.

    Returns ``{"action": "send" | "skip" | "block", "reason": str}`` and,
    for a sendable row, ``address``. The gate check runs from the row
    (never from the roster), per the recruit status-gate law.
    """
    status_raw = str(row.get("status") or "")
    vocab_issue = participant_status_issue(status_raw)
    if vocab_issue:
        return {"action": "skip", "reason": vocab_issue}
    status = status_raw.strip().lower()
    if status == "withdrawn":
        return {"action": "skip", "reason": "withdrawn; the row is never contacted again"}
    if status != SEND_FROM_STATUS:
        return {
            "action": "skip",
            "reason": f"status is {status!r}; the send path advances {SEND_FROM_STATUS!r} rows",
        }
    if str(row.get("DM sent (date)") or "").strip():
        return {"action": "skip", "reason": "DM sent (date) is already stamped; never double-send"}
    gate_lines = participant_gate_lines(row, SEND_FROM_STATUS, SEND_VARIANT)
    if gate_lines:
        return {
            "action": "block",
            "reason": "; ".join(gate_lines) + "; the row is never emailed with an empty gate",
        }
    match = _EMAIL_RE.search(str(row.get("contact") or ""))
    if not match:
        return {
            "action": "skip",
            "reason": "no email address in contact (a Slack-only contact is not emailed)",
        }
    return {"action": "send", "reason": "", "address": match.group(0)}


def plan_sends(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Decide every row; pure. Returns ``(plan, skipped)``.

    ``plan`` holds sendable rows in table order, one per recipient: the
    first row for an address sends, and every later row with the same
    address is a duplicate skip (one email per recipient).
    """
    plan: list[dict] = []
    skipped: list[dict] = []
    claimed: dict[str, str] = {}
    for entry in entries:
        decision = evaluate_row(entry["row"])
        if decision["action"] != "send":
            skipped.append({**entry, "action": decision["action"], "reason": decision["reason"]})
            continue
        address = decision["address"].lower()
        first_id = claimed.get(address)
        if first_id is not None:
            skipped.append({
                **entry,
                "action": "skip",
                "reason": f"duplicate recipient; already planned on row {first_id}",
            })
            continue
        claimed[address] = str(entry["row"].get("participant id") or "-")
        plan.append({**entry, "address": decision["address"]})
    return plan, skipped


def parse_template(text: str, variant: str) -> tuple[str, str]:
    """Split a merge template into ``(subject, body)``; fail closed.

    The first non-empty line must start with ``Subject: ``. Every
    ``{{token}}`` must name an approved column of the variant; an unknown
    token raises before anything is merged or sent.
    """
    valid = {column_token(column) for column in PARTICIPANT_COLUMNS[variant]}
    lines = text.splitlines()
    subject = ""
    body_start = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.strip().lower().startswith("subject:"):
            subject = line.strip()[len("Subject:"):].strip()
            body_start = index + 1
            break
        raise _Usage(
            "template must start with a 'Subject: ' line; found "
            f"{line.strip()[:40]!r}"
        )
    if body_start is None:
        raise _Usage("template is empty; it needs a 'Subject: ' line")
    body = "\n".join(lines[body_start:])
    if body.startswith("\n"):
        body = body[1:]
    used = set(_TOKEN_RE.findall(subject)) | set(_TOKEN_RE.findall(body))
    unknown = sorted(used - valid)
    if unknown:
        named = ", ".join("{{" + token + "}}" for token in unknown)
        raise _Usage(f"template tokens match no approved column: {named}")
    return subject, body


def merge_template(subject: str, body: str, row: dict) -> tuple[str, str, list[str]]:
    """Bind one row's cells into the template; pure.

    Returns ``(subject, body, empty_tokens)``: the merged lines plus the
    sorted tokens the template uses whose value is empty on this row
    (the dry-run preview shows them; an empty cell merges as empty).
    """
    values = {column_token(key): str(value or "") for key, value in row.items()}
    merged_body = _TOKEN_RE.sub(lambda m: values.get(m.group(1), ""), body)
    merged_subject = _TOKEN_RE.sub(lambda m: values.get(m.group(1), ""), subject)
    used = set(_TOKEN_RE.findall(subject)) | set(_TOKEN_RE.findall(body))
    empty_tokens = sorted(token for token in used if not values.get(token))
    return merged_subject, merged_body, empty_tokens


def build_message(
    from_address: str, address: str, subject: str, body: str
) -> EmailMessage:
    """One recipient per message: exactly one ``To``, never ``Cc``/``Bcc``."""
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = address
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=address.partition("@")[2] or "localhost")
    message.set_content(body)
    return message


def mask_address(address: str) -> str:
    """Masked recipient for the default report: first characters only."""
    local, _, domain = address.partition("@")
    return f"{(local[:1] or '*')}***@{(domain[:1] or '*')}***"


def stamp_rows(text: str, stamps: list[dict]) -> str:
    """Write the send stamps into the participants text; pure.

    Each stamp names the row's ``line`` index, the ``status_index`` and
    ``dm_index`` cell positions, and the values to write. Only stamped
    rows change; a stamped row is rebuilt in canonical ``| a | b |``
    spacing. Short rows pad to the cell index before writing.
    """
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    for stamp in stamps:
        cells = split_cells(lines[stamp["line"]])
        width = max(stamp["status_index"], stamp["dm_index"]) + 1
        if len(cells) < width:
            cells += [""] * (width - len(cells))
        cells[stamp["status_index"]] = stamp["status_value"]
        cells[stamp["dm_index"]] = stamp["dm_value"]
        lines[stamp["line"]] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def _smtp_deliver(
    plan: list[dict], settings: dict, report: list[str], show: bool = False
) -> set[int]:
    """Real send path: one SMTP connection, one message per plan row.

    Returns the set of plan indexes that sent. A failed row is reported
    (its reason is scrubbed so an SMTP error echo never prints an
    address), stays unstamped, and the remaining rows still go out.
    ``show`` is the ``--show-contacts`` flag: the recipient prints in
    full only when it is set, masked otherwise.
    """
    host = str(settings.get("smtp_host") or "").strip()
    try:
        port = int(str(settings.get("smtp_port") or "587").strip())
    except ValueError:
        raise _Usage(f"smtp_port is not a number: {settings.get('smtp_port')!r}") from None
    from_address = str(settings.get("from_address") or "").strip()
    user = str(settings.get("smtp_user") or "").strip()
    password = str(settings.get("smtp_password") or "")
    use_tls = str(settings.get("use_tls") or "true").strip().lower() not in (
        "false",
        "0",
        "no",
        "off",
    )
    sent: set[int] = set()
    with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT_SECONDS) as server:
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()
        if user:
            server.login(user, password)
        for index, item in enumerate(plan):
            message = build_message(
                from_address, item["address"], item["subject"], item["body"]
            )
            try:
                server.send_message(message)
            except Exception as exc:  # one failed row never stops the wave
                report.append(f"FAILED {item['label']}: {_scrub(str(exc))}")
                continue
            sent.add(index)
            shown = item["address"] if show else mask_address(item["address"])
            report.append(f"SENT {item['label']} ({shown})")
    return sent


def run(
    args: dict[str, str],
    environ: dict | None = None,
    deliver=None,
) -> tuple[int, str]:
    """One CLI invocation; returns ``(exit_code, stdout_text)``.

    The default mode is a dry run: merged messages print, nothing is
    sent, nothing is stamped. ``--send`` is the only path that opens an
    SMTP connection and writes stamps. ``deliver`` is injectable so the
    repo-level test module can pin the exit-code law without a network;
    the callable takes ``(plan, settings, report, show)`` and returns
    the set of plan indexes that sent.
    """
    show_contacts = bool(args.get("show_contacts"))
    participants_value = str(args.get("participants") or "").strip()
    if not participants_value:
        raise _Usage("--participants <participants.md> is required")
    settings, settings_source = load_send_settings(environ)
    template_value = str(args.get("template") or "").strip() or str(
        settings.get("template_path") or ""
    ).strip()
    if not template_value:
        raise _Usage(
            "--template <merge-template.md> is required (or set "
            "recruit.email.template_path / UXR_RECRUIT_TEMPLATE)"
        )

    participants_path = Path(participants_value).expanduser()
    if not participants_path.is_file():
        raise _Usage(f"participants file not found: {participants_path}")
    text = participants_path.read_text(encoding="utf-8")
    template_path = Path(template_value).expanduser()
    if not template_path.is_file():
        raise _Usage(f"template file not found: {template_path}")
    try:
        today = (
            date.fromisoformat(str(args.get("today")).strip())
            if str(args.get("today") or "").strip()
            else date.today()
        )
    except ValueError:
        raise _Usage(f"--today is not a date: {args.get('today')!r}") from None

    external_table = None
    internal_rows = 0
    for table in parse_tables(text):
        variant, issues = detect_variant(table["header"])
        if variant == SEND_VARIANT and external_table is None:
            external_table = table
        elif variant == "internal":
            internal_rows += len(table["rows"])
        elif variant is None and issues and "participant id" in [
            cell.strip().lower() for cell in table["header"]
        ]:
            raise _Usage(
                "the participants table header drifted from the approved sets: "
                + " ".join(issues)
            )
    if external_table is None:
        raise _Usage(
            "no approved external participants table found (the header must "
            f"match the approved {SEND_VARIANT} column set)"
        )
    subject, body = parse_template(template_path.read_text(encoding="utf-8"), SEND_VARIANT)

    header_lower = [cell.strip().lower() for cell in external_table["header"]]
    status_index = header_lower.index("status")
    dm_index = header_lower.index("dm sent (date)")
    entries: list[dict] = []
    for table_row in external_table["rows"]:
        row, has_extra = row_map(external_table["header"], table_row["cells"])
        if has_extra:
            entries.append({
                "row": row,
                "line": table_row["line"],
                "skip_note": "the row has more cells than the header; not sendable",
            })
            continue
        entries.append({"row": row, "line": table_row["line"]})

    plan, skipped = plan_sends([
        entry for entry in entries if "skip_note" not in entry
    ])
    flagged = [entry for entry in entries if "skip_note" in entry]

    report: list[str] = []
    stamps: list[dict] = []
    failed = 0
    send_mode = bool(args.get("send"))

    if send_mode and plan:
        missing = [key for key in ("smtp_host", "from_address") if not str(settings.get(key) or "").strip()]
        if missing:
            raise _Usage(
                "--send needs an SMTP account; set recruit.email."
                + " and recruit.email.".join(missing)
                + " in config/org.yaml (gitignored) or the UXR_RECRUIT_* env vars"
            )
    for item in plan:
        merged_subject, merged_body, empty_tokens = merge_template(subject, body, item["row"])
        item["subject"] = merged_subject
        item["body"] = merged_body
        item["empty_note"] = (
            " (empty value: " + ", ".join("{{" + t + "}}" for t in empty_tokens) + ")"
            if empty_tokens
            else ""
        )
        item["label"] = f"row {item['row'].get('participant id') or '-'}"

    if send_mode and plan:
        outcomes = (deliver or _smtp_deliver)(plan, settings, report, show_contacts)
        failed = len(plan) - len(outcomes)
        for index, item in enumerate(plan):
            if index not in outcomes:
                continue  # the deliver path reported the failure; no stamp
            stamps.append({
                "line": item["line"],
                "status_index": status_index,
                "dm_index": dm_index,
                "status_value": SEND_TO_STATUS,
                "dm_value": today.isoformat(),
            })
            report.append(
                f"STAMP {item['label']}: status {SEND_FROM_STATUS} -> {SEND_TO_STATUS}, "
                f"DM sent (date) {today.isoformat()}"
            )
    else:
        for item in plan:
            shown = item["address"] if show_contacts else mask_address(item["address"])
            report.append(
                f"SEND {item['label']} to {shown} "
                f'subject "{item["subject"]}"{item["empty_note"]}'
            )
            report.append("--- message preview ---")
            report.append(item["body"])
            report.append("--- end message ---")

    if not send_mode:
        report.insert(0, "DRY RUN: no send, no stamp, no write")
    else:
        report.insert(0, f"SEND: SMTP account from {settings_source}")
    for entry in flagged:
        report.append(f"SKIP row {entry['row'].get('participant id') or '-'}: {entry['skip_note']}")
    for entry in skipped:
        prefix = "BLOCK" if entry["action"] == "block" else "SKIP"
        report.append(f"{prefix} row {entry['row'].get('participant id') or '-'}: {entry['reason']}")
    if internal_rows:
        report.append(
            f"SKIP internal flow: {internal_rows} row(s) stay in the drafted-DM path "
            "(the MVP send path has no internal address column)"
        )
    sent_count = len(stamps)
    report.append(
        f"done: {sent_count} sent, {failed} failed, "
        f"{len(skipped) + len(flagged)} skipped"
        + (f", {internal_rows} internal" if internal_rows else "")
        + (" (dry run)" if not send_mode else "")
    )

    if send_mode and stamps:
        participants_path.write_text(stamp_rows(text, stamps), encoding="utf-8")

    output = "\n".join(report) + "\n"
    if show_contacts:
        return (EXIT_SEND_FAIL if failed else EXIT_OK), output
    return (EXIT_SEND_FAIL if failed else EXIT_OK), _scrub(output)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK

    flags: dict[str, str] = {}
    index = 0
    flag_names = {"--participants": "participants", "--template": "template", "--today": "today"}
    switches = {"--send": "send", "--show-contacts": "show_contacts"}
    while index < len(args):
        token = args[index]
        if token in flag_names:
            if index + 1 >= len(args):
                print(f"recruit_send: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            flags[flag_names[token]] = args[index + 1]
            index += 2
            continue
        if token in switches:
            flags[switches[token]] = "1"
            index += 1
            continue
        print(f"recruit_send: unknown argument {token!r}", file=sys.stderr)
        return EXIT_USAGE
    try:
        code, output = run(flags)
    except _Usage as exc:
        print(f"recruit_send: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
