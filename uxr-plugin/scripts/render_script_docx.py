#!/usr/bin/env python3
"""Render an interview script Markdown file to the team-format .docx (issue 11).

Optional publish step of ``interview-script``: turn the saved
``interview-script-<KEY>.md`` into a styled ``.docx`` for the study folder
and Google Docs conversion. ``verify`` checks a rendered ``.docx`` against
the same format rules. Publish itself (upload, conversion, sharing) is the
skill's job; this script only converts and checks files on disk.

Subcommands:

- ``render <in.md> <out.docx>``  - convert Markdown to the styled docx.
- ``verify <in.docx>``           - check formatting of a rendered docx.

Exit codes: 0 ok; 1 verify mismatch; 2 usage error, unreadable input, or
``python-docx`` missing (the message includes the install hint); 3
internal assertion (an element the parser cannot place).

Format rules:

- Every paragraph: line spacing 1.15, zero space before and after.
- Headings H1/H2/H3 keep their heading styles.
- ``**Read Aloud:**`` followed by an italic block: one paragraph with a
  bold ``Read Aloud:`` label run and an italic body run (block lines are
  joined with single spaces).
- ``- Note: ...`` lines: bulleted list style, bold, italic, grey #666666.
- ``N. [criteria] Question?`` conditionals: the bracket part bold grey,
  the rest normal.
- ``*[Moderator: ...]*`` cues: italic.
- ``**[LABEL]. ** item`` survey items: bold ``[LABEL]. `` run, normal text.
- Probes (``   a. ...``): indented paragraph.

``verify`` checks only the element types the document actually contains:
a script with no notes, no read-aloud blocks, or no conditionals passes
those checks untouched, and the spacing rule still applies to every
paragraph.

Usage::

    python scripts/render_script_docx.py render <in.md> <out.docx>
    python scripts/render_script_docx.py verify <in.docx>
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

HAVE_DOCX: bool | None = None
DOCX_IMPORT_ERROR: Exception | None = None
Document = Pt = RGBColor = None  # bound by _load_docx()


def _load_docx() -> None:
    """Import python-docx on first use.

    The old module-level import made every usage and parse-error path
    pay the python-docx import debt even though those paths never
    render. HAVE_DOCX stays None until the first _load_docx() call.
    """
    global HAVE_DOCX, DOCX_IMPORT_ERROR
    if HAVE_DOCX is not None:
        return
    try:
        from docx import Document as _Document  # type: ignore[import-not-found]
        from docx.shared import Pt as _Pt, RGBColor as _RGBColor  # type: ignore[import-not-found]

        globals()["Document"] = _Document
        globals()["Pt"] = _Pt
        globals()["RGBColor"] = _RGBColor
        HAVE_DOCX = True
    except ImportError as exc:  # pragma: no cover - exercised on hosts without it
        HAVE_DOCX = False
        DOCX_IMPORT_ERROR = exc

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2

INSTALL_HINT = (
    "python-docx is not installed. Install it with: pip install python-docx"
)

LINE_SPACING = 1.15
GREY = "666666"

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
QUESTION_RE = re.compile(r"^(\d+)\.\s+(.*)$")
CONDITIONAL_RE = re.compile(r"^\[([^\]]*)\]\s*(.*)$")
PROBE_RE = re.compile(r"^ {3}([a-z])\. (.*)$")
NOTE_RE = re.compile(r"^-\s+Note:\s*(.*)$")
READ_ALOUD_RE = re.compile(r"^\*\*Read Aloud:\*\*\s*$")
MODERATOR_RE = re.compile(r"^\*\[(Moderator:.*)\]\*\s*$")
SURVEY_RE = re.compile(r"^\*\*\[([^\]]+)\]\.\s?\*\*\s*(.*)$")
ITALIC_RE = re.compile(r"^\*([^*].*)\*\s*$")


@dataclass
class Element:
    """One typed block from the script Markdown."""

    kind: str  # heading, read_aloud, note, conditional, question, probe,
    #            survey, moderator, plain
    text: str
    level: int = 0      # heading level
    criteria: str = ""  # conditional bracket text
    label: str = ""     # survey label
    letter: str = ""    # probe letter


def parse_script(text: str) -> list[Element]:
    """Classify script Markdown lines into typed elements."""
    elements: list[Element] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if READ_ALOUD_RE.match(line):
            body: list[str] = []
            probe = index + 1
            while probe < len(lines):
                italic = ITALIC_RE.match(lines[probe])
                if not italic:
                    break
                body.append(italic.group(1).strip())
                probe += 1
            elements.append(Element("read_aloud", " ".join(body)))
            index = probe
            continue
        heading = HEADING_RE.match(line)
        if heading:
            elements.append(
                Element("heading", heading.group(2).strip(), level=len(heading.group(1)))
            )
            index += 1
            continue
        note = NOTE_RE.match(line)
        if note:
            elements.append(Element("note", note.group(1).strip()))
            index += 1
            continue
        moderator = MODERATOR_RE.match(line)
        if moderator:
            elements.append(Element("moderator", moderator.group(1).strip()))
            index += 1
            continue
        survey = SURVEY_RE.match(line)
        if survey:
            elements.append(Element("survey", survey.group(2).strip(), label=survey.group(1).strip()))
            index += 1
            continue
        question = QUESTION_RE.match(line)
        if question:
            number = question.group(1)
            rest = question.group(2).strip()
            conditional = CONDITIONAL_RE.match(rest)
            if conditional:
                elements.append(
                    Element(
                        "conditional",
                        conditional.group(2).strip(),
                        criteria=conditional.group(1).strip(),
                        label=number,
                    )
                )
            else:
                elements.append(Element("question", rest, label=number))
            index += 1
            continue
        probe = PROBE_RE.match(line)
        if probe:
            elements.append(Element("probe", probe.group(2).strip(), letter=probe.group(1)))
            index += 1
            continue
        elements.append(Element("plain", stripped))
        index += 1
    return elements


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _paragraph(doc, **_kwargs):
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.line_spacing = LINE_SPACING
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    return paragraph


def render_document(elements: list[Element], doc):
    """Write parsed elements into a python-docx Document, in order."""
    for element in elements:
        if element.kind == "heading":
            paragraph = doc.add_heading(element.text, level=element.level)
            fmt = paragraph.paragraph_format
            fmt.line_spacing = LINE_SPACING
            fmt.space_before = Pt(0)
            fmt.space_after = Pt(0)
            continue
        paragraph = _paragraph(doc)
        if element.kind == "read_aloud":
            label_run = paragraph.add_run("Read Aloud: ")
            label_run.bold = True
            body_run = paragraph.add_run(element.text)
            body_run.italic = True
        elif element.kind == "note":
            paragraph.style = doc.styles["List Bullet"]
            run = paragraph.add_run(element.text)
            run.bold = True
            run.italic = True
            run.font.color.rgb = RGBColor.from_string(GREY)
        elif element.kind == "conditional":
            number_run = paragraph.add_run(f"{element.label}. ")
            number_run.bold = True
            bracket_run = paragraph.add_run(f"[{element.criteria}] ")
            bracket_run.bold = True
            bracket_run.font.color.rgb = RGBColor.from_string(GREY)
            paragraph.add_run(element.text)
        elif element.kind == "question":
            number_run = paragraph.add_run(f"{element.label}. ")
            number_run.bold = True
            paragraph.add_run(element.text)
        elif element.kind == "probe":
            paragraph.paragraph_format.left_indent = Pt(18)
            letter_run = paragraph.add_run(f"{element.letter}. ")
            letter_run.italic = True
            paragraph.add_run(element.text)
        elif element.kind == "survey":
            label_run = paragraph.add_run(f"[{element.label}]. ")
            label_run.bold = True
            paragraph.add_run(element.text)
        elif element.kind == "moderator":
            run = paragraph.add_run(element.text)
            run.italic = True
        else:  # plain
            paragraph.add_run(element.text)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def _classify_paragraph(paragraph) -> str:
    """Detect which element type a docx paragraph renders."""
    text = paragraph.text.strip()
    style_name = (paragraph.style.name or "") if paragraph.style is not None else ""
    if style_name.startswith("Heading"):
        return "heading"
    if text.startswith("Read Aloud:"):
        return "read_aloud"
    if style_name.startswith("List"):
        return "note"
    if re.match(r"^\d+\.\s*\[", text):
        return "conditional"
    if re.match(r"^\d+\.\s", text):
        return "question"
    if re.match(r"^[a-z]\.\s", text):
        return "probe"
    if re.match(r"^\[[^\]]+\]\.", text):
        return "survey"
    if text.startswith("Moderator:"):
        return "moderator"
    if text:
        return "plain"
    return "empty"


def _check_spacing(paragraph, mismatches: list[str], index: int) -> None:
    fmt = paragraph.paragraph_format
    spacing = fmt.line_spacing
    if spacing is not None and abs(float(spacing) - LINE_SPACING) > 0.001:
        mismatches.append(
            f"paragraph {index}: line spacing {spacing} is not {LINE_SPACING}"
        )
    for name, value in (("space before", fmt.space_before), ("space after", fmt.space_after)):
        if value is not None and abs(value.pt) > 0.001:
            mismatches.append(f"paragraph {index}: {name} {value.pt}pt is not 0pt")


def _check_read_aloud(paragraph, mismatches: list[str], index: int) -> None:
    runs = [run for run in paragraph.runs if run.text.strip()]
    label = next((run for run in runs if run.text.strip().startswith("Read Aloud:")), None)
    if label is None or not label.bold:
        mismatches.append(f"paragraph {index}: 'Read Aloud:' label is not bold")
    body = [run for run in runs if run is not label]
    if not body:
        mismatches.append(f"paragraph {index}: read-aloud body run is missing")
    elif not all(run.italic for run in body):
        mismatches.append(f"paragraph {index}: read-aloud body is not italic")


def _check_note(paragraph, mismatches: list[str], index: int) -> None:
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs:
        mismatches.append(f"paragraph {index}: note has no runs")
        return
    for run in runs:
        if not (run.bold and run.italic):
            mismatches.append(f"paragraph {index}: note run is not bold italic")
            break
        rgb = run.font.color.rgb if run.font.color and run.font.color.rgb else None
        if rgb is None or str(rgb) != GREY:
            mismatches.append(f"paragraph {index}: note run is not grey {GREY}")
            break


def _check_conditional(paragraph, mismatches: list[str], index: int) -> None:
    bracket = next(
        (run for run in paragraph.runs if "[" in run.text and "]" in run.text), None
    )
    if bracket is None:
        mismatches.append(f"paragraph {index}: conditional bracket run is missing")
        return
    if not bracket.bold:
        mismatches.append(f"paragraph {index}: conditional bracket is not bold")
    rgb = bracket.font.color.rgb if bracket.font.color and bracket.font.color.rgb else None
    if rgb is None or str(rgb) != GREY:
        mismatches.append(f"paragraph {index}: conditional bracket is not grey {GREY}")


def _check_survey(paragraph, mismatches: list[str], index: int) -> None:
    first = next((run for run in paragraph.runs if run.text.strip()), None)
    if first is None or not first.bold:
        mismatches.append(f"paragraph {index}: survey label run is not bold")


def _check_probe(paragraph, mismatches: list[str], index: int) -> None:
    indent = paragraph.paragraph_format.left_indent
    if indent is None or indent.pt <= 0:
        mismatches.append(f"paragraph {index}: probe is not indented")


def _check_moderator(paragraph, mismatches: list[str], index: int) -> None:
    if not any(run.italic for run in paragraph.runs if run.text.strip()):
        mismatches.append(f"paragraph {index}: moderator cue is not italic")


_ELEMENT_CHECKS = {
    "read_aloud": _check_read_aloud,
    "note": _check_note,
    "conditional": _check_conditional,
    "survey": _check_survey,
    "probe": _check_probe,
    "moderator": _check_moderator,
}


def verify_document(doc) -> tuple[bool, list[str]]:
    """Check a rendered docx; only element types present are checked."""
    mismatches: list[str] = []
    present: set[str] = set()
    for index, paragraph in enumerate(doc.paragraphs, start=1):
        kind = _classify_paragraph(paragraph)
        if kind == "empty":
            continue
        present.add(kind)
        _check_spacing(paragraph, mismatches, index)
        checker = _ELEMENT_CHECKS.get(kind)
        if checker is not None:
            checker(paragraph, mismatches, index)
    return (not mismatches), mismatches


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _require_docx() -> int:
    _load_docx()
    if HAVE_DOCX:
        return EXIT_OK
    print(INSTALL_HINT, file=sys.stderr)
    return EXIT_USAGE


def cmd_render(md_path: str, docx_path: str) -> int:
    code = _require_docx()
    if code != EXIT_OK:
        return code
    source = Path(md_path)
    if not source.is_file():
        print(f"render: input file not found: {md_path}", file=sys.stderr)
        return EXIT_USAGE
    target = Path(docx_path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    elements = parse_script(source.read_text(encoding="utf-8", errors="replace"))
    if not elements:
        print(f"render: no content parsed from {md_path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        doc = Document()
        render_document(elements, doc)
        doc.save(str(target))
    except Exception as exc:
        print(f"render: failed to write {docx_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"rendered {len(elements)} elements to {target}")
    return EXIT_OK


def cmd_verify(docx_path: str) -> int:
    code = _require_docx()
    if code != EXIT_OK:
        return code
    source = Path(docx_path)
    if not source.is_file():
        print(f"verify: file not found: {docx_path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        doc = Document(str(source))
    except Exception as exc:
        print(f"verify: cannot open {docx_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    ok, mismatches = verify_document(doc)
    print(f"verify {docx_path}")
    for mismatch in mismatches:
        print(f"  [mismatch] {mismatch}")
    if ok:
        print("result: exit 0 (format rules hold)")
        return EXIT_OK
    print(f"result: exit {EXIT_MISMATCH} ({len(mismatches)} mismatch(es))")
    return EXIT_MISMATCH


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

FIXTURE = """# Interview Script: Invoice Approval Self Service

