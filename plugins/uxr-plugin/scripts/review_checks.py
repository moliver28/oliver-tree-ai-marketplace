#!/usr/bin/env python3
"""Deterministic hard-rule checker for interview scripts (issue 11).

The interview-script review loop saves nothing before this checker passes:
``check`` proves the hard rules the review loop depends on, so the exit
code, not reviewer judgment, gates the save.

Subcommands:

- ``check <path>``  - check one script file.
- ``selftest``      - exercise every check and the schema offline.

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
config is unavailable. The selftest pins its own values so it stays
deterministic on any host.

Usage::

    python scripts/review_checks.py check <path>
    python scripts/review_checks.py selftest
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
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


def _internal_validate_flag(flag: object) -> str | None:
    """Mirror of the schema's flag rules for hosts without jsonschema."""
    if not isinstance(flag, dict):
        return "flag is not an object"
    missing = [key for key in FLAG_REQUIRED if key not in flag]
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    unknown = [key for key in flag if key not in FLAG_REQUIRED]
    if unknown:
        return f"unknown keys: {', '.join(unknown)}"
    agent = flag["agent"]
    flag_type = flag["flag_type"]
    if agent not in ("expert-participant", "novice-participant"):
        return f"agent {agent!r} not a reader"
    if flag_type not in FLAG_TYPE_ENUM:
        return f"flag_type {flag_type!r} not in enum"
    if agent == "expert-participant" and flag_type not in EXPERT_TYPES:
        return f"expert-participant cannot emit {flag_type!r}"
    if agent == "novice-participant" and flag_type not in NOVICE_TYPES:
        return f"novice-participant cannot emit {flag_type!r}"
    if flag["severity"] not in SEVERITY_ENUM:
        return f"severity {flag['severity']!r} not in enum"
    if flag["confidence"] not in CONFIDENCE_ENUM:
        return f"confidence {flag['confidence']!r} not in enum"
    if flag["synthetic"] is not True:
        return "synthetic must be true"
    if not isinstance(flag["artifact_grounded"], bool):
        return "artifact_grounded must be a boolean"
    if flag_type == "flat-answer-risk" and flag["confidence"] != "hedged":
        return "flat-answer-risk requires confidence hedged"
    if flag["artifact_grounded"] and flag_type not in (
        "unexecutable-step",
        "artifact-mismatch",
    ):
        return "artifact_grounded true requires an artifact flag type"
    for key in (
        "flag_id",
        "section_anchor",
        "quoted_evidence",
        "why",
        "suggested_minimal_fix",
    ):
        if not isinstance(flag[key], str) or not flag[key]:
            return f"{key} must be a non-empty string"
    return None


def _internal_validate_edit(edit: object) -> str | None:
    """Mirror of the schema's edit rules for hosts without jsonschema."""
    if not isinstance(edit, dict):
        return "edit is not an object"
    missing = [key for key in EDIT_REQUIRED if key not in edit]
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    unknown = [key for key in edit if key not in EDIT_REQUIRED]
    if unknown:
        return f"unknown keys: {', '.join(unknown)}"
    ids = edit["resolves_flag_ids"]
    if not isinstance(ids, list) or len(ids) < 1:
        return "resolves_flag_ids must be a non-empty array"
    if len(set(ids)) != len(ids):
        return "resolves_flag_ids has duplicates"
    if any(not isinstance(i, str) or not i for i in ids):
        return "resolves_flag_ids entries must be non-empty strings"
    if edit["edit_kind"] not in EDIT_KIND_ENUM:
        return f"edit_kind {edit['edit_kind']!r} not in enum"
    if edit["hard_rule_preserved"] not in HARD_RULE_ENUM:
        return f"hard_rule_preserved {edit['hard_rule_preserved']!r} not in enum"
    for key in ("edit_id", "section_anchor"):
        if not isinstance(edit[key], str) or not edit[key]:
            return f"{key} must be a non-empty string"
    for key in ("before_text", "after_text"):
        if not isinstance(edit[key], str):
            return f"{key} must be a string"
    return None


