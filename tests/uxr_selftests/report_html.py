from _harness import bind

bind("scripts.report_html", globals())
def _selftest() -> int:
    """Offline checks: safety, determinism, structure, bar strengths."""
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/report_html.py selftest")

    fixture = (
        "---\n"
        "slug: report-leadership-2026-11-09-abc-237\n"
        "ticket: ABC-237\n"
        "tier: strategic\n"
        "audience: leadership\n"
        "date: 2026-11-09\n"
        "sources_cited: [onboarding-confusion, import-flow]\n"
        "hypotheses:\n"
        "  - id: H1\n"
        '    label: "Import reduces confusion"\n'
        "    verdict: Supported\n"
        "  - id: H2\n"
        '    label: "Users want the summary first"\n'
        "    verdict: Partially supported\n"
        "  - id: H3\n"
        '    label: "Docs are enough"\n'
        "    verdict: Not supported\n"
        "  - id: H4\n"
        '    label: "Data loss is rare"\n'
        "    verdict: Insufficient evidence\n"
        "---\n\n"
        "# Import redesign findings\n\n"
        "## Executive Summary\n\n"
        "- Import loses files and trust with them.\n"
        "- Participants want the summary screen first.\n"
        "- The docs path needs a rebuild before launch.\n\n"
        "## Key Findings\n\n"
        'Ada said: "<script>alert(1)</script> it just vanished." '
        "Cited as [S:onboarding-confusion].\n\n"
        "- Finding one with detail.\n"
        "- Finding two with detail.\n\n"
        "## Methodology\n\n"
        "Eight sessions, 45 minutes each, think-aloud.\n"
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        source = tmp / "report.md"
        source.write_text(fixture, encoding="utf-8")
        first = tmp / "out" / "one.html"
        second = tmp / "out" / "two.html"
        check(
            "render exits 0",
            cmd_render(str(source), str(first)) == EXIT_OK,
        )
        cmd_render(str(source), str(second))
        bytes_one = first.read_bytes()
        bytes_two = second.read_bytes()
        check("two renders are byte-identical", bytes_one == bytes_two)
        html = bytes_one.decode("utf-8")
        check(
            "a <script> quote renders as text, never as script",
            "<script>" not in html and "&lt;script>alert(1)&lt;/script>" in html,
            "raw script tag found" if "<script>" in html else "escaped form missing",
        )
        check(
            "header shows ticket, tier, audience",
            "ABC-237 \u00b7 strategic \u00b7 leadership" in html,
        )
        widths = [int(m) for m in re.findall(r'style="width:(\d+)%"', html)]
        check(
            "four hypotheses give four bars of different lengths",
            len(widths) == 4 and len(set(widths)) == 4 and set(widths) == {90, 60, 30, 12},
            repr(widths),
        )
        check(
            "takeaway cards number 2 to 4",
            2 <= len(re.findall(r'<div class="takeaway">', html)) <= 4,
            str(len(re.findall(r'<div class="takeaway">', html))),
        )
        open_sections = len(re.findall(r'<details class="sec" open>', html))
        check("exactly one section is open", open_sections == 1, str(open_sections))
        method_positions = html.find('<details class="sec method">')
        check("method section exists and is closed",
              method_positions >= 0 and '<details class="sec method" open>' not in html)
        check(
            "method section is last",
            html.rfind('<details class="sec') == method_positions,
        )
        plain = "# Just a body\n\nNo front matter at all.\n"
        plain_html = render_html(plain)
        check(
            "a body without front matter still renders",
            plain_html.startswith("<!DOCTYPE html>")
            and '<div class="takeaway">' not in plain_html,
        )

    check("render without args is usage", main(["render"]) == EXIT_USAGE)
    check(
        "render of a missing file fails cleanly",
        main(["render", "no-such-file.md", str(Path("out.html"))]) == EXIT_FAIL,
    )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
