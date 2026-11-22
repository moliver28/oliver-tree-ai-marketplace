from _harness import bind

bind("lib.spec_blocks", globals())
GOLDEN_SPEC: dict = {
    "history": "Billing rework shipped last quarter and invoice-related support tickets doubled.",
    "decision": "Should the redesigned invoice page ship to all tenants, decided by the product trio.",
    "hypotheses": [
        {"label": "H1", "text": "Admins cannot find the invoice export on the current page."},
        {"label": "H2", "text": "A totals summary card reduces invoice support tickets."},
    ],
    "assumptions": [
        {"label": "A1", "text": "Tenants reconcile invoices at least once a month."}
    ],
    "resources": [
        {
            "label": "Prior research",
            "url": "https://example.com/docs/prior-research",
            "share_status": "shared",
        },
        {
            "label": "Draft deck",
            "url": "https://example.com/docs/draft-deck",
            "share_status": "private",
            "share_note": "ask the author for access",
        },
        {"label": "Ticket notes", "text": "Summary copied from the ticket thread."},
    ],
    "research_questions": [
        "How do admins export invoices today?",
        "What blocks a first-time export?",
    ],
    "sample_size": "8-10 admins",
    "persona": "Tenant admins",
    "session_length": "45 min interviews",
    "artifact_link": "https://example.com/docs/script",
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
            "work_area": "invoice exports",
            "status": "Scheduled",
            "channel": "internal",
        },
        {"name": "Rook Example", "reason": "Waitlist"},
    ],
    "results": None,
    "study_title": "Invoice export usability",
    "method_key": "interview",
    "channel": "internal",
}


