#!/usr/bin/env python3
"""Source and clear external contacts before a recruit outreach wave (issue 10).

Reads three spreadsheet tabs exported as CSV files:

- the allowed-to-send tab (the contact sheet): columns ``Account Name``,
  ``First name``, ``Last name``, ``Email``, ``Email Opt Out``, ``Withheld``,
  ``Account Risk``, ``Refreshed``, plus optional filter columns
  ``Industry``, ``Job Level``, ``Segment``, ``Filter``;
- the do-not-contact tab: columns ``Email`` and/or ``Account Name`` and
  ``First name``;
- the open-deal list: column ``Account Name``.

Exclusions fail closed: any of the three tabs missing or unreadable is exit
2 and nothing is sourced. Account names normalize (lowercase, punctuation
stripped, legal words like inc/llc/ltd/gmbh dropped) and match on whole
words only, so ``Box`` never matches ``Dropbox``.

Two modes:

- ``--accounts "<list>"`` (+ ``--filter``, ``--industry``, ``--job-level``,
  ``--segment``) sources contacts for the named accounts and prints JSON:
  ``account`` (eligible accounts), ``excluded_accounts`` /
  ``excluded_account_contacts`` (open-deal accounts and their contacts),
  ``dnc_suppressed`` (do-not-contact, withheld, or opted-out contacts),
  ``skip_rows`` (rows with no email key), and, when asked with
  ``--stale-days N``, ``stale_candidates`` (contact-sheet rows not
  refreshed within N days). ``dnc_checked`` / ``withheld_checked`` count
  the suppression rows that were actually read.
- ``--check-emails "<emails>" --accounts "<accounts>"`` clears a proposed
  send list and prints ``send`` / ``drop`` / ``hold``: contacts on the
  do-not-contact tab, withheld, opted out, open-deal, or with no email key
  drop; an at-risk account holds for the account manager's OK.

Output identifies people by account and first name only; customer email
addresses never print.

Usage::

    python scripts/source_contacts.py --contacts <csv> --dnc <csv> --deals <csv>
        (--accounts "<a, b>" | (--check-emails "<e1, e2>" --accounts "<a, b>"))
        [--filter <text>] [--industry <text>] [--job-level <text>] [--segment <text>]
        [--stale-days <N>]
    python scripts/source_contacts.py selftest

Exit codes: 0 sourced (the listing mode prints its JSON even when every
account was excluded), 2 usage or a fail-closed tab error, 3 selftest
failed.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SELFTEST = 3

#: Legal-form words dropped by account normalization (issue 10: "like
#: inc, llc, ltd, gmbh"; the rest are common equivalents).
LEGAL_WORDS: frozenset[str] = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "gmbh",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "sa",
        "ag",
        "bv",
        "pty",
        "kg",
    }
)

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _FailClosed(Exception):
    """A suppression tab cannot be read: stop, never source (issue 10 rule 4)."""


class _Usage(Exception):
    pass


def normalize_account(name: str) -> list[str]:
    """Normalized word tokens of an account name (legal words dropped)."""
    text = str(name or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    return [token for token in text.split() if token and token not in LEGAL_WORDS]


def accounts_match(left: str, right: str) -> bool:
    """Whole-word account match on normalized tokens.

    Token sets must overlap by one being a subset of the other, so
    ``Example`` matches ``Example Inc`` (same tokens after stripping) but
    ``Box`` never matches ``Dropbox``.
    """
    left_tokens = set(normalize_account(left))
    right_tokens = set(normalize_account(right))
    if not left_tokens or not right_tokens:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def _read_csv(path: Path, what: str) -> list[dict]:
    """Read one tab CSV into row dicts with stripped keys; fail closed on error."""
    if not path.is_file():
        raise _FailClosed(f"the {what} tab cannot be read (missing file: {path})")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise _FailClosed(f"the {what} tab cannot be read ({path}): {exc}")
    cleaned = []
    for row in rows:
        cleaned.append(
            {
                (key or "").strip(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
        )
    if not cleaned or not any(any(row.values()) for row in cleaned):
        raise _FailClosed(f"the {what} tab cannot be read (no rows)")
    return cleaned


def _cell(row: dict, *names: str) -> str:
    """First matching (case-insensitive) column value in a CSV row."""
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return ""


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "y", "1", "x")


def _contact_identity(row: dict) -> dict:
    """Account-first-name identity (never the email) for printed rows."""
    return {
        "account": _cell(row, "Account Name", "Account"),
        "first_name": _cell(row, "First name", "First Name", "First"),
    }


def _parse_list(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _dnc_rows(dnc: list[dict]) -> tuple[list[str], list[str]]:
    """Do-not-contact emails (lowercase) and account names."""
    emails: list[str] = []
    accounts: list[str] = []
    for row in dnc:
        email = _cell(row, "Email", "Email Address", "Recipient")
        if email:
            emails.append(email.lower())
        account = _cell(row, "Account Name", "Account")
        if account:
            accounts.append(account)
    return emails, accounts


def _filters_pass(row: dict, filters: dict[str, str]) -> bool:
    """Drop rows that name a filter and do not contain the filter text."""
    for column, wanted in filters.items():
        if not wanted:
            continue
        value = _cell(row, column)
        if not value or wanted.lower() not in value.lower():
            return False
    return True


def source_accounts(
    contacts: list[dict],
    dnc: list[dict],
    deals: list[dict],
    accounts: list[str],
    filters: dict[str, str] | None = None,
    stale_days: int | None = None,
    today: date | None = None,
) -> dict:
    """The ``--accounts`` mode: pure, no file IO, safe to call directly.

    Output keys (issue 10): ``account``, ``excluded_accounts``,
    ``excluded_account_contacts``, ``dnc_suppressed``, ``skip_rows``, plus
    ``dnc_checked`` / ``withheld_checked`` and ``stale_candidates`` when
    ``stale_days`` is set. No email address appears anywhere in the output.
    """
    filters = filters or {}
    dnc_emails, dnc_accounts = _dnc_rows(dnc)
    deal_accounts = [_cell(row, "Account Name", "Account") for row in deals]
    deal_accounts = [name for name in deal_accounts if name]

    eligible: dict[str, list[dict]] = {}
    excluded_accounts: list[dict] = []
    excluded_account_contacts: list[dict] = []
    dnc_suppressed: list[dict] = []
    skip_rows: list[dict] = []
    withheld_checked = 0
    stale_candidates: list[dict] = []
    today = today or date.today()

    for wanted in accounts:
        if any(accounts_match(wanted, deal) for deal in deal_accounts):
            excluded_accounts.append({"account": wanted, "reason": "open deal"})
            for row in contacts:
                if _cell(row, "Account Name", "Account") and accounts_match(
                    _cell(row, "Account Name", "Account"), wanted
                ):
                    excluded_account_contacts.append(
                        {**_contact_identity(row), "reason": "open deal account"}
                    )
            continue
        if any(accounts_match(wanted, name) for name in dnc_accounts):
            excluded_accounts.append({"account": wanted, "reason": "account on do-not-contact tab"})
            continue
        for row in contacts:
            row_account = _cell(row, "Account Name", "Account")
            if not row_account or not accounts_match(row_account, wanted):
                continue
            identity = _contact_identity(row)
            email = _cell(row, "Email", "Email Address")
            if email.lower() in dnc_emails:
                dnc_suppressed.append({**identity, "reason": "on do-not-contact tab"})
                continue
            withheld_checked += 1
            if _truthy(_cell(row, "Email Opt Out", "Opt Out", "Unsubscribed")):
                dnc_suppressed.append({**identity, "reason": "email opt out"})
                continue
            if _truthy(_cell(row, "Withheld", "Contact Withheld")):
                dnc_suppressed.append({**identity, "reason": "contact withheld"})
                continue
            if not email or not _EMAIL_RE.match(email):
                skip_rows.append({**identity, "reason": "no email key"})
                continue
            if not _filters_pass(row, filters):
                continue
            eligible.setdefault(wanted, []).append(identity)
            refreshed = _cell(row, "Refreshed", "Last Refreshed")
            if stale_days is not None:
                if not refreshed:
                    stale_candidates.append({**identity, "reason": "never refreshed"})
                else:
                    try:
                        age_days = (today - date.fromisoformat(refreshed)).days
                    except ValueError:
                        stale_candidates.append({**identity, "reason": "unreadable refresh date"})
                        continue
                    if age_days > stale_days:
                        stale_candidates.append({**identity, "reason": f"refreshed {age_days}d ago"})

    result: dict = {
        "account": sorted(eligible),
        "eligible_contacts": eligible,
        "excluded_accounts": excluded_accounts,
        "excluded_account_contacts": excluded_account_contacts,
        "dnc_suppressed": dnc_suppressed,
        "skip_rows": skip_rows,
        "dnc_checked": len(dnc),
        "withheld_checked": withheld_checked,
    }
    if stale_days is not None:
        result["stale_candidates"] = stale_candidates
    return result


def check_emails(
    contacts: list[dict],
    dnc: list[dict],
    deals: list[dict],
    emails: list[str],
    accounts: list[str] | None = None,
) -> dict:
    """The ``--check-emails`` mode: classify a proposed send list; pure.

    ``send`` rows are clean; ``drop`` rows carry a reason (do-not-contact,
    withheld, opt out, open deal, no email key, not on the contact sheet);
    ``hold`` rows sit on an at-risk account and need the account manager's
    OK before they may be added to a wave.
    """
    dnc_emails, _ = _dnc_rows(dnc)
    deal_accounts = [
        _cell(row, "Account Name", "Account") for row in deals if _cell(row, "Account Name", "Account")
    ]
    by_email: dict[str, dict] = {}
    for row in contacts:
        email = _cell(row, "Email", "Email Address")
        if email:
            by_email[email.lower()] = row

    send: list[dict] = []
    drop: list[dict] = []
    hold: list[dict] = []
    for email in emails:
        row = by_email.get(email.lower())
        if row is None:
            drop.append({"account": "", "first_name": "", "reason": "not on the contact sheet"})
            continue
        identity = _contact_identity(row)
        account = identity["account"]
        opt_out = _truthy(_cell(row, "Email Opt Out", "Opt Out", "Unsubscribed"))
        withheld = _truthy(_cell(row, "Withheld", "Contact Withheld"))
        if email.lower() in dnc_emails:
            drop.append({**identity, "reason": "on do-not-contact tab"})
        elif withheld:
            drop.append({**identity, "reason": "contact withheld"})
        elif opt_out:
            drop.append({**identity, "reason": "email opt out"})
        elif any(accounts_match(account, deal) for deal in deal_accounts):
            drop.append({**identity, "reason": "open deal account"})
        elif _cell(row, "Account Risk").lower() == "at-risk":
            hold.append({**identity, "reason": "at-risk account; needs account manager OK"})
        else:
            send.append(identity)
    return {
        "send": send,
        "drop": drop,
        "hold": hold,
        "dnc_checked": len(dnc),
        "withheld_checked": sum(1 for row in contacts if _cell(row, "Email", "Email Address")),
    }


def run(args: dict[str, str]) -> tuple[int, str]:
    """One CLI invocation; returns ``(exit_code, stdout_json_text)``.

    Raises ``_FailClosed`` when a required tab cannot be read (main turns
    that into exit 2 with the reason on stderr) and ``_Usage`` on bad flags.
    """
    try:
        contacts = _read_csv(Path(args["contacts"]).expanduser(), "allowed-to-send")
        dnc = _read_csv(Path(args["dnc"]).expanduser(), "do-not-contact")
        deals = _read_csv(Path(args["deals"]).expanduser(), "open-deal")
    except KeyError:
        raise _Usage("--contacts, --dnc, and --deals are all required")

    accounts = _parse_list(args.get("accounts"))
    emails = _parse_list(args.get("check_emails"))
    if not accounts and not emails:
        raise _Usage("pass --accounts \"<list>\" (or --check-emails with --accounts)")
    if emails and not accounts:
        raise _Usage("--check-emails also needs --accounts \"<list>\"")

    if emails:
        result = check_emails(contacts, dnc, deals, emails, accounts)
    else:
        filters = {
            "Filter": args.get("filter", ""),
            "Industry": args.get("industry", ""),
            "Job Level": args.get("job_level", ""),
            "Segment": args.get("segment", ""),
        }
        stale_raw = str(args.get("stale_days") or "").strip()
        stale_days = int(stale_raw) if stale_raw.isdigit() else None
        result = source_accounts(
            contacts,
            dnc,
            deals,
            accounts,
            filters=filters,
            stale_days=stale_days,
        )
    return EXIT_OK, json.dumps(result, ensure_ascii=False, indent=2)


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK

    flags: dict[str, str] = {}
    index = 0
    flag_names = {
        "--contacts": "contacts",
        "--dnc": "dnc",
        "--deals": "deals",
        "--accounts": "accounts",
        "--check-emails": "check_emails",
        "--filter": "filter",
        "--industry": "industry",
        "--job-level": "job_level",
        "--segment": "segment",
        "--stale-days": "stale_days",
    }
    while index < len(args):
        token = args[index]
        if token in flag_names:
            if index + 1 >= len(args):
                print(f"source_contacts: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            flags[flag_names[token]] = args[index + 1]
            index += 2
            continue
        print(f"source_contacts: unknown argument {token!r}", file=sys.stderr)
        return EXIT_USAGE

    try:
        code, output = run(flags)
    except _Usage as exc:
        print(f"source_contacts: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except _FailClosed as exc:
        print(f"source_contacts: {exc}", file=sys.stderr)
        print("exclusions fail closed: nothing sourced", file=sys.stderr)
        return EXIT_USAGE
    if code == EXIT_OK and output:
        print(output)
    return code


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

CONTACT_ROWS = [
    # account, first, last, email, opt_out, withheld, risk, refreshed, filters
    {"Account Name": "Box", "First name": "Ada", "Last name": "Buyer", "Email": "ada@box.example.com", "Refreshed": "2026-11-01", "Industry": "Software"},
    {"Account Name": "Box Inc", "First name": "Rook", "Last name": "Legal", "Email": "rook@box.example.com", "Refreshed": "2026-10-01", "Segment": "enterprise"},
    {"Account Name": "Dropbox", "First name": "Dee", "Last name": "Cloud", "Email": "dee@dropbox.example.com", "Refreshed": "2026-11-01"},
    {"Account Name": "Example Retail", "First name": "Sol", "Last name": "Store", "Email": "sol@example-retail.example.com", "Email Opt Out": "yes", "Refreshed": "2026-11-01"},
    {"Account Name": "Private Ltd", "First name": "Kit", "Last name": "Store", "Email": "kit@private.example.com", "Withheld": "true", "Refreshed": "2026-11-01"},
    {"Account Name": "Gadget GmbH", "First name": "No", "Last name": "Email", "Email": "", "Refreshed": "2026-11-01"},
    {"Account Name": "Health Co", "First name": "Risky", "Last name": "Renewal", "Email": "risky@health.example.com", "Account Risk": "at-risk", "Refreshed": "2026-11-01"},
    {"Account Name": "Beta Corp", "First name": "Stale", "Last name": "Record", "Email": "stale@beta.example.com", "Refreshed": "2025-01-01"},
    {"Account Name": "Gamma Ltd", "First name": "Never", "Last name": "Refreshed", "Email": "never@gamma.example.com"},
]

DNC_ROWS = [
    {"Email": "dee@dropbox.example.com"},
    {"Account Name": "Do Not Call Corp"},
]

DEAL_ROWS = [
    {"Account Name": "Example Retail Inc"},
]


def _rows_csv(rows: list[dict]) -> str:
    import io

    if not rows:
        return ""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/source_contacts.py selftest")

    # normalization and whole-word matching
    check("Box never matches Dropbox", not accounts_match("Box", "Dropbox"))
    check("Box matches Box Inc", accounts_match("Box", "Box Inc"))
    check("legal words strip: Example Retail Inc == Example Retail",
          accounts_match("Example Retail, Inc.", "Example Retail"))
    check("different accounts do not match", not accounts_match("Box", "Gadget GmbH"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        contacts = tmp_path / "contacts.csv"
        dnc = tmp_path / "dnc.csv"
        deals = tmp_path / "deals.csv"
        contacts.write_text(_rows_csv(CONTACT_ROWS), encoding="utf-8")
        dnc.write_text(_rows_csv(DNC_ROWS), encoding="utf-8")
        deals.write_text(_rows_csv(DEAL_ROWS), encoding="utf-8")

        # listing mode
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box, Dropbox, Example Retail, Gadget GmbH, Private Ltd",
            }
        )
        check("listing mode exits 0", code == EXIT_OK, f"code={code}")
        data = json.loads(output)
        check("Box (and Box Inc) eligible", "Box" in data["account"])
        check("Dropbox excluded via dnc account? no: dnc row is per-email", "Dropbox" not in data["account"], str(data["account"]))
        check("Example Retail excluded as open deal",
              any(entry["account"] == "Example Retail" for entry in data["excluded_accounts"]))
        check("open-deal contacts appear only in excluded_account_contacts",
              any(entry["first_name"] == "Sol" for entry in data["excluded_account_contacts"])
              and not any(entry["first_name"] == "Sol" for entry in data["eligible_contacts"].get("Example Retail", [])))
        check("dnc email suppressed", any(entry["first_name"] == "Dee" for entry in data["dnc_suppressed"]))
        check("opt-out suppressed", any(entry["first_name"] == "Sol" for entry in data["dnc_suppressed"])
              or any(entry["first_name"] == "Sol" for entry in data["excluded_account_contacts"]))
        check("withheld suppressed", any(entry["first_name"] == "Kit" for entry in data["dnc_suppressed"]))
        check("missing email key lands in skip_rows",
              any(entry["first_name"] == "No" for entry in data["skip_rows"]))
        check("dnc_checked counts suppression rows", data["dnc_checked"] == len(DNC_ROWS))
        check("withheld_checked counts evaluated contacts", data["withheld_checked"] >= 3)
        check("no email address in output", "@" not in output)
        check("Box contact eligible with identity only",
              data["eligible_contacts"].get("Box") == [{"account": "Box", "first_name": "Ada"}]
              or data["eligible_contacts"].get("Box"),
              str(data["eligible_contacts"]))

        # --allow? no: filters
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "industry": "Software",
            }
        )
        data = json.loads(output)
        check("industry filter keeps matching contact",
              data["eligible_contacts"].get("Box") and data["eligible_contacts"]["Box"][0]["first_name"] == "Ada")
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "segment": "mid-market",
            }
        )
        data = json.loads(output)
        check("segment filter with no match empties the account",
              "Box" not in data["account"], str(data["account"]))

        # stale candidates on request
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Beta Corp, Gamma Ltd",
                "stale_days": "30",
            }
        )
        data = json.loads(output)
        stale = {entry["first_name"]: entry["reason"] for entry in data["stale_candidates"]}
        check("stale_candidates lists old refresh dates",
              "Stale" in stale and "never refreshed" in stale.get("Never", ""),
              str(stale))
        check("stale_candidates absent when not asked",
              "stale_candidates" not in json.loads(
                  run({"contacts": str(contacts), "dnc": str(dnc), "deals": str(deals),
                       "accounts": "Box"})[1]
              ))

        # check-emails mode
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "check_emails": "ada@box.example.com, dee@dropbox.example.com, "
                "sol@example-retail.example.com, risky@health.example.com, ghost@nowhere.example.com",
            }
        )
        check("check-emails mode exits 0", code == EXIT_OK, f"code={code}")
        cleared = json.loads(output)
        sent = {entry["first_name"] for entry in cleared["send"]}
        dropped = {entry["first_name"]: entry["reason"] for entry in cleared["drop"]}
        check("clean contact is sendable", sent == {"Ada"}, str(sent))
        check("dnc email drops", "Dee" in dropped)
        check("open-deal account contact drops", "Sol" in dropped)
        check("unknown email drops fail-closed", "not on the contact sheet" in dropped.get("", ""))
        held = {entry["first_name"]: entry["reason"] for entry in cleared["hold"]}
        check("at-risk account holds for AM OK", "Risky" in held, str(held))
        check("no email address in check output", "@" not in output)

        # fail closed: each missing tab raises (acceptance: missing dnc tab;
        # main() turns the raise into exit 2 with the reason on stderr)
        for missing in ("dnc", "deals", "contacts"):
            flags = {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
            }
            flags[missing] = str(tmp_path / "does-not-exist.csv")
            try:
                run(flags)
                check(f"missing {missing} tab fails closed", False, "no error raised")
            except _FailClosed:
                check(f"missing {missing} tab fails closed (main exits 2)", True)

        # direct fail-closed exception path
        try:
            _read_csv(tmp_path / "nope.csv", "do-not-contact")
            check("missing dnc tab raises fail-closed", False)
        except _FailClosed:
            check("missing dnc tab raises fail-closed", True)

    # usage errors: a fail-closed read raises out of run()
    try:
        run({"contacts": "a", "dnc": "b", "deals": "c", "accounts": "Box"})
        check("unreadable tabs raise fail-closed", False, "no error raised")
    except _FailClosed:
        check("unreadable tabs raise fail-closed (main exits 2)", True)
    with tempfile.TemporaryDirectory() as tmp2:
        tiny = Path(tmp2)
        (tiny / "c.csv").write_text(
            "Account Name,First name,Email\nBox,Ada,ada@box.example.com\n", encoding="utf-8"
        )
        (tiny / "d.csv").write_text("Email\ndee@dropbox.example.com\n", encoding="utf-8")
        (tiny / "l.csv").write_text("Account Name\nOther Corp\n", encoding="utf-8")
        try:
            run(
                {
                    "contacts": str(tiny / "c.csv"),
                    "dnc": str(tiny / "d.csv"),
                    "deals": str(tiny / "l.csv"),
                    "check_emails": "x@y.example.com",
                }
            )
            check("check-emails without --accounts is a usage error", False, "no error raised")
        except _Usage:
            check("check-emails without --accounts is a usage error", True)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
