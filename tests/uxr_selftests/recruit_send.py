"""Recruit send selftest (W5): the MVP email-send laws.

Checks that ``scripts/recruit_send.py`` respects the shipped gate law
(the approved column sets, the locked status vocabulary, and the
per-variant gate map are imported, not copied), that the dry run
changes nothing while the real send stamps ``DM sent (date)`` and
advances ``invited`` to ``scheduled`` per the gate map with failed rows
unstamped, that one message carries exactly one recipient and never a
``Cc`` or ``Bcc`` (a duplicate address sends once), that contacts are
masked by default and shown only with the explicit flag, and that the
exit-code law holds (0 clean, 1 a send failed, 2 usage). Rides the
smoke check-3 glob; parity enrollment is out of scope (W2 adapters
precedent).
"""
from _harness import bind

bind("scripts.recruit_send", globals())

import csv  # selftest-only import (no shipped surface)
import tempfile  # selftest-only import (no shipped surface)
from scripts import recruit_funnel as _funnel  # the identity pin source

EXIT_SELFTEST = 3  # selftest failure exit (runner convention)

PARTICIPANTS = """# Participants

## Internal flow (default)

| participant id | name | role/segment | team/org area | source (org-chart path) | screener result | status | consent-to-record | DM sent (date) | notes |
|---|---|---|---|---|---|---|---|---|---|
| I-01 | Val Example | engineer | platform | manager path | pass | identified | | | |

## External flow (`--external`)

| participant id | name/pseudonym | contact | source (panel/channel) | screener result | status | consent-to-record | incentive status | DM sent (date) | prep note | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| P-01 | Ada Example | ada.example@example.com | panel | role fit: yes | invited | | not sent | | | |
| P-02 | Rook Example | rook.example@example.com | panel | role fit: yes | scheduled | yes | not sent | 2026-11-20 | | |
| P-03 | Sol Example | | panel | role fit: yes | invited | | not sent | | | |
| P-04 | Kit Example | @kit-slack | panel | role fit: yes | invited | | not sent | | | |
| P-05 | Dee Example | ada.example@example.com | panel | role fit: yes | invited | | not sent | | | |
| P-06 | Gus Example | gus.example@example.com | panel | role fit: yes | withdrawn | | not sent | | | |
| P-07 | Ida Example | ida.example@example.com | panel | role fit: yes | invited | | not sent | | | |

Rules:

- One row per participant; samples stay synthetic.
"""

TEMPLATE = """Subject: Interview invite: {{name_pseudonym}}

Hi {{name_pseudonym}},

Thank you for agreeing to take part in our study.
"""


