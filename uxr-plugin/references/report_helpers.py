#!/usr/bin/env python3
"""Deterministic helpers for ``report`` (issue 03).

Every number the report command shows is computed here; the command prints
helper output verbatim and adds the narrative on top. All checks run
offline: no tracker, no chat, no calendar, no network.

Subcommands:

- ``scope-tier --type <research type> --investment <level>
  [--pod-names "<raw group string>"] [--pod-count <n>]``
  Prints ``lite``, ``standard``, or ``strategic`` -- the report tier from
  the matrix in ``report.tier_matrix`` (a built-in default is used when
  the config value is empty). Two or more groups raise the tier one step
  unless the investment is ``0`` (``report.multi_group_bump``). The tier
  never goes above ``strategic``.

- ``verdict [--json-file <file>] [--kind hypothesis|assumption]
  [--threshold <0..1>]``
  Reads ``{"<label>": {"Supports": n, "Challenges": n, "Mixed": n}}``
  (assumption labels: ``Holds`` / ``Breaks`` / ``Untested``) from the
  file or stdin and prints ``{"<label>": "<verdict>"}``. Rule (denominator
  is the count for that one label; ``report.verdict_threshold`` default
  0.60): hypothesis -- Supports share at or above the threshold is
  ``Supported``; Challenges share at or above is ``Not supported``; other
  evidence without a dominant side is ``Partially supported``; no
  evidence is ``Insufficient evidence``. Assumption -- same rule with
  ``Holds`` / ``Breaks`` / ``Untested``; evidence without a dominant side
  reads as ``Insufficient evidence`` (the assumption vocabulary has no
  middle verdict).

- ``channels --pod <group> --tier lite|standard|strategic``
  Prints the JSON list of chat channel names for the group from
  ``routing.group_to_channels``. A list value is used verbatim for any
  tier; a mapping value is tiered: ``standard`` uses its ``standard``
  list, ``strategic`` uses ``standard`` plus ``strategic`` (deduplicated,
  order kept), ``lite`` gives ``[]``. Unmapped group: ``[]``.

- ``report-filename --key <KEY> --audience <audience> --date <YYYY-MM-DD>``
  Prints ``report-<aud>-<date>-<key>.md``, lowercase.

- ``evidence-weight --workspace <dir> [--threshold]``
  Parses every ``interviews/*-summary.md`` alignment block (the frozen
  contract with debrief) and prints ``{rq_coverage, hypothesis_verdicts,
  assumption_verdicts, sessions_tallied, sessions_with_alignment_block}``.
  ``rq_coverage`` maps each ``RQ<n>`` seen in any block to the share of
  tallied sessions that surfaced direct evidence for it (the exact
  ``No direct evidence this session.`` line does not count). A ``WARN``
  line goes to stderr when fewer than half of the sessions carry an
  alignment block.

- ``word-count-sections --file <draft.md>``
  Prints ``{"<H2 title>": <words>}`` in document order. A section runs
  from its ``## `` heading to the next heading of any level. The command
  marks a section ``OVER`` at more than 20% above its tier limit.

- ``check-citations --draft-file <draft.md> --sources-dir <dir>``
  Collects every ``[S:<slug>]`` in the draft and prints
  ``[{"slug": ..., "found": ...}, ...]``, missing slugs first. A slug is
  known when some ``*.md`` under the sources dir carries it as its front
  matter ``slug`` (else as its filename stem).

- ``codebook-codes --file <analysis/codes.md>``
  Prints the codebook table as ``[{code, definition, anchor, sources}]``.

- ``classify-themes --codes-file <codes.md> --themes-file <themes.md>
  [--json]``
  Prints the bias-check table ``Theme | Origin | RQs supporting |
  Fragile?`` and the line ``Researcher-framed: N. Emergent: N.
  Single-RQ conclusions: <ids>.`` Origin rule: a theme is
  ``participant-emergent`` when every one of its codes exists in the
  codebook with a non-empty anchor example and at least one source;
  otherwise it is ``researcher-framed``. RQ support comes from the
  ``RQ<n>`` ids in the Synthesis-file cell (when the cell names a
  readable file, that file is scanned too). A theme is fragile when
  fewer than 2 RQs support it; the summary line lists the fragile
  themes' ``#`` ids. ``--json`` prints the machine-readable list instead.

- ``cross-study --current-file <report.md> --priors-glob <glob>``
  Compares the current report's front-matter hypotheses against prior
  reports' front matter and prints ``{confirms, reverses, new}`` (lists
  of current hypothesis labels). Matching key: the normalized label
  text; bare ``H<digit>`` ids never match across reports. Classes:
  Supported/Holds positive, Not supported/Breaks negative, the rest
  neutral. Same decisive class confirms, opposite reverses; a neutral
  verdict on either side is listed nowhere.

- ``altitude --level brief|standard|deep``
  Prints the tier the altitude maps to: brief to lite, standard to
  standard, deep to strategic.

- ``pod-to-area --pod <group>``
  Prints the product area from ``routing.group_to_area``, or
  ``UNMAPPED`` when the group has no entry.

- ``validate-finish-title --title "<title>" --pod <area>``
  Checks the finish rule: the title starts with the product area, ends
  with ``YYYY-MM``, and carries a non-empty middle (the
  ``ssot.finished_title_pattern`` shape ``<Product Area> <What it was>
  <YYYY-MM>``; a custom pattern is compiled from its placeholders).
  Prints ``ok`` or ``FAIL: <reason>``; exit 1 on failure.

- ``arr-parse --reply-file <file>``
  Extracts ``{account: "$1.2M"}`` pairs from a revenue-tool reply
  (``Account: $1.2M`` lines and pipe-table rows). The command writes the
  output to ``<state_dir>/arr-<KEY>.json``, which
  ``debrief_helpers.py render-appendix --arr-file`` reads -- the write
  step and the read step meet at that path.


Exit codes: 0 ok, 1 a check failed or input unreadable, 2 usage, 4
self-test failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import util  # noqa: E402  (shared plumbing)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

TIERS = ("lite", "standard", "strategic")
INVESTMENTS = ("0", "SM", "M", "LRG", "XLG", "XXLG")

#: The tier matrix from issue 03. ``config report.tier_matrix`` may
#: override it (shape ``{<research type>: {<investment>: <tier>}}``).
DEFAULT_TIER_MATRIX: dict[str, dict[str, str]] = {
    "strategic": {"0": "lite", "SM": "standard", "M": "standard",
                  "LRG": "strategic", "XLG": "strategic", "XXLG": "strategic"},
    "generative": {"0": "lite", "SM": "lite", "M": "standard",
                   "LRG": "standard", "XLG": "strategic", "XXLG": "strategic"},
    "evaluative": {"0": "lite", "SM": "lite", "M": "lite",
                   "LRG": "standard", "XLG": "strategic", "XXLG": "strategic"},
    "other": {"0": "lite", "SM": "lite", "M": "lite",
              "LRG": "lite", "XLG": "strategic", "XXLG": "strategic"},
}

DEFAULT_VERDICT_THRESHOLD = 0.60

#: Hypothesis stances (debrief alignment contract) and their evidence class.
HYPOTHESIS_STANCES = ("Supports", "Challenges", "Mixed")
ASSUMPTION_STANCES = ("Holds", "Breaks", "Untested")

ALTITUDE_MAP = {"brief": "lite", "standard": "standard", "deep": "strategic"}

#: Exact debrief wording for an unanswered research question.
NO_EVIDENCE_SENTENCE = "no direct evidence this session"

#: Verdict strength shown by the Method-section bars (percent widths).
#: Distinct by construction so bars never render one constant width.
VERDICT_STRENGTH = {
    "Supported": 90,
    "Not supported": 30,
    "Partially supported": 60,
    "Insufficient evidence": 12,
    "Holds": 90,
    "Breaks": 30,
    "Untested": 12,
}

FINISH_TITLE_PATTERN = "<Product Area> <What it was> <YYYY-MM>"

ALIGN_ENTER_TOKENS = ("insights", "research alignment")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
RQ_LINE_RE = re.compile(r"^-\s+(RQ\d+)\s*\(([^)]*)\)\s*:\s*(.*)$", re.IGNORECASE)
H_LINE_RE = re.compile(
    r"^-\s+(H\d+)\s*\(([^)]*)\)\s*:\s*(Supports|Challenges|Mixed)\b",
    re.IGNORECASE,
)
A_LINE_RE = re.compile(
    r"^-\s+(A\d+)\s*\(([^)]*)\)\s*:\s*(Holds|Breaks|Untested)\b",
    re.IGNORECASE,
)
CITE_RE = re.compile(r"\[S:([^\[\]\s]+)\]")
ARR_FIGURE_RE = re.compile(r"\$\s?\d(?:[\d,\.]*\d)?\s?[KMBkmb]?")
DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
MONTH_SUFFIX_RE = re.compile(r"(\d{4}-\d{2})\s*$")


# ---------------------------------------------------------------------------
# configuration (fail-soft: the one loader, None on any failure)
# ---------------------------------------------------------------------------


def load_plugin_config() -> dict | None:
    """Load the plugin config through lib.util.load_config; None when unavailable."""
    return util.load_config()


def _config_section(config: dict | None, name: str) -> dict:
    if not isinstance(config, dict):
        return {}
    value = config.get(name)
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# shared parsers
# ---------------------------------------------------------------------------


def _split_flow(inner: str) -> list[str]:
    """Split a YAML flow sequence body on commas outside quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    for char in inner:
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            buf.append(char)
            continue
        if char == ",":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(char)
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def _parse_scalar(raw: str):
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        return [_parse_scalar(part) for part in _split_flow(text[1:-1])]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_pair(text: str) -> tuple[str, str]:
    """Split ``key: value`` on the first colon outside quotes."""
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == ":":
            return text[:index].strip(), text[index + 1:].strip()
    return text.strip(), ""


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse the deliverable front matter (a YAML subset) from text.

    Supports ``key: scalar`` and ``key: [a, b]`` at the top level and one
    nesting level of ``key:`` list items with inline or indented pairs --
    exactly the shape of the report deliverable header:

        ---
        slug: report-leadership-2026-11-09-abc-237
        hypotheses:
          - id: H1
            label: "Import reduces confusion"
            verdict: Supported
        sources_cited: [onboarding-confusion, import-flow]
        ---

    Returns ``(data, body)``; data is empty when there is no front matter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    data: dict = {}
    current_key: str | None = None
    current_item: dict | None = None
    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if stripped.startswith("- "):
            if current_key is None:
                continue
            bucket = data.setdefault(current_key, [])
            if not isinstance(bucket, list):
                continue
            body = stripped[2:].strip()
            if _split_pair(body)[1] or (":" in body):
                key, value = _split_pair(body)
                current_item = {key: _parse_scalar(value)}
                bucket.append(current_item)
            else:
                bucket.append(_parse_scalar(body))
                current_item = None
            continue
        if stripped == "-":
            if current_key is not None:
                bucket = data.setdefault(current_key, [])
                if isinstance(bucket, list):
                    current_item = {}
                    bucket.append(current_item)
            continue
        if ":" not in stripped:
            continue
        key, value = _split_pair(stripped)
        if indent >= 2 and current_item is not None:
            current_item[key] = _parse_scalar(value)
            continue
        current_item = None
        if value:
            data[key] = _parse_scalar(value)
            current_key = key
        else:
            data[key] = []
            current_key = key
    return data, "\n".join(lines[end + 1:])