def validate_review_json(instance: object) -> tuple[bool, str]:
    """Validate a reader flag array or writer edit log against the schema.

    Uses ``jsonschema`` with ``references/review-flags.schema.json`` when
    installed; otherwise a built-in mirror of the same rules. Returns
    ``(ok, error)``.
    """
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    schema_doc: dict = {}
    if SCHEMA_PATH.is_file():
        try:
            schema_doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schema_doc = {}
    if jsonschema is not None and schema_doc:
        validator_cls = jsonschema.validators.validator_for(schema_doc)
        validator_cls.check_schema(schema_doc)
        definitions = schema_doc.get("definitions", {})
        if isinstance(instance, list):
            if not instance:
                return True, ""  # an empty array is clean
            looks_flag = all(
                isinstance(item, dict) and "flag_id" in item for item in instance
            )
            # Validate the array against the referenced item definition so
            # errors name the real rule (ownership, hedged confidence) not
            # a generic anyOf mismatch.
            name = "flag_array" if looks_flag else "edit_array"
            subschema = {"$ref": f"#/definitions/{name}", "definitions": definitions}
            validator = validator_cls(subschema)
            errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
            if errors:
                return False, errors[0].message
            return True, ""
        errors = sorted(
            validator_cls(schema_doc).iter_errors(instance), key=lambda e: list(e.path)
        )
        if errors:
            return False, errors[0].message
        return True, ""
    # Built-in mirror (jsonschema missing or schema file unreadable).
    if isinstance(instance, list):
        if not instance:
            return True, ""
        looks_flag = all(
            isinstance(item, dict) and "flag_id" in item for item in instance
        )
        validator = _internal_validate_flag if looks_flag else _internal_validate_edit
        for index, item in enumerate(instance):
            error = validator(item)
            if error:
                return False, f"item {index}: {error}"
        return True, ""
    if isinstance(instance, dict):
        for key, kind in (("flags", _internal_validate_flag), ("edits", _internal_validate_edit)):
            if key in instance and isinstance(instance[key], list):
                for index, item in enumerate(instance[key]):
                    error = kind(item)
                    if error:
                        return False, f"{key}[{index}]: {error}"
        return True, ""
    return False, "instance is neither an array nor an object"


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


