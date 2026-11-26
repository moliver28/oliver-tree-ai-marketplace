#!/usr/bin/env python3
"""Apply recruitment ops to the study spec and re-render the ticket body (issue 10).

This is the only write path the recruit command uses against the spec. It
takes an ops file, applies it to the spec JSON, validates, renders, and then
writes both the spec file and the rendered body -- or nothing at all.

Ops JSON (issue 10 shape)::

    {
      "update": [{"match": "<name substring>", "set": {"status": "..."},
                  "reason_append": "<text>"}],
      "add":    [{"name": "...", "email": "...", "slack": "...", "title": "...",
                  "company": "...", "industry": "...", "arr": "...",
                  "reason": "...", "work_area": "...", "status": "...",
                  "channel": "internal|external"}],
      "funnel": {"sheet": "<sheet id>", "tabs": ["Wave 1"],
                 "fit": {"users": 120, "accounts": 40, "as_of": "2026-11-09",
                          "basis": "product analytics cohort"}},
      "refit": false
    }

Rules:

- ``update`` matches a roster row by case-insensitive substring on the
  name; ``set`` accepts only roster fields (status must be an allowed
  status); ``reason_append`` appends to the row's reason.
- ``add`` dedupes on email (case-insensitive), then on name. A duplicate
  add fills only blank fields and promotes the status only from Potential
  Candidate(s), Selected for Distribution, Outreach Sent, Survey Sent,
  Reminder Sent, or No Response -- and only to a status of the same or
  higher rank. It never demotes, so a Data Collected row stays Data
  Collected and re-running the same add is idempotent.
- ``funnel`` records the merge sheet, the wave tabs (accumulating, deduped,
  ordered), and the fit snapshot; the fit is only replaced when ``refit``
  is true (or absent before).
- The spec is validated first; on any validation failure the run exits 3
  and writes nothing. Success re-renders the body with
  ``lib/spec_blocks.build_document`` and writes the spec file and the body
  JSON.
- ``--dry-run`` prints the plan and writes nothing.

Usage::

    python scripts/roster_apply.py --spec <path.spec.json> --ops <json-or-@file>
        --out <body.json> [--dry-run]

Exit codes: 0 applied (or planned), 2 usage / unreadable input, 3
validation failed (nothing written), 4 rendered document incomplete
(nothing written).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import config as _config  # noqa: E402
from lib import spec_blocks as _spec  # noqa: E402
from lib import cli as _cli  # noqa: E402  (shared plumbing)
from lib import util as _util  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATE = 3
EXIT_INCOMPLETE = 4
EXIT_SELFTEST = 5

#: Statuses a duplicate add may still promote from (issue 10).
PROMOTABLE_FROM: tuple[str, ...] = (
    "Potential Candidate",
    "Potential Candidates",
    "Selected for Distribution",
    "Outreach Sent",
    "Survey Sent",
    "Reminder Sent",
    "No Response",
)

#: Progress rank inside PROMOTABLE_FROM; anything outside the tuple is a
#: reached (fixed) state and never demotes.
STATUS_RANK: dict[str, int] = {
    "Potential Candidate": 0,
    "Potential Candidates": 0,
    "Selected for Distribution": 0,
    "Outreach Sent": 1,
    "Survey Sent": 1,
    "No Response": 1,
    "Reminder Sent": 2,
}


class _Usage(_cli.UsageError):
    pass


class _Validation(Exception):
    """Validation failed; carry the error list and write nothing."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _read_json(path: Path, what: str) -> object:
    try:
        return _util.read_json_arg(path, what, expanduser=False)
    except _util.JsonReadError as exc:
        raise _Usage(_util.json_error_message(exc, what)) from exc.exc


def _ops_from_arg(value: str) -> dict:
    """Ops JSON from an inline string or ``@file``."""
    text = value.strip()
    if text.startswith("@"):
        ops = _read_json(Path(text[1:]).expanduser(), "ops file")
    else:
        try:
            ops = json.loads(text)
        except ValueError as exc:
            raise _Usage(f"--ops is not valid JSON: {exc}") from exc
    if not isinstance(ops, dict):
        raise _Usage("ops must be a JSON object")
    return ops


def _promote(current: str, incoming: str) -> str:
    """The status a duplicate add lands on: never demote, never regress."""
    if current == incoming:
        return current
    if current not in PROMOTABLE_FROM:
        return current
    if incoming not in PROMOTABLE_FROM:
        return incoming  # a reached state (Scheduled, Data Collected, ...) wins
    if STATUS_RANK.get(incoming, 0) >= STATUS_RANK.get(current, 0):
        return incoming
    return current


