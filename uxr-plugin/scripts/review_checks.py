#!/usr/bin/env python3
"""Deterministic hard-rule checker for interview scripts (issue 11).

The interview-script review loop saves nothing before this checker passes:
``check`` proves the hard rules the review loop depends on, so the exit
code, not reviewer judgment, gates the save.

Subcommands:

- ``check <path>``  - check one script file.

Exit codes for ``check``: 0 clean, 1 warning (fix or accept explicitly),
2 unparseable (the file does not match the script template shape at all,
or the invocation or path is bad), 3 assertion failed (a hard rule is
broken; the loop sends the findings back to ``script-writer`` once, then
stops on a second 3).

Checks (block = exit 3, warn = exit 1):

- ``em-en-dash``      - any U+2014 or U+2013 anywhere. Block.
- ``word-cap``        - main question over the word cap (default 20;
  probes exempt). Block.
- ``time-sum``        - section minutes total over budget minus buffer
  (defaults 60 - 8 = 52). Block.
- ``header-order``    - H1 first, then ``<Tracker> Ticket:``, optional
  ``Prototype Link:``, ``UXR:``, ``PD and-or PM:``, and ``## Research
  Questions`` before the first ``###`` section. Block.
- ``heading-levels``  - one H1; ``Research Questions``, ``Moderator
  Notes``, ``Script``, and the RQ map are H2 in that order. Block.
- ``numbering``       - probe letters near-missed (indent, case, gaps, or
  duplicates; the shape is ``   a.``); a conditional line not ending in
  ``?``. Block.
- ``survey-label``    - ``**[LABEL]. **`` with no item text on the line.
  Block.
- ``reading-level``   - Flesch-Kincaid grade over grade_block (12) blocks;
  over grade_warn (10) warns; when ``textstat`` is not installed the
  check is advisory (skipped, exit unaffected).
- ``survey-wording``  - a labeled item that differs from the canonical
  items in ``references/quant-measures.md``. Warn.
- ``yes-no-question`` - main question starting with do, does, did, is,
  are, was, were, can, could, will, would, has, or have. Warn.
- ``rq-coverage``     - RQ map row with no digit in the Script Qs column.
  Warn.
- ``double-negative`` - two or more negations in one main question. Warn.

Main-question checks (word cap, yes/no, double negative, reading level)
apply to lines in the ``## Script`` region only; research question lists
and RQ map rows are not spoken questions. Unparseable means: no
``### N. Title (M min)`` section, no ``**Time budget**: N min`` line, or
no RQ map heading; those exit 2 before the other checks run (the em dash
check still reports, since it needs no structure).

Configuration: ``script.default_minutes``, ``script.time_buffer``,
``script.word_cap``, ``script.grade_warn``, ``script.grade_block`` read
through ``lib/config.py load_config()``; built-in defaults apply when the
config is unavailable. Tests pin their own values so they stay
deterministic on any host.

Usage::

    python scripts/review_checks.py check <path>
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

try:  # config is optional; built-in defaults keep the checker standalone
    from lib import config as _config  # noqa: E402
except Exception:  # pragma: no cover - only on a broken install
    _config = None  # type: ignore[assignment]

EXIT_CLEAN = 0
EXIT_WARN = 1
EXIT_UNPARSEABLE = 2
EXIT_BLOCK = 3

DEFAULT_CONFIG = {
    "default_minutes": 60,
    "time_buffer": 8,
    "word_cap": 20,
    "grade_warn": 10,
    "grade_block": 12,
}

QUANT_MEASURES_PATH = PLUGIN_ROOT / "references" / "quant-measures.md"

EM_DASH = "\u2014"
EN_DASH = "\u2013"

YES_NO_OPENERS = frozenset(
    "do does did is are was were can could will would has have".split()
)

NEGATION_WORDS = frozenset(
    "no not never none nothing nobody nowhere neither nor without cannot "
    "hardly barely".split()
)

H1_RE = re.compile(r"^#(?!#)\s+(.*)$")
H2_RE = re.compile(r"^##(?!#)\s+(.*)$")
H3_RE = re.compile(r"^###\s+(.*)$")
SECTION_RE = re.compile(r"^###\s+(\d+)\.\s+(.+?)\s+\((\d+)\s*min\)\s*$")
QUESTION_RE = re.compile(r"^(\d+)\.\s+(.*)$")
CONDITIONAL_RE = re.compile(r"^\[([^\]]*)\]\s*(.*)$")
PROBE_RE = re.compile(r"^ {3}([a-z])\. (.*)$")
PROBE_NEAR_MISS_RE = re.compile(r"^(?:[ \t]{0,2}[A-Za-z]\.| {3}[A-Z]\.| {4,}[A-Za-z]\.)")
NOTE_RE = re.compile(r"^-\s+Note:\s*(.*)$")
READ_ALOUD_RE = re.compile(r"^\*\*Read Aloud:\*\*\s*$")
MODERATOR_RE = re.compile(r"^\*\[Moderator:.*\]\*\s*$")
ITALIC_RE = re.compile(r"^\*([^*].*)\*\s*$")
SURVEY_RE = re.compile(r"^\*\*\[([^\]]+)\]\.\s?\*\*\s*(.*)$")
SURVEY_NEAR_MISS_RE = re.compile(r"^\*\*\[[^\]]+\]\.")
TIME_BUDGET_RE = re.compile(r"^\*\*Time budget\*\*:\s*(\d+)\s*min\.?\s*$", re.IGNORECASE)
TIME_BUDGET_PREFIX = "**Time budget**"
TICKET_RE = re.compile(r"^[A-Z][A-Za-z ]{0,30}(?:Ticket|Issue|Item|Task):\s*\S")
PROTOTYPE_RE = re.compile(r"^Prototype Link:\s*\S")
UXR_RE = re.compile(r"^UXR:\s*\S")
PDPM_RE = re.compile(r"^PD and-or PM:\s*\S")
BOLD_META_RE = re.compile(r"^\*\*[^*]+\*\*:\s*\S")
RQMAP_TEXT_RE = re.compile(r"research question.*script question map", re.IGNORECASE)

# Heading text -> normalized key for the required H2 chain.
REQUIRED_H2 = ("research questions", "moderator notes", "script")


@dataclass
class Finding:
    """One checker finding; severity block/warn/structure."""

    check: str
    severity: str  # "block" | "warn" | "structure"
    line: int | None
    detail: str

    def render(self) -> str:
        where = f" line {self.line}" if self.line else ""
        return f"[{self.severity}] {self.check}{where}: {self.detail}"


def _int(value: object, fallback: int) -> int:
    try:
        return int(str(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def load_script_config() -> dict:
    """Resolve the script.* config keys with built-in fallbacks."""
    merged = dict(DEFAULT_CONFIG)
    if _config is not None:
        try:
            section = _config.load_config().get("script") or {}
            if isinstance(section, dict):
                for key in DEFAULT_CONFIG:
                    if key in section:
                        merged[key] = _int(section[key], DEFAULT_CONFIG[key])
        except Exception:
            pass  # fail open to defaults; the checker never crashes on config
    return merged


# ---------------------------------------------------------------------------
# Quant measures (canonical item texts)
# ---------------------------------------------------------------------------


def _normalize_item(text: str) -> str:
    text = text.strip().strip("\"'“”‘’")
    text = re.sub(r"\s+", " ", text.lower())
    return text.rstrip(".").strip()


def load_canonical_items(path: Path = QUANT_MEASURES_PATH) -> dict[str, list[str]]:
    """Parse the fenced JSON block in quant-measures.md; {} when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    items: dict[str, list[str]] = {}
    for measure in data.get("measures", []):
        key = str(measure.get("key", "")).strip()
        if key:
            items[key] = [str(item) for item in measure.get("items", []) if item]
    return items


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Schema validation (flags and edit log)
# ---------------------------------------------------------------------------

