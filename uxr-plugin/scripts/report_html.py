#!/usr/bin/env python3
"""Render a report deliverable as one self-contained HTML file (issue 03).

``report_html.py render <md> <html>`` turns the Markdown deliverable and
its front matter into a single HTML file with no external assets:

- one self-contained file; byte-identical on two runs (no clock, no
  randomness);
- ``<`` is escaped before the Markdown conversion, so a participant
  quote carrying ``<script>`` renders as text and never as script;
- the header shows ``{ticket} - {tier} - {audience}`` from the front
  matter;
- 2 to 4 takeaway cards are drawn from the Executive Summary (bullets
  first, then sentences; Key Findings is the fallback when the tier has
  no Executive Summary);
- one ``<details class="sec">`` per H2 section, the first open;
- the Method section renders collapsed and last, with one bar per
  front-matter hypothesis whose length shows verdict strength
  (Supported 90, Partially supported 60, Not supported 30,
  Insufficient evidence 12) -- never one constant full width;
- accent and verdict colors meet WCAG 4.5:1 on both backgrounds
  (``--bg`` and ``--surface``); ``validate_report_html.py check``
  verifies that mechanically.

Exit codes: 0 ok, 1 input error, 2 usage, 4 self-test failure.
"""

from __future__ import annotations

import re
import sys
from html import escape as html_escape
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REFERENCES_DIR = SCRIPTS_DIR.parent / "references"
if str(REFERENCES_DIR) not in sys.path:
    sys.path.insert(0, str(REFERENCES_DIR))

from report_helpers import VERDICT_STRENGTH, parse_front_matter  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

#: Verdict class -> color token and chip label used by the bars.
VERDICT_COLOR = {
    "Supported": "pos",
    "Holds": "pos",
    "Partially supported": "mid",
    "Not supported": "neg",
    "Breaks": "neg",
    "Insufficient evidence": "low",
    "Untested": "low",
}

#: Fallback order for the takeaway source section (title match, lower case).
TAKEAWAY_SECTIONS = ("executive summary", "key findings", "summary")

CSS = """
:root {
  --bg: #ffffff;
  --surface: #f5f7fa;
  --fg: #1a1f2e;
  --accent: #0b5cad;
  --pos: #116639;
  --mid: #7a5800;
  --neg: #a61b1b;
  --low: #4b5563;
}
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 1.5rem; max-width: 46rem;
       background: var(--bg); color: var(--fg);
       font: 16px/1.6 system-ui, sans-serif; }
header .meta { color: var(--accent); font-weight: 600; letter-spacing: 0.02em; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
         gap: 0.75rem; margin: 1.25rem 0; }
.takeaway { background: var(--surface); border-left: 4px solid var(--accent);
            padding: 0.75rem 1rem; border-radius: 0.25rem; }
details.sec { background: var(--surface); border-radius: 0.25rem;
              margin: 0.75rem 0; padding: 0.5rem 1rem; }
details.sec > summary { cursor: pointer; font-weight: 600; color: var(--accent); }
.bar-row { display: grid; grid-template-columns: minmax(8rem, 14rem) auto 1fr;
           gap: 0.6rem; align-items: center; margin: 0.4rem 0; }
.bar-label { font-size: 0.9rem; }
.bar-verdict { font-size: 0.8rem; font-weight: 600; }
.bar-verdict.pos { color: var(--pos); }
.bar-verdict.mid { color: var(--mid); }
.bar-verdict.neg { color: var(--neg); }
.bar-verdict.low { color: var(--low); }
.bar-track { background: var(--bg); border: 1px solid var(--low);
             border-radius: 0.2rem; height: 0.8rem; overflow: hidden; }
.bar-fill { height: 100%; }
.bar-fill.pos { background: var(--pos); }
.bar-fill.mid { background: var(--mid); }
.bar-fill.neg { background: var(--neg); }
.bar-fill.low { background: var(--low); }
table { border-collapse: collapse; margin: 0.75rem 0; }
th, td { border: 1px solid var(--low); padding: 0.3rem 0.6rem;
         text-align: left; font-size: 0.9rem; }
blockquote { border-left: 3px solid var(--accent); margin-left: 0;
             padding-left: 1rem; color: var(--fg); }
pre { background: var(--surface); padding: 0.75rem; border-radius: 0.25rem;
      overflow-x: auto; }
a { color: var(--accent); }
"""

H2_SPLIT_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
EM_RE = re.compile(r"\*([^*]+)\*")
UL_RE = re.compile(r"^[-*+]\s+")
OL_RE = re.compile(r"^\d+[.)]\s+")


