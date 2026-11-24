from _harness import bind

bind("scripts.scaffold_workspace", globals())
def _write_template(root: Path, *, with_hypotheses_token: bool = True) -> Path:
    template = root / "template"
    (template / "recruitment").mkdir(parents=True)
    (template / "sources").mkdir()
    hyp_token = "{{HYPOTHESES_BLOCK}}" if with_hypotheses_token else ""
    (template / "00-overview.md").write_text(
        "\n".join(
            [
                "# {{STUDY_TITLE}}",
                "",
                "## Ticket",
                "",
                "- Ticket: {{TICKET_KEY}} ({{STATUS}})",
                "- Link: {{TICKET_URL}}",
                "",
                "## Team",
                "",
                "- UXR: {{UXR_NAME}} Slack: {{SLACK_CHANNEL}}",
                "",
                "## JTBD & Personas",
                "",
                "{{JTBD_REFS}}",
                "",
                "{{PERSONA_REFS}}",
                "",
                "## Background",
                "",
                "{{HISTORY}}",
                "",
                "## Key decision",
                "",
                "{{DECISION}}",
                "",
                "## Hypotheses",
                "",
                hyp_token,
                "",
                "## Assumptions",
                "",
                "{{ASSUMPTIONS_BLOCK}}",
                "",
                "## Research questions",
                "",
                "{{RESEARCH_QUESTIONS_BLOCK}}",
                "",
                "## Resources",
                "",
                "{{RESOURCES_BLOCK}}",
                "",
                "## Method",
                "",
                "- Method: {{METHOD}} key {{METHOD_KEY}} channel {{CHANNEL}}",
                "- Sample: {{SAMPLE}} persona {{PERSONA}} length {{SESSION_LENGTH}}",
                "- Type {{RESEARCH_TYPE}} investment {{INVESTMENT}} pod {{POD}}",
                "- People: pm {{PM_NAME}} pd {{DESIGNER_NAME}} em {{EM_NAME}}",
                "",
                "## Participants",
                "",
                "{{COLUMN_NOTES}}",
                "",
                "{{PARTICIPANTS_TABLE}}",
                "",
                "Statuses: {{STATUS_VOCABULARY}}",
            ]
        ),
        encoding="utf-8",
    )
    (template / "recruitment" / "participants.md").write_text(
        "{{COLUMN_NOTES}}\n\n{{PARTICIPANTS_TABLE}}\n\nStatuses: {{STATUS_VOCABULARY}}\n",
        encoding="utf-8",
    )
    (template / "CLAUDE.md").write_text(
        "# {{STUDY_SLUG}}\n\nStudy {{STUDY_TITLE}} for {{TICKET_KEY}}.\n",
        encoding="utf-8",
    )
    (template / ".gitignore").write_text(
        "interviews/participant-key.md\ninterviews/raw-transcripts/\n.env\n", encoding="utf-8"
    )
    return template


def _five_hypothesis_spec() -> dict:
    return {
        "history": "Support tickets doubled after the billing rework.",
        "decision": "Should the redesigned invoice page ship to all tenants?",
        "hypotheses": [
            {"label": f"H{i}", "text": f"Hypothesis {i} is falsifiable."} for i in range(1, 6)
        ],
        "assumptions": [{"label": "A1", "text": "Admins reconcile invoices monthly."}],
        "research_questions": ["How do admins export invoices today?"],
        "resources": [
            {
                "label": "Prior research",
                "url": "https://example.com/prior",
                "share_status": "shared",
            },
            {
                "label": "Draft deck",
                "url": "https://example.com/deck",
                "share_status": "private",
                "share_note": "ask the author",
            },
        ],
        "jtbd_refs": [{"label": "Get paid fast", "url": "https://example.com/jtbd", "ring": "internal"}],
        "persona_refs": [{"label": "Tenant admin", "url": "https://example.com/persona", "ring": "external"}],
        "slack_channel": {"name": " invoicing ", "id": "C1"},
        "method_key": "interview",
        "channel": "internal",
    }


def _readme_with_table(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Research",
                "",
                README_TABLE_HEADER,
                README_TABLE_DELIM,
                "| [Old study](old-study/) | [OLD-1](https://example.com/old) | Done | Ada | 3 files |",
                "",
                "Notes below the table.",
            ]
        ),
        encoding="utf-8",
    )