FLAG_REQUIRED = (
    "flag_id",
    "agent",
    "flag_type",
    "severity",
    "section_anchor",
    "quoted_evidence",
    "why",
    "suggested_minimal_fix",
    "synthetic",
    "artifact_grounded",
    "confidence",
)
EXPERT_TYPES = frozenset(
    "over-explanation redundant-question jargon-mismatch flat-answer-risk".split()
)
NOVICE_TYPES = frozenset(
    "unfamiliar-term ambiguous-instruction unexecutable-step artifact-mismatch".split()
)
FLAG_TYPE_ENUM = EXPERT_TYPES | NOVICE_TYPES
SEVERITY_ENUM = frozenset("critical high medium low".split())
CONFIDENCE_ENUM = frozenset(("asserted", "hedged"))
EDIT_REQUIRED = (
    "edit_id",
    "resolves_flag_ids",
    "section_anchor",
    "before_text",
    "after_text",
    "edit_kind",
    "hard_rule_preserved",
)
EDIT_KIND_ENUM = frozenset(
    "word-swap phrase-swap sentence-rewrite question-replace probe-add".split()
)
HARD_RULE_ENUM = frozenset(
    "no-yes-no word-cap no-em-dash rq-coverage time-math structure-invariant".split()
)
SCHEMA_PATH = PLUGIN_ROOT / "references" / "review-flags.schema.json"


