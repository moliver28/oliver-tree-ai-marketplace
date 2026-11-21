from _harness import bind

bind("references.debrief_helpers", globals())
def _selftest() -> int:
    """Offline checks for every subcommand's logic."""
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("references/debrief_helpers.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # --- is_interview_shaped -------------------------------------------
        check(
            "Weekly sync is never interview-shaped",
            not is_interview_shaped(
                {"title": "Weekly sync", "attendees": ["a@partner.example"]}
            ),
        )
        check(
            "1:1 in the title is excluded even with an external attendee",
            not is_interview_shaped({"title": "1:1 with Pat", "attendees": ["p@vendor.example"]}),
        )
        check(
            "stand-up style titles are excluded",
            not is_interview_shaped({"title": "Team stand-up", "attendees": ["a@x.example", "b@x.example"]}),
        )
        check(
            "an external attendee shapes an interview",
            is_interview_shaped(
                {"title": "User interview: Ada", "attendees": ["ada@acme.example"]}
            ),
        )
        check(
            "a known internal domain is not external",
            not is_interview_shaped(
                {"title": "User interview: Ada", "attendees": ["me@corp.example"]},
                internal_domains=("corp.example",),
            ),
        )
        check(
            "two internal attendees still shape an interview",
            is_interview_shaped(
                {"title": "Usability session", "attendees": ["me@corp.example", "you@corp.example"]},
                internal_domains=("corp.example",),
            ),
        )
        check(
            "four internal attendees are not interview-shaped",
            not is_interview_shaped(
                {
                    "title": "Design review",
                    "attendees": ["a@corp.example", "b@corp.example", "c@corp.example", "d@corp.example"],
                },
                internal_domains=("corp.example",),
            ),
        )
        check(
            "a dict attendee list with an external email shapes an interview",
            is_interview_shaped(
                {
                    "title": "Customer call",
                    "attendees": [{"email": "buyer@bigco.example"}, {"email": "me@corp.example"}],
                },
                internal_domains=("corp.example",),
            ),
        )

        # --- check_stale_transcripts + cache --------------------------------
        root = tmp / "research"
        workspace = root / "atlas-onboarding"
        (workspace / "interviews").mkdir(parents=True)
        (workspace / "interviews" / "atlas-onboarding-2026-11-02-summary.md").write_text(
            "summary", encoding="utf-8"
        )
        events = [
            {"title": "Interview with Ada", "start": "2026-11-02T10:00:00",
             "attendees": ["ada@acme.example"]},
            {"title": "Interview with Bob", "start": "2026-11-05T14:00:00",
             "attendees": ["bob@bigco.example"]},
            {"title": "Weekly sync", "start": "2026-11-06T09:00:00",
             "attendees": ["a@corp.example", "b@corp.example"]},
            {"title": "Old session", "start": "2026-10-01T10:00:00",
             "attendees": ["x@acme.example"]},
        ]
        stale = check_stale_transcripts(
            events, [root], 7, date.fromisoformat("2026-11-09")
        )
        check(
            "only the summary-less in-window interview is stale",
            stale == [{"title": "Interview with Bob", "date": "2026-11-05"}],
            repr(stale),
        )
        cache_path = tmp / "state" / "stale-transcript-cache.json"
        _write_cache(cache_path, stale)
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        check(
            "cache holds checked_at and the stale list",
            cache.get("checked_at")
            and cache.get("stale") == [{"title": "Interview with Bob", "date": "2026-11-05"}],
            repr(cache),
        )

        # --- render-appendix -------------------------------------------------
        key_path = tmp / "participant-key.md"
        key_path.write_text(
            "# Participant key\n\n"
            "| Name | Role | Account | ARR | Email |\n"
            "|---|---|---|---|---|\n"
            "| Ada Lovelace | Platform PM | Acme | $1.2M | ada@acme.example |\n"
            "| Grace Hopper | Staff EM | BigCo |  | grace@bigco.example |\n"
            "|  | Role Only |  |  |  |\n",
            encoding="utf-8",
        )
        headers, rows = read_participant_key(key_path)
        lines = render_appendix_lines(headers, rows, {"BigCo": "$800K"})
        check(
            "appendix prints Name, Role (Account, ARR) with arr-file fill",
            lines == ["Ada Lovelace, Platform PM (Acme, $1.2M)", "Grace Hopper, Staff EM (BigCo, $800K)"],
            repr(lines),
        )
        lines_no_arr = render_appendix_lines(headers, rows, {})
        check(
            "absent ARR stays out when no arr-file fills it",
            lines_no_arr[1] == "Grace Hopper, Staff EM (BigCo)",
            repr(lines_no_arr),
        )

        # --- pick_transcript --------------------------------------------------
        candidates = [
            {"source": "recorder-raw", "kind": "raw text", "path": "C:/recordings/raw.txt"},
            {"source": "otter-recap", "kind": "speaker-labeled with a summary", "url": "https://otter.example/recap"},
            {"source": "zoom-audio", "kind": "speaker-labeled", "url": "https://zoom.example/x"},
        ]
        picked = pick_transcript(candidates)
        check(
            "priority picks the speaker-labeled candidate with a summary",
            picked["chosen"]["source"] == "otter-recap",
            repr(picked),
        )
        check(
            "the two losing candidates are named, not copied",
            [item["source"] for item in picked["named_not_copied"]] == ["zoom-audio", "recorder-raw"],
            repr(picked["named_not_copied"]),
        )
        picked_raw_only = pick_transcript(
            [{"source": "raw-a", "kind": "raw text"}, {"source": "raw-b", "kind": "raw text"}]
        )
        check(
            "equal ranks keep the first candidate",
            picked_raw_only["chosen"]["source"] == "raw-a"
            and [item["source"] for item in picked_raw_only["named_not_copied"]] == ["raw-b"],
            repr(picked_raw_only),
        )
        check("no candidates choose nothing", pick_transcript([])["chosen"] is None)

        # --- check_recap -------------------------------------------------------
        footer = "_Posted by Claude Code on behalf of Ada._"
        good = (
            "[uxr-debrief 2026-11-05]\n\n"
            "The session ran 42 minutes with Ada, a platform PM at Acme, from the "
            "Otter recap. Transcript link: https://otter.example/recap; filed at "
            "interviews/atlas-onboarding-2026-11-05-summary.md.\n\n"
            "What landed: onboarding feels long, and she gave up on the second step. "
            "She wants the summary screen first. The import flow confused her.\n\n"
            "Not covered: billing permissions.\n\n" + footer
        )
        check("a well-formed recap passes", check_recap(good, "2026-11-05", footer) == [],
              repr(check_recap(good, "2026-11-05", footer)))
        bad_code = good.replace("the second step", "RQ2 stayed open and H1 held")
        failures_code = check_recap(bad_code, "2026-11-05", footer)
        check(
            "a bare RQ/H token fails the recap",
            any("RQ2" in line for line in failures_code),
            repr(failures_code),
        )
        long_text = "[uxr-debrief 2026-11-05]\n" + ("word " * 210)
        check(
            "a recap over the word cap fails",
            any("200" in line for line in check_recap(long_text, "2026-11-05", "")),
            repr(check_recap(long_text, "2026-11-05", "")),
        )
        missing_sections = "[uxr-debrief 2026-11-05]\n\nShort note.\n"
        check(
            "missing What landed / Not covered sections fail",
            len(check_recap(missing_sections, "2026-11-05", "")) == 2,
            repr(check_recap(missing_sections, "2026-11-05", "")),
        )
        check(
            "a wrong heading date fails",
            any("exactly" in line for line in check_recap(good, "2026-11-06", footer)),
            repr(check_recap(good, "2026-11-06", footer)),
        )
        check(
            "a missing or wrong footer fails",
            any("footer" in line for line in check_recap(good, "2026-11-05", "_Signed otherwise._")),
            repr(check_recap(good, "2026-11-05", "_Signed otherwise._")),
        )

        # --- check_summary_stances ----------------------------------------------
        aligned = (
            "# Session\n\nNotes.\n\n"
            "## Insights \u2192 Research Alignment\n"
            "**Research Questions**\n"
            "- RQ1 (How do users import?): The import lost her file once.\n"
            "**Hypotheses**\n"
            "- H1 (Import reduces confusion): Supports - she retried three times.\n"
            "- H2 (Summary first): Mixed - liked it, missed the chart.\n"
            "**Assumptions**\n"
            "- A1 (Data loss is rare): Holds this session - no loss observed.\n"
            "\n## Notable quotes\n"
        )
        check(
            "a contract alignment block passes check-summary",
            check_summary_stances(aligned) == [],
            repr(check_summary_stances(aligned)),
        )
        off_assumption = check_summary_stances(aligned.replace(
            "- A1 (Data loss is rare): Holds this session - no loss observed.",
            "- A1 (Data loss is rare): Mixed this session - half lost."))
        check(
            "an off-contract assumption stance warns",
            off_assumption == [
                "WARN stance on A1 (Data loss is rare) is outside the contract "
                "(Holds / Breaks / Untested); rewrite the alignment block in the summary"
            ],
            repr(off_assumption),
        )
        off_hypothesis = check_summary_stances(aligned.replace(
            "- H2 (Summary first): Mixed - liked it, missed the chart.",
            "- H2 (Summary first): Holds - liked it."))
        check(
            "an off-contract hypothesis stance warns",
            len(off_hypothesis) == 1 and "H2" in off_hypothesis[0]
            and "Supports / Challenges / Mixed" in off_hypothesis[0],
            repr(off_hypothesis),
        )
        check(
            "a summary without an alignment block warns",
            len(check_summary_stances("# Session notes\n\nNo block.\n")) == 1,
            repr(check_summary_stances("# Session notes\n\nNo block.\n")),
        )
        off_path = tmp / "off-contract-summary.md"
        off_path.write_text(aligned.replace(
            "- A1 (Data loss is rare): Holds this session - no loss observed.",
            "- A1 (Data loss is rare): Mixed this session - half lost."),
            encoding="utf-8")
        check(
            "check-summary exits 1 on an off-contract stance",
            main(["check-summary", "--file", str(off_path)]) == EXIT_FAIL,
        )
        good_path = tmp / "aligned-summary.md"
        good_path.write_text(aligned, encoding="utf-8")
        check(
            "check-summary exits 0 on a contract block",
            main(["check-summary", "--file", str(good_path)]) == EXIT_OK,
        )

        # --- upload_plan ---------------------------------------------------------
        nb = tmp / "notebook-study"
        (nb / "interviews" / "raw-transcripts").mkdir(parents=True)
        (nb / OVERVIEW_MARKER).write_text("# plan", encoding="utf-8")
        (nb / "interviews" / "notebook-study-2026-11-02-summary.md").write_text("s", encoding="utf-8")
        (nb / "interviews" / "notebook-study-2026-11-05-summary.md").write_text("s", encoding="utf-8")
        (nb / "interviews" / "participant-key.md").write_text("key", encoding="utf-8")
        (nb / "interviews" / "raw-transcripts" / "raw.txt").write_text("raw", encoding="utf-8")
        plan = upload_plan(nb)
        names = [item["source_name"] for item in plan["uploads"]]
        check(
            "upload plan names the plan and session sources",
            names == ["Research-Plan-notebook-study", "T-notebook-study-2026-11-02",
                      "T-notebook-study-2026-11-05"],
            repr(names),
        )
        upload_paths = " ".join(item["path"] for item in plan["uploads"])
        check(
            "no participant-key or raw-transcripts path is uploadable",
            "participant-key" not in upload_paths and "raw-transcripts" not in upload_paths,
            repr(upload_paths),
        )
        excluded_text = " ".join(item["path"] for item in plan["excluded"])
        check(
            "forbidden paths are reported as excluded",
            "participant-key.md" in excluded_text and "raw-transcripts/raw.txt" in excluded_text,
            repr(excluded_text),
        )

    # --- usage errors ------------------------------------------------------
    check(
        "missing --events-json is a usage error",
        main(["check-stale-transcripts", "--research-dirs", "."]) == EXIT_USAGE,
    )
    check(
        "missing --key is a usage error",
        main(["render-appendix"]) == EXIT_USAGE,
    )
    check(
        "missing --candidates is a usage error",
        main(["pick-transcript"]) == EXIT_USAGE,
    )
    check(
        "missing --file is a usage error",
        main(["check-recap"]) == EXIT_USAGE,
    )
    check(
        "missing --file for check-summary is a usage error",
        main(["check-summary"]) == EXIT_USAGE,
    )
    check(
        "missing --workspace is a usage error",
        main(["upload-plan"]) == EXIT_USAGE,
    )
    check(
        "missing --payload is a usage error for assemble-summary",
        main(["assemble-summary", "--file", "x.md"]) == EXIT_USAGE,
    )
    check(
        "missing --date is a usage error for render-recap",
        main(["render-recap", "--file", "x.md", "--payload", "y.json"]) == EXIT_USAGE,
    )
    with tempfile.TemporaryDirectory() as td:
        payload_path = Path(td) / "payload.json"
        payload_path.write_text(json.dumps({
            "session": {"paragraph": "A 45-minute session with Participant A about finding the timeline."},
            "quotes": [{"speaker": "Participant A", "text": "I looked in the header first."}],
            "alignment": {
                "rq": [{"id": "RQ1", "short": "where users look", "finding": "Header first."},
                       {"id": "RQ2", "short": "first planning attempt", "finding": ""}],
                "hypotheses": [{"id": "H1", "label": "Header first", "stance": "Supports", "why": "cited funnel counts"}],
                "assumptions": [{"id": "A1", "label": "first-session want", "stance": "Holds", "why": "clearly described"}],
            },
        }, ensure_ascii=False), encoding="utf-8")
        summary_path = Path(td) / "summary.md"
        code = main(["assemble-summary", "--file", str(summary_path), "--payload", str(payload_path)])
        text = summary_path.read_text(encoding="utf-8")
        check("assemble-summary writes the frozen block",
              code == EXIT_OK
              and "## Insights → Research Alignment" in text
              and "- RQ2 (first planning attempt): No direct evidence this session." in text
              and "Holds this session - clearly described" in text, repr(text[:200]))
        check("assemble-summary output passes check-summary",
              main(["check-summary", "--file", str(summary_path)]) == EXIT_OK)
        recap_path = Path(td) / "recap.md"
        code = main(["render-recap", "--file", str(recap_path), "--payload", str(payload_path),
                     "--date", "2026-11-18", "--footer", "Posted by the runner."])
        recap = recap_path.read_text(encoding="utf-8")
        check("render-recap writes the fixed shape",
              code == EXIT_OK and recap.startswith("[uxr-debrief 2026-11-18]")
              and "What landed:" in recap and "Not covered:" in recap
              and recap.rstrip().endswith("Posted by the runner."), repr(recap[:120]))
        check("render-recap output passes check-recap",
              main(["check-recap", "--file", str(recap_path), "--date", "2026-11-18",
                    "--footer", "Posted by the runner."]) == EXIT_OK)

    # --- golden recap fixture: the prose shape byte-matches the baseline ---
    fixture = (Path(__file__).resolve().parent.parent if (Path(__file__).resolve().parent.parent / "tests").is_dir() else Path(__file__).resolve().parent.parent.parent) / "tests" / "fixtures" / "debrief"
    case_path, expected_path = fixture / "recap-golden.json", fixture / "recap-golden.expected.txt"
    if case_path.is_file() and expected_path.is_file():
        case = json.loads(case_path.read_text(encoding="utf-8"))
        got = render_recap_text(case["payload"], case["date"], case["footer"])
        check("recap-golden fixture byte-matches the baseline draft",
              got == expected_path.read_text(encoding="utf-8"),
              repr(got[:160]))
        check("recap-golden fixture passes check-recap",
              check_recap(got, case["date"], case["footer"]) == [],
              repr(check_recap(got, case["date"], case["footer"])))
    else:
        print("skip: fixtures not shipped (repo-level tests/)")  # installed plugin has no fixtures

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