def apply_ops(spec: dict, ops: dict, config: dict | None = None) -> tuple[dict, list[str]]:
    """Apply one ops object to a deep-copied spec; pure, raises _Validation.

    Returns ``(new_spec, notes)`` where notes describe each change (names
    and statuses only; never emails). Raises ``_Validation`` when an op is
    malformed or the resulting spec fails ``validate_spec``.
    """
    if config is None:
        try:
            config = _config.load_config()
        except _config.ConfigError:
            config = {}
    new_spec = copy.deepcopy(spec)
    if not isinstance(new_spec, dict):
        raise _Validation(["spec is not a JSON object"])
    notes: list[str] = []
    roster: list[dict] = [row for row in (new_spec.get("roster") or []) if isinstance(row, dict)]
    allowed = _spec.status_set(config)
    roster_fields = set(_spec.ROSTER_FIELDS)

    for index, op in enumerate(ops.get("update") or []):
        if not isinstance(op, dict):
            raise _Validation([f"update[{index}] is not an object"])
        match = str(op.get("match") or "").strip()
        if not match:
            raise _Validation([f"update[{index}].match is required"])
        needle = match.lower()
        hits = [row for row in roster if needle in str(row.get("name") or "").lower()]
        if not hits:
            notes.append(f"update: no roster row matches {match!r}")
            continue
        fields = op.get("set") or {}
        if not isinstance(fields, dict):
            raise _Validation([f"update[{index}].set must be an object"])
        unknown = sorted(set(fields) - roster_fields)
        if unknown:
            raise _Validation(
                [f"update[{index}] sets unknown roster field(s): {', '.join(unknown)}"]
            )
        status = str(fields.get("status") or "").strip()
        if "status" in fields and status not in allowed:
            raise _Validation([f"update[{index}].status {status!r} is not an allowed roster status"])
        reason_append = str(op.get("reason_append") or "").strip()
        for row in hits:
            before = str(row.get("status") or _spec.DEFAULT_ROSTER_STATUS)
            for field, value in fields.items():
                if field == "status" and not status:
                    continue
                row[field] = str(value).strip()
            if reason_append:
                existing = str(row.get("reason") or "").strip()
                row["reason"] = f"{existing}; {reason_append}" if existing else reason_append
            after = str(row.get("status") or _spec.DEFAULT_ROSTER_STATUS)
            notes.append(
                f"update: {row.get('name')} {before} -> {after}"
                + (f" (reason: {reason_append})" if reason_append else "")
            )

    for index, row_op in enumerate(ops.get("add") or []):
        if not isinstance(row_op, dict):
            raise _Validation([f"add[{index}] is not an object"])
        unknown = sorted(set(row_op) - roster_fields)
        if unknown:
            raise _Validation(
                [f"add[{index}] carries unknown roster field(s): {', '.join(unknown)}"]
            )
        name = str(row_op.get("name") or "").strip()
        if not name:
            raise _Validation([f"add[{index}].name is required"])
        email = str(row_op.get("email") or "").strip().lower()
        duplicate = None
        if email:
            duplicate = next(
                (row for row in roster if str(row.get("email") or "").strip().lower() == email),
                None,
            )
        if duplicate is None:
            duplicate = next(
                (row for row in roster if str(row.get("name") or "").strip().lower() == name.lower()),
                None,
            )
        if duplicate is not None:
            before = str(duplicate.get("status") or _spec.DEFAULT_ROSTER_STATUS)
            for field, value in row_op.items():
                if field == "status":
                    continue
                if not str(duplicate.get(field) or "").strip():
                    duplicate[field] = str(value).strip()
            incoming_status = str(row_op.get("status") or "").strip()
            if incoming_status and incoming_status not in allowed:
                raise _Validation(
                    [f"add[{index}].status {incoming_status!r} is not an allowed roster status"]
                )
            after = _promote(before, incoming_status or before)
            duplicate["status"] = after
            notes.append(
                f"add: {name} already on roster ({email or 'name'}); kept {after}"
                if after == before
                else f"add: {name} already on roster; promoted {before} -> {after}"
            )
            continue
        row = {field: "" for field in _spec.ROSTER_FIELDS}
        for field, value in row_op.items():
            row[field] = str(value).strip()
        row["name"] = name
        if not row["status"]:
            row["status"] = _spec.DEFAULT_ROSTER_STATUS
        if row["status"] not in allowed:
            raise _Validation([f"add[{index}].status {row['status']!r} is not an allowed roster status"])
        if row["channel"] not in ("internal", "external"):
            row["channel"] = _spec.DEFAULT_ROSTER_CHANNEL
        roster.append(row)
        notes.append(f"add: {name} ({row['status']}, {row['channel']})")

    new_spec["roster"] = roster

    funnel_op = ops.get("funnel")
    if funnel_op is not None:
        if not isinstance(funnel_op, dict):
            raise _Validation(["funnel must be an object"])
        funnel = copy.deepcopy(new_spec.get("funnel") or {})
        if not isinstance(funnel, dict):
            funnel = {}
        refit_requested = ops.get("refit") is True
        sheet = str(funnel_op.get("sheet") or "").strip()
        if sheet and (not str(funnel.get("sheet") or "").strip() or refit_requested):
            funnel["sheet"] = sheet
        tabs = funnel_op.get("tabs")
        if tabs is not None:
            if not isinstance(tabs, list) or any(not str(t).strip() for t in tabs):
                raise _Validation(["funnel.tabs must be a list of tab names"])
            existing = [str(t) for t in (funnel.get("tabs") or []) if str(t).strip()]
            for tab in tabs:
                tab = str(tab).strip()
                if tab and tab not in existing:
                    existing.append(tab)
            funnel["tabs"] = existing
        fit = funnel_op.get("fit")
        if fit is not None:
            if not isinstance(fit, dict):
                raise _Validation(["funnel.fit must be an object"])
            if not str(funnel.get("fit") or "") or refit_requested:
                funnel["fit"] = fit
        elif refit_requested and funnel_op.get("fit") is None:
            raise _Validation(["refit: true needs funnel.fit in the same ops object"])
        new_spec["funnel"] = funnel
        notes.append(
            f"funnel: sheet={funnel.get('sheet') or 'unset'}"
            f" tabs={','.join(funnel.get('tabs') or []) or 'none'}"
            f" fit={'set' if funnel.get('fit') else 'unset'}"
        )

    ok, errors = _spec.validate_spec(new_spec, config=config)
    if not ok:
        raise _Validation(errors)
    return new_spec, notes