# ---------------------------------------------------------------------------
# Core text checks
# ---------------------------------------------------------------------------


def _strip_conditional(text: str) -> tuple[str | None, str]:
    """Split a question into (criteria, question text); criteria may be None."""
    match = CONDITIONAL_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, text.strip()


def _script_region(lines: list[str]) -> tuple[int, int]:
    """Line index range (start, end) of the ## Script section body."""
    start = end = -1
    for index, line in enumerate(lines):
        match = H2_RE.match(line)
        if not match:
            continue
        text = match.group(1).strip().lower()
        if text == "script" and start == -1:
            start = index + 1
        elif start != -1:
            end = index
            break
    if start == -1:
        return -1, -1
    if end == -1:
        end = len(lines)
    return start, end


def _reading_level_texts(lines: list[str]) -> list[str]:
    """Spoken text and question/probe lines inside the Script region."""
    start, end = _script_region(lines)
    texts: list[str] = []
    if start == -1:
        return texts
    in_read_aloud = False
    for line in lines[start:end]:
        stripped = line.strip()
        if READ_ALOUD_RE.match(line):
            in_read_aloud = True
            continue
        if in_read_aloud:
            if MODERATOR_RE.match(line):
                continue
            italic = ITALIC_RE.match(line)
            if italic:
                texts.append(italic.group(1).strip())
                continue
            in_read_aloud = False
        question = QUESTION_RE.match(line)
        if question:
            _, question_text = _strip_conditional(question.group(2))
            texts.append(question_text)
            continue
        probe = PROBE_RE.match(line)
        if probe:
            texts.append(probe.group(2).strip())
    return texts


def _classify_grade(grade: float, cfg: dict) -> str:
    """ok | warn | block for a Flesch-Kincaid grade value."""
    if grade > cfg["grade_block"]:
        return "block"
    if grade > cfg["grade_warn"]:
        return "warn"
    return "ok"