def _write_fixture(directory: str) -> tuple[str, str]:
    participants_path = Path(directory) / "participants.md"
    template_path = Path(directory) / "template.md"
    # newline='': the fixture bytes carry exactly the string's LF endings on
    # every platform, so the byte-level stamp checks hold on Windows too.
    participants_path.write_text(PARTICIPANTS, encoding="utf-8", newline="")
    template_path.write_text(TEMPLATE, encoding="utf-8", newline="")
    return str(participants_path), str(template_path)


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/recruit_send.py selftest")

    # The column and gate law is imported from recruit_funnel, not copied.
    check("column law is imported, not duplicated",
          PARTICIPANT_COLUMNS is _funnel.PARTICIPANT_COLUMNS)
    check("the gate helpers come from recruit_funnel (no redefinition)",
          participant_gate_lines is _funnel.participant_gate_lines
          and participant_status_issue is _funnel.participant_status_issue
          and participant_header_issues is _funnel.participant_header_issues)
    check("the send advances invited to scheduled, per the shipped gate map",
          SEND_FROM_STATUS == "invited" and SEND_TO_STATUS == "scheduled",
          f"{SEND_FROM_STATUS} -> {SEND_TO_STATUS}")
    check("the scheduled gate is DM sent (date) (the stamp satisfies it)",
          _funnel.PARTICIPANT_STATUS_GATES["external"]["scheduled"] == ("DM sent (date)",),
          str(_funnel.PARTICIPANT_STATUS_GATES["external"]))

    # Gate law the send respects (evaluate_row, per row, no model call).
    row = {
        "participant id": "P-01", "name/pseudonym": "Ada Example",
        "contact": "ada.example@example.com", "screener result": "role fit: yes",
        "status": "invited", "consent-to-record": "", "incentive status": "not sent",
        "DM sent (date)": "", "prep note": "", "notes": "",
    }
    decision = evaluate_row(row)
    check("invited row with contact and no stamp is sendable",
          decision["action"] == "send" and decision["address"] == "ada.example@example.com",
          str(decision))
    empty_contact = dict(row, contact="")
    decision = evaluate_row(empty_contact)
    check("empty contact blocks the send (the gate law, fail closed)",
          decision["action"] == "block" and "GATE invited: contact is empty" in decision["reason"],
          str(decision))
    for status, why in (
        ("identified", "not yet invited"),
        ("scheduled", "already outreached"),
        ("incentive-sent", "already outreached"),
        ("withdrawn", "never contacted again"),
    ):
        decision = evaluate_row(dict(row, status=status))
        check(f"{status} row is skipped ({why})",
              decision["action"] == "skip", str(decision))
    decision = evaluate_row(dict(row, status="Maybe Later"))
    check("off-vocabulary status is skipped",
          decision["action"] == "skip" and "locked vocabulary" in decision["reason"],
          str(decision))
    decision = evaluate_row(dict(row, **{"DM sent (date)": "2026-11-20"}))
    check("already-stamped row is skipped (never double-send)",
          decision["action"] == "skip" and "double-send" in decision["reason"],
          str(decision))
    decision = evaluate_row(dict(row, contact="@kit-slack"))
    check("a Slack-only contact is not emailed",
          decision["action"] == "skip" and "no email address" in decision["reason"],
          str(decision))

    # One email per recipient: a duplicate address sends once.
    with tempfile.TemporaryDirectory() as directory:
        participants_path, template_path = _write_fixture(directory)
        tables = parse_tables(PARTICIPANTS)
        external = next(t for t in tables if detect_variant(t["header"])[0] == "external")
        entries = []
        for table_row in external["rows"]:
            row_dict, _extra = row_map(external["header"], table_row["cells"])
            entries.append({"row": row_dict, "line": table_row["line"]})
        plan, skipped = plan_sends(entries)
        check("one plan entry per recipient address (2 sendable rows)",
              len(plan) == 2
              and sorted(item["address"] for item in plan)
              == ["ada.example@example.com", "ida.example@example.com"],
              str([item["address"] for item in plan]))
        check("the duplicate-recipient row is skipped, never sent twice",
              any("duplicate recipient" in entry["reason"] for entry in skipped),
              str([entry["reason"] for entry in skipped]))

        # One recipient per message: exactly one To, never Cc or Bcc.
        message = build_message("team@example.com", "ada.example@example.com",
                                "Subject line", "Body line.")
        check("the message carries exactly one To",
              str(message["To"]) == "ada.example@example.com", str(message["To"]))
        check("the message never carries a Cc or Bcc",
              message["Cc"] is None and message["Bcc"] is None,
              f"Cc={message['Cc']} Bcc={message['Bcc']}")

        # Template law: tokens name approved columns; unknown tokens fail closed.
        subject, body = parse_template(TEMPLATE, "external")
        check("the template token {{name_pseudonym}} names an approved column",
              "name_pseudonym" in {column_token(c) for c in PARTICIPANT_COLUMNS["external"]}
              and "name/pseudonym" in PARTICIPANT_COLUMNS["external"],
              subject)
        merged_subject, merged_body, empty_tokens = merge_template(
            subject, body, {"name/pseudonym": "Ada Example"})
        check("the merge binds the column cell into the subject and body",
              merged_subject == "Interview invite: Ada Example"
              and "Hi Ada Example," in merged_body and empty_tokens == [],
              f"{merged_subject!r} {empty_tokens!r}")
        try:
            parse_template("Subject: hi {{booking_link}}\n\nBody.", "external")
            check("unknown template token fails closed", False, "no error raised")
        except _Usage:
            check("unknown template token fails closed", True)
        for stray_token in ("{{Name}}", "{{prep-note}}"):
            try:
                parse_template(f"Subject: hi {stray_token}\n\nBody.", "external")
                check(f"stray token {stray_token} fails closed", False, "no error raised")
            except _Usage:
                check(f"stray token {stray_token} fails closed", True)
        check("env fallback names pinned (9 values, in order)",
              list(ENV_FALLBACKS.values()) == [
                  "UXR_RECRUIT_SMTP_HOST",
                  "UXR_RECRUIT_SMTP_PORT",
                  "UXR_RECRUIT_SMTP_USER",
                  "UXR_RECRUIT_SMTP_PASSWORD",
                  "UXR_RECRUIT_FROM",
                  "UXR_RECRUIT_USE_TLS",
                  "UXR_RECRUIT_TEMPLATE",
                  "UXR_RECRUIT_WEBAPP_URL",
                  "UXR_RECRUIT_UNSUBSCRIBE",
              ])
        check("Message-ID domain is the sender domain",
              "@team.example.com" in str(build_message(
                  "researcher@team.example.com", "p@example.org", "s", "b")["Message-ID"]))

        # Dry-run default: exit 0, merged preview, no change on disk, masked.
        before = Path(participants_path).read_bytes()
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"}, environ={})
        check("the dry run exits 0", code == EXIT_OK, str(code))
        check("the dry run prints the merged messages",
              "DRY RUN" in out and "Hi Ada Example," in out, out[:120])
        check("the dry run changes nothing on disk",
              Path(participants_path).read_bytes() == before)
        check("the dry run masks the contact by default",
              "ada.example@example.com" not in out and "a***@e***" in out, out[:200])
        code, out = run({"participants": participants_path, "template": template_path,
                         "show_contacts": "1", "today": "2026-11-22"}, environ={})
        check("--show-contacts shows the contact (the explicit flag)",
              "ada.example@example.com" in out, out[:200])

        # --export-sheet: the approved Sheet header, one row per participant,
        # the docstring mapping; exit 0, nothing else changes.
        export_path = Path(directory) / "sheet-export.csv"
        before_export = Path(participants_path).read_bytes()
        code, out = run({"participants": participants_path, "export_sheet": str(export_path)},
                        environ={})
        check("the export exits 0", code == EXIT_OK, str(code))
        check("the export writes no send report lines",
              out.startswith("EXPORT:") and "DRY RUN" not in out, out[:120])
        check("the export changes nothing on disk",
              Path(participants_path).read_bytes() == before_export)
        exported = list(csv.reader(export_path.read_text(encoding="utf-8").splitlines()))
        expected_header = (list(_funnel.DEFAULT_WAVE_TAB_HEADERS)
                           + list(_funnel.PARTICIPANT_COLUMNS["external"]))
        check("the export header is the wave-tab headers + the approved columns",
              exported[0] == expected_header, str(exported[0]))
        check("the export carries one row per external participant",
              len(exported) - 1 == len(external["rows"]), f"{len(exported) - 1} rows")
        id_index = expected_header.index("participant id")
        ada_row = next(r for r in exported[1:] if r[id_index] == "P-01")
        check("the export maps Recipient to the contact email",
              ada_row[expected_header.index("Recipient")] == "ada.example@example.com",
              str(ada_row))
        check("the export maps First name to name/pseudonym",
              ada_row[expected_header.index("First name")] == "Ada Example", str(ada_row))
        check("the export leaves Account Name and Booking link empty",
              ada_row[expected_header.index("Account Name")] == ""
              and ada_row[expected_header.index("Booking link")] == "", str(ada_row))
        check("the export carries the status column verbatim",
              ada_row[expected_header.index("status")] == "invited", str(ada_row))
        kit_row = next(r for r in exported[1:] if r[id_index] == "P-04")
        check("a Slack-only contact exports an empty Recipient",
              kit_row[expected_header.index("Recipient")] == "", str(kit_row))
        drifted = Path(directory) / "participants-drifted.md"
        drifted.write_text(PARTICIPANTS.replace("| prep note |", "| prep notes |"),
                           encoding="utf-8", newline="")
        try:
            run({"participants": str(drifted),
                 "export_sheet": str(Path(directory) / "never.csv")}, environ={})
            check("the export refuses a drifted header (exit 2)", False, "no error raised")
        except _Usage:
            check("the export refuses a drifted header (exit 2)", True)
        try:
            run({"participants": participants_path,
                 "export_sheet": str(Path(directory) / "no-such-dir" / "never.csv")},
                environ={})
            check("the export refuses an unwritable path (exit 2)", False, "no error raised")
        except _Usage:
            check("the export refuses an unwritable path (exit 2)", True)

        # Exit-code law: a failed send exits 1 and stamps nothing.
        SEND_ENV = {"UXR_RECRUIT_SMTP_HOST": "smtp.example.com",
                    "UXR_RECRUIT_FROM": "team@example.com"}

        def deliver_none(plan, settings, report, show):
            report.append(f"FAILED {plan[0]['label']}: [email] refused")
            return set()

        code, out = run({"participants": participants_path, "template": template_path,
                         "send": "1", "today": "2026-11-22"}, environ=SEND_ENV,
                        deliver=deliver_none)
        check("every send failed exits 1", code == EXIT_SEND_FAIL, str(code))
        check("failed rows get no stamp (file byte-identical)",
              Path(participants_path).read_bytes() == before)

        # --send with zero sendable rows and an account present: no send, no
        # spurious refusal, exit 0 (issue 137: the account check fires on the
        # send mode, not on the plan being non-empty).
        def deliver_never(plan, settings, report, show):  # any call here is a bug
            raise AssertionError("no plan, no deliver")

        zero_path = Path(directory) / "participants-zero.md"
        zero_path.write_text(PARTICIPANTS.replace("| invited |", "| scheduled |"),
                             encoding="utf-8", newline="")
        code, out = run({"participants": str(zero_path), "template": template_path,
                         "send": "1", "today": "2026-11-22"}, environ=SEND_ENV,
                        deliver=deliver_never)
        check("--send with zero sendable rows and an account exits 0",
              code == EXIT_OK and "SMTP account" in out and "done: 0 sent, 0 failed" in out,
              f"exit={code} head={out[:160]}")

        # The real send path: stamps + advance per the gate law; exit 0.
        def deliver_all(plan, settings, report, show):
            for item in plan:
                report.append(f"SENT {item['label']}")
            return set(range(len(plan)))

        code, out = run({"participants": participants_path, "template": template_path,
                         "send": "1", "today": "2026-11-22"}, environ=SEND_ENV,
                        deliver=deliver_all)
        after = Path(participants_path).read_text(encoding="utf-8")
        stamped_row = next(line for line in after.splitlines()
                           if line.startswith("| P-01 "))
        untouched_row = next(line for line in after.splitlines()
                             if line.startswith("| P-02 "))
        check("the send exits 0 on full success", code == EXIT_OK, str(code))
        check("the sent row is stamped DM sent (date) and advances to scheduled",
              "| scheduled |" in stamped_row and "| 2026-11-22 |" in stamped_row,
              stamped_row)
        check("rows the send did not touch stay byte-identical",
              "| scheduled | yes | not sent | 2026-11-20 |" in untouched_row,
              untouched_row)
        check("the skipped withdrawn row is never stamped",
              "| withdrawn |" in after and "gus.example@example.com" in after)
        check("a stamped LF file gains no CR bytes (issue 137)",
              b"\r" not in Path(participants_path).read_bytes(),
              repr(Path(participants_path).read_bytes()[:80]))

        # stamp_rows: only stamped cells change; line endings survive.
        text = "| a | b |\n| c | d |\n"
        stamped = stamp_rows(text, [{"line": 1, "status_index": 0, "dm_index": 1,
                                     "status_value": "x", "dm_value": "y"}])
        check("stamp_rows rewrites only the stamped row",
              stamped == "| a | b |\n| x | y |\n", repr(stamped))
        crlf = "| a | b |\r\n| c | d |\r\n"
        stamped_crlf = stamp_rows(crlf, [{"line": 1, "status_index": 0, "dm_index": 1,
                                          "status_value": "x", "dm_value": "y"}])
        check("stamp_rows keeps CRLF endings byte-true (issue 137)",
              stamped_crlf == "| a | b |\r\n| x | y |\r\n", repr(stamped_crlf))

        # A connect/login failure is one clean ERROR line and no sent rows,
        # never a traceback (issue 137); run() then exits 1 by the failed-row law.
        error_report: list[str] = []
        sent_set = _smtp_deliver(
            [{"address": "probe@example.org", "subject": "s", "body": "b", "label": "row X"}],
            {"smtp_host": "127.0.0.1", "smtp_port": "1", "from_address": "team@example.com"},
            error_report,
        )
        check("a refused SMTP connect reports one clean ERROR line (no traceback)",
              sent_set == set() and len(error_report) == 1
              and error_report[0].startswith("ERROR connect/login to 127.0.0.1:"),
              repr(error_report))

    # Usage law: exit 2 surfaces as _Usage (main prints it and exits 2).
    for name, args in (
        ("missing participants path", {"template": "t"}),
        ("missing template path", {"participants": "p"}),
    ):
        try:
            run(args, environ={})
            check(f"usage: {name} fails closed", False, "no error raised")
        except _Usage:
            check(f"usage: {name} fails closed", True)
    try:
        run({"participants": "/no/such/file.md", "template": "t"}, environ={})
        check("usage: unreadable participants file fails closed", False, "no error raised")
    except _Usage:
        check("usage: unreadable participants file fails closed", True)

    # --send without an SMTP account refuses (usage), dry run never needs one.
    # The config layer is pointed at an empty file (issue 137), so the check
    # holds on a machine whose real config/org.yaml carries an account.
    with tempfile.TemporaryDirectory() as directory:
        participants_path, template_path = _write_fixture(directory)
        empty_config = Path(directory) / "empty-org.yaml"
        empty_config.write_text("", encoding="utf-8")
        values, source = load_send_settings(environ={}, config_file=str(empty_config))
        check("an injected empty config carries no account values",
              not values["smtp_host"] and not values["from_address"],
              f"source={source} host={values['smtp_host']}")
        # Regression (2026-11-23 mail-merge test wave): the example file's
        # documentation defaults (smtp_port 587, use_tls true) must not
        # shadow the env fallbacks — an env-only account must resolve the
        # env port, not the example port.
        values, source = load_send_settings(
            environ={"UXR_RECRUIT_SMTP_HOST": "smtp.example.com",
                     "UXR_RECRUIT_SMTP_PORT": "1",
                     "UXR_RECRUIT_FROM": "team@example.com"},
            config_file=str(empty_config),
        )
        check("env port beats the example-file default",
              values["smtp_port"] == "1" and values["use_tls"] is None,
              f"source={source} port={values['smtp_port']} tls={values['use_tls']}")
        try:
            run({"participants": participants_path, "template": template_path,
                 "send": "1", "today": "2026-11-22"},
                environ={}, config_file=str(empty_config))
            check("--send without an SMTP account refuses", False, "no error raised")
        except _Usage as exc:
            check("--send without an SMTP account refuses",
                  "SMTP account" in str(exc), str(exc))
        zero_path = Path(directory) / "participants-zero.md"
        zero_path.write_text(PARTICIPANTS.replace("| invited |", "| scheduled |"),
                             encoding="utf-8", newline="")
        try:
            run({"participants": str(zero_path), "template": template_path,
                 "send": "1", "today": "2026-11-22"},
                environ={}, config_file=str(empty_config))
            check("--send with zero sendable rows and no account refuses", False,
                  "no error raised")
        except _Usage as exc:
            check("--send with zero sendable rows and no account refuses",
                  "SMTP account" in str(exc), str(exc))

        # Unsubscribe footer: rides only when unsubscribe is on (default)
        # and a webapp URL is set; config layer and env fallbacks both work.
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"},
                        environ={"UXR_RECRUIT_WEBAPP_URL": "https://script.example.com/exec"},
                        config_file=str(empty_config))
        check("the footer rides on a webapp URL (default unsubscribe true)",
              "To stop these emails, open: https://script.example.com/exec?u=P-01" in out,
              out[:300])
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"},
                        environ={"UXR_RECRUIT_WEBAPP_URL": "https://script.example.com/exec",
                                 "UXR_RECRUIT_UNSUBSCRIBE": "false"},
                        config_file=str(empty_config))
        check("unsubscribe false removes the footer", "To stop these emails" not in out)
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"},
                        environ={}, config_file=str(empty_config))
        check("no webapp URL means no footer", "To stop these emails" not in out)
        footer_config = Path(directory) / "org-footer.yaml"
        footer_config.write_text(
            "recruit:\n  email:\n"
            "    webapp_url: https://config.example.com/exec\n"
            "    smtp_host: smtp.config.example.com\n"
            "    from_address: team@example.com\n",
            encoding="utf-8",
        )
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"},
                        environ={}, config_file=str(footer_config))
        check("a config webapp_url alone adds the footer",
              "To stop these emails, open: https://config.example.com/exec?u=P-01" in out,
              out[:300])
        values, source = load_send_settings(environ={}, config_file=str(footer_config))
        check("config recruit.email values load (config layer regression pin)",
              values["webapp_url"] == "https://config.example.com/exec"
              and values["smtp_host"] == "smtp.config.example.com"
              and source == "config recruit.email.*", f"{values} {source}")
        off_config = Path(directory) / "org-unsub-off.yaml"
        off_config.write_text(
            "recruit:\n  email:\n"
            "    webapp_url: https://config.example.com/exec\n"
            "    unsubscribe: false\n",
            encoding="utf-8",
        )
        code, out = run({"participants": participants_path, "template": template_path,
                         "today": "2026-11-22"}, environ={}, config_file=str(off_config))
        check("config unsubscribe false removes the footer", "To stop these emails" not in out)
        port_config = Path(directory) / "org-port.yaml"
        port_config.write_text(
            "recruit:\n  email:\n"
            "    smtp_host: smtp.config.example.com\n"
            "    smtp_port: 587\n"
            "    from_address: team@example.com\n",
            encoding="utf-8",
        )
        values, source = load_send_settings(
            environ={"UXR_RECRUIT_SMTP_PORT": "2525"}, config_file=str(port_config))
        check("an example-file port resets so the env port applies",
              values["smtp_port"] == "2525", f"{values} {source}")

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