def parse_alignment_block(text: str) -> dict:
    """Parse one summary's ``## Insights -> Research Alignment`` block.

    Frozen contract with ``debrief`` (change both together, or not at
    all): enter at a line holding both "Insights" and "Research
    Alignment"; read ``- RQ1 (...)``, ``- H1 (label): stance``, and
    ``- A1 (label): stance`` lines; leave at the next ``## `` heading
    that does not carry "Insights" (or at end of text).

    Returns ``{found, rqs, hypotheses, assumptions}`` where each ``rqs``
    entry is ``{id, question, evidence, covered}`` and hypothesis and
    assumption entries are ``{id, label, stance}`` with canonical
    capitalized stances. Lines outside the contract shapes are ignored.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        lowered = line.lower()
        if ALIGN_ENTER_TOKENS[0] in lowered and ALIGN_ENTER_TOKENS[1] in lowered:
            start = index + 1
            break
    result = {"found": start is not None, "rqs": [], "hypotheses": [], "assumptions": []}
    if start is None:
        return result
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("## ") and "insights" not in stripped.lower():
            break
        match = RQ_LINE_RE.match(stripped)
        if match:
            rq_id, question, evidence = match.group(1), match.group(2).strip(), match.group(3).strip()
            covered = NO_EVIDENCE_SENTENCE not in evidence.lower().rstrip(". ")
            result["rqs"].append(
                {"id": rq_id, "question": question, "evidence": evidence, "covered": covered}
            )
            continue
        match = H_LINE_RE.match(stripped)
        if match:
            stance = match.group(3).capitalize()
            result["hypotheses"].append(
                {"id": match.group(1), "label": match.group(2).strip(), "stance": stance}
            )
            continue
        match = A_LINE_RE.match(stripped)
        if match:
            stance = match.group(3).capitalize()
            result["assumptions"].append(
                {"id": match.group(1), "label": match.group(2).strip(), "stance": stance}
            )
    return result


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------


def verdict_from_tallies(tallies: dict, kind: str, threshold: float) -> str:
    """One label's verdict from its stance counts (denominator = that label)."""
    counts: dict[str, int] = {}
    for key, value in (tallies or {}).items():
        canonical = str(key).strip().capitalize()
        counts[canonical] = counts.get(canonical, 0) + (int(value) if value else 0)
    total = sum(counts.values())
    if total <= 0:
        return "Insufficient evidence"
    if kind == "assumption":
        for stance, verdict in (
            ("Holds", "Holds"),
            ("Breaks", "Breaks"),
            ("Untested", "Untested"),
        ):
            if counts.get(stance, 0) / total >= threshold:
                return verdict
        return "Insufficient evidence"
    if counts.get("Supports", 0) / total >= threshold:
        return "Supported"
    if counts.get("Challenges", 0) / total >= threshold:
        return "Not supported"
    return "Partially supported"