def _replace_once(haystack: str, old: str, new: str) -> str:
    assert old in haystack, f"fixture edit target not found: {old!r}"
    return haystack.replace(old, new, 1)


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        suffix = f" ({detail})" if detail and not condition else ""
        print(f"  [{'ok' if condition else 'FAIL'}] {name}{suffix}")
        if not condition:
            failures.append(name)

    cfg = dict(DEFAULT_CONFIG)
    quant = load_canonical_items()
    check("quant-measures.md canonical block parses", bool(quant), "no items found")

    def run(text: str) -> tuple[int, list[Finding]]:
        findings = check_text(text, cfg=cfg, quant_items=quant)
        return _exit_code(findings), findings

    def names(findings: list[Finding]) -> set[str]:
        return {finding.check for finding in findings}

    # 1. Canonical fixture is clean.
    code, findings = run(_fixture())
    check("canonical fixture exits 0", code == EXIT_CLEAN,
          "; ".join(f.render() for f in findings))

    # 2. A 21-word main question blocks.
    question_21 = " ".join(SALTED_QUESTION_21) + "?"
    text = _replace_once(
        _fixture(),
        "4. What else about the approval tools slows you down?",
        f"4. {question_21}",
    )
    code, findings = run(text)
    check("21-word main question exits 3", code == EXIT_BLOCK and "word-cap" in names(findings),
          f"exit {code}")

    # 3. An em dash blocks.
    text = _replace_once(
        _fixture(),
        "*Thanks for making time today.",
        "*Thanks for making time today \u2014 really.",
    )
    code, findings = run(text)
    check("em dash exits 3", code == EXIT_BLOCK and "em-en-dash" in names(findings),
          f"exit {code}")

    # 4. 53 minutes against a 60-minute budget blocks; 50 passes.
    over = _fixture(ci_minutes=22)  # 4 + 10 + 22 + 10 + 5 + 2 = 53
    assert "**Time budget**: 60 min" in over
    code, findings = run(over)
    check("53 minutes vs 60 budget exits 3", code == EXIT_BLOCK and "time-sum" in names(findings),
          f"exit {code}")
    check("53-minute fixture total is 53", "53 min; scripted cap is 52" in
          next((f.detail for f in findings if f.check == "time-sum"), ""),
          "unexpected detail")

    # 5. A yes/no opener warns.
    text = _replace_once(
        _fixture(),
        "4. What else about the approval tools slows you down?",
        "4. Did the approval tools slow you down?",
    )
    code, findings = run(text)
    check("yes/no opener exits 1", code == EXIT_WARN and "yes-no-question" in names(findings),
          f"exit {code}; " + "; ".join(f.render() for f in findings))

    # 6. Unparseable shapes exit 2.
    text = "\n".join(
        line for line in _fixture().splitlines() if not H3_RE.match(line)
    )
    code, findings = run(text)
    check("no ### sections exits 2", code == EXIT_UNPARSEABLE
          and any(f.severity == "structure" for f in findings), f"exit {code}")
    text = _replace_once(_fixture(), "**Time budget**: 60 min\n", "")
    code, findings = run(text)
    check("no time budget line exits 2", code == EXIT_UNPARSEABLE, f"exit {code}")
    text = "\n".join(
        line for line in _fixture().splitlines()
        if "Script Question Map" not in line
    )
    code, findings = run(text)
    check("no RQ map heading exits 2", code == EXIT_UNPARSEABLE, f"exit {code}")

    # 7. Schema: empty array, valid flag, asserted flat-answer-risk fails.
    ok, error = validate_review_json([])
    check("schema: empty flag array passes", ok, error)
    valid_flag = {
        "flag_id": "EXP-1",
        "agent": "expert-participant",
        "flag_type": "over-explanation",
        "severity": "medium",
        "section_anchor": "### 2. Context and Current State (10 min)",
        "quoted_evidence": "An invoice, as you may know, is a document.",
        "why": "The persona approves invoices weekly.",
        "suggested_minimal_fix": "Cut the definition.",
        "synthetic": True,
        "artifact_grounded": False,
        "confidence": "asserted",
    }
    ok, error = validate_review_json([valid_flag])
    check("schema: valid expert flag passes", ok, error)
    bad_flag = dict(valid_flag, flag_type="flat-answer-risk", confidence="asserted")
    ok, error = validate_review_json([bad_flag])
    check("schema: flat-answer-risk with asserted fails", not ok, "validated")
    hedged_flag = dict(valid_flag, flag_type="flat-answer-risk", confidence="hedged")
    ok, error = validate_review_json([hedged_flag])
    check("schema: flat-answer-risk with hedged passes", ok, error)
    cross_flag = dict(valid_flag, agent="novice-participant")
    ok, error = validate_review_json([cross_flag])
    check("schema: novice cannot emit expert flag type", not ok, "validated")
    grounded_flag = {
        "flag_id": "NOV-1",
        "agent": "novice-participant",
        "flag_type": "unexecutable-step",
        "severity": "high",
        "section_anchor": "### 4. Design Walkthrough (10 min)",
        "quoted_evidence": "4. Click 'Export to PDF'.",
        "why": "The manifest has no such control.",
        "suggested_minimal_fix": "Name a control the manifest confirms.",
        "synthetic": True,
        "artifact_grounded": True,
        "confidence": "asserted",
    }
    ok, error = validate_review_json([grounded_flag])
    check("schema: artifact-grounded novice flag passes", ok, error)
    grounded_bad = dict(grounded_flag, agent="expert-participant")
    ok, error = validate_review_json([grounded_bad])
    check("schema: expert cannot emit artifact-grounded flag", not ok, "validated")
    valid_edit = {
        "edit_id": "ED-1",
        "resolves_flag_ids": ["NOV-1"],
        "section_anchor": "### 4. Design Walkthrough (10 min)",
        "before_text": "4. Click 'Export to PDF'.",
        "after_text": "4. Open the export panel.",
        "edit_kind": "sentence-rewrite",
        "hard_rule_preserved": "structure-invariant",
    }
    ok, error = validate_review_json([valid_edit])
    check("schema: valid edit passes", ok, error)
    empty_edit = dict(valid_edit, resolves_flag_ids=[])
    ok, error = validate_review_json([empty_edit])
    check("schema: edit with empty resolves_flag_ids fails", not ok, "validated")
    ok, error = validate_review_json({"flags": [valid_flag], "edits": [valid_edit]})
    check("schema: envelope object passes", ok, error)

    # 8. Header order and heading levels.
    text = _replace_once(
        _fixture(),
        "Jira Ticket: PROJ-482\nPrototype Link: https://example.test/proto/invoice-approval\nUXR: Alex Rivera",
        "UXR: Alex Rivera\nJira Ticket: PROJ-482\nPrototype Link: https://example.test/proto/invoice-approval",
    )
    code, findings = run(text)
    check("header line out of order exits 3",
          code == EXIT_BLOCK and "header-order" in names(findings), f"exit {code}")
    text = "\n".join(
        line for line in _fixture().splitlines()
        if line.strip() != "## Moderator Notes" and "Record the session" not in line
        and "Keep the session" not in line
    )
    code, findings = run(text)
    check("missing Moderator Notes H2 exits 3",
          code == EXIT_BLOCK and "heading-levels" in names(findings), f"exit {code}")

    # 9. Numbering near-misses.
    text = _replace_once(_fixture(), "   a. Who saw it next?", "  a. Who saw it next?")
    code, findings = run(text)
    check("probe indent near-miss exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(), "   a. Where did it stall?", "   a. Where did it stall. Not a question"
    )
    text = _replace_once(
        text,
        "5. [if they mention exports] What were you trying to produce?",
        "5. [if they mention exports] Tell me what you were trying to produce",
    )
    code, findings = run(text)
    check("conditional without ? exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")
    text = _replace_once(_fixture(), "   b. Who unblocked it?", "   c. Who unblocked it?")
    code, findings = run(text)
    check("probe letter gap exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")

    # 10. Survey label with no item text blocks; wording drift warns.
    text = _replace_once(
        _fixture(),
        "**[umux_lite_usability_7_point]. ** This system is easy to use.",
        "**[umux_lite_usability_7_point]. **",
    )
    code, findings = run(text)
    check("survey label with no text exits 3",
          code == EXIT_BLOCK and "survey-label" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(),
        "**[umux_lite_usability_7_point]. ** This system is easy to use.",
        "**[umux_lite_usability_7_point]. ** This system is simple to use.",
    )
    code, findings = run(text)
    check("survey wording drift exits 1",
          code == EXIT_WARN and "survey-wording" in names(findings), f"exit {code}")

    # 11. Double negative warns; RQ coverage gap warns.
    text = _replace_once(
        _fixture(),
        "6. If you owned the approval flow, what would you change first?",
        "6. What did you not like, and what would you never use again?",
    )
    code, findings = run(text)
    check("double negative exits 1",
          code == EXIT_WARN and "double-negative" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(), "| RQ2 | Discover Problem | JTBD | 4, 5, 6 |",
        "| RQ2 | Discover Problem | JTBD | see above |",
    )
    code, findings = run(text)
    check("RQ row without script question exits 1",
          code == EXIT_WARN and "rq-coverage" in names(findings), f"exit {code}")

    # 12. Reading-level classification boundaries (no textstat needed).
    check("reading-level grade 9.5 is ok", _classify_grade(9.5, cfg) == "ok")
    check("reading-level grade 10.5 is warn", _classify_grade(10.5, cfg) == "warn")
    check("reading-level grade 12.5 is block", _classify_grade(12.5, cfg) == "block")

    # 13. CLI end to end.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "interview-script-PROJ-482.md"
        path.write_text(_fixture(), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check on canonical fixture exits 0", proc.returncode == EXIT_CLEAN,
              proc.stdout[-300:])
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check"],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check without a path exits 2", proc.returncode == EXIT_UNPARSEABLE,
              f"exit {proc.returncode}")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check", str(Path(tmp) / "nope.md")],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check on a missing file exits 2", proc.returncode == EXIT_UNPARSEABLE,
              f"exit {proc.returncode}")

    print(f"review_checks.py selftest")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip())
        return EXIT_UNPARSEABLE
    command = args[0]
    if command == "check" and len(args) == 2:
        return cmd_check(args[1])
    if command == "selftest" and len(args) == 1:
        return _selftest()
    print(__doc__.strip())
    return EXIT_UNPARSEABLE


if __name__ == "__main__":
    raise SystemExit(main())
