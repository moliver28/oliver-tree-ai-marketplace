"""Recruit enforcement selftest (issue 51): the approved column law.

Checks that ``scripts/recruit_funnel.py`` carries the approved
participants-table column sets (MO column law 2026-11-22), the locked
eight-value status vocabulary (the mail-merge wave adds ``cancelled``),
and the status-gate map exactly as the recruit command states it, and
that the additive checkers enforce the gate law without touching the
funnel outputs. Rides the smoke check-3
glob; parity enrollment is out of scope (W2 adapters precedent).
"""
from _harness import bind

bind("scripts.recruit_funnel", globals())


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/recruit_enforcement.py selftest")

    # The approved column law (issue 51, MO 2026-11-22): exact lists, exact order.
    check(
        "internal column set matches the approved list",
        PARTICIPANT_COLUMNS["internal"] == (
            "participant id", "name", "role/segment", "team/org area",
            "source (org-chart path)", "screener result", "status",
            "consent-to-record", "DM sent (date)", "notes",
        ),
        str(PARTICIPANT_COLUMNS["internal"]),
    )
    check(
        "external column set matches the approved list",
        PARTICIPANT_COLUMNS["external"] == (
            "participant id", "name/pseudonym", "contact", "source (panel/channel)",
            "screener result", "status", "consent-to-record", "incentive status",
            "DM sent (date)", "prep note", "notes",
        ),
        str(PARTICIPANT_COLUMNS["external"]),
    )
    check(
        "status vocabulary is the locked eight values",
        PARTICIPANT_STATUSES == (
            "identified", "screened", "invited", "scheduled", "completed",
            "incentive-sent", "withdrawn", "cancelled",
        ),
        str(PARTICIPANT_STATUSES),
    )
    check(
        "every gate column is a column of its variant",
        all(
            column in PARTICIPANT_COLUMNS[variant]
            for variant, gates in PARTICIPANT_STATUS_GATES.items()
            for columns in gates.values()
            for column in columns
        ),
        str(PARTICIPANT_STATUS_GATES),
    )
    check("withdrawn has no gate entry",
          "withdrawn" not in PARTICIPANT_STATUS_GATES["internal"]
          and "withdrawn" not in PARTICIPANT_STATUS_GATES["external"])
    check("cancelled has no gate entry and needs nothing",
          "cancelled" not in PARTICIPANT_STATUS_GATES["internal"]
          and "cancelled" not in PARTICIPANT_STATUS_GATES["external"]
          and participant_gate_lines(
              {column: "" for column in PARTICIPANT_COLUMNS["external"]},
              "cancelled", "external") == [])

    # Header checker: the approved sets pass; drift is reported per kind.
    check("approved internal header passes",
          participant_header_issues(list(PARTICIPANT_COLUMNS["internal"]), "internal") == [])
    check("approved external header passes",
          participant_header_issues(list(PARTICIPANT_COLUMNS["external"]), "external") == [])
    check("header compare is case-insensitive and strips cells",
          participant_header_issues(
              [" Participant ID ", "NAME", "Role/segment", "Team/org area",
               "Source (org-chart path)", "Screener result", "Status",
               "Consent-to-record", "DM sent (date)", "Notes"], "internal") == [])
    missing = participant_header_issues(
        [c for c in PARTICIPANT_COLUMNS["internal"] if c != "consent-to-record"], "internal")
    check("missing approved column is reported",
          any("missing 'consent-to-record'" in line for line in missing), str(missing))
    reordered = list(PARTICIPANT_COLUMNS["internal"])
    reordered[1], reordered[2] = reordered[2], reordered[1]
    order_issues = participant_header_issues(reordered, "internal")
    check("reordered approved column is reported",
          any("out of order" in line for line in order_issues), str(order_issues))
    extra = participant_header_issues(
        list(PARTICIPANT_COLUMNS["external"]) + ["boss name"], "external")
    check("unrecognized extra column is reported",
          any("extra column 'boss name'" in line for line in extra), str(extra))
    duplicated = list(PARTICIPANT_COLUMNS["external"]) + ["status"]
    dup_issues = participant_header_issues(duplicated, "external")
    check("duplicated approved column is named as a duplicate",
          any("duplicate column 'status'" in line for line in dup_issues)
          and not any("out of order" in line for line in dup_issues), str(dup_issues))
    check("unknown variant is reported",
          participant_header_issues([], "panel") == [
              "participant columns: unknown variant 'panel' (use internal or external)"])

    # Status vocabulary checker.
    check("locked statuses pass", all(participant_status_issue(s) == "" for s in PARTICIPANT_STATUSES))
    issue = participant_status_issue("Maybe Later")
    check("off-vocabulary status is flagged", "outside the locked vocabulary" in issue, issue)

    # Gate law, external variant: each status gate blocks on its empty column.
    full = {column: "x" for column in PARTICIPANT_COLUMNS["external"]}
    full["consent-to-record"] = "yes"
    full["status"] = "completed"
    for status in ("identified", "screened", "invited", "scheduled", "completed", "incentive-sent"):
        check(f"fully filled external row advances to {status}",
              participant_gate_lines(full, status, "external") == [],
              str(participant_gate_lines(full, status, "external")))
    for status, column in (
        ("screened", "screener result"),
        ("invited", "contact"),
        ("scheduled", "DM sent (date)"),
    ):
        row = dict(full, **{column: ""})
        lines = participant_gate_lines(row, status, "external")
        check(f"empty {column} blocks {status} (external)",
              lines == [f"GATE {status}: {column} is empty"], str(lines))

    # Gate law, internal variant: invited gates on the org-chart source.
    full_internal = {column: "x" for column in PARTICIPANT_COLUMNS["internal"]}
    check("filled org-chart source advances internal invited",
          participant_gate_lines(full_internal, "invited", "internal") == [])
    row = dict(full_internal, **{"source (org-chart path)": ""})
    lines = participant_gate_lines(row, "invited", "internal")
    check("empty org-chart source blocks internal invited",
          lines == ["GATE invited: source (org-chart path) is empty"], str(lines))
    check("contact alone does not satisfy the internal invited gate",
          participant_gate_lines(
              dict(full_internal, **{"source (org-chart path)": "", "contact": "x"}),
              "invited", "internal") == ["GATE invited: source (org-chart path) is empty"])

    # completed: consent-to-record must hold yes, not merely something.
    for value, allowed in (("yes", True), ("Yes", True), ("", False), ("no", False), ("pending", False)):
        row = dict(full_internal, **{"consent-to-record": value})
        lines = participant_gate_lines(row, "completed", "internal")
        check(f"consent-to-record {value!r} {'advances' if allowed else 'blocks'} completed",
              (lines == []) if allowed else any("consent-to-record is not yes" in line or
                                               "consent-to-record is empty" in line
                                               for line in lines), str(lines))

    # incentive-sent: completed first, then no column gate blocks a filled row.
    row = dict(full, **{"status": "scheduled"})
    lines = participant_gate_lines(row, "incentive-sent", "external")
    check("incentive-sent from scheduled is blocked",
          lines == ["GATE incentive-sent: the row is not at completed"], str(lines))
    row = dict(full, **{"status": "completed"})
    check("incentive-sent from a completed row advances",
          participant_gate_lines(row, "incentive-sent", "external") == [])

    # withdrawn any time, from any row; unknown statuses pass through.
    empty = {column: "" for column in PARTICIPANT_COLUMNS["external"]}
    check("withdrawn is allowed from a fully empty row",
          participant_gate_lines(empty, "withdrawn", "external") == [])
    check("withdrawn is allowed from internal rows too",
          participant_gate_lines(
              {column: "" for column in PARTICIPANT_COLUMNS["internal"]},
              "withdrawn", "internal") == [])
    check("status outside the vocabulary passes through unchecked",
          participant_gate_lines(empty, "Outreach Sent", "external") == [])
    check("unknown variant is reported by the gate checker, never passed",
          participant_gate_lines(empty, "screened", "panel") == [
              "participant gates: unknown variant 'panel' (use internal or external)"])

    # Additive proof: the funnel table path still renders unchanged.
    _table, numbers = build_table(TABLE_SPEC, config={}, funnel_data=FUNNEL_DATA, wave="Wave 1")
    check("funnel table still computes from the fixture spec",
          numbers["totals"]["Scheduled"][4] == 1 and numbers["totals"]["Bounced"][2] == 1,
          str(numbers["totals"]))

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
