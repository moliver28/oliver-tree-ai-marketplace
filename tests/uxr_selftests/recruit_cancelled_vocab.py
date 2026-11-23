"""Vocabulary selftest (the mail-merge wave): cancelled in the docs.

Text-level checks: the recruit command's status-gate section lists
`cancelled` (lowercase, exact spelling) with the needs-nothing gate,
the workspace participants template carries `cancelled` in its locked
vocabulary line plus the leaves-only-by-the-recruit-flow rule, step 12
names both cancellation stores with the right spelling per store
(lowercase on the workspace table, capital-C ``Cancelled`` on the spec
roster through ``roster_apply.py``), and ``scripts/recruit_funnel.py``
carries the eighth locked status. Rides the smoke check-3 glob.
"""
from _harness import bind

bind("scripts.recruit_funnel", globals())

from pathlib import Path

EXIT_SELFTEST = 3  # selftest failure exit (runner convention)

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"
COMMAND = (PLUGIN_ROOT / "commands" / "uxr-recruit.md").read_text(encoding="utf-8")
TEMPLATE = (
    PLUGIN_ROOT / "templates" / "workspace" / "recruitment" / "participants.md"
).read_text(encoding="utf-8")

GATES_SECTION = COMMAND.split("## Status gates")[1].split("## Internal flow")[0]


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/recruit_cancelled_vocab.py selftest")

    # The command's gate section: vocabulary line, needs-nothing gate,
    # exact lowercase spelling.
    check("the command's vocabulary line carries cancelled",
          "incentive-sent, withdrawn, cancelled" in GATES_SECTION, GATES_SECTION[:200])
    check("the command's gate list gains the needs-nothing cancelled bullet",
          "`cancelled` needs nothing; it is allowed from any status at any" in GATES_SECTION,
          GATES_SECTION[-300:])
    check("the command spells it cancelled (lowercase) throughout",
          "CANCELLED" not in COMMAND and "Canceled" not in COMMAND)
    check("the command's external step 12 reads the Tracking export and batch-applies",
          "Tracking tab export CSV" in COMMAND and "one `roster_apply.py` batch" in COMMAND
          and "one re-invite" in COMMAND)
    # Step 12 names both cancellation stores with the right spelling per store:
    # the workspace table is lowercase, the spec roster (roster_apply.py's
    # allowed-status list) is capitalized, so a lowercase roster write exits 3.
    check("step 12 spells lowercase cancelled on the workspace table",
          "`cancelled` (lowercase) in the workspace participants table" in COMMAND,
          COMMAND[COMMAND.find("Tracking tab export"):][:400])
    check("step 12 spells capital-C Cancelled on the spec roster",
          "`Cancelled` (capital C) on the spec roster" in COMMAND,
          COMMAND[COMMAND.find("Tracking tab export"):][:400])
    check("step 12 never routes a lowercase write through roster_apply",
          "a lowercase write exits 3" in COMMAND,
          COMMAND[COMMAND.find("Tracking tab export"):][:400])
    check("the command's external step 7 points at the google screener setup",
          "google/README.md" in COMMAND and "screener form" in COMMAND)
    check("the command's Inputs carry --prep=<csv>", "--prep=<csv>" in COMMAND)
    check("the command carries a --prep step through recruit_funnel",
          "recruit_funnel.py\" --prep" in COMMAND and "no prep briefs" in COMMAND)

    # The workspace template: vocabulary line plus the leaves rule.
    check("the template's vocabulary line carries cancelled",
          "incentive-sent, withdrawn, cancelled" in TEMPLATE, TEMPLATE[:300])
    check("the template pins the leaves-cancelled-only-by-the-recruit-flow rule",
          "A row leaves `cancelled` only by the recruit flow." in TEMPLATE)
    check("the template spells it cancelled (lowercase)",
          "CANCELLED" not in TEMPLATE and "Canceled" not in TEMPLATE)

    # The funnel source carries the eighth locked status.
    check("the funnel source carries cancelled in the locked vocabulary",
          "cancelled" in PARTICIPANT_STATUSES)
    check("cancelled has no gate entry in the funnel source",
          "cancelled" not in PARTICIPANT_STATUS_GATES["internal"]
          and "cancelled" not in PARTICIPANT_STATUS_GATES["external"])

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
