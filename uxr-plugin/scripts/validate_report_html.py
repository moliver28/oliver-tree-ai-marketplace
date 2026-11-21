#!/usr/bin/env python3
"""Mechanical check for a rendered report HTML file (issue 03).

``validate_report_html.py check <html> --deliverable=<md>`` verifies:

- the takeaway count is 2 to 4;
- exactly one ``<details class="sec">`` section is open;
- the Method section, when present, is closed;
- every ``[S:<slug>``] citation in the deliverable appears in the
  deliverable's front-matter ``sources_cited``;
- the accent and verdict colors meet WCAG 4.5:1 contrast on both
  backgrounds (``--bg`` and ``--surface``), computed with the WCAG
  relative-luminance formula from the CSS variables the render defines.

Each broken rule prints one ``WARN:`` line; exit 1 on any WARN, 0 when
clean, 2 usage. The two-agent review loop runs after this check passes.

Exit codes: 0 clean, 1 any WARN or unreadable input, 2 usage, 4
self-test failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REFERENCES_DIR = SCRIPTS_DIR.parent / "references"
for entry in (str(SCRIPTS_DIR), str(REFERENCES_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from report_helpers import CITE_RE, collect_citations, parse_front_matter  # noqa: E402

EXIT_OK = 0
EXIT_WARN = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

CONTRAST_MINIMUM = 4.5

#: CSS variables checked, and the backgrounds each must hold contrast on.
COLOR_ROLES = ("accent", "pos", "mid", "neg", "low")
BACKGROUND_ROLES = ("bg", "surface")

TAKEAWAY_RE = re.compile(r'<div class="takeaway"')
OPEN_SECTION_RE = re.compile(r'<details class="sec"[^>]*\bopen\b')
METHOD_ELEMENT_RE = re.compile(r'<details class="sec method"[^>]*>')
CSS_VAR_RE = re.compile(r"--([a-z][a-z0-9-]*)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;")

MIN_TAKEAWAYS = 2
MAX_TAKEAWAYS = 4


# ---------------------------------------------------------------------------
# WCAG contrast
# ---------------------------------------------------------------------------


def _relative_luminance(hex_color: str) -> float:
    text = hex_color.lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    red, green, blue = (int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two hex colors (>= 1.0)."""
    one = _relative_luminance(first)
    two = _relative_luminance(second)
    lighter, darker = max(one, two), min(one, two)
    return (lighter + 0.05) / (darker + 0.05)


def parse_css_variables(html: str) -> dict[str, str]:
    """``{role: hex}`` for every CSS custom property defined in the file."""
    return {name: value for name, value in CSS_VAR_RE.findall(html or "")}


# ---------------------------------------------------------------------------
# the checks
# ---------------------------------------------------------------------------


def check_report_html(html: str, deliverable_text: str) -> list[str]:
    """One ``WARN:`` line per broken rule; an empty list is a pass."""
    warnings: list[str] = []

    takeaways = len(TAKEAWAY_RE.findall(html))
    if not MIN_TAKEAWAYS <= takeaways <= MAX_TAKEAWAYS:
        warnings.append(
            f"WARN: {takeaways} takeaway cards found; the count must be 2 to 4"
        )

    open_sections = len(OPEN_SECTION_RE.findall(html))
    if open_sections != 1:
        warnings.append(
            f"WARN: {open_sections} sections are open; exactly one must be open"
        )

    for match in METHOD_ELEMENT_RE.finditer(html):
        if "open" in match.group(0):
            warnings.append("WARN: the Method section must render closed")

    front, _body = parse_front_matter(deliverable_text)
    cited_raw = front.get("sources_cited") if isinstance(front, dict) else None
    sources_cited = {
        str(slug).strip()
        for slug in (cited_raw if isinstance(cited_raw, list) else [])
        if str(slug).strip()
    }
    for slug in collect_citations(deliverable_text):
        if slug not in sources_cited:
            warnings.append(
                f"WARN: citation [S:{slug}] is not in the deliverable's sources_cited"
            )

    variables = parse_css_variables(html)
    for role in BACKGROUND_ROLES + COLOR_ROLES:
        if role not in variables:
            warnings.append(f"WARN: the stylesheet does not define --{role}")
    backgrounds = [variables[role] for role in BACKGROUND_ROLES if role in variables]
    for role in COLOR_ROLES:
        color = variables.get(role)
        if not color or not backgrounds:
            continue
        for background in backgrounds:
            ratio = contrast_ratio(color, background)
            if ratio < CONTRAST_MINIMUM:
                warnings.append(
                    f"WARN: --{role} {color} on {background} has contrast "
                    f"{ratio:.2f}:1, below the {CONTRAST_MINIMUM}:1 minimum"
                )
    return warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_check(html_value: str, deliverable_value: str) -> int:
    if not html_value or not deliverable_value:
        print("validate_report_html: check needs <html> and --deliverable=<md>", file=sys.stderr)
        return EXIT_USAGE
    html_path = Path(html_value).expanduser()
    deliverable_path = Path(deliverable_value).expanduser()
    for label, path in (("html", html_path), ("deliverable", deliverable_path)):
        if not path.is_file():
            print(f"validate_report_html: {label} not found: {path}", file=sys.stderr)
            return EXIT_WARN
    try:
        html = html_path.read_text(encoding="utf-8")
        deliverable = deliverable_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"validate_report_html: cannot read input: {exc}", file=sys.stderr)
        return EXIT_WARN
    warnings = check_report_html(html, deliverable)
    for warning in warnings:
        print(warning)
    if warnings:
        print(f"check FAILED ({len(warnings)} warning(s))")
        return EXIT_WARN
    print("check: all checks passed")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    if args[0] == "check":
        positional = [arg for arg in args[1:] if not arg.startswith("--")]
        flags: dict[str, str] = {}
        for arg in args[1:]:
            if arg.startswith("--") and "=" in arg:
                flag, value = arg.split("=", 1)
                flags[flag] = value
            elif arg.startswith("--"):
                print(f"validate_report_html: {arg} needs a value", file=sys.stderr)
                return EXIT_USAGE
        deliverable = flags.get("--deliverable") or ""
        if len(positional) != 1 or not deliverable:
            print(
                "validate_report_html: check needs exactly <html> and --deliverable=<md>",
                file=sys.stderr,
            )
            return EXIT_USAGE
        return cmd_check(positional[0], deliverable)
    print(f"validate_report_html: unknown subcommand {args[0]!r}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