# ---------------------------------------------------------------------------
# markdown (subset) conversion -- input text is already < and & escaped
# ---------------------------------------------------------------------------


def _inline(text: str) -> str:
    """Inline Markdown (code, links, bold, italic) over escaped text."""
    placeholders: list[str] = []

    def stash(html: str) -> str:
        placeholders.append(html)
        return f"\x00{len(placeholders) - 1}\x00"

    text = INLINE_CODE_RE.sub(lambda m: stash(f"<code>{m.group(1)}</code>"), text)
    text = LINK_RE.sub(
        lambda m: stash(f'<a href="{html_escape(m.group(2), quote=True)}">{m.group(1)}</a>'),
        text,
    )
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = EM_RE.sub(r"<em>\1</em>", text)
    for index, snippet in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", snippet)
    return text


def _markdown_to_html(markdown: str) -> str:
    """A deterministic subset: headings, lists, quotes, tables, fences, paragraphs."""
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = stripped[:3]
            body: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                body.append(lines[index])
                index += 1
            index += 1  # closing fence
            out.append("<pre><code>" + "\n".join(body) + "</code></pre>")
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[index + 1]):
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(cell)}</th>" for cell in header)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row)
                                 + "</tr>" for row in rows)
                       + "</tbody></table>")
            continue
        if stripped.startswith("> "):
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("> "):
                quote.append(lines[index].strip()[2:])
                index += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            continue
        if UL_RE.match(stripped):
            items: list[str] = []
            while index < len(lines) and UL_RE.match(lines[index].strip()):
                items.append(_inline(UL_RE.sub("", lines[index].strip(), count=1)))
                index += 1
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
            continue
        if OL_RE.match(stripped):
            ordered: list[str] = []
            while index < len(lines) and OL_RE.match(lines[index].strip()):
                ordered.append(_inline(OL_RE.sub("", lines[index].strip(), count=1)))
                index += 1
            out.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered) + "</ol>")
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{level}>{_inline(stripped[level + 1:].strip())}</h{level}>")
            index += 1
            continue
        if not stripped:
            index += 1
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(?:[-*+]\s|\d+[.)]\s|>|\||#|```)", lines[index].strip()
        ):
            paragraph.append(_inline(lines[index].strip()))
            index += 1
        out.append("<p>" + " ".join(paragraph) + "</p>")
    return "\n".join(out)


def escape_body(markdown: str) -> str:
    """Escape before conversion: raw markup can never reach the output."""
    return str(markdown or "").replace("&", "&amp;").replace("<", "&lt;")


# ---------------------------------------------------------------------------
# structure: sections, takeaways, bars
# ---------------------------------------------------------------------------


def split_sections(body_markdown: str) -> list[tuple[str, str]]:
    """``(title, section_markdown)`` per H2; the preamble gets an empty title."""
    sections: list[tuple[str, str]] = []
    matches = list(H2_SPLIT_RE.finditer(body_markdown))
    if not matches:
        return [("", body_markdown)]
    preamble = body_markdown[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body_markdown)
        sections.append((match.group(1).strip(), body_markdown[match.end():end].strip()))
    return sections


def is_method_title(title: str) -> bool:
    return "method" in str(title or "").lower()


def extract_takeaways(body_markdown: str) -> list[str]:
    """2 to 4 takeaway lines from the Executive Summary (with fallbacks).

    Bullets are preferred; fewer than two falls back to sentences of the
    same section; a lone sentence is split at a middle word boundary.
    """
    sections = split_sections(body_markdown)
    source = ""
    lowered_titles = [title.lower() for title, _ in sections]
    for wanted in TAKEAWAY_SECTIONS:
        for title, text in sections:
            if wanted in title.lower():
                source = text
                break
        if source:
            break
    if not source:
        for title, text in sections:
            if title:
                source = text
                break
    if not source:
        return []
    lines = [line.strip() for line in source.splitlines()]
    bullets = [UL_RE.sub("", line, count=1) for line in lines if UL_RE.match(line)]
    if len(bullets) >= 2:
        return bullets[:4]
    prose = [line for line in lines if line and not re.match(r"^#{1,6}\s+", line)]
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(" ".join(prose)) if s.strip()]
    if len(sentences) >= 2:
        return sentences[:4]
    if sentences:
        words = sentences[0].split()
        if len(words) >= 4:
            cut = len(words) // 2
            return [" ".join(words[:cut]), " ".join(words[cut:])]
        return [sentences[0], sentences[0]]
    return []


