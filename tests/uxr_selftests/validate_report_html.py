from _harness import bind

bind("scripts.validate_report_html", globals())
def _selftest() -> int:
    """Offline checks over renders of known fixtures."""
    import tempfile

    import report_html

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/validate_report_html.py selftest")

    good_fixture = (
        "---\n"
        "slug: report-leadership-2026-11-09-abc-237\n"
        "ticket: ABC-237\n"
        "tier: strategic\n"
        "audience: leadership\n"
        "date: 2026-11-09\n"
        "sources_cited: [onboarding-confusion]\n"
        "hypotheses:\n"
        "  - id: H1\n"
        '    label: "Import reduces confusion"\n'
        "    verdict: Supported\n"
        "---\n\n"
        "## Executive Summary\n\n"
        "- Import loses files and trust with them.\n"
        "- Participants want the summary screen first.\n\n"
        "## Key Findings\n\n"
        "The quote cites [S:onboarding-confusion] as evidence.\n\n"
        "## Methodology\n\n"
        "Eight sessions, think-aloud.\n"
    )
    good_html = report_html.render_html(good_fixture)
    warnings = check_report_html(good_html, good_fixture)
    check("a correct render passes with no warnings", warnings == [], repr(warnings))

    check(
        "contrast math matches WCAG reference values",
        round(contrast_ratio("#000000", "#ffffff"), 2) == 21.0
        and round(contrast_ratio("#767676", "#ffffff"), 2) == 4.54
        and contrast_ratio("#777777", "#ffffff") < 4.5,
    )

    one_card = good_html.replace(
        '<div class="takeaway">Participants want the summary screen first.</div>', ""
    )
    warnings = check_report_html(one_card, good_fixture)
    check(
        "a single takeaway card warns",
        any("takeaway" in line for line in warnings),
        repr(warnings),
    )

    five_cards = good_html.replace(
        "</section>",
        '<div class="takeaway">Third card.</div>\n'
        '<div class="takeaway">Fourth card.</div>\n'
        '<div class="takeaway">Fifth card.</div>\n    </section>',
    )
    warnings = check_report_html(five_cards, good_fixture)
    check(
        "five takeaway cards warn",
        any("takeaway" in line for line in warnings),
        repr(warnings),
    )

    two_open = good_html.replace(
        '<details class="sec">\n    <summary>Key Findings</summary>',
        '<details class="sec" open>\n    <summary>Key Findings</summary>',
    )
    warnings = check_report_html(two_open, good_fixture)
    check(
        "a second open section warns",
        any("open" in line for line in warnings),
        repr(warnings),
    )

    method_open = good_html.replace(
        '<details class="sec method">', '<details class="sec method" open>'
    )
    warnings = check_report_html(method_open, good_fixture)
    check(
        "an open Method section warns",
        any("Method" in line for line in warnings),
        repr(warnings),
    )

    uncited_fixture = good_fixture.replace(
        "[S:onboarding-confusion] as evidence.",
        "[S:onboarding-confusion] and [S:not-listed] as evidence.",
    )
    warnings = check_report_html(report_html.render_html(uncited_fixture), uncited_fixture)
    check(
        "a citation outside sources_cited warns",
        any("[S:not-listed]" in line for line in warnings),
        repr(warnings),
    )

    low_contrast = good_html.replace("--pos: #116639;", "--pos: #90ee90;")
    warnings = check_report_html(low_contrast, good_fixture)
    check(
        "a low-contrast verdict color warns",
        any("--pos" in line for line in warnings),
        repr(warnings),
    )

    missing_var = good_html.replace("--accent: #0b5cad;", "")
    warnings = check_report_html(missing_var, good_fixture)
    check(
        "a missing color variable warns",
        any("--accent" in line for line in warnings),
        repr(warnings),
    )

    check(
        "check without args is usage",
        main(["check"]) == EXIT_USAGE,
    )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
