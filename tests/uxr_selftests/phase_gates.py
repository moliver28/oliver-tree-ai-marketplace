from _harness import bind

bind("lib.phase_gates", globals())
def _ready_spec() -> dict:
    """A spec that passes every reference spec predicate."""
    return {
        "history": "Support tickets doubled after the billing rework shipped.",
        "decision": "Should the redesigned invoice page ship to all tenants?",
        "hypotheses": [{"label": "H1", "text": "Admins cannot find invoice export."}],
        "research_questions": ["How do admins export invoices today?"],
        "sample_size": "8-10 admins",
        "persona": "Tenant admins",
        "session_length": "45 min interviews",
        "roster": [{"name": "Ada Example", "status": "Scheduled"}],
        "results": "Ship it: admins completed exports faster with the new page.",
    }


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/phase_gates.py --selftest")

    spec = _ready_spec()
    all_fields = _fields(
        ux_researcher=True, pod=True, research_method=True, output_link=True
    )

    # --- every gated phase passes when everything is set ---------------------
    for phase in (
        "Planned",
        "Writing Script / Survey",
        "Recruiting",
        "Collecting Data",
        "Creating Report",
        "Done",
    ):
        ok, missing = check_phase_readiness(phase, spec, all_fields)
        check(f"ready ticket passes the gate for {phase}", ok and missing == [], str(missing))

    # --- each phase blocks on its own gap -------------------------------------
    cases = (
        ("Planned", _fields(ux_researcher=True, pod=True), _ready_spec() | {"history": "", "decision": ""}, "background_filled"),
        ("Planned", _fields(ux_researcher=True, pod=True), _ready_spec() | {"research_questions": []}, "research_questions_nonempty"),
        ("Planned", _fields(pod=True), spec, "field 'ux_researcher' is not set"),
        ("Planned", _fields(ux_researcher=True), spec, "field 'pod' is not set"),
        ("Writing Script / Survey", _fields(), spec, "field 'research_method' is not set"),
        ("Recruiting", _fields(research_method=True), _ready_spec() | {"roster": []}, "roster_nonempty"),
        ("Recruiting", _fields(research_method=True), _ready_spec() | {"persona": ""}, "recruitment_strategy_filled"),
        ("Recruiting", _fields(), spec, "field 'research_method' is not set"),
        ("Collecting Data", _fields(), _ready_spec() | {"roster": [{"name": "Bo", "status": "Outreach Sent"}]}, "roster_has_scheduled"),
        ("Creating Report", _fields(), spec, "field 'output_link' is not set"),
        ("Done", _fields(output_link=True), _ready_spec() | {"results": None}, "results_filled"),
        ("Done", _fields(), spec, "field 'output_link' is not set"),
    )
    for phase, fields, gated_spec, needle in cases:
        ok, missing = check_phase_readiness(phase, gated_spec, fields)
        check(
            f"{phase} blocks when its bar is unmet ({needle})",
            not ok and any(needle in item for item in missing),
            f"ok={ok} missing={missing}",
        )

    # --- exact missing-item strings --------------------------------------------
    ok, missing = check_phase_readiness("Done", spec, _fields())
    check(
        "field missing strings use the exact issue format",
        not ok and missing == ["field 'output_link' is not set"],
        str(missing),
    )
    ok, missing = check_phase_readiness(
        "Done", _ready_spec() | {"results": None}, _fields(output_link=True)
    )
    check(
        "spec missing strings use the exact issue format",
        not ok and missing == ["spec check failed: results_filled"],
        str(missing),
    )

    # --- slash variant and whitespace-insensitive matching ---------------------
    ok, _ = check_phase_readiness("Writing Script/Survey", spec, _fields(research_method=True))
    check("slash variant matches the phase key", ok)
    check(
        "match_phase is case- and whitespace-insensitive in both directions",
        match_phase("writing script /survey", REFERENCE_REQUIREMENTS)
        == "Writing Script / Survey"
        and match_phase("collecting", REFERENCE_REQUIREMENTS) == "Collecting Data"
        and match_phase("done", REFERENCE_REQUIREMENTS) == "Done",
    )

    # --- ungated statuses pass --------------------------------------------------
    for status in ("Summarizing Data", "Blocked", "Somewhere Unheard Of"):
        ok, missing = check_phase_readiness(status, {}, _fields())
        check(f"ungated status {status!r} passes with no requirements", ok and missing == [])

    # --- suggestion cases ---------------------------------------------------------
    check(
        "suggest returns the next phase when its bar is met",
        suggest_next_phase("Planned", spec, _fields(research_method=True))
        == "Writing Script / Survey",
    )
    check(
        "suggest returns None when the next phase fails its bar",
        suggest_next_phase("Planned", spec, _fields()) is None,
    )
    check(
        "suggest crosses into Collecting Data on a scheduled roster",
        suggest_next_phase("Recruiting", spec, _fields(research_method=True))
        == "Collecting Data",
    )
    check(
        "suggest returns None when no roster row is scheduled",
        suggest_next_phase(
            "Recruiting", _ready_spec() | {"roster": [{"name": "Bo", "status": "No Response"}]},
            _fields(research_method=True),
        )
        is None,
    )
    check(
        "suggest returns None when the next phase is ungated (Collecting Data -> Summarizing Data)",
        suggest_next_phase("Collecting Data", spec, _fields()) is None,
    )
    check(
        "suggest reaches Done only with output and results",
        suggest_next_phase("Creating Report", spec, _fields(output_link=True)) == "Done"
        and suggest_next_phase("Creating Report", spec, _fields()) is None,
    )
    check(
        "suggest returns None at the last phase and off the phase_order",
        suggest_next_phase("Done", spec, all_fields) is None
        and suggest_next_phase("Blocked", spec, all_fields) is None,
    )

    # --- config overrides ------------------------------------------------------------
    custom = {
        "workflow": {
            "phase_order": ["Drafting", "Fieldwork", "Wrapped"],
            "requirements": {
                "Fieldwork": ("spec:roster_nonempty",),
                "Wrapped": ("spec:results_filled",),
            },
        }
    }
    check(
        "config phase_order and requirements drive the gate",
        check_phase_readiness("Fieldwork", _ready_spec() | {"roster": []}, _fields(), config=custom)
        == (False, ["spec check failed: roster_nonempty"])
        and check_phase_readiness("Drafting", {}, _fields(), config=custom) == (True, [])
        and suggest_next_phase("Drafting", _ready_spec() | {"roster": []}, _fields(), config=custom)
        is None
        and suggest_next_phase("Drafting", _ready_spec(), _fields(), config=custom)
        == "Fieldwork",
    )
    check(
        "config phase_order replaces the reference order",
        unknown_requirement_keys(custom) == [],
    )
    check(
        "empty config requirements keep the reference table",
        check_phase_readiness("Done", {}, _fields(output_link=True), config={"workflow": {"requirements": {}}})
        == (False, ["spec check failed: results_filled"]),
    )

    # --- every requirements key matches a live status name ----------------------------
    check(
        "every reference requirements key matches a phase_order status",
        unknown_requirement_keys() == [],
        str(unknown_requirement_keys()),
    )
    check(
        "every field fix hint covers a requirement field key",
        set(FIELD_FIX_HINTS) == set(FIELD_SOURCES),
    )
    check(
        "every spec predicate has a fix hint",
        set(SPEC_FIX_HINTS) == set(SPEC_CHECKS),
        f"predicates={sorted(SPEC_CHECKS)} hints={sorted(SPEC_FIX_HINTS)}",
    )
    check(
        "edit_fix maps missing items to edit shorthands",
        edit_fix("field 'research_method' is not set") == "method=<value>"
        and edit_fix("spec check failed: results_filled") == "results=<text>"
        and edit_fix("phase gate crashed on malformed input: x") == "",
    )

    # --- missing_lines (the blocked-move golden format) -------------------------
    check(
        "missing_lines quotes the spec-check predicate",
        missing_lines([{"item": "spec check failed: roster_has_scheduled",
                        "fix": "roster~=Name|status=Scheduled"}], "UXR-101")
        == ["missing: spec check failed: 'roster_has_scheduled' -> run edit UXR-101 roster~=Name|status=Scheduled"],
    )
    check(
        "missing_lines renders other items verbatim and drops an empty fix",
        missing_lines([{"item": "field 'research_method' is not set", "fix": ""}], "ABC-42")
        == ["missing: field 'research_method' is not set"],
    )
    check(
        "missing_lines accepts the whole check output",
        missing_lines({"ok": False, "missing": [{"item": "spec check failed: results_filled",
                                                 "fix": "results=<text>"}]}, "UXR-101")
        == ["missing: spec check failed: 'results_filled' -> run edit UXR-101 results=<text>"],
    )
    gates_fixture = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "gates"
    blocked_path, blocked_expected = gates_fixture / "blocked-move.json", gates_fixture / "blocked-move.expected.txt"
    if blocked_path.is_file() and blocked_expected.is_file():
        case = json.loads(blocked_path.read_text(encoding="utf-8"))
        got = missing_lines(case, case["key"])
        check("blocked-move fixture byte-matches the golden line",
              "\n".join(got) + ("\n" if got else "") == blocked_expected.read_text(encoding="utf-8"),
              repr(got))
    else:
        print("skip: fixtures not shipped (repo-level tests/)")  # installed plugin has no fixtures

    # --- build_field_state --------------------------------------------------------------
    check(
        "field state reads shorthand-named values",
        build_field_state({"uxr": "Ada", "pod": ["Platform"], "method": [], "output": ""})
        == {"ux_researcher": True, "pod": True, "research_method": False, "output_link": False},
    )
    check(
        "field state resolves tracker field ids through config",
        build_field_state(
            {"cf_uxr": "Ada", "cf_method": "Survey"},
            config={"fields": {"uxr": {"id": "cf_uxr"}, "method": {"id": "cf_method"}}},
        )
        == {"ux_researcher": True, "pod": False, "research_method": True, "output_link": False},
    )
    check(
        "boolean field state passes through",
        build_field_state({"research_method": True})
        == {"ux_researcher": False, "pod": False, "research_method": True, "output_link": False},
    )
    check(
        "empty and whitespace values count as unset; non-dict input counts as nothing",
        build_field_state({"pod": "   ", "method": {}})["pod"] is False
        and build_field_state(None) == {key: False for key in FIELD_SOURCES},
    )

    # --- gates never raise ----------------------------------------------------------------
    ok, missing = check_phase_readiness("Done", "not a spec", None)
    check(
        "non-dict spec and missing field state fail closed without raising",
        ok is False and "results_filled" in " ".join(missing),
        str(missing),
    )
    ok, _ = check_phase_readiness(None, None, None)
    check("None target status matches nothing and passes", ok)

    # --- the real CLI: a blocked check exits 1, a pass exits 0 ------------------------------
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec_file = tmp / "spec.json"
            spec_file.write_text(json.dumps(_ready_spec()), encoding="utf-8")
            blocked = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py"),
                 "check", "--status", "Recruiting", "--spec", str(spec_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check(
                "CLI check on an empty-fields ticket exits 1 with fix hints",
                blocked.returncode == 1
                and '"ok": false' in blocked.stdout
                and "method=<value>" in blocked.stdout,
                f"code={blocked.returncode} out={blocked.stdout[:200]!r}",
            )
            fields_file = tmp / "fields.json"
            fields_file.write_text(
                json.dumps({"output": "https://example.com/report"}), encoding="utf-8"
            )
            passing = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py"),
                 "suggest", "--status", "Creating Report", "--spec", str(spec_file),
                 "--fields", str(fields_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check(
                "CLI suggest on a ready ticket prints the phase and exits 0",
                passing.returncode == 0 and passing.stdout.strip() == "Done",
                f"code={passing.returncode} out={passing.stdout!r}",
            )
            usage = subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "lib" / "phase_gates.py")],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            check("CLI with no subcommand prints usage and exits 2", usage.returncode == 2)
    except OSError as exc:
        check("CLI subprocess checks ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