def check_text(
    text: str,
    cfg: dict | None = None,
    quant_items: dict[str, list[str]] | None = None,
) -> list[Finding]:
    """Run every hard-rule check on script text; returns findings."""
    cfg = cfg or load_script_config()
    quant_items = quant_items if quant_items is not None else load_canonical_items()
    lines = text.splitlines()
    findings: list[Finding] = []

    # Universal: em dash / en dash anywhere.
    for index, line in enumerate(lines, start=1):
        for name, dash in (("em dash", EM_DASH), ("en dash", EN_DASH)):
            if dash in line:
                findings.append(
                    Finding("em-en-dash", "block", index, f"{name} in: {line.strip()!r}")
                )

    # Structure detection.
    h1_lines = [(i, H1_RE.match(l).group(1).strip()) for i, l in enumerate(lines, 1) if H1_RE.match(l)]
    h2_hits: list[tuple[int, str]] = []
    for index, line in enumerate(lines, 1):
        match = H2_RE.match(line)
        if match:
            h2_hits.append((index, match.group(1).strip()))
    sections: list[tuple[int, int, str, int]] = []
    for index, line in enumerate(lines, 1):
        match = SECTION_RE.match(line)
        if match:
            sections.append((index, int(match.group(1)), match.group(2), int(match.group(3))))
    malformed_h3 = [
        (index, line.strip())
        for index, line in enumerate(lines, 1)
        if H3_RE.match(line) and not SECTION_RE.match(line)
    ]

    unparseable: list[str] = []
    if not sections:
        unparseable.append("no '### N. Title (M min)' sections")
    budget: int | None = None
    budget_line: int | None = None
    for index, line in enumerate(lines, 1):
        match = TIME_BUDGET_RE.match(line)
        if match:
            budget = int(match.group(1))
            budget_line = index
            break
    if budget is None:
        unparseable.append("no '**Time budget**: N min' line")
    rqmap_index = next(
        (index for index, hit in enumerate(h2_hits) if RQMAP_TEXT_RE.search(hit[1])),
        None,
    )
    if rqmap_index is None:
        unparseable.append("no '## Research Question -> Script Question Map' heading")

    if unparseable:
        for message in unparseable:
            findings.append(Finding("structure", "structure", None, message))
        return findings  # fix the template shape first; exit 2

    # heading-shape: any ### line that is not a valid section heading.
    for index, raw in malformed_h3:
        findings.append(
            Finding(
                "heading-shape",
                "block",
                index,
                f"not '### N. Title (M min)': {raw!r}",
            )
        )

    # time-sum: scripted minutes over budget minus buffer.
    total_minutes = sum(section[3] for section in sections)
    cap = budget - cfg["time_buffer"]
    if total_minutes > cap:
        findings.append(
            Finding(
                "time-sum",
                "block",
                sections[0][0],
                f"sections total {total_minutes} min; scripted cap is {cap} min "
                f"(budget {budget} minus buffer {cfg['time_buffer']})",
            )
        )

    # header-order: H1 first, header lines in order, RQs before section 1.
    first_content = next((i for i, l in enumerate(lines, 1) if l.strip()), None)
    if first_content is None or not h1_lines or h1_lines[0][0] != first_content:
        findings.append(
            Finding("header-order", "block", first_content, "first line is not the H1 title")
        )
    first_h2_line = h2_hits[0][0] if h2_hits else len(lines) + 1
    header_region = [
        (index, line)
        for index, line in enumerate(lines, 1)
        if h1_lines and h1_lines[0][0] < index < first_h2_line and line.strip()
    ]
    ticket_at = prototype_at = uxr_at = pdpm_at = None
    for index, line in enumerate(header_region):
        raw = line[1]
        if TICKET_RE.match(raw):
            ticket_at = index if ticket_at is None else ticket_at
            if ticket_at != index:
                findings.append(
                    Finding("header-order", "block", line[0], "more than one ticket header line")
                )
        elif PROTOTYPE_RE.match(raw):
            if prototype_at is None:
                prototype_at = index
        elif UXR_RE.match(raw):
            if uxr_at is None:
                uxr_at = index
        elif PDPM_RE.match(raw):
            if pdpm_at is None:
                pdpm_at = index
        elif not BOLD_META_RE.match(raw):
            findings.append(
                Finding(
                    "header-order",
                    "block",
                    line[0],
                    f"unexpected line before the first H2: {raw.strip()!r}",
                )
            )
    if ticket_at is None:
        findings.append(
            Finding("header-order", "block", h1_lines[0][0] if h1_lines else 1,
                    "missing '<Tracker> Ticket:' header line")
        )
    if uxr_at is None:
        findings.append(Finding("header-order", "block", None, "missing 'UXR:' header line"))
    if pdpm_at is None:
        findings.append(
            Finding("header-order", "block", None, "missing 'PD and-or PM:' header line")
        )
    order_pairs = [
        ("ticket", ticket_at, "prototype", prototype_at),
        ("prototype", prototype_at, "UXR", uxr_at),
        ("UXR", uxr_at, "PD and-or PM", pdpm_at),
    ]
    for first_name, first_at, second_name, second_at in order_pairs:
        if first_at is not None and second_at is not None and second_at < first_at:
            findings.append(
                Finding(
                    "header-order",
                    "block",
                    None,
                    f"{second_name} line appears before {first_name} line",
                )
            )
    if sections:
        first_section_line = sections[0][0]
        rq_heading_line = next(
            (index for index, hit in enumerate(h2_hits) if hit[1].strip().lower() == "research questions"),
            None,
        )
        if rq_heading_line is None or h2_hits[rq_heading_line][0] > first_section_line:
            findings.append(
                Finding(
                    "header-order",
                    "block",
                    first_section_line,
                    "'## Research Questions' does not precede the first section",
                )
            )

    # heading-levels: one H1; required headings are H2 in order.
    if len(h1_lines) != 1:
        findings.append(
            Finding("heading-levels", "block", h1_lines[0][0] if h1_lines else 1,
                    f"exactly one H1 required, found {len(h1_lines)}")
        )
    all_headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines, 1):
        for level, regex in ((1, H1_RE), (2, H2_RE), (3, H3_RE)):
            match = regex.match(line)
            if match:
                all_headings.append((level, index, match.group(1).strip().lower()))
                break
    positions: dict[str, int] = {}
    for name in REQUIRED_H2:
        hits = [(level, index) for level, index, text in all_headings if text == name]
        if not hits:
            findings.append(
                Finding("heading-levels", "block", None, f"missing required heading '{name}'")
            )
            continue
        off_level = next(((level, index) for level, index in hits if level != 2), None)
        if off_level is not None:
            findings.append(
                Finding(
                    "heading-levels",
                    "block",
                    off_level[1],
                    f"'{name}' must be an H2, found H{off_level[0]}",
                )
            )
        positions[name] = min(index for _, index in hits)
    # Order of the required H2s (first occurrences must increase).
    ordered = [positions[name] for name in REQUIRED_H2 if name in positions]
    if ordered != sorted(ordered):
        findings.append(
            Finding(
                "heading-levels",
                "block",
                None,
                "required H2 headings out of order: research questions, moderator notes, script",
            )
        )

    # Question checks inside the Script region.
    start, end = _script_region(lines)
    region = list(enumerate(lines[start:end], start=start + 1)) if start != -1 else []
    current_question: int | None = None
    probe_letters: dict[int, list[str]] = {}
    for index, line in region:
        question = QUESTION_RE.match(line)
        if question:
            number = int(question.group(1))
            criteria, question_text = _strip_conditional(question.group(2))
            if criteria is not None and not question_text.endswith("?"):
                findings.append(
                    Finding(
                        "numbering",
                        "block",
                        index,
                        f"conditional question must end in '?': {line.strip()!r}",
                    )
                )
            # word-cap
            words = question_text.split()
            if len(words) > cfg["word_cap"]:
                findings.append(
                    Finding(
                        "word-cap",
                        "block",
                        index,
                        f"main question is {len(words)} words (cap {cfg['word_cap']}): "
                        f"{question_text!r}",
                    )
                )
            # yes-no opener
            first_word = re.sub(r"^[\"'(*\[]+", "", words[0]).lower() if words else ""
            if first_word in YES_NO_OPENERS:
                findings.append(
                    Finding(
                        "yes-no-question",
                        "warn",
                        index,
                        f"starts with {first_word!r}: {question_text!r}",
                    )
                )
            # double negative
            tokens = re.findall(r"[a-z']+", question_text.lower())
            negations = sum(
                1 for token in tokens if token in NEGATION_WORDS or token.endswith("n't")
            )
            if negations >= 2:
                findings.append(
                    Finding(
                        "double-negative",
                        "warn",
                        index,
                        f"{negations} negations in one main question: {question_text!r}",
                    )
                )
            current_question = number
            continue
        if PROBE_NEAR_MISS_RE.match(line):
            findings.append(
                Finding(
                    "numbering",
                    "block",
                    index,
                    f"probe letter near-miss (use '   a.' with three spaces, lowercase): "
                    f"{line.strip()!r}",
                )
            )
            continue
        probe = PROBE_RE.match(line)
        if probe:
            if current_question is None:
                findings.append(
                    Finding("numbering", "block", index, f"probe with no preceding main question: {line.strip()!r}")
                )
            else:
                probe_letters.setdefault(current_question, []).append(probe.group(1))
            continue

    # Probe letter sequences per question: a, b, c with no gaps or dupes.
    for number, letters in probe_letters.items():
        expected = [chr(ord("a") + offset) for offset in range(len(letters))]
        if letters != expected:
            findings.append(
                Finding(
                    "numbering",
                    "block",
                    None,
                    f"probe letters for question {number} are {letters}, expected {expected}",
                )
            )

    # reading-level (advisory when textstat is missing).
    spoken = _reading_level_texts(lines)
    word_total = sum(len(text.split()) for text in spoken)
    if word_total < 30:
        grade: float | None = None
    else:
        try:
            import textstat  # type: ignore[import-not-found]

            grade = float(textstat.flesch_kincaid_grade(" ".join(spoken)))
        except ImportError:
            grade = None
        except Exception:
            grade = None
    if grade is None:
        findings.append(
            Finding("reading-level", "advisory", None,
                    "skipped (textstat not installed, or fewer than 30 words of spoken text)")
        )
    else:
        level = _classify_grade(grade, cfg)
        if level == "block":
            findings.append(
                Finding("reading-level", "block", budget_line,
                        f"Flesch-Kincaid grade {grade:.1f} over block level {cfg['grade_block']}")
            )
        elif level == "warn":
            findings.append(
                Finding("reading-level", "warn", budget_line,
                        f"Flesch-Kincaid grade {grade:.1f} over warn level {cfg['grade_warn']}")
            )

    # survey-label (block) and survey-wording (warn) across the whole file.
    canonical_normalized = {
        key: [_normalize_item(item) for item in items] for key, items in quant_items.items()
    }
    all_canonical = [item for items in canonical_normalized.values() for item in items]
    for index, line in enumerate(lines, 1):
        survey = SURVEY_RE.match(line)
        if survey:
            label = survey.group(1).strip()
            item_text = survey.group(2).strip()
            if not item_text:
                findings.append(
                    Finding("survey-label", "block", index, f"[{label}] has no item text on the line")
                )
                continue
            if not canonical_normalized:
                continue  # quant-measures.md unreadable; wording check advisory
            normalized = _normalize_item(item_text)
            key_normalized = _normalize_item(label)
            if key_normalized in canonical_normalized:
                if normalized not in canonical_normalized[key_normalized]:
                    findings.append(
                        Finding(
                            "survey-wording",
                            "warn",
                            index,
                            f"[{label}] item differs from quant-measures.md: {item_text!r}",
                        )
                    )
            else:
                tokens = _token_set(item_text)
                drifted = [
                    canonical
                    for canonical in all_canonical
                    if _jaccard(tokens, _token_set(canonical)) >= 0.5
                    and canonical != normalized
                ]
                if drifted:
                    findings.append(
                        Finding(
                            "survey-wording",
                            "warn",
                            index,
                            f"[{label}] item wording differs from quant-measures.md: {item_text!r}",
                        )
                    )
        elif SURVEY_NEAR_MISS_RE.match(line):
            findings.append(
                Finding(
                    "survey-label",
                    "block",
                    index,
                    f"survey label near-miss (use '**[LABEL]. ** item text'): {line.strip()!r}",
                )
            )

    # rq-coverage: RQ map rows need a digit in the Script Qs column.
    if rqmap_index is not None:
        map_start = h2_hits[rqmap_index][0]
        seen_table_row = False
        for index in range(map_start, len(lines)):
            line = lines[index]
            if H2_RE.match(line) and index != map_start:
                break
            if not line.lstrip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 4 or not cells[0] or set(cells[0]) <= set("-: "):
                continue  # separator or short row
            if not seen_table_row:
                seen_table_row = True  # first row is the column header
                continue
            if not any(char.isdigit() for char in cells[3]):
                findings.append(
                    Finding(
                        "rq-coverage",
                        "warn",
                        index + 1,
                        f"RQ map row has no script question: {line.strip()!r}",
                    )
                )

    return findings


