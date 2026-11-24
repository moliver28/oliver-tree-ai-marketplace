"""Recruit pipeline selftest (issue 50): the deterministic stage law.

Checks that ``scripts/recruit_funnel.py`` carries the configurable
recruitment pipeline (the shipped default order, the known deterministic
stage names, the unknown-stage usage error), the three suppress-stage
checks with the never-recontact status law, the suppression-list reader
that fails closed, and that the config contract and the command and
reference docs carry the same law. The plugin ships no org-specific
suppression list, name, or default (the org-specific-data scan at the
end). Rides the smoke check-3 glob; parity enrollment is out of scope
(W2 adapters precedent).
"""
from _harness import bind

bind("scripts.recruit_funnel", globals())

import tempfile  # selftest-only import (no shipped surface)
from pathlib import Path

EXIT_SELFTEST = 3  # selftest failure exit (runner convention)

_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"


def _read(*parts: str) -> str:
    return (_PLUGIN_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/recruit_pipeline.py selftest")

    # The shipped pipeline law (issue 50): exact default order, exact
    # known stage set, each stage named to a deterministic action.
    check("the default pipeline is the shipped order",
          DEFAULT_PIPELINE == ("identify", "screen", "suppress", "invite", "schedule", "send"),
          str(DEFAULT_PIPELINE))
    check("every default stage carries a deterministic action line",
          all(name in KNOWN_STAGES and KNOWN_STAGES[name].strip() for name in DEFAULT_PIPELINE),
          str(sorted(KNOWN_STAGES)))
    check("the known stage set is exactly the default set",
          set(KNOWN_STAGES) == set(DEFAULT_PIPELINE), str(sorted(KNOWN_STAGES)))
    check("resolve_pipeline returns the default with no config",
          resolve_pipeline(None) == DEFAULT_PIPELINE)
    check("resolve_pipeline returns the default with an empty section",
          resolve_pipeline({"recruitment": {"pipeline": []}}) == DEFAULT_PIPELINE)
    check("resolve_pipeline honors a custom order",
          resolve_pipeline({"recruitment": {"pipeline": ["suppress", "invite"]}})
          == ("suppress", "invite"))
    try:
        resolve_pipeline({"recruitment": {"pipeline": ["identify", "launch"]}})
        check("an unknown stage is a usage error", False, "no error raised")
    except _Usage as exc:
        check("an unknown stage is a usage error",
              "launch" in str(exc) and "identify" in str(exc), str(exc))

    # The suppress-stage law: three checks, never-recontact statuses,
    # the skip marking, and the fail-closed list reader.
    check("the suppress checks are the three shipped checks in order",
          SUPPRESSION_CHECKS == ("status law", "bounce", "suppression list"),
          str(SUPPRESSION_CHECKS))
    check("the never-recontact statuses are the locked four",
          NEVER_RECONTACT_STATUSES
          == frozenset({"completed", "incentive-sent", "withdrawn", "cancelled"}),
          str(sorted(NEVER_RECONTACT_STATUSES)))
    check("the suppression skip marking follows the skip law",
          SUPPRESSION_SKIP_PREFIX == "skip: suppressed", SUPPRESSION_SKIP_PREFIX)
    with tempfile.TemporaryDirectory() as directory:
        list_file = Path(directory) / "list.txt"
        list_file.write_text("one@example.com\n\nExample Co\n", encoding="utf-8")
        check("the list reader keeps one identifier per line and drops blanks",
              read_suppression_ids(str(list_file)) == ["one@example.com", "Example Co"],
              str(read_suppression_ids(str(list_file))))
        try:
            read_suppression_ids(str(Path(directory) / "absent.txt"))
            check("the list reader fails closed on a missing file", False, "no error raised")
        except _Usage:
            check("the list reader fails closed on a missing file", True)

    # The config contract carries the keys (example file + REQUIRED_KEYS).
    example = _read("config", "org.example.yaml")
    check("the example config documents the recruitment section",
          "recruitment:" in example and "pipeline:" in example, "section missing")
    check("the example config ships the default stage list verbatim",
          'pipeline: ["identify", "screen", "suppress", "invite", "schedule", "send"]' in example,
          "default list line missing")
    check("the example config ships a generic empty suppression list",
          'suppression_list: ""' in example, "empty key line missing")
    config_py = _read("lib", "config.py")
    for dotted in ("recruitment.pipeline", "recruitment.suppression_list",
                   "recruitment.meeting_service"):
        check(f"REQUIRED_KEYS carries {dotted}", f'"{dotted}",' in config_py, "key missing")

    # The command and reference docs carry the same law.
    command = _read("commands", "uxr-recruit.md")
    check("the command states the pipeline section",
          "## Pipeline and suppression (deterministic, zero model calls)" in command,
          "section missing")
    check("the command states the default stage order",
          "identify, screen, suppress, invite, schedule, send" in command, "order missing")
    check("the command states the three suppress checks",
          all(phrase in command for phrase in (
              "Status law:", "Bounce marks:", "Suppression list:")), "checks missing")
    check("the command states the never-recontact statuses",
          all(status in command for status in (
              "`completed`", "`incentive-sent`", "`withdrawn`", "`cancelled`")),
          "statuses missing")
    check("the command states the suppression skip marking",
          "skip: suppressed" in command and "Never" in command, "marking missing")
    check("the command states the pipeline check and its exit law",
          "--pipeline-check" in command and "exits 2" in command, "check missing")
    reference = _read("references", "recruit-outreach.md")
    check("the reference states the suppress stage",
          "## The suppress stage (deterministic, zero model calls)" in reference,
          "section missing")
    check("the reference names the three suppression skip reasons",
          all(reason in reference for reason in (
              "skip: suppressed (status law)",
              "skip: suppressed (bounce)",
              "skip: suppressed (suppression list)")), "reasons missing")
    check("the reference V4 line carries the suppressed counts",
          "suppressed counts" in reference and "suppression-list" in reference, "V4 missing")

    # The meeting-service law (issue 55): the default never auto-attaches
    # a conferencing link; the five documented values; V2 re-asserted.
    check("the example config ships the appointment-link default",
          'meeting_service: "appointment-link"' in example, "default missing")
    check("the example config documents the five values",
          all(value in example for value in (
              "appointment-link", "none", "google-meet", "zoom", "other")),
          "values missing")
    check("the command carries the meeting-service safety rule",
          "Meeting-service law" in command and "never auto-attach" in command,
          "law missing")
    check("the command names all five meeting-service values",
          all(value in command for value in (
              "`appointment-link`", "`none`", "`google-meet`", "`zoom`", "`other`")),
          "values missing")
    check("the command states the google-meet double condition",
          "unless the config names" in command and "`google-meet` and the user's own flow creates it" in command,
          "condition missing")
    check("the reference carries the meeting-service law",
          "## The meeting-service law" in reference and "never auto-attach" in reference,
          "law missing")
    check("the reference re-asserts the V2 self-test law",
          "The V2 self-test law is unchanged" in reference and "no redirect URL" in reference,
          "V2 missing")

    # No org-specific list, name, or default ships anywhere (issue 50).
    # The needle is split so this scan's own source never matches.
    needle = "mid" + "ship"
    offenders = [
        str(path.relative_to(_PLUGIN_ROOT).as_posix())
        for path in sorted(_PLUGIN_ROOT.rglob("*.py")) + sorted(_PLUGIN_ROOT.rglob("*.md")) + sorted(_PLUGIN_ROOT.rglob("*.yaml"))
        if needle in path.read_text(encoding="utf-8", errors="replace").lower()
    ]
    check("no org-specific suppression name ships in the plugin", offenders == [], str(offenders))
    repo_tests = Path(__file__).resolve().parents[2] / "tests"
    test_offenders = [
        str(path.relative_to(repo_tests).as_posix())
        for path in sorted(repo_tests.rglob("*.py"))
        if needle in path.read_text(encoding="utf-8", errors="replace").lower()
    ]
    check("no org-specific suppression name ships in the tests", test_offenders == [],
          str(test_offenders))

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