def run(
    spec_path_value: str,
    ops_value: str,
    out_value: str,
    dry_run: bool = False,
    config: dict | None = None,
) -> tuple[int, str]:
    """One CLI invocation; returns ``(exit_code, stdout_text)``. Pure until
    the final writes (skipped under --dry-run)."""
    if config is None:
        try:
            config = _config.load_config()
        except _config.ConfigError:
            config = {}
    spec = _read_json(Path(spec_path_value).expanduser(), "spec")
    ops = _ops_from_arg(ops_value)
    out_path = Path(out_value).expanduser() if out_value else None
    if out_path is None:
        raise _Usage("--out <body.json> is required")

    try:
        new_spec, notes = apply_ops(spec, ops, config=config)
    except _Validation as exc:
        return EXIT_VALIDATE, "".join(f"  - {error}\n" for error in exc.errors)

    try:
        body = _spec.build_document(new_spec, config=config)
    except ValueError as exc:
        return EXIT_USAGE, f"roster_apply: render failed: {exc}\n"
    complete, problems = _spec.assert_full_document(body)
    if not complete:
        return EXIT_INCOMPLETE, "".join(f"  - {problem}\n" for problem in problems)

    if dry_run:
        report = ["dry-run: no files written"]
        report.extend(f"  {note}" for note in notes)
        report.append(f"  would write spec: {spec_path_value}")
        report.append(f"  would write body: {out_path}")
        return EXIT_OK, "\n".join(report) + "\n"

    meta = new_spec.get("_meta")
    if isinstance(meta, dict):
        meta["last_edited_at"] = _spec.make_meta("roster_apply")["last_edited_at"]
    body_text = (
        body + "\n" if isinstance(body, str) else json.dumps(body, ensure_ascii=False) + "\n"
    )
    Path(spec_path_value).expanduser().write_text(
        json.dumps(new_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out_path.write_text(body_text, encoding="utf-8")
    report = [f"applied: {len(notes)} change(s)"]
    report.extend(f"  {note}" for note in notes)
    report.append(f"  wrote spec: {spec_path_value}")
    report.append(f"  wrote body: {out_path}")
    return EXIT_OK, "\n".join(report) + "\n"


MCP_SURFACE = {
    "description": (
        "roster_apply.py: apply recruitment ops to the study spec, validate, "
        "re-render the body, and write the spec and body files (or nothing on "
        "any failure). The only write path the recruit command uses against "
        "the spec."),
    "flags": [
        {"name": "spec", "flag": "--spec", "type": "string", "required": True},
        {"name": "ops", "flag": "--ops", "type": "string", "required": True,
         "help": "ops JSON inline, or @path to an ops file"},
        {"name": "out", "flag": "--out", "type": "string", "required": True,
         "help": "path to write the rendered body JSON"},
    ],
    "switches": [
        {"name": "dry_run", "flag": "--dry-run", "type": "boolean",
         "help": "apply nothing; report only"},
    ],
}


def main(argv: list[str] | None = None) -> int:
    return _cli.run_main(
        argv,
        prog="roster_apply",
        doc=__doc__,
        mcp_surface=MCP_SURFACE,
        run=lambda flags: run(
            flags.get("spec", ""),
            flags.get("ops", ""),
            flags.get("out", ""),
            dry_run=flags.get("dry_run") == "1",
        ),
        flag_names={"--spec": "spec", "--ops": "ops", "--out": "out"},
        switches={"--dry-run": "dry_run"},
    )


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit(main())