def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/scaffold_workspace.py selftest")

    # --- slug ----------------------------------------------------------------
    check("slug lowercases and hyphenates", make_slug("Invoice Export Usability!", "Q1-2027")
          == "invoice-export-usability-q1-2027")
    check("slug collapses non-alphanumeric runs to one hyphen",
          make_slug("Pricing -- & Packaging (v2)", "q3-2026") == "pricing-packaging-v2-q3-2026")
    check("slug trims leading and trailing hyphens", make_slug("  --Admin 42 --", "q2-2026")
          == "admin-42-q2-2026")
    check("slug does not append the quarter twice", make_slug("Billing Q3-2026", "q3-2026")
          == "billing-q3-2026")
    long_title = "Understanding how enterprise tenants reconcile multi-entity invoices across quarters"
    long_slug = make_slug(long_title, "q1-2027", 50)
    body = long_slug.rsplit("-q1-2027", 1)[0]
    check(
        "slug cuts a long body at the last hyphen inside max_body",
        len(long_slug) <= 50 + len("-q1-2027") and body == body.rstrip("-") and "-" in body
        and len(body) <= 50,
        long_slug,
    )
    check("slug falls back to 'study' on a punctuation-only title",
          make_slug("!!!", "q1-2027") == "study-q1-2027")

    # --- block and computed tokens --------------------------------------------
    config = {"org": {"team_share_domain": "example.com"}}
    blocks = render_block_tokens(_five_hypothesis_spec(), config)
    hyp_text = blocks["HYPOTHESES_BLOCK"][0]
    check(
        "hypotheses render as numbered bold-label lines in order",
        hyp_text.splitlines() == [
            "1. **H1.** Hypothesis 1 is falsifiable.",
            "2. **H2.** Hypothesis 2 is falsifiable.",
            "3. **H3.** Hypothesis 3 is falsifiable.",
            "4. **H4.** Hypothesis 4 is falsifiable.",
            "5. **H5.** Hypothesis 5 is falsifiable.",
        ],
        hyp_text,
    )
    check(
        "resources lock private links and append the share legend",
        f"- [{LOCK} ][Draft deck](https://example.com/deck) (ask the author)"
        in blocks["RESOURCES_BLOCK"][0]
        and "- [Prior research](https://example.com/prior)" in blocks["RESOURCES_BLOCK"][0]
        and "set the example.com domain to Commenter" in blocks["RESOURCES_BLOCK"][0],
        blocks["RESOURCES_BLOCK"][0],
    )
    check("refs render label, url, and ring",
          blocks["PERSONA_REFS"][0] == "- [Tenant admin](https://example.com/persona) _external_",
          blocks["PERSONA_REFS"][0])
    check("slack channel renders as a hash name", blocks["SLACK_CHANNEL"][0] == "#invoicing")
    empty = render_block_tokens({}, config)
    check("empty lists render italic notes",
          empty["HYPOTHESES_BLOCK"][0] == "_No hypotheses defined yet._"
          and empty["RESOURCES_BLOCK"][0] == "_No resources linked yet._"
          and empty["SLACK_CHANNEL"] == ("_No Slack channel yet._", False),
          repr(empty["HYPOTHESES_BLOCK"][0]))

    check(
        "survey plus external gives the acceptance columns",
        participants_columns("survey", "external")
        == ["Name", "Title", "Company", "ARR", "Reason", "Email", "Status"],
    )
    check(
        "interview plus internal gives the acceptance columns",
        participants_columns("interview", "internal")
        == ["Name", "Title", "Reason", "Email", "Slack", "Status", "Session date", "Recording"],
    )

    # --- scaffold ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        spec_path = root / "study.spec.json"
        spec_path.write_text(json.dumps(_five_hypothesis_spec()), encoding="utf-8")
        readme = root / "README.md"
        _readme_with_table(readme)
        target = root / "invoice-export-q1-2027"
        mapping = {
            "STUDY_TITLE": "Invoice Export Usability",
            "STUDY_SLUG": target.name,
            "TICKET_KEY": "ABC-42",
            "STATUS": "Planned",
            "POD": "Invoicing",
            "UXR_NAME": "Ada Example",
            "PM_NAME": "PM Example",
            "DESIGNER_NAME": "PD Example",
            "EM_NAME": "EM Example",
            "DECISION": "Ship the redesigned page?",
            "RESEARCH_TYPE": "Evaluative",
            "METHOD": "Internal Interviews",
            "SAMPLE": "8-10 admins",
            "PERSONA": "Tenant admins",
            "SESSION_LENGTH": "45 min",
            "INVESTMENT": "M",
            "TICKET_URL": "https://example.com/browse/ABC-42",
        }
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme),
                "--spec": str(spec_path),
            }
        )
        check("scaffold exits 0", code == EXIT_OK, str(code))

        # Acceptance: no {{ left in any .md file.
        leftovers = [
            str(p) for p in sorted(target.rglob("*.md")) if "{{" in p.read_text(encoding="utf-8")
        ]
        check("no {{ tokens survive in workspace .md files", not leftovers, str(leftovers))

        # Acceptance: 5 hypotheses in order in 00-overview.md.
        overview = (target / "00-overview.md").read_text(encoding="utf-8")
        hyp_start = overview.splitlines().index("## Hypotheses")
        hyp_end = next(
            i for i, line in enumerate(overview.splitlines()[hyp_start + 1:], hyp_start + 1)
            if line.startswith("## ")
        )
        numbered = [
            line for line in overview.splitlines()[hyp_start + 1:hyp_end]
            if re.match(r"^\d+\. \*\*", line)
        ]
        check("5 hypotheses appear in order in 00-overview.md",
              len(numbered) == 5 and numbered[0].startswith("1. **H1.**")
              and numbered[4].startswith("5. **H5.**"), str(numbered))

        # Acceptance: README gets exactly one new row; the table stays contiguous.
        readme_lines = readme.read_text(encoding="utf-8").splitlines()
        table_rows = [
            line for line in readme_lines if line.strip().startswith("|") and "---" not in line
        ]
        new_row = [line for line in table_rows if "Invoice Export Usability" in line]
        check(
            "README gains exactly one row and stays contiguous",
            len(table_rows) == 3
            and len(new_row) == 1
            and "[ABC-42](https://example.com/browse/ABC-42)" in new_row[0]
            and "0 files" in new_row[0]
            and readme_lines.index(table_rows[2]) == readme_lines.index(table_rows[1]) + 1,
            "\n".join(table_rows),
        )

        # Participants table columns for interview/internal (from the spec).
        participants = (target / "recruitment" / "participants.md").read_text(encoding="utf-8")
        header_line = next(
            (line for line in participants.splitlines() if line.startswith("| Name")), ""
        )
        check(
            "spec method/channel drive the participants header (interview, internal)",
            header_line == "| Name | Title | Reason | Email | Slack | Status | Session date | Recording |",
            header_line,
        )

        # Acceptance: git check-ignore succeeds in the new workspace.
        gate = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "gitignore_gate.py"),
             "assert-ignored", "--repo", str(target),
             "interviews/raw-transcripts/x.txt", "interviews/participant-key.md"],
            capture_output=True, text=True, timeout=60,
        )
        check("gitignore gate passes in the scaffolded workspace", gate.returncode == 0,
              gate.stderr.strip())

        # Acceptance: the scaffold commit stages only the workspace and the README.
        code, top, _ = _git(["rev-parse", "--show-toplevel"], target)
        repo = Path(top)
        show = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        committed = sorted(show.stdout.split())
        expected_files = sorted(
            [Path(os.path.relpath(p, repo)).as_posix() for p in target.rglob("*") if p.is_file()]
            + [Path(os.path.relpath(readme, repo)).as_posix()]
        )
        check(
            "the commit stages only the workspace and the README",
            committed == sorted(set(expected_files)),
            f"committed={committed}",
        )
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--",
             str(Path(os.path.relpath(target, repo)).as_posix()),
             str(Path(os.path.relpath(readme, repo)).as_posix())],
            capture_output=True, text=True, timeout=60,
        )
        check("the workspace and README are clean after the scaffold commit",
              status.stdout.strip() == "", status.stdout)

        # Acceptance: a second scaffold to the same target fails.
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme),
                "--spec": str(spec_path),
            }
        )
        check("second scaffold to the same target exits 3", code == EXIT_ASSERT, str(code))
        check("second scaffold adds no README row",
              len([line for line in readme.read_text(encoding="utf-8").splitlines()
                   if "Invoice Export Usability" in line]) == 1)

        # F4: a parent git repo around the research root must not swallow the
        # initial commit; the root itself becomes the repository.
        root4 = Path(td) / "parented"
        research4 = root4 / "research"
        research4.mkdir(parents=True)
        _git(["init", "-q"], root4)
        (root4 / ".gitignore").write_text("research/\n", encoding="utf-8")
        template4 = _write_template(root4)
        readme4 = research4 / "README.md"
        _readme_with_table(readme4)
        target4 = research4 / "parented-study"
        code4 = cmd_scaffold(
            {
                "--template": str(template4),
                "--target": str(target4),
                "--mapping": json.dumps({"STUDY_TITLE": "Parented Study",
                                         "TICKET_KEY": "ABC-90", "STUDY_SLUG": "parented-study",
                                         "STATUS": "Planned", "UXR_NAME": "Ada",
                                         "TICKET_URL": "https://example.com/ABC-90"}),
                "--readme": str(readme4),
                "--spec": str(spec_path),
            }
        )
        check("scaffold inside a parent git repo exits 0", code4 == EXIT_OK, str(code4))
        top_code4, top4, _ = _git(["rev-parse", "--show-toplevel"], target4)
        check("the research root is its own repository",
              top_code4 == 0 and Path(top4).resolve() == research4.resolve(), top4)
        log_code4, log4, _ = _git(["log", "--oneline"], research4)
        check("the initial commit lands in the research root repo",
              log_code4 == 0 and "Add parented-study workspace" in log4, log4)

        # Template missing the hypotheses token fails with exit 3.
        root2 = Path(td) / "second"
        root2.mkdir()
        template2 = _write_template(root2, with_hypotheses_token=False)
        readme2 = root2 / "README.md"
        _readme_with_table(readme2)
        code = cmd_scaffold(
            {
                "--template": str(template2),
                "--target": str(root2 / "ws"),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme2),
                "--spec": str(spec_path),
            }
        )
        check("removing {{HYPOTHESES_BLOCK}} from the template exits 3",
              code == EXIT_ASSERT, str(code))
        check("the failed scaffold leaves no target behind", not (root2 / "ws").exists())

        # Spec prose containing {{x}} is not a failure.
        root3 = Path(td) / "third"
        root3.mkdir()
        template3 = _write_template(root3)
        spec3 = _five_hypothesis_spec()
        spec3["history"] = "Legacy body said {{HISTORY}} once."
        spec_path3 = root3 / "study.spec.json"
        spec_path3.write_text(json.dumps(spec3), encoding="utf-8")
        readme3 = root3 / "README.md"
        _readme_with_table(readme3)
        target3 = root3 / "ws3"
        code = cmd_scaffold(
            {
                "--template": str(template3),
                "--target": str(target3),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme3),
                "--spec": str(spec_path3),
                "--no-commit": "true",
            }
        )
        check("a {{x}} inside spec prose is not a failure", code == EXIT_OK, str(code))
        prose_kept = "{{HISTORY}} once." in (target3 / "00-overview.md").read_text(encoding="utf-8")
        check("the spec prose token stays as prose", prose_kept)

        # Usage errors.
        check("scaffold without --template exits 2",
              cmd_scaffold({"--target": "x", "--readme": "y"}) == EXIT_USAGE)
        check("scaffold with bad mapping JSON exits 2",
              cmd_scaffold({"--template": str(template), "--target": str(root3 / "ws4"),
                            "--readme": str(readme3), "--mapping": "{oops"}) == EXIT_USAGE)
        check("scaffold with an unreadable spec exits 2",
              cmd_scaffold({"--template": str(template), "--target": str(root3 / "ws5"),
                            "--readme": str(readme3), "--spec": str(root3 / "absent.json"),
                            "--no-commit": "true"}) == EXIT_USAGE)

    # --- --no-commit makes no commit ----------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(root / "ws"),
                "--mapping": json.dumps({"STUDY_TITLE": "No commit study", "TICKET_KEY": "X-1",
                                         "STUDY_SLUG": "ws",
                                         "TICKET_URL": "https://example.com/X-1"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        check("scaffold --no-commit exits 0 outside a repo", code == EXIT_OK, str(code))
        check("scaffold --no-commit creates no repository", not (root / ".git").exists())

    # --- lookup-workspace ------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        target = root / "lookup-study"
        cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps({"STUDY_TITLE": "Lookup Study", "TICKET_KEY": "ABC-77",
                                         "STUDY_SLUG": "lookup-study", "STATUS": "Planned",
                                         "UXR_NAME": "Ada",
                                         "TICKET_URL": "https://example.com/ABC-77"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        found = find_workspace("ABC-77", readme)
        check("lookup-workspace finds the scaffolded workspace",
              found is not None and found.name == "lookup-study", str(found))
        check("lookup resolves relative to the README",
              found is not None and (found / "00-overview.md").is_file())
        check("lookup misses on an unknown ticket", find_workspace("ABC-999", readme) is None)
        code = cmd_lookup({"--ticket": "ABC-999", "--readme": str(readme)})
        check("lookup miss exits 1", code == EXIT_WARN, str(code))
        check("lookup without --ticket exits 2", cmd_lookup({"--readme": str(readme)}) == EXIT_USAGE)

    # --- render-overview --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        spec_path = root / "s.json"
        spec_path.write_text(json.dumps(_five_hypothesis_spec()), encoding="utf-8")
        target = root / "render-study"
        cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps({"STUDY_TITLE": "Render Study", "TICKET_KEY": "ABC-8",
                                         "STUDY_SLUG": "render-study", "STATUS": "Planned",
                                         "UXR_NAME": "Ada", "METHOD": "Internal Interviews",
                                         "TICKET_URL": "https://example.com/ABC-8"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        overview = target / "00-overview.md"
        before = overview.read_text(encoding="utf-8")
        method_before = next(
            line for line in before.splitlines() if line.startswith("- Method:")
        )
        edited = before.replace("# Render Study", "# Render Study (renamed by hand)")
        overview.write_text(edited, encoding="utf-8")
        spec2 = _five_hypothesis_spec()
        spec2["hypotheses"] = [{"label": "H1", "text": "Only one hypothesis now."}]
        spec2["decision"] = "Updated decision."
        spec_path2 = root / "s2.json"
        spec_path2.write_text(json.dumps(spec2), encoding="utf-8")
        code = cmd_render_overview(
            {"--ticket": "ABC-8", "--readme": str(readme), "--spec": str(spec_path2)}
        )
        after = overview.read_text(encoding="utf-8")
        method_after = next(
            (line for line in after.splitlines() if line.startswith("- Method:")), ""
        )
        check("render-overview exits 0", code == EXIT_OK, str(code))
        check("render-overview rewrites an owned section",
              "Updated decision." in after and "Only one hypothesis now." in after)
        check("render-overview keeps hand-owned sections",
              method_before == method_after and "(renamed by hand)" in after)
        # Missing section is an assertion failure.
        broken = overview.read_text(encoding="utf-8").replace("## Key decision", "## Key call")
        overview.write_text(broken, encoding="utf-8")
        code = cmd_render_overview(
            {"--ticket": "ABC-8", "--readme": str(readme), "--spec": str(spec_path2)}
        )
        check("render-overview with a missing owned section exits 3",
              code == EXIT_ASSERT, str(code))
        check("render-overview on an unknown ticket exits 1",
              cmd_render_overview({"--ticket": "ABC-999", "--readme": str(readme),
                                   "--spec": str(spec_path2)}) == EXIT_WARN)
        check("render-overview without --spec exits 2",
              cmd_render_overview({"--ticket": "ABC-8", "--readme": str(readme)}) == EXIT_USAGE)

    # --- append-outreach-entry -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log = root / "outreach-log.md"
        log.write_text("# Outreach log\n\nNewest first.\n\n---\n", encoding="utf-8")
        code = cmd_append_outreach(
            {
                "--log-path": str(log),
                "--date": "2026-11-09",
                "--name": "Ada Example",
                "--channel": "slack",
                "--status-from": "Potential Candidate",
                "--status-to": "Outreach Sent",
                "--notes": "Asked for 30 minutes.",
                "--slot": ["Tue 10:00", "Wed 14:00"],
                "--hold": ["Tue 10:00"],
                "--action": "Nudge in 2 business days",
            }
        )
        check("append-outreach-entry exits 0", code == EXIT_OK, str(code))
        text = log.read_text(encoding="utf-8")
        divider_index = text.splitlines().index("---")
        check("entry lands right after the first --- line",
              "Ada Example" in text.splitlines()[divider_index + 2], text)
        cmd_append_outreach(
            {
                "--log-path": str(log),
                "--date": "2026-11-10",
                "--name": "Rook Example",
                "--channel": "email",
                "--status-from": "No Response",
                "--status-to": "Scheduled",
            }
        )
        text2 = log.read_text(encoding="utf-8")
        first_entry = text2.splitlines()[text2.splitlines().index("---") + 2]
        check("newest entry is inserted first", "Rook Example" in first_entry, first_entry)
        check("slots and holds render as detail bullets",
              "Slots offered: Tue 10:00; Wed 14:00" in text
              and "Holds placed: Tue 10:00" in text, text)
        broken = root / "broken-log.md"
        broken.write_text("# No divider here\n", encoding="utf-8")
        check("append without a divider exits 3",
              cmd_append_outreach({"--log-path": str(broken), "--date": "2026-01-01",
                                   "--name": "X"}) == EXIT_ASSERT)
        check("append without a date exits 2",
              cmd_append_outreach({"--log-path": str(log), "--name": "X"}) == EXIT_USAGE)
        check("append with a missing log exits 2",
              cmd_append_outreach({"--log-path": str(root / "absent.md"), "--date": "2026-01-01",
                                   "--name": "X"}) == EXIT_USAGE)

    # --- validate-recruitment -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        participants = root / "participants.md"
        survey_external = (
            "| Name | Title | Company | ARR | Reason | Email | Status |\n"
            "|---|---|---|---|---|---|---|\n"
            "| Ada | Admin | Example Co | $10k |Exports daily | ada@example.com | Survey Sent |\n"
        )
        participants.write_text("# Participants\n\n" + survey_external, encoding="utf-8")
        check("validate passes on matching survey/external table",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_OK)
        participants.write_text("# Participants\n\n" + survey_external.replace(
            "| Survey Sent |", "| Maybe Later |"), encoding="utf-8")
        check("validate warns (exit 1) on an unknown status",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_WARN)
        participants.write_text(
            "# Participants\n\n| Name | Title |\n|---|---|\n", encoding="utf-8")
        check("validate warns (exit 1) on a header mismatch",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_WARN)
        participants.write_text("# No table\n", encoding="utf-8")
        check("validate with no table exits 3",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_ASSERT)
        check("validate rejects an unknown method with exit 2",
              cmd_validate_recruitment({"--path": str(participants), "--method": "panel",
                                        "--channel": "internal"}) == EXIT_USAGE)
        check("validate rejects an unknown channel with exit 2",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "partner"}) == EXIT_USAGE)
        check("validate with a missing file exits 2",
              cmd_validate_recruitment({"--path": str(root / "absent.md"), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_USAGE)
        check("acceptance column sets hold",
              participants_columns("survey", "external")
              == ["Name", "Title", "Company", "ARR", "Reason", "Email", "Status"]
              and participants_columns("interview", "internal")
              == ["Name", "Title", "Reason", "Email", "Slack", "Status", "Session date", "Recording"])

    # --- validate-recruitment, approved two-table shape (issue 135) ---------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        shipped = (Path(__file__).resolve().parents[2] / "uxr-plugin" / "templates"
                   / "workspace" / "recruitment" / "participants.md").read_text(encoding="utf-8")
        participants = root / "participants.md"
        participants.write_text(shipped, encoding="utf-8")
        check("the shipped two-table template validates clean (exit 0)",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_OK)
        two_tables = (
            "# Participants\n\n"
            "## Internal flow (default)\n\n"
            "| participant id | name | role/segment | team/org area |"
            " source (org-chart path) | screener result | status | consent-to-record |"
            " DM sent (date) | notes |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n"
            "| I-01 | Val Example | engineer | platform | manager path | pass"
            " | identified | | | |\n\n"
            "## External flow (`--external`)\n\n"
            "| participant id | name/pseudonym | contact | source (panel/channel) |"
            " screener result | status | consent-to-record | incentive status |"
            " DM sent (date) | prep note | notes |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n"
            "| P-01 | Ada Example | ada.example@example.com | panel | role fit: yes"
            " | invited | | not sent | | | |\n"
        )
        participants.write_text(two_tables, encoding="utf-8")
        check("a filled two-table file validates clean (exit 0)",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_OK)
        participants.write_text(
            two_tables.replace("| screener result |", "| screener |", 1), encoding="utf-8")
        check("a drifted approved header warns (exit 1), never asserts",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_WARN)
        participants.write_text(
            two_tables.replace("| invited |", "| maybe |"), encoding="utf-8")
        check("an unknown status in the two-table shape warns (exit 1)",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_WARN)
        participants.write_text("# Participants\n\nno tables here\n", encoding="utf-8")
        check("a table-less file still asserts (exit 3)",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_ASSERT)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
