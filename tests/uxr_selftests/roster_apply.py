from _harness import bind

bind("scripts.roster_apply", globals())

import spec_blocks as _spec  # tests/uxr_selftests/spec_blocks.py: the moved selftest_config home (selftest body stays verbatim)

BASE_SPEC: dict = {
    "history": "Ticket intake doubled after the pricing change.",
    "decision": "Should the intake redesign ship to GA?",
    "hypotheses": [{"label": "H1", "text": "Admins miss the intake link."}],
    "research_questions": ["How do admins open intake today?"],
    "study_title": "Intake usability",
    "method_key": "interview",
    "channel": "internal",
    "roster": [
        {
            "name": "Ada Example",
            "email": "ada@example.com",
            "slack": "@ada",
            "title": "Admin",
            "company": "Example Co",
            "industry": "Software",
            "arr": "$10k",
            "reason": "Exports daily",
            "work_area": "intake",
            "status": "Scheduled",
            "channel": "internal",
        },
        {"name": "Rook Example", "email": "rook@example.com", "reason": "Waitlist"},
    ],
}


def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/roster_apply.py selftest")

    # duplicate add: idempotent, never demotes a Data Collected row
    spec = copy.deepcopy(BASE_SPEC)
    spec["roster"][0]["status"] = "Data Collected"
    ops = {"add": [{"name": "Ada Example", "email": "ada@example.com", "status": "Potential Candidate"}]}
    new_spec, notes = apply_ops(spec, ops, config=_spec.selftest_config())
    row = new_spec["roster"][0]
    check("duplicate add on a Data Collected row keeps the status", row["status"] == "Data Collected", str(notes))
    new_spec2, _ = apply_ops(new_spec, ops, config=_spec.selftest_config())
    check("re-running the same add is idempotent", new_spec2 == new_spec)

    # promotion only from the promotable set
    spec["roster"][0]["status"] = "Outreach Sent"
    new_spec, notes = apply_ops(
        spec, {"add": [{"name": "Ada Example", "email": "ada@example.com", "status": "Scheduled"}]},
        config=_spec.selftest_config(),
    )
    check("Outreach Sent promotes to Scheduled", new_spec["roster"][0]["status"] == "Scheduled")
    spec["roster"][0]["status"] = "Reminder Sent"
    new_spec, _ = apply_ops(
        spec, {"add": [{"name": "Ada Example", "email": "ada@example.com", "status": "Survey Sent"}]},
        config=_spec.selftest_config(),
    )
    check("Reminder Sent never goes back to Survey Sent", new_spec["roster"][0]["status"] == "Reminder Sent")

    # fresh add fills defaults; dedupe falls back to name without an email
    new_spec, notes = apply_ops(
        spec, {"add": [{"name": "New Person", "reason": "Wave 1", "channel": "external", "company": "Acme"}]},
        config=_spec.selftest_config(),
    )
    added = new_spec["roster"][-1]
    check("fresh add lands with defaults and given fields",
          added["name"] == "New Person" and added["status"] == "Potential Candidate"
          and added["channel"] == "external" and added["company"] == "Acme")
    check("duplicate by name (no email) fills blanks only",
          apply_ops(
              new_spec,
              {"add": [{"name": "New Person", "title": "Director"}]},
              config=_spec.selftest_config(),
          )[0]["roster"][-1]["title"] == "Director"
          and apply_ops(
              new_spec,
              {"add": [{"name": "New Person", "company": "Other"}]},
              config=_spec.selftest_config(),
          )[0]["roster"][-1]["company"] == "Acme")

    # update: substring match, reason_append, status validation
    new_spec, notes = apply_ops(
        spec,
        {"update": [{"match": "ada", "set": {"status": "Cancelled"}, "reason_append": "declined by chat"}]},
        config=_spec.selftest_config(),
    )
    check("update matches by substring and appends reason",
          new_spec["roster"][0]["status"] == "Cancelled"
          and "declined by chat" in new_spec["roster"][0]["reason"])
    try:
        apply_ops(spec, {"update": [{"match": "ada", "set": {"status": "Not A Status"}}]},
                  config=_spec.selftest_config())
        check("bad update status raises validation", False)
    except _Validation:
        check("bad update status raises validation", True)
    try:
        apply_ops(spec, {"update": [{"match": "ada", "set": {"nickname": "x"}}]},
                  config=_spec.selftest_config())
        check("unknown update field raises validation", False)
    except _Validation:
        check("unknown update field raises validation", True)

    # funnel ops: accumulate tabs, keep fit unless refit
    ops = {
        "funnel": {
            "sheet": "sheet-123",
            "tabs": ["Wave 1"],
            "fit": {"users": 100, "accounts": 30, "as_of": "2026-11-09", "basis": "product analytics cohort"},
        }
    }
    one, _ = apply_ops(BASE_SPEC, ops, config=_spec.selftest_config())
    two, _ = apply_ops(
        one,
        {"funnel": {"sheet": "sheet-999", "tabs": ["Wave 2"], "fit": {"users": 1, "accounts": 1}}},
        config=_spec.selftest_config(),
    )
    funnel = two["funnel"]
    check("tabs accumulate deduped in order", funnel["tabs"] == ["Wave 1", "Wave 2"], str(funnel["tabs"]))
    check("sheet set once is kept", funnel["sheet"] == "sheet-123", str(funnel["sheet"]))
    check("fit kept without refit", funnel["fit"]["users"] == 100)
    three, _ = apply_ops(
        one,
        {"refit": True, "funnel": {"sheet": "sheet-999", "tabs": ["Wave 9"],
         "fit": {"users": 55, "accounts": 20, "as_of": "2026-11-01", "basis": "rebuilt cohort"}}},
        config=_spec.selftest_config(),
    )
    check("refit replaces sheet and fit", three["funnel"]["sheet"] == "sheet-999"
          and three["funnel"]["fit"]["users"] == 55 and three["funnel"]["tabs"] == ["Wave 1", "Wave 9"])
    try:
        apply_ops(one, {"refit": True, "funnel": {"sheet": "s"}}, config=_spec.selftest_config())
        check("refit without fit raises validation", False)
    except _Validation:
        check("refit without fit raises validation", True)

    # end-to-end run: dry-run writes nothing, real run writes spec + body
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        spec_file = tmp_path / "ABC-1.spec.json"
        body_file = tmp_path / "body.json"
        spec_file.write_text(json.dumps(BASE_SPEC, ensure_ascii=False), encoding="utf-8")
        before = spec_file.read_bytes()
        ops_text = json.dumps({"add": [{"name": "Wave Person", "email": "wave@example.com"}]})

        code, output = run(str(spec_file), ops_text, str(body_file), dry_run=True,
                           config=_spec.selftest_config())
        check("dry-run exits 0 and reports without writing",
              code == EXIT_OK and "dry-run" in output
              and spec_file.read_bytes() == before and not body_file.exists(), output)

        code, output = run(str(spec_file), ops_text, str(body_file), config=_spec.selftest_config())
        check("real run exits 0 and writes both files",
              code == EXIT_OK and body_file.exists(), output)
        written = json.loads(spec_file.read_text(encoding="utf-8"))
        check("written spec carries the added row",
              any(row["name"] == "Wave Person" for row in written["roster"]))
        body_text = body_file.read_text(encoding="utf-8")
        check("written body renders the roster (the added name appears)",
              len(body_text) > 100 and "Wave Person" in body_text)

        # validation failure exits 3 and writes nothing
        spec_file.write_text(json.dumps(BASE_SPEC, ensure_ascii=False), encoding="utf-8")
        before = spec_file.read_bytes()
        code, output = run(
            str(spec_file),
            json.dumps({"add": [{"name": "Bad Status", "status": "Warp Speed"}]}),
            str(body_file),
            config=_spec.selftest_config(),
        )
        check("invalid add exits 3 with nothing written",
              code == EXIT_VALIDATE and output.startswith("  - ")
              and spec_file.read_bytes() == before, f"code={code} out={output!r}")

        try:
            run(str(tmp_path / "missing.json"), ops_text, str(body_file),
                config=_spec.selftest_config())
            check("missing spec raises usage", False, "no error raised")
        except _Usage:
            check("missing spec raises usage (main exits 2)", True)

        try:
            run(str(spec_file), "{not json", str(body_file), config=_spec.selftest_config())
            check("invalid ops raises usage", False, "no error raised")
        except _Usage:
            check("invalid ops raises usage (main exits 2)", True)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