def _exit_code(findings: list[Finding]) -> int:
    severities = {finding.severity for finding in findings}
    if "structure" in severities:
        return EXIT_UNPARSEABLE
    if "block" in severities:
        return EXIT_BLOCK
    if "warn" in severities:
        return EXIT_WARN
    return EXIT_CLEAN


def cmd_check(path: str) -> int:
    script_path = Path(path)
    if not script_path.is_file():
        print(f"review_checks.py check: file not found: {path}", file=sys.stderr)
        return EXIT_UNPARSEABLE
    text = script_path.read_text(encoding="utf-8", errors="replace")
    findings = check_text(text)
    print(f"review_checks.py check {path}")
    for finding in findings:
        print(f"  {finding.render()}")
    blocks = sum(1 for f in findings if f.severity == "block")
    warns = sum(1 for f in findings if f.severity == "warn")
    structures = sum(1 for f in findings if f.severity == "structure")
    code = _exit_code(findings)
    if code == EXIT_CLEAN:
        print("result: exit 0 (clean)")
    else:
        print(
            f"result: exit {code} "
            f"({structures} structure, {blocks} block, {warns} warn)"
        )
    return code


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

SALTED_QUESTION_21 = [
    "Describe", "the", "very", "last", "time", "you", "had", "to", "chase",
    "a", "missing", "approval", "from", "someone", "on", "another", "team",
    "before", "your", "release", "shipped",
]