Jira Ticket: PROJ-482
Prototype Link: https://example.test/proto/invoice-approval
UXR: Alex Rivera
PD and-or PM: Sam Chen and-or Dana Patel
**Time budget**: 60 min
**Method**: External Interviews
**Date drafted**: 2026-11-09
**Drafted from**: ticket PROJ-482

## Research Questions

1. How do teams approve invoices today?

## Moderator Notes

- Note: Record the session after consent.

## Script

### 1. Intro and Consent (4 min)

**Read Aloud:**
*Thanks for making time today.*

1. What does a typical workday look like for you?
   a. What changed for your team in the last year?
2. [if they mention exports] What were you trying to produce?

**[umux_lite_usability_7_point]. ** This system is easy to use.

*[Moderator: Keep the session on the time budget.]*
"""

MINIMAL_FIXTURE = """# Interview Script: Tiny

**Time budget**: 60 min

## Research Questions

1. How does the flow work?

## Script

### 1. Intro (4 min)

**Read Aloud:**
*Just one spoken line.*

1. What happens next?
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; full doc in this file
        return EXIT_USAGE
    command = args[0]
    if command == "render" and len(args) == 3:
        return cmd_render(args[1], args[2])
    if command == "verify" and len(args) == 2:
        return cmd_verify(args[1])
    print(__doc__.strip().splitlines()[0])  # terse usage pointer; full doc in this file
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