def takeaway_cards(body_markdown: str) -> str:
    cards = extract_takeaways(body_markdown)
    if not cards:
        return ""
    rendered = "\n".join(
        f'      <div class="takeaway">{_inline(escape_body(card))}</div>'
        for card in cards
    )
    return f'    <section class="cards">\n{rendered}\n    </section>'


def hypothesis_bars(hypotheses: list) -> str:
    """One bar per front-matter hypothesis; length shows verdict strength."""
    rows: list[str] = []
    for entry in hypotheses or []:
        if not isinstance(entry, dict):
            continue
        hyp_id = str(entry.get("id", "")).strip()
        label = str(entry.get("label", "")).strip()
        verdict = str(entry.get("verdict", "Insufficient evidence")).strip()
        color = VERDICT_COLOR.get(verdict, "low")
        width = VERDICT_STRENGTH.get(verdict, 12)
        name = html_escape(f"{hyp_id} - {label}".strip(" -"), quote=True)
        rows.append(
            f'      <div class="bar-row"><span class="bar-label">{name}</span>'
            f'<span class="bar-verdict {color}">{html_escape(verdict, quote=True)}</span>'
            f'<div class="bar-track"><div class="bar-fill {color}" '
            f'style="width:{width}%"></div></div></div>'
        )
    if not rows:
        return ""
    body = "\n".join(rows)
    return f'      <div class="bars">\n{body}\n      </div>'


def render_html(markdown_text: str) -> str:
    """The full self-contained document for one deliverable."""
    front, body = parse_front_matter(markdown_text)
    ticket = html_escape(str(front.get("ticket", "")), quote=True)
    tier = html_escape(str(front.get("tier", "")), quote=True)
    audience = html_escape(str(front.get("audience", "")), quote=True)
    slug = html_escape(str(front.get("slug", "report")), quote=True)
    hypotheses = front.get("hypotheses") if isinstance(front.get("hypotheses"), list) else []
    escaped_body = escape_body(body)
    sections = split_sections(escaped_body)
    prose_sections = [section for section in sections if not is_method_title(section[0])]
    method_sections = [section for section in sections if is_method_title(section[0])]

    details: list[str] = []
    for position, (title, text) in enumerate(prose_sections):
        open_attr = " open" if position == 0 else ""
        heading = html_escape(title, quote=True)
        details.append(
            f'  <details class="sec"{open_attr}>\n'
            f"    <summary>{heading}</summary>\n"
            f"    {_markdown_to_html(text)}\n  </details>"
        )
    for title, text in method_sections:
        heading = html_escape(title, quote=True)
        bars = hypothesis_bars(hypotheses)
        bars_block = f"\n{bars}\n" if bars else ""
        details.append(
            f'  <details class="sec method">\n'
            f"    <summary>{heading}</summary>\n"
            f"    {_markdown_to_html(text)}{bars_block}\n  </details>"
        )
    cards = takeaway_cards(escaped_body)
    cards_block = f"\n{cards}\n" if cards else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{slug}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f'  <header><p class="meta">{ticket} \u00b7 {tier} \u00b7 {audience}</p></header>\n'
        f"{cards_block}\n"
        "<main>\n" + "\n".join(details) + "\n</main>\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_render(source_value: str, target_value: str) -> int:
    if not source_value or not target_value:
        print("report_html: render needs <md> <html>", file=sys.stderr)
        return EXIT_USAGE
    source = Path(source_value).expanduser()
    if not source.is_file():
        print(f"report_html: deliverable not found: {source}", file=sys.stderr)
        return EXIT_FAIL
    try:
        markdown_text = source.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"report_html: cannot read deliverable: {exc}", file=sys.stderr)
        return EXIT_FAIL
    html = render_html(markdown_text)
    target = Path(target_value).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    except OSError as exc:
        print(f"report_html: cannot write html: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(f"rendered {target} ({len(html)} bytes)")
    return EXIT_OK


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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK if not args else EXIT_USAGE
    if args[0] in ("--selftest", "selftest"):
        return _selftest()
    if args[0] == "render":
        positional = [arg for arg in args[1:] if not arg.startswith("--")]
        if len(positional) != 2:
            print("report_html: render needs exactly <md> <html>", file=sys.stderr)
            return EXIT_USAGE
        return cmd_render(positional[0], positional[1])
    print(f"report_html: unknown subcommand {args[0]!r}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