def _stance_counts(entries: list[dict], stances: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """label -> {stance: count} over parsed alignment entries."""
    tally: dict[str, dict[str, int]] = {}
    for entry in entries:
        stance = entry.get("stance", "")
        if stance not in stances:
            continue
        label = entry.get("label") or entry.get("id", "")
        row = tally.setdefault(label, {})
        row[stance] = row.get(stance, 0) + 1
    return tally


def compute_verdict_maps(blocks: list[dict], threshold: float) -> tuple[dict, dict]:
    """Hypothesis and assumption verdict maps over parsed alignment blocks."""
    hyp_tally: dict[str, dict[str, int]] = {}
    asm_tally: dict[str, dict[str, int]] = {}
    for block in blocks:
        for label, row in _stance_counts(block.get("hypotheses", []), HYPOTHESIS_STANCES).items():
            merged = hyp_tally.setdefault(label, {})
            for stance, count in row.items():
                merged[stance] = merged.get(stance, 0) + count
        for label, row in _stance_counts(block.get("assumptions", []), ASSUMPTION_STANCES).items():
            merged = asm_tally.setdefault(label, {})
            for stance, count in row.items():
                merged[stance] = merged.get(stance, 0) + count
    hyp_verdicts = {
        label: verdict_from_tallies(counts, "hypothesis", threshold)
        for label, counts in hyp_tally.items()
    }
    asm_verdicts = {
        label: verdict_from_tallies(counts, "assumption", threshold)
        for label, counts in asm_tally.items()
    }
    return hyp_verdicts, asm_verdicts


# ---------------------------------------------------------------------------
# scope-tier
# ---------------------------------------------------------------------------


def normalize_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in ("strategic", "generative", "evaluative"):
        return text
    return "other"


def compute_scope_tier(
    research_type: str,
    investment: str,
    pod_names: str = "",
    pod_count: int | None = None,
    matrix: dict | None = None,
    multi_group_bump: bool = True,
) -> str:
    """Report tier from the matrix, bumped one step for 2+ groups."""
    table = matrix or DEFAULT_TIER_MATRIX
    normalized: dict[str, dict[str, str]] = {}
    for type_key, row in table.items():
        if isinstance(row, dict):
            normalized[str(type_key).strip().lower()] = {
                str(inv).strip().upper(): str(tier).strip().lower()
                for inv, tier in row.items()
            }
    investment_key = str(investment or "").strip().upper()
    if investment_key not in INVESTMENTS:
        raise ValueError(
            f"unknown investment {investment!r}; use one of {', '.join(INVESTMENTS)}"
        )
    type_key = normalize_type(research_type)
    base = normalized.get(type_key, DEFAULT_TIER_MATRIX[type_key]).get(
        investment_key, DEFAULT_TIER_MATRIX[type_key][investment_key]
    )
    if base not in TIERS:
        base = "lite"
    if pod_count is None:
        groups = len([part for part in re.split(r"[,;]", pod_names or "") if part.strip()])
    else:
        groups = pod_count
    if multi_group_bump and groups >= 2 and investment_key != "0":
        index = min(TIERS.index(base) + 1, len(TIERS) - 1)
        return TIERS[index]
    return base


# ---------------------------------------------------------------------------
# channels, filename, altitude, pod-to-area, finish title
# ---------------------------------------------------------------------------


def resolve_channels(mapping: dict, pod: str, tier: str) -> list[str]:
    """Chat channel names for one pod and tier from routing.group_to_channels."""
    value = None
    if isinstance(mapping, dict):
        if pod in mapping:
            value = mapping[pod]
        else:
            lowered = str(pod).strip().lower()
            for key, candidate in mapping.items():
                if str(key).strip().lower() == lowered:
                    value = candidate
                    break
    if value is None:
        return []
    if isinstance(value, list):
        return [str(name) for name in value if str(name).strip()]
    if isinstance(value, dict):
        standard = [str(name) for name in (value.get("standard") or []) if str(name).strip()]
        strategic = [str(name) for name in (value.get("strategic") or []) if str(name).strip()]
        tier_key = str(tier or "").strip().lower()
        if tier_key == "strategic":
            seen: set[str] = set()
            merged: list[str] = []
            for name in standard + strategic:
                if name not in seen:
                    seen.add(name)
                    merged.append(name)
            return merged
        if tier_key == "standard":
            return standard
        return []
    return []


def report_filename(key: str, audience: str, date_text: str) -> str:
    """``report-<aud>-<date>-<key>.md``, lowercase."""
    aud = re.sub(r"[^a-z0-9]+", "-", str(audience or "").strip().lower()).strip("-")
    key_slug = re.sub(r"[^a-z0-9-]+", "-", str(key or "").strip().lower()).strip("-")
    if not aud:
        raise ValueError("audience is required")
    if not key_slug:
        raise ValueError("key is required")
    if not DATE_RE.match(str(date_text or "").strip()):
        raise ValueError("date must look like YYYY-MM-DD")
    return f"report-{aud}-{date_text.strip()}-{key_slug}.md"


def map_altitude(level: str) -> str:
    tier = ALTITUDE_MAP.get(str(level or "").strip().lower())
    if tier is None:
        raise ValueError("altitude must be one of brief, standard, deep")
    return tier


def pod_to_area(mapping: dict, pod: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    if pod in mapping:
        return str(mapping[pod]) or None
    lowered = str(pod).strip().lower()
    for key, value in mapping.items():
        if str(key).strip().lower() == lowered:
            return str(value) or None
    return None


def validate_finish_title(title: str, pod: str, pattern: str = FINISH_TITLE_PATTERN) -> list[str]:
    """Finish-rule failures for a deliverable title; empty list means ok."""
    failures: list[str] = []
    title = str(title or "").strip()
    pod = str(pod or "").strip()
    pattern = str(pattern or "").strip() or FINISH_TITLE_PATTERN
    if not title:
        return ["title is empty"]
    if not pod:
        return ["pod (product area) is required"]
    month = MONTH_SUFFIX_RE.search(title)
    if not month:
        failures.append("title must end with a YYYY-MM month")
    if not title.lower().startswith(pod.lower()):
        failures.append(f"title must start with the product area {pod!r}")
    middle = title[len(pod):month.end() - len(month.group(1)) if month else len(title)]
    middle = title[len(pod):month.start()] if month else ""
    if not middle.strip(" -"):
        failures.append("title needs a non-empty middle part (what it was)")
    if pattern != FINISH_TITLE_PATTERN:
        regex = _pattern_to_regex(pattern, pod)
        if not re.fullmatch(regex, title, re.IGNORECASE):
            failures.append(f"title does not match the configured pattern {pattern!r}")
    return failures


def _pattern_to_regex(pattern: str, pod: str) -> str:
    """Compile a finish-title pattern; known placeholders are anchored."""
    pieces: list[str] = []
    index = 0
    for match in re.finditer(r"<([^<>]+)>", pattern):
        pieces.append(re.escape(pattern[index:match.start()]))
        token = match.group(1).strip().lower()
        if "product area" in token:
            pieces.append(re.escape(pod))
        elif token in ("yyyy-mm", "year-month"):
            pieces.append(r"\d{4}-\d{2}")
        elif token == "yyyy":
            pieces.append(r"\d{4}")
        else:
            pieces.append(r".+?")
        index = match.end()
    pieces.append(re.escape(pattern[index:]))
    return "".join(pieces)


# ---------------------------------------------------------------------------
# arr-parse
# ---------------------------------------------------------------------------

#: Cells and line labels that are never account names.
_NON_NAME_TOKENS = {"account", "accounts", "name", "customer", "customers",
                    "total", "arr", "annual recurring revenue"}


def _clean_name(raw: str) -> str:
    text = re.sub(r"\s*ARR\s*$", "", str(raw or "").strip(), flags=re.IGNORECASE)
    text = text.strip(" \t:;|\u2013\u2014-\"'")
    text = re.sub(r"\s+", " ", text)
    return text


def _is_name(token: str) -> bool:
    text = _clean_name(token)
    if not text or ARR_FIGURE_RE.search(text):
        return False
    return text.lower() not in _NON_NAME_TOKENS


def parse_arr_reply(text: str) -> dict[str, str]:
    """``{account: "$1.2M"}`` pairs from a revenue-tool reply.

    Recognized shapes per line: ``Account: $1.2M``, ``Account - $1.2M
    ARR``, ``Account | $1.2M``, and pipe-table rows (``| Account |
    $1.2M |``). First occurrence wins; junk lines are ignored.
    """
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
                continue  # separator row
            figure = ""
            figure_index = -1
            for index, cell in enumerate(cells):
                found = ARR_FIGURE_RE.search(cell)
                if found:
                    figure = found.group(0).replace(" ", "")
                    figure_index = index
                    break
            if figure_index < 0:
                continue
            name = ""
            for index in range(figure_index - 1, -1, -1):
                if _is_name(cells[index]):
                    name = _clean_name(cells[index])
                    break
            if name:
                result.setdefault(name, figure)
            continue
        separated = re.match(
            r"^(.{2,64}?)\s*(?:[:;\u2013\u2014\|]\s*|\s-\s+)(?:ARR\s*[:;\-]?\s*)?"
            r"(\$\s?\d(?:[\d,\.]*\d)?\s?[KMBkmb]?)\b",
            stripped,
        )
        if separated:
            name = _clean_name(separated.group(1))
            figure = separated.group(2).replace(" ", "")
            if _is_name(separated.group(1)):
                result.setdefault(name, figure)
            continue
        spaced = re.match(
            r"^([A-Za-z][\w .,&'/()-]{1,63}?)\s+"
            r"(\$\s?\d(?:[\d,\.]*\d)?\s?[KMBkmb]?)\s*(?:ARR)?\s*$",
            stripped,
        )
        if spaced and _is_name(spaced.group(1)):
            result.setdefault(_clean_name(spaced.group(1)), spaced.group(2).replace(" ", ""))
    return result


# ---------------------------------------------------------------------------
# evidence-weight
# ---------------------------------------------------------------------------


def evidence_weight(workspace: Path, threshold: float) -> dict:
    """Coverage and verdicts over one workspace's interview summaries."""
    summaries = sorted((workspace / "interviews").glob("*-summary.md"))
    blocks: list[dict] = []
    with_block = 0
    rq_seen: list[str] = []
    rq_covered: dict[str, int] = {}
    for path in summaries:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        block = parse_alignment_block(text)
        if block["found"]:
            with_block += 1
        blocks.append(block)
        for entry in block["rqs"]:
            rq_id = entry["id"]
            if rq_id not in rq_seen:
                rq_seen.append(rq_id)
            if entry["covered"]:
                rq_covered[rq_id] = rq_covered.get(rq_id, 0) + 1
    total_sessions = len(summaries)
    rq_coverage = {
        rq_id: (round(rq_covered.get(rq_id, 0) / total_sessions, 4) if total_sessions else 0.0)
        for rq_id in rq_seen
    }
    hypothesis_verdicts, assumption_verdicts = compute_verdict_maps(blocks, threshold)
    return {
        "rq_coverage": rq_coverage,
        "hypothesis_verdicts": hypothesis_verdicts,
        "assumption_verdicts": assumption_verdicts,
        "sessions_tallied": total_sessions,
        "sessions_with_alignment_block": with_block,
    }


# ---------------------------------------------------------------------------
# word-count-sections
# ---------------------------------------------------------------------------


def word_count_sections(text: str) -> dict[str, int]:
    """``{H2 title: words}`` in document order.

    A section runs from its ``## `` heading to the next ``## `` heading;
    deeper headings (``###`` and below) stay inside their parent section,
    so sub-headed content counts toward the H2 word limit. Heading and
    list-marker tokens never count as words.
    """
    counts: dict[str, int] = {}
    current: str | None = None
    words = 0
    for line in (text or "").splitlines():
        stripped = line.strip()
        match = HEADING_RE.match(stripped)
        if match:
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= 2:
                if current is not None:
                    counts[current] = words
                current = match.group(1).strip() if level == 2 else None
                words = 0
            continue
        if current is not None:
            body = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", stripped)
            words += len(body.split())
    if current is not None:
        counts[current] = words
    return counts


# ---------------------------------------------------------------------------
# check-citations
# ---------------------------------------------------------------------------


def collect_citations(text: str) -> list[str]:
    """Every ``[S:<slug>]`` slug in text, first occurrence order."""
    seen: list[str] = []
    for match in CITE_RE.finditer(text or ""):
        slug = match.group(1)
        if slug not in seen:
            seen.append(slug)
    return seen


def known_source_slugs(sources_dir: Path) -> set[str]:
    """Slugs of the source notes under a workspace sources dir.

    A note's slug is its front-matter ``slug`` value when present, else
    its filename stem. ``README.md`` files never count.
    """
    slugs: set[str] = set()
    if not sources_dir.is_dir():
        return slugs
    for path in sorted(sources_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        front, _ = parse_front_matter(text)
        slug = front.get("slug") if isinstance(front, dict) else None
        slugs.add(str(slug).strip() if slug else path.stem)
    return slugs


def check_citations(draft_text: str, sources_dir: Path) -> list[dict]:
    """``[{slug, found}]`` for the draft's citations, missing slugs first."""
    known = known_source_slugs(sources_dir)
    slugs = collect_citations(draft_text)
    return [
        {"slug": slug, "found": slug in known}
        for slug in sorted(slugs, key=lambda item: (item in known, item))
    ]


# ---------------------------------------------------------------------------
# codebook-codes, classify-themes
# ---------------------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell) and any(cells)


def read_markdown_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """First markdown table in a file as (headers, row dicts)."""
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            if rows:
                break
            continue
        cells = _split_row(line)
        if _is_separator(cells):
            continue
        if not headers:
            headers = cells
            continue
        row = {header: cells[i] if i < len(cells) else "" for i, header in enumerate(headers)}
        if any(cell for cell in row.values()):
            rows.append(row)
    return headers, rows


def codebook_codes(codes_file: Path) -> list[dict]:
    """The codebook table as ``[{code, definition, anchor, sources}]``."""
    _headers, rows = read_markdown_table(codes_file)
    result: list[dict] = []
    for row in rows:
        code = row.get("Code", "")
        if not code:
            continue
        sources = [part.strip() for part in re.split(r"[,;]", row.get("Sources", "")) if part.strip()]
        result.append({
            "code": code,
            "definition": row.get("Definition", ""),
            "anchor": row.get("Anchor example", ""),
            "sources": sources,
        })
    return result


def _rq_ids_in(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\bRQ\d+\b", text or ""):
        if match.group(0) not in found:
            found.append(match.group(0))
    return found


def _synthesis_candidates(cell: str, themes_file: Path) -> list[Path]:
    name = cell.strip()
    if not name or not (name.endswith(".md") or "/" in name or "\\" in name):
        return []
    bases = [Path.cwd(), themes_file.parent, themes_file.parent.parent]
    return [base / name for base in bases]


def classify_themes(codes_file: Path, themes_file: Path) -> list[dict]:
    """Bias-check rows: ``{id, theme, origin, rqs, fragile}`` per theme.

    Origin rule: ``participant-emergent`` when every code of the theme
    exists in the codebook with a non-empty anchor example and at least
    one source; otherwise ``researcher-framed``. Fragile when fewer than
    2 RQs support the theme.
    """
    codes = {entry["code"].strip().lower(): entry for entry in codebook_codes(codes_file)}
    _headers, rows = read_markdown_table(themes_file)
    result: list[dict] = []
    for row in rows:
        theme = row.get("Theme", "")
        if not theme:
            continue
        theme_id = (row.get("#", "") or str(len(result) + 1)).strip()
        code_names = [part.strip() for part in re.split(r"[,;]", row.get("Codes", "")) if part.strip()]
        grounded = bool(code_names)
        for name in code_names:
            entry = codes.get(name.lower())
            if entry is None or not entry["anchor"] or not entry["sources"]:
                grounded = False
                break
        rqs = _rq_ids_in(row.get("Synthesis file", ""))
        if not rqs:
            for candidate in _synthesis_candidates(row.get("Synthesis file", ""), themes_file):
                if candidate.is_file():
                    try:
                        rqs = _rq_ids_in(candidate.read_text(encoding="utf-8"))
                    except OSError:
                        rqs = []
                    if rqs:
                        break
        result.append({
            "id": theme_id,
            "theme": theme,
            "origin": "participant-emergent" if grounded else "researcher-framed",
            "rqs": rqs,
            "fragile": len(rqs) < 2,
        })
    return result


def format_bias_check(rows: list[dict]) -> str:
    """The bias-check table plus the exact summary line."""
    lines = [
        "| Theme | Origin | RQs supporting | Fragile? |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['theme']} | {row['origin']} | {', '.join(row['rqs']) or '-'} "
            f"| {'yes' if row['fragile'] else 'no'} |"
        )
    framed = sum(1 for row in rows if row["origin"] == "researcher-framed")
    emergent = sum(1 for row in rows if row["origin"] == "participant-emergent")
    fragile_ids = [row["id"] for row in rows if row["fragile"]]
    ids = ", ".join(fragile_ids) if fragile_ids else "none"
    lines.append(f"Researcher-framed: {framed}. Emergent: {emergent}. Single-RQ conclusions: {ids}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# cross-study
# ---------------------------------------------------------------------------

_POSITIVE_VERDICTS = {"supported", "holds"}
_NEGATIVE_VERDICTS = {"not supported", "breaks"}


def _normalize_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _verdict_class(verdict: str) -> str:
    lowered = str(verdict or "").strip().lower()
    if lowered in _POSITIVE_VERDICTS:
        return "positive"
    if lowered in _NEGATIVE_VERDICTS:
        return "negative"
    return "neutral"


def cross_study(current_text: str, prior_texts: list[str]) -> dict[str, list[str]]:
    """``{confirms, reverses, new}`` for the current report's hypotheses.

    Matching key: normalized label text. Bare ``H<digit>`` ids never
    match across reports. Decisive classes confirm or reverse; when
    either side is neutral the label is listed under none of the keys.
    """
    current_front, _ = parse_front_matter(current_text)
    hypotheses = current_front.get("hypotheses") if isinstance(current_front, dict) else None
    current = []
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict) and item.get("label"):
                current.append((str(item["label"]), str(item.get("verdict", ""))))
    prior: dict[str, str] = {}
    for text in prior_texts:
        front, _ = parse_front_matter(text)
        entries = front.get("hypotheses") if isinstance(front, dict) else None
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict) and item.get("label"):
                prior[_normalize_label(item["label"])] = str(item.get("verdict", ""))
    confirms: list[str] = []
    reverses: list[str] = []
    new: list[str] = []
    for label, verdict in current:
        key = _normalize_label(label)
        prior_verdict = prior.get(key)
        if prior_verdict is None:
            new.append(label)
            continue
        current_class = _verdict_class(verdict)
        prior_class = _verdict_class(prior_verdict)
        if current_class == "neutral" or prior_class == "neutral":
            continue
        if current_class == prior_class:
            confirms.append(label)
        else:
            reverses.append(label)
    return {"confirms": confirms, "reverses": reverses, "new": new}


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------


def _load_json_arg(value: str):
    if value:
        return util.read_json_document(value)
    return json.loads(sys.stdin.read())


def cmd_scope_tier(args: dict[str, str]) -> int:
    research_type = args.get("--type") or ""
    investment = args.get("--investment") or ""
    if not research_type or not investment:
        print("report_helpers: scope-tier needs --type and --investment", file=sys.stderr)
        return EXIT_USAGE
    pod_count = None
    if args.get("--pod-count"):
        try:
            pod_count = int(args["--pod-count"])
        except ValueError:
            print("report_helpers: --pod-count needs an integer", file=sys.stderr)
            return EXIT_USAGE
    config = load_plugin_config()
    report_config = _config_section(config, "report")
    matrix = report_config.get("tier_matrix") or None
    bump = report_config.get("multi_group_bump", True)
    try:
        tier = compute_scope_tier(
            research_type, investment,
            pod_names=args.get("--pod-names") or "",
            pod_count=pod_count,
            matrix=matrix if isinstance(matrix, dict) and matrix else None,
            multi_group_bump=bool(bump),
        )
    except ValueError as exc:
        print(f"report_helpers: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(tier)
    return EXIT_OK


def cmd_verdict(args: dict[str, str]) -> int:
    kind = (args.get("--kind") or "hypothesis").strip().lower()
    if kind not in ("hypothesis", "assumption"):
        print("report_helpers: --kind must be hypothesis or assumption", file=sys.stderr)
        return EXIT_USAGE
    threshold = DEFAULT_VERDICT_THRESHOLD
    if args.get("--threshold"):
        try:
            threshold = float(args["--threshold"])
        except ValueError:
            print("report_helpers: --threshold needs a number", file=sys.stderr)
            return EXIT_USAGE
    try:
        data = _load_json_arg(args.get("--json-file") or "")
    except (OSError, ValueError) as exc:
        print(f"report_helpers: cannot read verdict input: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not isinstance(data, dict):
        print("report_helpers: verdict input must be a JSON object", file=sys.stderr)
        return EXIT_FAIL
    result = {
        str(label): verdict_from_tallies(counts if isinstance(counts, dict) else {}, kind, threshold)
        for label, counts in data.items()
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_channels(args: dict[str, str]) -> int:
    pod = args.get("--pod") or ""
    tier = (args.get("--tier") or "standard").strip().lower()
    if not pod:
        print("report_helpers: channels needs --pod", file=sys.stderr)
        return EXIT_USAGE
    if tier not in TIERS:
        print("report_helpers: --tier must be lite, standard, or strategic", file=sys.stderr)
        return EXIT_USAGE
    routing = _config_section(load_plugin_config(), "routing")
    mapping = routing.get("group_to_channels") if isinstance(routing, dict) else None
    print(json.dumps(resolve_channels(mapping if isinstance(mapping, dict) else {}, pod, tier)))
    return EXIT_OK


def cmd_report_filename(args: dict[str, str]) -> int:
    key = args.get("--key") or ""
    audience = args.get("--audience") or ""
    date_text = args.get("--date") or ""
    if not key or not audience or not date_text:
        print(
            "report_helpers: report-filename needs --key, --audience, and --date",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        print(report_filename(key, audience, date_text))
    except ValueError as exc:
        print(f"report_helpers: {exc}", file=sys.stderr)
        return EXIT_USAGE
    draft_value = args.get("--check-citations") or ""
    if draft_value:
        sources_value = args.get("--sources-dir") or ""
        if not sources_value:
            print("report_helpers: --check-citations needs --sources-dir", file=sys.stderr)
            return EXIT_USAGE
        try:
            text = Path(draft_value).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            print(f"report_helpers: cannot read draft: {exc}", file=sys.stderr)
            return EXIT_FAIL
        sources_dir = Path(sources_value).expanduser()
        if not sources_dir.is_dir():
            print(f"report_helpers: sources dir not found: {sources_dir}", file=sys.stderr)
            return EXIT_FAIL
        print(json.dumps(check_citations(text, sources_dir), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_evidence_weight(args: dict[str, str]) -> int:
    workspace_value = args.get("--workspace") or ""
    if not workspace_value:
        print("report_helpers: evidence-weight needs --workspace <dir>", file=sys.stderr)
        return EXIT_USAGE
    workspace = Path(workspace_value).expanduser()
    interviews = workspace / "interviews"
    if not interviews.is_dir():
        print(f"report_helpers: no interviews/ directory under {workspace}", file=sys.stderr)
        return EXIT_FAIL
    threshold = DEFAULT_VERDICT_THRESHOLD
    if args.get("--threshold"):
        try:
            threshold = float(args["--threshold"])
        except ValueError:
            print("report_helpers: --threshold needs a number", file=sys.stderr)
            return EXIT_USAGE
    result = evidence_weight(workspace, threshold)
    if result["sessions_tallied"] and (
        result["sessions_with_alignment_block"] * 2 < result["sessions_tallied"]
    ):
        print(
            f"WARN fewer than half of the sessions have an alignment block "
            f"({result['sessions_with_alignment_block']} of {result['sessions_tallied']}); "
            f"run debrief on the missing sessions",
            file=sys.stderr,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_word_count_sections(args: dict[str, str]) -> int:
    file_value = args.get("--file") or ""
    if not file_value:
        print("report_helpers: word-count-sections needs --file", file=sys.stderr)
        return EXIT_USAGE
    try:
        text = Path(file_value).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        print(f"report_helpers: cannot read draft: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(word_count_sections(text), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_check_citations(args: dict[str, str]) -> int:
    draft_value = args.get("--draft-file") or ""
    sources_value = args.get("--sources-dir") or ""
    if not draft_value or not sources_value:
        print(
            "report_helpers: check-citations needs --draft-file and --sources-dir",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        text = Path(draft_value).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        print(f"report_helpers: cannot read draft: {exc}", file=sys.stderr)
        return EXIT_FAIL
    sources_dir = Path(sources_value).expanduser()
    if not sources_dir.is_dir():
        print(f"report_helpers: sources dir not found: {sources_dir}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(check_citations(text, sources_dir), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_codebook_codes(args: dict[str, str]) -> int:
    file_value = args.get("--file") or ""
    if not file_value:
        print("report_helpers: codebook-codes needs --file", file=sys.stderr)
        return EXIT_USAGE
    codes_file = Path(file_value).expanduser()
    if not codes_file.is_file():
        print(f"report_helpers: codes file not found: {codes_file}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(codebook_codes(codes_file), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_classify_themes(args: dict[str, str]) -> int:
    codes_value = args.get("--codes-file") or ""
    themes_value = args.get("--themes-file") or ""
    if not codes_value or not themes_value:
        print(
            "report_helpers: classify-themes needs --codes-file and --themes-file",
            file=sys.stderr,
        )
        return EXIT_USAGE
    codes_file = Path(codes_value).expanduser()
    themes_file = Path(themes_value).expanduser()
    for path in (codes_file, themes_file):
        if not path.is_file():
            print(f"report_helpers: file not found: {path}", file=sys.stderr)
            return EXIT_FAIL
    rows = classify_themes(codes_file, themes_file)
    if args.get("--json"):
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(format_bias_check(rows))
    return EXIT_OK


def cmd_cross_study(args: dict[str, str]) -> int:
    current_value = args.get("--current-file") or ""
    priors_value = args.get("--priors-glob") or ""
    if not current_value or not priors_value:
        print(
            "report_helpers: cross-study needs --current-file and --priors-glob",
            file=sys.stderr,
        )
        return EXIT_USAGE
    current_path = Path(current_value).expanduser()
    if not current_path.is_file():
        print(f"report_helpers: current file not found: {current_path}", file=sys.stderr)
        return EXIT_FAIL
    try:
        current_text = current_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"report_helpers: cannot read current file: {exc}", file=sys.stderr)
        return EXIT_FAIL
    prior_texts: list[str] = []
    for path in sorted(Path().glob(priors_value)):
        if path.is_file() and path != current_path:
            try:
                prior_texts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
    print(json.dumps(cross_study(current_text, prior_texts), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_altitude(args: dict[str, str]) -> int:
    level = args.get("--level") or ""
    if not level:
        print("report_helpers: altitude needs --level", file=sys.stderr)
        return EXIT_USAGE
    try:
        print(map_altitude(level))
    except ValueError as exc:
        print(f"report_helpers: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def cmd_pod_to_area(args: dict[str, str]) -> int:
    pod = args.get("--pod") or ""
    if not pod:
        print("report_helpers: pod-to-area needs --pod", file=sys.stderr)
        return EXIT_USAGE
    routing = _config_section(load_plugin_config(), "routing")
    mapping = routing.get("group_to_area") if isinstance(routing, dict) else None
    area = pod_to_area(mapping if isinstance(mapping, dict) else {}, pod)
    print(area if area else "UNMAPPED")
    return EXIT_OK


def cmd_validate_finish_title(args: dict[str, str]) -> int:
    title = args.get("--title") or ""
    pod = args.get("--pod") or ""
    if not title or not pod:
        print(
            "report_helpers: validate-finish-title needs --title and --pod",
            file=sys.stderr,
        )
        return EXIT_USAGE
    ssot = _config_section(load_plugin_config(), "ssot")
    pattern = ssot.get("finished_title_pattern") if isinstance(ssot, dict) else None
    failures = validate_finish_title(
        title, pod, str(pattern) if pattern else FINISH_TITLE_PATTERN
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return EXIT_FAIL
    print("ok")
    return EXIT_OK


def cmd_arr_parse(args: dict[str, str]) -> int:
    file_value = args.get("--reply-file") or ""
    if not file_value:
        print("report_helpers: arr-parse needs --reply-file", file=sys.stderr)
        return EXIT_USAGE
    reply_path = Path(file_value).expanduser()
    if not reply_path.is_file():
        print(f"report_helpers: reply file not found: {reply_path}", file=sys.stderr)
        return EXIT_FAIL
    try:
        text = reply_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"report_helpers: cannot read reply: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(parse_arr_reply(text), indent=2, ensure_ascii=False))
    return EXIT_OK


SUBCOMMANDS = (
    "scope-tier", "verdict", "channels", "report-filename", "evidence-weight",
    "word-count-sections", "check-citations", "codebook-codes", "classify-themes",
    "cross-study", "altitude", "pod-to-area", "validate-finish-title", "arr-parse",
)

HANDLERS = {
    "scope-tier": cmd_scope_tier,
    "verdict": cmd_verdict,
    "channels": cmd_channels,
    "report-filename": cmd_report_filename,
    "evidence-weight": cmd_evidence_weight,
    "word-count-sections": cmd_word_count_sections,
    "check-citations": cmd_check_citations,
    "codebook-codes": cmd_codebook_codes,
    "classify-themes": cmd_classify_themes,
    "cross-study": cmd_cross_study,
    "altitude": cmd_altitude,
    "pod-to-area": cmd_pod_to_area,
    "validate-finish-title": cmd_validate_finish_title,
    "arr-parse": cmd_arr_parse,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    command = args[0]
    if command not in SUBCOMMANDS:
        print(f"report_helpers: unknown subcommand {command!r}", file=sys.stderr)
        return EXIT_USAGE
    parsed: dict[str, str] = {}
    index = 1
    while index < len(args):
        token = args[index]
        if token.startswith("--") and "=" in token:
            flag, value = token.split("=", 1)
            parsed[flag] = value
        elif token.startswith("--"):
            if index + 1 >= len(args):
                print(f"report_helpers: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            parsed[token] = args[index + 1]
            index += 1
        else:
            print(f"report_helpers: unexpected argument {token!r}", file=sys.stderr)
            return EXIT_USAGE
        index += 1
    return HANDLERS[command](parsed)


if __name__ == "__main__":
    raise SystemExit(main())
