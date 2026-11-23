from _harness import bind

bind("scripts.recruit_funnel", globals())
def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/recruit_funnel.py selftest")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        spec_file = tmp_path / "ABC-1.spec.json"
        spec_file.write_text(json.dumps(TABLE_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")
        data_file = tmp_path / "funnel.json"
        data_file.write_text(json.dumps(FUNNEL_DATA, ensure_ascii=False, indent=2), encoding="utf-8")
        before = spec_file.read_bytes()

        # --status with no funnel key: nine-row table, no funnel usage, zero writes
        code, output = run({"spec": str(spec_file), "status": "1"}, config={})
        check("--status exits 0", code == EXIT_OK, f"code={code}")
        for row_name in TABLE_ROWS:
            check(f"table prints row {row_name!r}", f"| {row_name} |" in output)
        for column in TABLE_COLUMNS:
            check(f"table prints column {column!r}", column in output)
        check("spec file is byte-identical after --status", spec_file.read_bytes() == before)
        check("zero writes: no funnel data needed, nothing written", "wave:" in output)

        # roster-derived numbers (no funnel key beyond fit)
        numbers_spec = json.loads(spec_file.read_text(encoding="utf-8"))
        numbers_spec.pop("funnel")
        plain_file = tmp_path / "plain.json"
        plain_file.write_text(json.dumps(numbers_spec, ensure_ascii=False), encoding="utf-8")
        code, output = run({"spec": str(plain_file)}, config={})
        check("no funnel key still prints the table", "| Fit |" in output and code == EXIT_OK)
        _table, numbers = build_table(numbers_spec, config={})
        check("internal Sent counts Outreach Sent only", numbers["totals"]["Sent"][0] == 1)
        check("external Sent counts roster channel", numbers["totals"]["Sent"][4] == 1)
        check(
            "Scheduled counts the four statuses",
            numbers["totals"]["Scheduled"][0] == 1 and numbers["totals"]["Scheduled"][4] == 1,
        )

        # table with funnel data: this-wave never exceeds total
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(data_file), "wave": "Wave 1"}, config={}
        )
        check("funnel-data table exits 0", code == EXIT_OK, f"code={code}")
        check("output never contains an email address", "@" not in output)
        _table, numbers = build_table(TABLE_SPEC, config={}, funnel_data=FUNNEL_DATA, wave="Wave 1")
        sent_t, sent_w = numbers["totals"]["Sent"], numbers["this_wave"]["Sent"]
        check(
            "this-wave Sent never exceeds total",
            all(w <= t for t, w in zip(sent_t, sent_w)),
            f"totals={sent_t} this={sent_w}",
        )
        check("bounced count comes from the sheet", numbers["totals"]["Bounced"][2] == 1)
        check("skips count as not-allowed this wave", numbers["this_wave"]["Not allowed"][2] == 1)

        # preflight: bad booking link exits 2 (acceptance)
        bad_link_data = json.loads(json.dumps(FUNNEL_DATA))
        bad_link_data["tabs"]["Wave 1"]["rows"][0]["booking_link"] = "https://docs.example.com/doc/1"
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps(bad_link_data), encoding="utf-8")
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(bad_file), "wave": "Wave 1", "preflight": "1"},
            config={},
        )
        check("preflight exits 2 on a non-booking-page URL", code == EXIT_BLOCKED, output)
        check("BLOCK line names the reason", "booking link is not a booking-page URL" in output)

        # preflight: Google appointment-schedule links pass (issue 50 fix:
        # the shipped pattern carried a hyphenated shape Google never
        # emits, so a real appointment link was refused and a
        # redirect-wrapped URL could end up in the send instead). The
        # share link Google's Copy link emits and the underlying page it
        # resolves to both pass; a redirect wrapper still blocks.
        for label, link in (
            ("share", "https://calendar.app.google/AcZssZ0example123"),
            ("page", "https://calendar.google.com/calendar/u/0/appointments/schedules/AcZssZ0example123"),
        ):
            google_data = json.loads(json.dumps(FUNNEL_DATA))
            google_data["tabs"]["Wave 1"]["rows"][0]["booking_link"] = link
            google_file = tmp_path / f"google_{label}.json"
            google_file.write_text(json.dumps(google_data), encoding="utf-8")
            code, output = run(
                {"spec": str(spec_file), "funnel_data": str(google_file), "wave": "Wave 1", "preflight": "1"},
                config={},
            )
            check(f"google appointment {label} link passes preflight", code == EXIT_OK, output)
        redirect_data = json.loads(json.dumps(FUNNEL_DATA))
        redirect_data["tabs"]["Wave 1"]["rows"][0]["booking_link"] = (
            "https://www.google.com/url?q=https://calendar.app.google/AcZssZ0example123"
        )
        redirect_file = tmp_path / "google_redirect.json"
        redirect_file.write_text(json.dumps(redirect_data), encoding="utf-8")
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(redirect_file), "wave": "Wave 1", "preflight": "1"},
            config={},
        )
        check("redirect-wrapped link still blocks", code == EXIT_BLOCKED, output)

        # preflight: suppression and duplication reasons
        blocked_data = json.loads(json.dumps(FUNNEL_DATA))
        blocked_data["tabs"]["Wave 2"]["rows"].append(
            dict(blocked_data["tabs"]["Wave 1"]["rows"][0])  # same person, second tab
        )
        blocked_data["tabs"]["Wave 1"]["rows"][1]["booking_link"] = (
            "https://calendly.com/team/renewal-60; https://savvycal.com/team/backup"
        )
        blocked_data["open_deal_accounts"] = ["Okta"]
        blocked_data["dnc_emails"] = ["dee@dropbox.example.com"]
        blocked_file = tmp_path / "blocked.json"
        blocked_file.write_text(json.dumps(blocked_data), encoding="utf-8")
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(blocked_file), "wave": "Wave 1", "preflight": "1"},
            config={},
        )
        check("preflight exits 2 when rows are blocked", code == EXIT_BLOCKED)
        check("listed twice is a block reason", "listed twice" in output)
        check("open-deal account blocks", "open deal account" in output)
        check("dnc email blocks", "do-not-contact" in output)
        check("not-one-value link blocks", "not one value" in output)
        check("no email address in BLOCK lines", "@" not in output)

        # preflight: clean wave exits 0 with the exact success line
        clean_data = json.loads(json.dumps(FUNNEL_DATA))
        clean_data["tabs"]["Wave 2"] = {
            "rows": [
                {"account": "Lantern", "first_name": "Lou", "email": "lou@lantern.example.com",
                 "email_sent": "", "booking_link": "https://calendly.com/team/renewal-60"}
            ],
            "skips": [],
        }
        clean_file = tmp_path / "clean.json"
        clean_file.write_text(json.dumps(clean_data), encoding="utf-8")
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(clean_file), "wave": "Wave 2", "preflight": "1"},
            config={},
        )
        check("clean wave passes preflight", code == EXIT_OK, output)
        check("success line is exact", "PREFLIGHT OK: 1 rows ready on Wave 2" in output)

        # preflight: empty wave -> no rows ready
        empty_data = json.loads(json.dumps(FUNNEL_DATA))
        empty_data["tabs"]["Wave 2"] = {"rows": [], "skips": []}
        empty_file = tmp_path / "empty.json"
        empty_file.write_text(json.dumps(empty_data), encoding="utf-8")
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(empty_file), "wave": "Wave 2", "preflight": "1"},
            config={},
        )
        check("no rows ready exits 2 with the reason", code == EXIT_BLOCKED and "no rows ready" in output)

        # preflight without funnel data
        code, output = run({"spec": str(spec_file), "preflight": "1"}, config={})
        check("preflight without funnel data exits 2", code == EXIT_BLOCKED and "funnel data" in output)

        # --reminder: business-day math and draft-only output
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(data_file), "reminder": "1",
             "today": "2026-11-06", "wave": "Wave 1"},
            config={"recruit": {"nudge_after_days": 2}},
        )
        check("reminder lists a send 3+ business days old", "NUDGE Wave 1" in output and "Ada" in output, output)
        check("reminder is draft-only wording", "draft only" in output)
        code, output = run(
            {"spec": str(spec_file), "funnel_data": str(data_file), "reminder": "1",
             "today": "2026-11-03", "wave": "Wave 1"},
            config={"recruit": {"nudge_after_days": 2}},
        )
        check("send under the window is not nudged", "No nudges due" in output, output)
        check("weekend does not count as a business day",
              business_days_between(date(2026, 11, 5), date(2026, 11, 9)) == 2)
        check("same day is zero business days", business_days_between(date(2026, 11, 6), date(2026, 11, 6)) == 0)

        # V1 draft check (acceptance: http fails)
        draft_bad = tmp_path / "draft_bad.txt"
        draft_bad.write_text(
            "Hi {{First name}}, book a time: https://calendly.com/team/renewal-60 - {{Booking link}}",
            encoding="utf-8",
        )
        code, output = run({"check_draft": str(draft_bad)}, config={})
        check("V1 fails when the draft body contains http", code == EXIT_V1 and "V1 FAIL" in output)
        draft_missing = tmp_path / "draft_missing.txt"
        draft_missing.write_text("Hi {{First name}}, any of these times work?", encoding="utf-8")
        code, output = run({"check_draft": str(draft_missing)}, config={})
        check("V1 fails on a missing merge token", code == EXIT_V1 and "Booking link" in output)
        draft_ok = tmp_path / "draft_ok.txt"
        draft_ok.write_text(
            "Hi {{First name}}, pick any time on the booking page (link in the sheet): {{Booking link}}",
            encoding="utf-8",
        )
        code, output = run({"check_draft": str(draft_ok)}, config={})
        check("V1 passes on tokens without http", code == EXIT_OK and "V1 OK" in output, output)

        # scrub is a final safety net even on hostile data
        hostile = scrub("contact bo@box.example.com now")
        check("scrub redacts email addresses", "@" not in hostile and "[email]" in hostile)

        # usage errors
        try:
            run({}, config={})
            check("missing --spec raises usage", False)
        except _Usage:
            check("missing --spec raises usage", True)
        try:
            run({"spec": str(tmp_path / "nope.json")}, config={})
            check("unreadable spec raises usage", False)
        except _Usage:
            check("unreadable spec raises usage", True)

        # cancelled: the eighth locked status (the 2026-11-23 mail-merge
        # ruling). It needs nothing and is legal from any status.
        check("cancelled is in the locked vocabulary", "cancelled" in PARTICIPANT_STATUSES)
        check("cancelled passes the vocabulary checker",
              participant_status_issue("cancelled") == "")
        check("cancelled carries no gate entry in either variant",
              "cancelled" not in PARTICIPANT_STATUS_GATES["internal"]
              and "cancelled" not in PARTICIPANT_STATUS_GATES["external"])
        empty_row = {column: "" for column in PARTICIPANT_COLUMNS["external"]}
        check("cancelled needs nothing (no gate on a fully empty row)",
              participant_gate_lines(empty_row, "cancelled", "external") == [])
        check("cancelled is legal from every status",
              all(
                  participant_gate_lines(dict(empty_row, status=frm), "cancelled", "external") == []
                  for frm in PARTICIPANT_STATUSES if frm != "cancelled"
              ))
        code, output = run({"spec": str(spec_file), "status": "1"}, config={})
        check("the funnel table still renders with the eight-value vocabulary",
              code == EXIT_OK and "| Fit |" in output, f"code={code}")

        # --prep: the printer over a Prep-tab export (the mail-merge wave).
        prep_file = tmp_path / "prep.csv"
        prep_file.write_text(
            "when,event,email,items\n"
            "2026-11-24 10:00,Session with Ada,ada@example.com,study title; consent form\n"
            "2026-11-25 13:00,Session with Rook,rook@example.com,prototype link\n",
            encoding="utf-8",
        )
        code, output = run({"prep": str(prep_file)}, config={})
        check("--prep exits 0", code == EXIT_OK, f"code={code}")
        check("--prep prints one brief per row",
              output.count("|") >= 4
              and "2026-11-24 10:00 | Session with Ada | study title; consent form" in output
              and "2026-11-25 13:00 | Session with Rook | prototype link" in output,
              output)
        check("--prep never prints the email column",
              "@" not in output, output)
        empty_prep = tmp_path / "prep-empty.csv"
        empty_prep.write_text("when,event,email,items\n", encoding="utf-8")
        code, output = run({"prep": str(empty_prep)}, config={})
        check("an empty prep export prints one no-prep-briefs line and exits 0",
              code == EXIT_OK and output.strip() == "no prep briefs", output)
        header_prep = tmp_path / "prep-header.csv"
        header_prep.write_text("time,person\n", encoding="utf-8")
        try:
            run({"prep": str(header_prep)}, config={})
            check("a prep export without the needed columns raises usage", False)
        except _Usage:
            check("a prep export without the needed columns raises usage", True)
        try:
            run({"prep": str(tmp_path / "no-such-prep.csv")}, config={})
            check("a missing prep file raises usage", False)
        except _Usage:
            check("a missing prep file raises usage", True)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