def _fixture(ci_minutes: int = 19) -> str:
    """Canonical clean script; ci_minutes tunes the Critical Incident length."""
    assert len(SALTED_QUESTION_21) == 21
    return f"""# Interview Script: Invoice Approval Self Service

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
2. Where does an approval stall, and why?

## Moderator Notes

- Note: Record the session after consent.
- Note: Keep the session on the time budget.

## Script

### 1. Intro and Consent (4 min)

**Read Aloud:**
*Thanks for making time today. This is a research chat about how invoice approvals work. Nothing here is a test of you.*

1. What does a typical workday look like for you?
   a. What changed for your team in the last year?

### 2. Context and Current State (10 min)

**Read Aloud:**
*I would love to hear how approvals work for your team today.*

2. Walk me through the last invoice you approved.
   a. Who saw it next?
   b. What did you check first?

### 3. Critical Incident ({ci_minutes} min)

**Read Aloud:**
*Think of the last invoice that got stuck.*

3. Tell me about that invoice.
   a. Where did it stall?
   b. Who unblocked it?
   c. What would have prevented the stall?

### 4. Probe Themes (10 min)

**Read Aloud:**
*A few more questions about the tools in this flow.*

4. What else about the approval tools slows you down?
5. [if they mention exports] What were you trying to produce?

### 5. Strategic Close (5 min)

**Read Aloud:**
*Last topic, then I will let you go.*

6. If you owned the approval flow, what would you change first?

### 6. Wrap (2 min)

**Read Aloud:**
*That is everything I needed. Thank you for the time.*

## Research Question -> Script Question Map

| RQ | Phase | Technique | Script Qs | Stakeholder Value |
|---|---|---|---|---|
| RQ1 | Validate Problem | Critical Incident | 2, 3 | Shows the approval path today |
| RQ2 | Discover Problem | JTBD | 4, 5, 6 | Surfaces the stall causes |

## Quality Check

- Checker: review_checks.py check exit 0 on this draft.

## Quant Measures

**[umux_lite_usability_7_point]. ** This system is easy to use.

## Leadership Read

- Approval stalls are real and recurring.
- The self service flow targets the stall point.
- A one-team pilot is the next step.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip())
        return EXIT_UNPARSEABLE
    command = args[0]
    if command == "check" and len(args) == 2:
        return cmd_check(args[1])
    print(__doc__.strip())
    return EXIT_UNPARSEABLE


if __name__ == "__main__":
    raise SystemExit(main())
