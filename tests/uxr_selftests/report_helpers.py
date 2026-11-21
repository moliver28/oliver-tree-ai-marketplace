from _harness import bind

bind("references.report_helpers", globals())
def _selftest() -> int:
    """Offline checks for every subcommand's logic."""
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("references/report_helpers.py selftest")

    # --- scope-tier --------------------------------------------------------
    check(
        "Strategic + LRG is strategic",
        compute_scope_tier("Strategic", "LRG") == "strategic",
    )
    check(
        "Evaluative + M + two pods bumps to standard",
        compute_scope_tier("Evaluative", "M", pod_names="Audit,Risk") == "standard",
        compute_scope_tier("Evaluative", "M", pod_names="Audit,Risk"),
    )
    check(
        "Evaluative + M with one group stays lite",
        compute_scope_tier("Evaluative", "M", pod_names="Audit") == "lite",
    )
    check(
        "investment 0 never bumps",
        compute_scope_tier("Evaluative", "0", pod_names="Audit,Risk") == "lite",
    )
    check(
        "strategic never bumps above strategic",
        compute_scope_tier("Strategic", "XXLG", pod_count=5) == "strategic",
    )
    check(
        "unknown type falls back to the Other row",
        compute_scope_tier("Mystery", "XLG") == "strategic",
    )
    try:
        compute_scope_tier("Strategic", "HUGE")
        check("unknown investment raises", False)
    except ValueError:
        check("unknown investment raises", True)

    # --- verdicts ------------------------------------------------------------
    hyp = {"H1 label": {"Supports": 3, "Challenges": 2}}
    check(
        "3/5 Supports meets the 0.60 threshold",
        verdict_from_tallies(hyp["H1 label"], "hypothesis", 0.60) == "Supported",
    )
    check(
        "2/5 Supports with the rest Mixed is partially supported",
        verdict_from_tallies({"Supports": 2, "Mixed": 3}, "hypothesis", 0.60)
        == "Partially supported",
    )
    check(
        "Challenges dominance is not supported",
        verdict_from_tallies({"Supports": 1, "Challenges": 4}, "hypothesis", 0.60)
        == "Not supported",
    )
    check("no evidence is insufficient", verdict_from_tallies({}, "hypothesis", 0.60)
          == "Insufficient evidence")
    check(
        "assumption dominant Holds",
        verdict_from_tallies({"Holds": 3, "Untested": 1}, "assumption", 0.60) == "Holds",
    )
    check(
        "assumption mixed without dominance reads as insufficient",
        verdict_from_tallies({"Holds": 1, "Breaks": 1}, "assumption", 0.60)
        == "Insufficient evidence",
    )

    # --- front matter parser ---------------------------------------------------
    fm_text = (
        "---\n"
        "slug: report-leadership-2026-11-09-abc-237\n"
        "ticket: ABC-237\n"
        "tier: strategic\n"
        "audience: leadership\n"
        "date: 2026-11-09\n"
        'sources_cited: [onboarding-confusion, import-flow]\n'
        "hypotheses:\n"
        "  - id: H1\n"
        '    label: "Import reduces confusion"\n'
        "    verdict: Supported\n"
        "  - id: H2\n"
        '    label: "Users want the summary first"\n'
        "    verdict: Partially supported\n"
        "---\n\n# Report\n"
    )
    front, body = parse_front_matter(fm_text)
    check(
        "front matter scalars parse",
        front.get("ticket") == "ABC-237" and front.get("tier") == "strategic"
        and front.get("date") == "2026-11-09",
        repr(front),
    )
    check(
        "front matter flow list parses",
        front.get("sources_cited") == ["onboarding-confusion", "import-flow"],
        repr(front.get("sources_cited")),
    )
    hyps = front.get("hypotheses")
    check(
        "front matter hypothesis items parse",
        isinstance(hyps, list) and len(hyps) == 2
        and hyps[0]["id"] == "H1" and hyps[0]["label"] == "Import reduces confusion"
        and hyps[1]["verdict"] == "Partially supported",
        repr(hyps),
    )
    check("front matter body is preserved", body.lstrip().startswith("# Report"), repr(body[:40]))

    # --- alignment block parser ---------------------------------------------
    summary = (
        "# Session\n\nAda, platform PM.\n\n"
        "## Insights \u2192 Research Alignment\n"
        "**Research Questions**\n"
        "- RQ1 (How do users import?): The import flow lost her file once.\n"
        "- RQ2 (Why the summary first?): No direct evidence this session.\n"
        "**Hypotheses**\n"
        "- H1 (Import reduces confusion): Supports - she retried three times.\n"
        "- H2 (Users want the summary first): Mixed - liked it, missed the chart.\n"
        "**Assumptions**\n"
        "- A1 (Data loss is rare): Breaks this session - it happened to her.\n"
        "- A2 (Docs are enough): Untested this session - never opened them.\n"
        "\n## Notable quotes\n"
        "More text that must not be parsed.\n"
    )
    block = parse_alignment_block(summary)
    check("alignment block is found", block["found"] is True)
    check(
        "RQ lines parse with coverage",
        [entry["id"] for entry in block["rqs"]] == ["RQ1", "RQ2"]
        and block["rqs"][0]["covered"] is True and block["rqs"][1]["covered"] is False,
        repr(block["rqs"]),
    )
    check(
        "hypothesis stances parse",
        block["hypotheses"] == [
            {"id": "H1", "label": "Import reduces confusion", "stance": "Supports"},
            {"id": "H2", "label": "Users want the summary first", "stance": "Mixed"},
        ],
        repr(block["hypotheses"]),
    )
    check(
        "assumption stances parse",
        block["assumptions"] == [
            {"id": "A1", "label": "Data loss is rare", "stance": "Breaks"},
            {"id": "A2", "label": "Docs are enough", "stance": "Untested"},
        ],
        repr(block["assumptions"]),
    )
    check(
        "parsing stops at the next H2 without Insights",
        parse_alignment_block(summary + "- H3 (x): Supports - after the cut.\n")["hypotheses"]
        == block["hypotheses"],
    )
    check("no block in plain text", parse_alignment_block("no marker here")["found"] is False)

    # --- evidence-weight -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        workspace = tmp / "atlas-onboarding"
        (workspace / "interviews").mkdir(parents=True)
        (workspace / "interviews" / "atlas-onboarding-2026-11-02-summary.md").write_text(
            summary, encoding="utf-8"
        )
        (workspace / "interviews" / "atlas-onboarding-2026-11-05-summary.md").write_text(
            summary.replace("Challenges - she retried", "Supports - she retried"),
            encoding="utf-8",
        )
        (workspace / "interviews" / "atlas-onboarding-2026-11-07-summary.md").write_text(
            "# A summary with no alignment block\n", encoding="utf-8"
        )
        result = evidence_weight(workspace, 0.60)
        check(
            "sessions tallied and block counts",
            result["sessions_tallied"] == 3 and result["sessions_with_alignment_block"] == 2,
            repr(result),
        )
        check(
            "rq coverage over tallied sessions",
            result["rq_coverage"] == {"RQ1": round(2 / 3, 4), "RQ2": 0.0},
            repr(result["rq_coverage"]),
        )
        check(
            "hypothesis verdicts from two blocks",
            result["hypothesis_verdicts"] == {
                "Import reduces confusion": "Supported",
                "Users want the summary first": "Partially supported",
            },
            repr(result["hypothesis_verdicts"]),
        )
        check(
            "assumption verdicts from two blocks",
            result["assumption_verdicts"] == {
                "Data loss is rare": "Breaks",
                "Docs are enough": "Untested",
            },
            repr(result["assumption_verdicts"]),
        )

    # --- channels --------------------------------------------------------------
    tiered = {"Audit": {"standard": ["#audit"], "strategic": ["#leadership"]}}
    check("standard tier uses its list", resolve_channels(tiered, "Audit", "standard") == ["#audit"])
    check(
        "strategic tier merges standard then strategic",
        resolve_channels(tiered, "Audit", "strategic") == ["#audit", "#leadership"],
    )
    check("lite tier drafts no chat channels", resolve_channels(tiered, "Audit", "lite") == [])
    check(
        "plain list values are used verbatim",
        resolve_channels({"Risk": ["#risk-main"]}, "Risk", "standard") == ["#risk-main"],
    )
    check("unknown pod gives an empty list", resolve_channels(tiered, "Widget", "standard") == [])

    # --- report-filename ---------------------------------------------------------
    check(
        "filename is lowercase with the expected shape",
        report_filename("ABC-237", "Leadership", "2026-11-09")
        == "report-leadership-2026-11-09-abc-237.md",
    )
    check(
        "audience keeps its internal hyphen",
        report_filename("ABC-9", "product-team", "2026-01-02")
        == "report-product-team-2026-01-02-abc-9.md",
    )
    try:
        report_filename("ABC-1", "leadership", "May 10th")
        check("bad date raises", False)
    except ValueError:
        check("bad date raises", True)

    # --- altitude -----------------------------------------------------------------
    check("brief maps to lite", map_altitude("brief") == "lite")
    check("standard maps to standard", map_altitude("standard") == "standard")
    check("deep maps to strategic", map_altitude("deep") == "strategic")
    try:
        map_altitude("ultra")
        check("unknown altitude raises", False)
    except ValueError:
        check("unknown altitude raises", True)

    # --- word-count-sections --------------------------------------------------------
    draft = (
        "---\nslug: x\n---\n\n"
        "## Executive Summary\n\nOne two three four five.\n\n"
        "### Subhead counts into the section\n\nSix seven.\n"
        "## Key Findings\n\n- alpha beta gamma delta epsilon\n"
        "- zeta eta theta\n"
        "## Implications\n\nShort.\n"
    )
    counts = word_count_sections(draft)
    check(
        "sections count words to the next H2, subheads included",
        counts == {"Executive Summary": 7, "Key Findings": 8, "Implications": 1},
        repr(counts),
    )

    # --- check-citations -------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sources = tmp / "sources" / "interviews"
        sources.mkdir(parents=True)
        (sources / "onboarding-confusion-2026-11-02.md").write_text(
            "---\nslug: onboarding-confusion\ntype: interview\n---\n\nnote\n",
            encoding="utf-8",
        )
        (sources / "README.md").write_text("readme", encoding="utf-8")
        (tmp / "draft.md").write_text(
            "Body cites [S:missing] and [S:onboarding-confusion] and [S:missing] again.\n",
            encoding="utf-8",
        )
        results = check_citations((tmp / "draft.md").read_text(encoding="utf-8"), tmp / "sources")
        check(
            "missing slugs list first with found false",
            results[0] == {"slug": "missing", "found": False}
            and results[1] == {"slug": "onboarding-confusion", "found": True},
            repr(results),
        )
        check("duplicates collapse", len(results) == 2, repr(results))

    # --- codebook + classify-themes -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        codes_path = tmp / "codes.md"
        codes_path.write_text(
            "# Codes\n\n"
            "| Code | Definition | Anchor example | Sources |\n"
            "|---|---|---|---|\n"
            "| lost-file | Import loses the file | \"It just vanished\" | S1, S2 |\n"
            "| summary-first | Wants the summary first | \"Show me the totals\" | S1 |\n"
            "| vague-hunch | No anchor yet | | |\n",
            encoding="utf-8",
        )
        themes_path = tmp / "themes.md"
        themes_path.write_text(
            "# Themes\n\n"
            "| # | Theme | Codes | Status | Evidence weight | Synthesis file |\n"
            "|---|---|---|---|---|---|\n"
            "| T1 | Import trust gap | lost-file, summary-first | saturated | strong | RQ1, RQ3 |\n"
            "| T2 | Summary placement | summary-first | developing | medium | RQ2 |\n"
            "| T3 | hunch | vague-hunch | emerging | weak | |\n",
            encoding="utf-8",
        )
        rows = classify_themes(codes_path, themes_path)
        check(
            "grounded theme is participant-emergent and not fragile",
            rows[0]["origin"] == "participant-emergent" and rows[0]["fragile"] is False
            and rows[0]["rqs"] == ["RQ1", "RQ3"],
            repr(rows[0]),
        )
        check(
            "single-RQ theme is fragile",
            rows[1]["origin"] == "participant-emergent" and rows[1]["fragile"] is True,
            repr(rows[1]),
        )
        check(
            "code without anchor or sources is researcher-framed",
            rows[2]["origin"] == "researcher-framed" and rows[2]["fragile"] is True,
            repr(rows[2]),
        )
        table = format_bias_check(rows)
        check(
            "bias check summary line matches the contract",
            table.splitlines()[-1]
            == "Researcher-framed: 1. Emergent: 2. Single-RQ conclusions: T2, T3.",
            repr(table.splitlines()[-1]),
        )

    # --- cross-study ------------------------------------------------------------------
    current = (
        "---\nhypotheses:\n  - id: H1\n    label: \"Import reduces confusion\"\n"
        "    verdict: Supported\n  - id: H2\n    label: \"Users want the summary first\"\n"
        "    verdict: Not supported\n  - id: H3\n    label: \"Brand new claim\"\n"
        "    verdict: Supported\n  - id: H4\n    label: \"Still murky\"\n"
        "    verdict: Partially supported\n---\n\nbody\n"
    )
    prior = (
        "---\nhypotheses:\n  - id: H1\n    label: \"Import reduces confusion\"\n"
        "    verdict: Supported\n  - id: H2\n    label: \"Users want the summary first\"\n"
        "    verdict: Supported\n  - id: H4\n    label: \"Still murky\"\n"
        "    verdict: Supported\n---\n\nbody\n"
    )
    result = cross_study(current, [prior])
    check(
        "same decisive class confirms",
        result["confirms"] == ["Import reduces confusion"],
        repr(result),
    )
    check(
        "opposite decisive classes reverse",
        result["reverses"] == ["Users want the summary first"],
        repr(result),
    )
    check("unmatched label is new", result["new"] == ["Brand new claim"], repr(result))
    check(
        "matched neutral verdicts land in no list",
        not any("Still murky" in items for items in result.values()),
        repr(result),
    )

    # --- pod-to-area + finish title -----------------------------------------------------
    check("pod maps to area", pod_to_area({"Audit": "Governance"}, "Audit") == "Governance")
    check("unknown pod is unmapped", pod_to_area({"Audit": "Governance"}, "Widget") is None)
    check(
        "finish title ok",
        validate_finish_title("Governance Import redesign 2026-11", "Governance") == [],
        repr(validate_finish_title("Governance Import redesign 2026-11", "Governance")),
    )
    check(
        "title must start with the pod",
        any("start" in line for line in
            validate_finish_title("Platform Import redesign 2026-11", "Governance")),
    )
    check(
        "title must end with YYYY-MM",
        any("YYYY-MM" in line for line in
            validate_finish_title("Governance Import redesign", "Governance")),
    )

    # --- arr-parse ---------------------------------------------------------------------
    reply = (
        "Here are the ARR figures you asked for:\n\n"
        "Acme Corp: $1.2M ARR\n"
        "BigCo Industries - $800K\n"
        "| Account | ARR |\n|---|---|\n| Tiny LLC | $40K |\n"
    )
    parsed = parse_arr_reply(reply)
    check(
        "arr pairs parse from labeled lines and table rows",
        parsed == {"Acme Corp": "$1.2M", "BigCo Industries": "$800K", "Tiny LLC": "$40K"},
        repr(parsed),
    )
    check(
        "arr parse never invents an account",
        parse_arr_reply("no figures in this reply") == {},
        repr(parse_arr_reply("no figures in this reply")),
    )

    # --- CLI usage errors ------------------------------------------------------------
    check("scope-tier without flags is usage", main(["scope-tier"]) == EXIT_USAGE)
    check("verdict without input is usage", main(["verdict", "--kind", "bogus"]) == EXIT_USAGE)
    check("channels without pod is usage", main(["channels"]) == EXIT_USAGE)
    check(
        "report-filename without flags is usage",
        main(["report-filename", "--key", "ABC-1"]) == EXIT_USAGE,
    )
    check("evidence-weight without workspace is usage", main(["evidence-weight"]) == EXIT_USAGE)
    check(
        "word-count-sections without file is usage",
        main(["word-count-sections"]) == EXIT_USAGE,
    )
    check("check-citations without flags is usage", main(["check-citations"]) == EXIT_USAGE)
    check("codebook-codes without file is usage", main(["codebook-codes"]) == EXIT_USAGE)
    check("classify-themes without files is usage", main(["classify-themes"]) == EXIT_USAGE)
    check("cross-study without flags is usage", main(["cross-study"]) == EXIT_USAGE)
    check("altitude without level is usage", main(["altitude"]) == EXIT_USAGE)
    check("pod-to-area without pod is usage", main(["pod-to-area"]) == EXIT_USAGE)
    check(
        "validate-finish-title without flags is usage",
        main(["validate-finish-title", "--title", "x"]) == EXIT_USAGE,
    )
    check("arr-parse without file is usage", main(["arr-parse"]) == EXIT_USAGE)
    check("unknown subcommand is usage", main(["nope"]) == EXIT_USAGE)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