def selftest_config(body_format: str = "markdown") -> dict:
    """A synthetic config for self-tests; no organization values.

    Public so the script self-tests (and later command self-tests) render
    against the same fixture config instead of the local machine's org.yaml.
    """
    return {
        "tracker": {"body_format": body_format},
        "org": {"team_share_domain": "example.com"},
        "links": {
            "calculator": "https://example.com/calculator",
            "templates": "https://example.com/templates",
            "plugin_repo": "https://example.com/plugin",
        },
        "recruit": {"statuses": {}, "status_colors": {}},
    }


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/spec_blocks.py --selftest")

    md_config = selftest_config("markdown")
    adf_config = selftest_config("adf")
    html_config = selftest_config("html")

    # --- golden render determinism ------------------------------------------
    md_one = build_document(GOLDEN_SPEC, config=md_config)
    md_two = build_document(GOLDEN_SPEC, config=md_config)
    adf_one = build_document(GOLDEN_SPEC, config=adf_config)
    adf_two = build_document(GOLDEN_SPEC, config=adf_config)
    html_one = build_document(GOLDEN_SPEC, config=html_config)
    html_two = build_document(GOLDEN_SPEC, config=html_config)
    check("golden markdown render is byte-identical on two runs", md_one == md_two)
    check(
        "golden adf render is byte-identical on two runs",
        json.dumps(adf_one, ensure_ascii=False, sort_keys=False) == json.dumps(adf_two, ensure_ascii=False, sort_keys=False),
    )
    check("golden html render is byte-identical on two runs", html_one == html_two)
    check(
        "golden spec renders non-empty bodies in all three formats",
        bool(md_one) and bool(adf_one.get("content")) and bool(html_one),
    )
    check(
        "explicit body_format overrides tracker.body_format",
        build_document(GOLDEN_SPEC, config=adf_config, body_format="markdown") == md_one,
    )
    check(
        "default config resolves to the markdown format",
        isinstance(build_document(GOLDEN_SPEC, config={}), str),
    )
    try:
        build_document(GOLDEN_SPEC, config=md_config, body_format="rtf")
        check("unknown explicit format raises ValueError", False, "no error")
    except ValueError:
        check("unknown explicit format raises ValueError", True)
    spec_before = json.dumps(GOLDEN_SPEC, ensure_ascii=False, sort_keys=True)
    build_document(GOLDEN_SPEC, config=md_config)
    spec_after = json.dumps(GOLDEN_SPEC, ensure_ascii=False, sort_keys=True)
    check("build_document does not mutate the spec", spec_before == spec_after)

    # --- node counts on the golden body --------------------------------------
    md_counts = document_counts(md_one)
    adf_counts = document_counts(adf_one)
    html_counts = document_counts(html_one)
    expected_counts = {
        "panels": 2,
        "background_tables": 1,
        "recruitment_tables": 1,
        "resources_sections": 1,
        "roster_sections": 1,
        "checklists": 1,
        "rq_lists": 1,
        "task_items": 5,
        "status_nodes": 2,
        "roster_rows": 2,
    }
    for label, counts in (("markdown", md_counts), ("adf", adf_counts), ("html", html_counts)):
        check(
            f"golden {label} body has the exact template node counts",
            counts == expected_counts,
            f"got {counts}",
        )
    ok, problems = assert_full_document(md_one)
    check("golden markdown body passes assert_full_document", ok, "; ".join(problems))
    ok, problems = assert_full_document(adf_one)
    check("golden adf body passes assert_full_document", ok, "; ".join(problems))
    ok, problems = assert_full_document(html_one)
    check("golden html body passes assert_full_document", ok, "; ".join(problems))

    # --- truncated bodies fail ------------------------------------------------
    md_lines = md_one.splitlines()
    truncated_md = "\n".join(md_lines[: len(md_lines) // 2])
    ok, problems = assert_full_document(truncated_md)
    check("truncated markdown body fails assert_full_document", not ok and bool(problems), str(problems))
    truncated_adf = {"type": "doc", "version": 1, "content": adf_one["content"][:2]}
    ok, problems = assert_full_document(truncated_adf)
    check("truncated adf body fails assert_full_document", not ok and bool(problems), str(problems))
    ok, problems = assert_full_document("random text without any structure")
    check("unstructured text fails assert_full_document", not ok and bool(problems), str(problems))
    ok, problems = assert_full_document(42)
    check("non-string non-dict body fails assert_full_document", not ok and bool(problems), str(problems))

    # --- template shape details ------------------------------------------------
    check(
        "unfilled slots render their placeholders (3 RQ slots from 2 RQs)",
        "3. Tertiary research question" in md_one
        and PLACEHOLDERS["results"] in md_one
        and PLACEHOLDERS["sample_size"] not in md_one,
    )
    check(
        "private resource renders the lock and the share legend",
        "\U0001f512 Draft deck:" in md_one and "so teammates can view." in md_one,
    )
    check(
        "shared resource carries no lock",
        "- Prior research: https://example.com/docs/prior-research" in md_one,
    )
    check(
        "roster badge renders as emoji dot plus bold status",
        "\U0001f7e2 **Scheduled**" in md_one and "\u26aa **Potential Candidate**" in md_one,
    )
    check(
        "checklist links come from config links.*",
        "[prioritization calculator](https://example.com/calculator)" in md_one
        and "[templates folder](https://example.com/templates)" in md_one
        and "[plugin commands](https://example.com/plugin)" in md_one,
    )

    # --- empty roster: blank row, still a complete document --------------------
    empty_roster_spec = {k: v for k, v in GOLDEN_SPEC.items() if k != "roster"}
    empty_body = build_document(empty_roster_spec, config=md_config)
    ok, problems = assert_full_document(empty_body)
    check(
        "spec without a roster renders a blank row and stays complete",
        ok and "|   |   |   |   |   |   |   |   |" in empty_body,
        "; ".join(problems),
    )
    adf_empty = build_document(empty_roster_spec, config=adf_config)
    ok, problems = assert_full_document(adf_empty)
    check("spec without a roster passes completeness as adf", ok, "; ".join(problems))

    # --- validate_spec rejections ----------------------------------------------
    cases = (
        ("empty spec fails validation", {}, "history and decision"),
        (
            "placeholder history fails validation",
            {**GOLDEN_SPEC, "history": PLACEHOLDERS["history"]},
            "history is still the placeholder",
        ),
        (
            "placeholder decision fails validation",
            {**GOLDEN_SPEC, "decision": PLACEHOLDERS["decision"]},
            "decision is still the placeholder",
        ),
        ("empty hypotheses fail validation", {**GOLDEN_SPEC, "hypotheses": []}, "non-empty list"),
        (
            "hypothesis placeholder text fails validation",
            {**GOLDEN_SPEC, "hypotheses": [{"label": "H1", "text": PLACEHOLDERS["hypotheses"]}]},
            "placeholder",
        ),
        (
            "hypothesis with empty label fails validation",
            {**GOLDEN_SPEC, "hypotheses": [{"label": "", "text": "Something falsifiable."}]},
            "label is empty",
        ),
        (
            "RQ placeholder fails validation",
            {**GOLDEN_SPEC, "research_questions": ["Primary research question"]},
            "placeholder text",
        ),
        (
            "empty RQ string fails validation",
            {**GOLDEN_SPEC, "research_questions": ["  "]},
            "non-empty string",
        ),
        (
            "assumption placeholder text fails validation",
            {**GOLDEN_SPEC, "assumptions": [{"label": "A1", "text": PLACEHOLDERS["assumptions"]}]},
            "placeholder",
        ),
        (
            "bad roster status fails validation",
            {**GOLDEN_SPEC, "roster": [{"name": "Ada Example", "status": "Maybe Later"}]},
            "not an allowed roster status",
        ),
        (
            "roster row without a name fails validation",
            {**GOLDEN_SPEC, "roster": [{"status": "Scheduled"}]},
            "name is required",
        ),
        (
            "bad roster channel fails validation",
            {**GOLDEN_SPEC, "roster": [{"name": "Ada Example", "channel": "partner"}]},
            "'internal' or 'external'",
        ),
        (
            "url without share_status fails validation",
            {
                **GOLDEN_SPEC,
                "resources": [{"label": "Deck", "url": "https://example.com/deck"}],
            },
            "without share_status",
        ),
        (
            "unknown share_status fails validation",
            {
                **GOLDEN_SPEC,
                "resources": [
                    {"label": "Deck", "url": "https://example.com/deck", "share_status": "pubic"}
                ],
            },
            "shared, private, or unknown",
        ),
        (
            "local file path resource fails validation",
            {**GOLDEN_SPEC, "resources": [{"label": "Deck", "text": "C:\\Users\\deck.pptx"}]},
            "local file path",
        ),
        (
            "relative path resource fails validation",
            {**GOLDEN_SPEC, "resources": [{"label": "Deck", "text": "./notes/deck.md"}]},
            "local file path",
        ),
        ("non-dict spec fails validation", "not a spec", "not a JSON object"),
        ("null spec fails validation", None, "not a JSON object"),
    )
    for name, spec, needle in cases:
        ok, errors = validate_spec(spec)
        check(
            name,
            ok is False and any(needle in error for error in errors),
            f"errors={errors}",
        )
    ok, _ = validate_spec(GOLDEN_SPEC, config=md_config)
    check("golden spec passes validation", ok)

    # --- validate_spec never raises ---------------------------------------------
    adversarial = [
        {"hypotheses": [{"label": ["list"], "text": {"dict": 1}}]},
        {"hypotheses": "nope", "research_questions": 42, "roster": "nope", "resources": 7},
        {"roster": [1, "two", None, {"name": {"nested": True}}]},
        {"resources": [{"url": 42}, {"label": None, "share_status": []}, "bare"]},
        {"research_questions": [None, 5, ["x"]], "assumptions": "nope"},
        {"history": ["list"], "decision": {"a": 1}, "hypotheses": [["x"]]},
    ]
    never_raised = all(
        isinstance(validate_spec(bad), tuple) and validate_spec(bad)[0] is False
        for bad in adversarial
    )
    check("validate_spec returns (False, errors) on adversarial input, never raises", never_raised)
    crash_free = all(
        not assert_full_document(bad)[0] for bad in [None, 42, {"type": "doc"}, {"content": "x"}]
    )
    check("assert_full_document never raises on malformed input", crash_free)

    # --- config-driven status set ------------------------------------------------
    custom_config = {
        "recruit": {
            "statuses": {"interview": ["Custom Status"], "survey": [], "recruited": [], "early": []},
            "status_colors": {"Custom Status": "blue"},
        }
    }
    ok, errors = validate_spec(
        {**GOLDEN_SPEC, "roster": [{"name": "Ada Example", "status": "Custom Status"}]},
        config=custom_config,
    )
    check("org-configured roster status validates", ok, "; ".join(errors))
    ok, _ = validate_spec(
        {**GOLDEN_SPEC, "roster": [{"name": "Ada Example", "status": "Scheduled"}]},
        config=custom_config,
    )
    check(
        "org-configured interview set replaces the default interview statuses",
        not ok,
    )

    # --- spec_from_body round trips ----------------------------------------------
    golden_roster = [
        {"name": "Ada Example", "status": "Scheduled"},
        {"name": "Rook Example", "status": "Potential Candidate"},
    ]
    for label, body in (
        ("markdown", md_one),
        ("adf", adf_one),
        ("html", html_one),
    ):
        recovered = spec_from_body(body)
        check(
            f"roster round trip through spec_from_body keeps name and status ({label})",
            recovered.get("roster") == golden_roster,
            f"got {recovered.get('roster')}",
        )
    recovered = spec_from_body(md_one)
    check(
        "history and decision round trip and skip placeholder slots (markdown)",
        recovered.get("history") == GOLDEN_SPEC["history"]
        and recovered.get("decision") == GOLDEN_SPEC["decision"],
        f"got {recovered.get('history')!r} / {recovered.get('decision')!r}",
    )
    check(
        "hypotheses round trip with labels (markdown)",
        recovered.get("hypotheses") == GOLDEN_SPEC["hypotheses"],
        f"got {recovered.get('hypotheses')}",
    )
    check(
        "research questions round trip without the placeholder slot (markdown)",
        recovered.get("research_questions") == GOLDEN_SPEC["research_questions"],
        f"got {recovered.get('research_questions')}",
    )
    check(
        "recovered spec carries no _meta",
        "_meta" not in recovered,
    )
    adf_recovered = spec_from_body(adf_one)
    check(
        "hypotheses and RQs round trip from the adf body",
        adf_recovered.get("hypotheses") == GOLDEN_SPEC["hypotheses"]
        and adf_recovered.get("research_questions") == GOLDEN_SPEC["research_questions"]
        and adf_recovered.get("history") == GOLDEN_SPEC["history"],
        repr(adf_recovered),
    )
    html_recovered = spec_from_body(html_one)
    check(
        "history, hypotheses, and RQs round trip from the html body",
        html_recovered.get("history") == GOLDEN_SPEC["history"]
        and html_recovered.get("hypotheses") == GOLDEN_SPEC["hypotheses"]
        and html_recovered.get("research_questions") == GOLDEN_SPEC["research_questions"],
        repr(html_recovered),
    )
    check(
        "placeholder-only body recovers nothing",
        spec_from_body(build_document({}, config=md_config)) == {},
        repr(spec_from_body(build_document({}, config=md_config))),
    )
    check(
        "spec_from_body never raises on junk",
        spec_from_body("}}garbage{{{") == {} or isinstance(spec_from_body("}}garbage{{{"), dict),
    )
    check("spec_from_body(42) returns {}", spec_from_body(42) == {})

    # --- shorthand parsers ----------------------------------------------------------
    check(
        "roster+= pads and defaults (acceptance example)",
        parse_roster_shorthand("+=", "Ada|ada@x.io|||Scheduled|")
        == {"name": "Ada", "email": "ada@x.io", "slack": "", "reason": "", "status": "Scheduled", "channel": "internal"},
    )
    check(
        "roster+= with fewer parts pads to six",
        parse_roster_shorthand("+=", "Bo")
        == {"name": "Bo", "email": "", "slack": "", "reason": "", "status": "Potential Candidate", "channel": "internal"},
    )
    check(
        "roster~= patches one field",
        parse_roster_shorthand("~=", "ada|status=Data Collected")
        == {"match": "ada", "set": {"status": "Data Collected"}},
    )
    check(
        "roster-= returns the match name",
        parse_roster_shorthand("-=", "Ada Example") == {"match": "Ada Example"},
    )
    check(
        "hypotheses+= yields label and text",
        parse_list_shorthand("+=", "H3|Export is findable.", LIST_SHORTHAND_FIELDS["hypotheses"])
        == {"label": "H3", "text": "Export is findable."},
    )
    resources_delta = parse_list_shorthand(
        "+=", "Plan|https://x|shared|", LIST_SHORTHAND_FIELDS["resources"]
    )
    check(
        "resources+= writes url, never url_or_text (acceptance)",
        "url" in resources_delta
        and "url_or_text" not in resources_delta
        and resources_delta.get("url") == "https://x"
        and resources_delta.get("share_status") == "shared",
        repr(resources_delta),
    )
    text_delta = parse_list_shorthand(
        "+=", "Notes|plain text context|", LIST_SHORTHAND_FIELDS["resources"]
    )
    check(
        "resources+= non-http value lands in text",
        text_delta.get("text") == "plain text context" and "url" not in text_delta,
        repr(text_delta),
    )
    check(
        "resources~= maps url_or_text too",
        parse_list_shorthand("~=", "Plan|url_or_text=https://y", LIST_SHORTHAND_FIELDS["resources"])
        == {"match": "Plan", "set": {"url": "https://y"}},
    )
    check(
        "resources-= returns the match label",
        parse_list_shorthand("-=", "Plan", LIST_SHORTHAND_FIELDS["resources"])
        == {"match": "Plan"},
    )

    shorthand_rejections = (
        ("roster+= without a name", lambda: parse_roster_shorthand("+=", "|a@b")),
        ("roster+= with too many parts", lambda: parse_roster_shorthand("+=", "a|b|c|d|e|f|g")),
        ("roster~= with an unknown field", lambda: parse_roster_shorthand("~=", "Ada|bogus=1")),
        ("roster~= without an assignment", lambda: parse_roster_shorthand("~=", "Ada|status")),
        ("roster-= with pipes", lambda: parse_roster_shorthand("-=", "Ada|extra")),
        ("roster with an unknown operator", lambda: parse_roster_shorthand("!", "Ada")),
        ("list+= with an empty label", lambda: parse_list_shorthand("+=", "|x", ("label", "text"))),
        ("list~= with an unknown field", lambda: parse_list_shorthand("~=", "H1|bogus=x", ("label", "text"))),
        ("list with an unknown operator", lambda: parse_list_shorthand("?", "H1", ("label", "text"))),
    )
    for name, thunk in shorthand_rejections:
        try:
            thunk()
            check(name, False, "no error raised")
        except ValueError:
            check(name, True)

    # --- meta and spec path ------------------------------------------------------------
    meta = make_meta("edit", created_at="2026-01-01T00:00:00Z", last_edited_at="2026-01-02T00:00:00Z")
    check(
        "_meta carries exactly the six canonical keys",
        tuple(meta.keys()) == META_KEYS,
        repr(tuple(meta.keys())),
    )
    check(
        "_meta timestamps keep the given ISO 8601 UTC values",
        meta["created_at"] == "2026-01-01T00:00:00Z" and meta["last_edited_at"] == "2026-01-02T00:00:00Z",
    )
    check("make_meta marks the writing command", meta["last_edited_by_command"] == "edit")
    check(
        "fresh timestamps look like ISO 8601 UTC (Z suffix)",
        make_meta("new")["created_at"].endswith("Z"),
    )
    check(
        "spec_path lands in <state_dir>/specs/<KEY>.spec.json",
        str(spec_path("ABC-42", {"paths": {"state_dir": "/tmp/state"}}).as_posix())
        == "/tmp/state/specs/ABC-42.spec.json",
    )

    # --- status colors -------------------------------------------------------------------
    check(
        "badge colors match the issue table",
        status_color("Scheduled") == "green"
        and status_color("No Show") == "red"
        and status_color("Outreach Sent") == "blue"
        and status_color("No Response") == "yellow"
        and status_color("Data Collected") == "purple"
        and status_color("Potential Candidates") == "neutral"
        and status_color("Qualified (screener)") == "green"
        and status_color("Disqualified (screener)") == "red"
        and status_color("Reminder Sent") == "blue"
        and status_color("Cancelled") == "red"
        and status_color("Selected for Distribution") == "purple"
        and status_color("Survey Sent") == "blue",
    )
    check(
        "unknown status falls back to neutral; config overrides win",
        status_color("Bogus") == "neutral"
        and status_color("Custom Status", custom_config) == "blue",
    )
    check(
        "status_set contains both default sets",
        set(DEFAULT_INTERVIEW_STATUSES) <= set(status_set())
        and set(DEFAULT_SURVEY_STATUSES) <= set(status_set()),
    )
    # --- W4 issue 60: the verbatim ask rule (fires only on _meta command "new") ---
    ask_spec = dict(GOLDEN_SPEC)
    ask_spec["ask_verbatim"] = "Should the invoice page ship to all tenants?"
    ask_spec["ask_source"] = "intake interview, 2026-11-21"
    new_meta = {"last_edited_by_command": "new"}
    ok, errors = validate_spec({**ask_spec, "_meta": new_meta}, selftest_config())
    check("a new-command spec with a filled ask validates", ok, repr(errors))
    empty_ask = {**ask_spec, "ask_verbatim": "   ", "_meta": new_meta}
    ok, errors = validate_spec(empty_ask, selftest_config())
    check(
        "an empty ask on a new-command spec fails with the exact line",
        not ok and "ask_verbatim is empty (the original ask must be stored verbatim)" in errors,
        repr(errors),
    )
    uplevel_spec = {
        **ask_spec,
        "_meta": new_meta,
        "ask_uplevels": [
            {"text": "Should the redesigned invoice page ship to all tenants?", "note": "sharpened"},
        ],
    }
    ok, errors = validate_spec(uplevel_spec, selftest_config())
    check("a distinct up-level keeps the spec valid", ok, repr(errors))
    uplevel_spec["ask_uplevels"] = [{"text": ask_spec["ask_verbatim"], "note": "copy"}]
    ok, errors = validate_spec(uplevel_spec, selftest_config())
    check(
        "a byte-equal up-level fails with the exact line",
        not ok and "ask_uplevel must not replace the original ask" in errors,
        repr(errors),
    )
    edit_meta = {"last_edited_by_command": "edit"}
    ok, errors = validate_spec({**GOLDEN_SPEC, "ask_verbatim": "", "_meta": edit_meta}, selftest_config())
    check("the ask rule never fires on an edit-command spec", ok, repr(errors))
    ok, errors = validate_spec(GOLDEN_SPEC, selftest_config())
    check("the ask rule never fires on a spec without _meta (fixture shape)", ok, repr(errors))
    retro_meta = {"last_edited_by_command": "retro"}
    ok, errors = validate_spec({**GOLDEN_SPEC, "_meta": retro_meta}, selftest_config())
    check("the ask rule never fires on a retro save (the gap records instead)", ok, repr(errors))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
