#!/usr/bin/env python3
"""Deterministic helpers for ``deck`` (issue 02).

Every number and structure the deck command shows is computed here; the
command prints helper output verbatim and adds the narrative on top. All
checks run offline: no tracker, no chat, no Drive, no network, and no
write into the plugin source tree -- generated persona fields are cached
under ``<state_dir>``, never next to the code (the reference plugin wrote
that cache into the source tree; do not copy that).

Subcommands:

- ``load-persona --persona <name> [--tier <t>] [--file <personas.json>]
  [--cache-dir <dir>]``
  Prints the persona JSON. The cached ``pe_framing_prompt`` from
  ``<cache-dir>/deck-persona-cache.json`` (when present) overrides the
  file's null value; ``--tier`` adds the computed ``cap`` and ``factor``.

- ``list-personas [--file <personas.json>]``
  Prints ``[{"name": ..., "label": ...}]``.

- ``validate-personas [--file <personas.json>]``
  Checks every persona against the required key contract; exit 1 on the
  first invalid entry (all problems are listed).

- ``slide-plan --persona <name> --tier lite|standard|strategic
  [--file ...] [--cache-dir ...]``
  Prints ``{persona, tier, factor, base_cap, cap, content_kinds,
  slide_priority_order, arc_order, methodology}``. The cap is
  ``max(3, round(base * factor))`` with factor lite 0.6, standard 1.0,
  strategic 1.5, and counts content slides only.

- ``beat-skeleton --rqs-file <rqs.json> [--arc-order "setup,conflict,..."]
  [--persona <name>]``
  Prints the four beat shells (``[{beat, title, connector, rq_ids}]``)
  in arc order with every ``rq_ids`` empty. The model assigns each RQ to
  one beat, writes the declarative title and the connector, then
  ``validate-beats`` must pass.

- ``validate-beats --beats-file <beats.json> --rqs-file <rqs.json>``
  Prints one ``[tag]`` line per problem and exits 1 on a block. Tags:
  ``[unknown]`` (a beat name not in the arc, or an assigned RQ id that
  is not in ``rqs.json``), ``[dup]`` (an RQ assigned to more than one
  beat), ``[orphan]`` (an RQ in ``rqs.json`` assigned to no beat),
  ``[empty]`` (a beat carrying no RQs, or an assigned beat with a
  missing title or connector). An empty beat is legal: ``[empty]``
  never blocks; ``[unknown]``, ``[dup]``, and ``[orphan]`` block.

- ``scaffold --beats-file <beats.json> --rqs-file <rqs.json>
  [--persona <name>] [--tier <t>] [--key <KEY>] [--audience <a>]
  [--title <t>] [--date <YYYY-MM-DD>]``
  Prints the outline JSON: cover, agenda, exec summary, background,
  then per non-empty beat one section slide and per RQ one question
  slide plus one finding slide, then recommendations, appendices (when
  the persona methodology is ``appendix`` or ``full_section``), end.
  With ``--persona`` the beats are ordered by the persona arc and the
  slide groups by ``slide_priority_order``.

- ``lint-outline --outline <outline.json> [--persona <name>]
  [--tier <t>]``
  Prints ``ok <check>`` / ``FAIL <check>: <detail>`` lines; exit 1 on
  any FAIL. Checks: structure (cover first, end last), the content-slide
  cap, non-empty titles, duplicate titles, RQ question/finding pairing,
  finding sources (and the strategic-tier ``single source; treat as
  preliminary`` note), filled text slots, and every visual spec.

- ``write-persona-field --persona <name> --field <key> --value <json>
  (--file <personas.json> | --cache-dir <dir>)``
  Writes one persona field. ``--file`` edits the personas file (after a
  validate); ``--cache-dir`` writes ``<dir>/deck-persona-cache.json`` --
  the runtime cache for ``pe_framing_prompt``. Exactly one target.

- ``deck-filename --audience <a> --date <YYYY-MM-DD> --key <KEY>``
  Prints ``deck-<audience>-<date>-<key>.pptx``, lowercase.

- ``finding-sources --synthesis <synthesis.md> [--min-sources 2]``
  Splits the synthesis into ``RQ<n>`` blocks and collects ``[S:slug]``
  citations per block. Prints ``[{id, sources, count, preliminary}]``
  in document order; ``preliminary`` is true when the count is below
  ``--min-sources`` (the strategic-tier wording is the command's job).


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

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

PERSONAS_RELATIVE_DEFAULT = "references/personas.json"
CACHE_FILENAME = "deck-persona-cache.json"

TIERS = ("lite", "standard", "strategic")
TIER_FACTORS = {"lite": 0.6, "standard": 1.0, "strategic": 1.5}

#: Slide kinds that count against the persona slide cap (issue 02).
CONTENT_SLIDE_KINDS = (
    "finding",
    "exec-summary",
    "stats",
    "three-col",
    "quote",
    "bullets",
    "content",
    "diagram",
)

BEATS = ("setup", "conflict", "resolution", "implication")
DEFAULT_ARC_ORDER = list(BEATS)

CANONICAL_PERSONAS = ("leadership", "design", "product", "research", "org")

#: Keys every persona must carry (issue 02). ``pe_framing_prompt`` may be
#: null in the shipped file; the runtime cache fills it.
REQUIRED_PERSONA_KEYS = (
    "label",
    "blind_spot",
    "adversarial_challenge",
    "breakthrough_format",
    "pe_framing_prompt",
    "slide_priority_order",
    "slide_cap",
    "appendix_rules",
    "voice_overrides",
    "exec_skeptic",
)

#: Methodology styles and the persona arc orders (issue 02 table).
METHODOLOGIES = ("appendix", "inline_brief", "full_section")
PERSONA_DEFAULTS: dict[str, dict] = {
    "leadership": {
        "slide_cap": 5,
        "slide_priority_order": ["exec_summary", "strategy_framing", "visuals"],
        "methodology": "appendix",
        "arc_order": ["implication", "setup", "conflict", "resolution"],
    },
    "design": {
        "slide_cap": 8,
        "slide_priority_order": ["visuals", "implications", "strategy_framing"],
        "methodology": "inline_brief",
        "arc_order": list(DEFAULT_ARC_ORDER),
    },
    "product": {
        "slide_cap": 7,
        "slide_priority_order": ["strategy_framing", "next_steps", "exec_summary"],
        "methodology": "appendix",
        "arc_order": list(DEFAULT_ARC_ORDER),
    },
    "research": {
        "slide_cap": 12,
        "slide_priority_order": ["methodology_framing", "findings_depth", "visuals"],
        "methodology": "full_section",
        "arc_order": list(DEFAULT_ARC_ORDER),
    },
    "org": {
        "slide_cap": 10,
        "slide_priority_order": ["strategy_framing", "exec_summary", "visuals"],
        "methodology": "inline_brief",
        "arc_order": list(DEFAULT_ARC_ORDER),
    },
}

#: Strategic-tier wording for findings carried by fewer than 2 sources.
SINGLE_SOURCE_NOTE = "single source; treat as preliminary"

CITE_RE = re.compile(r"\[S:([^\[\]\s]+)\]")
RQ_HEADING_RE = re.compile(r"^#{0,6}\s*(RQ\d+)\b", re.IGNORECASE)
FILENAME_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PRELIMINARY_RE = re.compile(re.escape(SINGLE_SOURCE_NOTE), re.IGNORECASE)


# ---------------------------------------------------------------------------
# configuration (fail-soft: the one loader, None on any failure)
# ---------------------------------------------------------------------------


def load_plugin_config() -> dict | None:
    """Load the plugin config through lib.config; None when unavailable."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def personas_file_from_config(config: dict | None) -> Path:
    """The personas file path: config ``deck.personas_file`` when set."""
    deck = (config or {}).get("deck")
    value = deck.get("personas_file") if isinstance(deck, dict) else None
    if isinstance(value, str) and value.strip():
        candidate = Path(value.strip())
        if not candidate.is_absolute():
            candidate = PLUGIN_ROOT / candidate
        return candidate
    return PLUGIN_ROOT / PERSONAS_RELATIVE_DEFAULT


# ---------------------------------------------------------------------------
# personas
# ---------------------------------------------------------------------------


def load_personas(file_value: str = "") -> dict:
    """Load the personas mapping from ``--file`` or the config default."""
    path = _personas_path(file_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    personas = data.get("personas") if isinstance(data, dict) else None
    if not isinstance(personas, dict) or not personas:
        raise ValueError(f"{path}: no 'personas' mapping")
    return personas


def _personas_path(file_value: str) -> Path:
    if file_value:
        candidate = Path(file_value).expanduser()
        if not candidate.is_absolute():
            candidate = PLUGIN_ROOT / candidate
        return candidate
    return personas_file_from_config(load_plugin_config())


def load_cached_fields(cache_dir: str) -> dict:
    """Read ``<cache-dir>/deck-persona-cache.json``; {} when absent."""
    if not cache_dir:
        return {}
    path = Path(cache_dir).expanduser() / CACHE_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    personas = data.get("personas") if isinstance(data, dict) else None
    return personas if isinstance(personas, dict) else {}


def write_cached_field(cache_dir: str, persona: str, field: str, value) -> Path:
    """Write one persona field into the state-dir cache (never the source tree)."""
    if not cache_dir:
        raise ValueError("write_cached_field needs a cache dir")
    base = Path(cache_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    path = base / CACHE_FILENAME
    data = {"personas": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("personas"), dict):
                data = loaded
        except (OSError, ValueError):
            pass
    entry = data["personas"].setdefault(persona, {})
    if isinstance(entry, dict):
        entry[field] = value
    else:
        data["personas"][persona] = {field: value}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def merge_persona_cache(persona: dict, cached: dict) -> dict:
    """Overlay the cached fields onto the persona (cache wins per key)."""
    merged = dict(persona)
    for key, value in (cached or {}).items():
        if value is not None:
            merged[key] = value
    return merged


def _is_string_list(value) -> bool:
    """True when the value is a list of non-empty strings."""
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def validate_personas(personas: dict) -> list[str]:
    """Return a list of problems ([] means valid)."""
    problems: list[str] = []
    if not isinstance(personas, dict) or not personas:
        return ["personas must be a non-empty mapping"]
    for name, persona in personas.items():
        if not isinstance(persona, dict):
            problems.append(f"{name}: persona must be a mapping")
            continue
        for key in REQUIRED_PERSONA_KEYS:
            if key not in persona:
                problems.append(f"{name}: missing required key '{key}'")
        if "slide_cap" in persona and (
            not isinstance(persona["slide_cap"], int) or persona["slide_cap"] < 1
        ):
            problems.append(f"{name}: slide_cap must be a positive integer")
        if "slide_priority_order" in persona and not _is_string_list(
            persona["slide_priority_order"]
        ):
            problems.append(f"{name}: slide_priority_order must be a list of strings")
        if "voice_overrides" in persona and not isinstance(persona["voice_overrides"], dict):
            problems.append(f"{name}: voice_overrides must be a mapping")
        if "methodology" in persona and persona["methodology"] not in METHODOLOGIES:
            problems.append(
                f"{name}: methodology must be one of {', '.join(METHODOLOGIES)}"
            )
        if "arc_order" in persona and not _is_string_list(persona["arc_order"]):
            problems.append(f"{name}: arc_order must be a list of strings")
        prompt = persona.get("pe_framing_prompt")
        if prompt is not None:
            problems.extend(_prompt_problems(name, prompt))
    for canonical in CANONICAL_PERSONAS:
        if canonical not in personas:
            problems.append(f"missing canonical persona '{canonical}'")
    return problems


def _prompt_problems(name: str, prompt) -> list[str]:
    """Shape checks for a cached pe_framing_prompt (ROLE/ATTACK/CHECKLIST)."""
    if not isinstance(prompt, dict):
        return [f"{name}: pe_framing_prompt must be null or a mapping"]
    problems = []
    for key in ("role", "attack", "checklist"):
        if not prompt.get(key):
            problems.append(f"{name}: pe_framing_prompt.{key} is empty")
    checklist = prompt.get("checklist")
    if checklist is not None:
        if not isinstance(checklist, list) or not _is_string_list(checklist):
            problems.append(f"{name}: pe_framing_prompt.checklist must be a list of strings")
        elif not (4 <= len(checklist) <= 6):
            problems.append(
                f"{name}: pe_framing_prompt.checklist needs 4 to 6 items, got {len(checklist)}"
            )
    return problems


def compute_cap(base_cap: int, tier: str) -> int:
    """``max(3, round(base * factor))``; content slides only."""
    if tier not in TIER_FACTORS:
        raise ValueError(f"tier must be one of {', '.join(TIERS)}")
    if not isinstance(base_cap, int) or base_cap < 1:
        raise ValueError("base cap must be a positive integer")
    return max(3, round(base_cap * TIER_FACTORS[tier]))


def persona_arc_order(persona: dict) -> list[str]:
    """The persona arc or the default arc."""
    order = persona.get("arc_order")
    if _is_string_list(order) and order:
        return list(order)
    return list(DEFAULT_ARC_ORDER)


def slide_plan(persona: dict, name: str, tier: str) -> dict:
    """The cap and ordering card the command shows in phases 3 to 5."""
    cap = compute_cap(persona["slide_cap"], tier)
    return {
        "persona": name,
        "tier": tier,
        "factor": TIER_FACTORS[tier],
        "base_cap": persona["slide_cap"],
        "cap": cap,
        "content_kinds": list(CONTENT_SLIDE_KINDS),
        "slide_priority_order": list(persona.get("slide_priority_order") or []),
        "arc_order": persona_arc_order(persona),
        "methodology": persona.get("methodology", "appendix"),
    }


# ---------------------------------------------------------------------------
# visuals (20 kinds; the doc list is generated from this table)
# ---------------------------------------------------------------------------


def _need_list(spec: dict, key: str) -> list | None:
    value = spec.get(key)
    return value if isinstance(value, list) else None


def _need_items(value, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and all(
        (value.get(key) not in (None, "")) or isinstance(value.get(key), (int, float))
        for key in keys
    )


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_visual(spec) -> tuple[bool, str]:
    """Validate one visual spec; ``(ok, reason)``. Unknown kind is invalid."""
    if not isinstance(spec, dict):
        return False, "visual spec must be a mapping"
    kind = spec.get("kind")
    if kind not in VISUAL_KINDS:
        return False, f"unknown visual kind {kind!r}"
    checker = VISUAL_KINDS[kind]
    return checker(spec)


def _check_bar(spec: dict) -> tuple[bool, str]:
    labels, values = _need_list(spec, "labels"), _need_list(spec, "values")
    if labels is None or values is None:
        return False, "bar needs labels and values lists"
    if len(labels) != len(values) or not labels:
        return False, "bar needs equal-length non-empty labels and values"
    if not all(_num(v) for v in values):
        return False, "bar values must be numbers"
    return True, ""


def _check_line(spec: dict) -> tuple[bool, str]:
    labels, series = _need_list(spec, "labels"), _need_list(spec, "series")
    if labels is None or series is None or not labels or not series:
        return False, "line needs non-empty labels and series lists"
    for entry in series:
        if not isinstance(entry, dict) or not _need_list(entry, "values"):
            return False, "line series entries need a values list"
        if not all(_num(v) for v in entry["values"]):
            return False, "line series values must be numbers"
    return True, ""


def _check_pie(spec: dict) -> tuple[bool, str]:
    slices = _need_list(spec, "slices")
    if slices is None:
        return False, "pie needs a slices list"
    if not 2 <= len(slices) <= 5:
        return False, f"pie needs 2 to 5 slices, got {len(slices)}"
    if not all(_need_items(s, ("label", "value")) and _num(s.get("value")) for s in slices):
        return False, "pie slices need label and numeric value"
    return True, ""


def _check_matrix2x2(spec: dict) -> tuple[bool, str]:
    quadrants = _need_list(spec, "quadrants")
    if quadrants is None or len(quadrants) != 4:
        return False, f"matrix2x2 needs exactly 4 quadrants, got {0 if quadrants is None else len(quadrants)}"
    if not all(isinstance(q, dict) and q.get("title") for q in quadrants):
        return False, "matrix2x2 quadrants need titles"
    return True, ""


def _check_funnel(spec: dict) -> tuple[bool, str]:
    stages = _need_list(spec, "stages")
    if stages is None or not stages:
        return False, "funnel needs a non-empty stages list"
    if not all(_need_items(s, ("label", "value")) for s in stages):
        return False, "funnel stages need label and value"
    return True, ""


def _check_timeline(spec: dict) -> tuple[bool, str]:
    milestones = _need_list(spec, "milestones")
    if milestones is None or len(milestones) < 2:
        return False, "timeline needs at least 2 milestones"
    if not all(_need_items(m, ("label",)) for m in milestones):
        return False, "timeline milestones need labels"
    return True, ""


def _check_sequence(kind: str, minimum: int):
    def checker(spec: dict) -> tuple[bool, str]:
        steps = _need_list(spec, "steps")
        if steps is None or len(steps) < minimum:
            return False, f"{kind} needs at least {minimum} steps"
        if not all(_need_items(s, ("label",)) for s in steps):
            return False, f"{kind} steps need labels"
        return True, ""

    return checker


def _check_pyramid(spec: dict) -> tuple[bool, str]:
    levels = _need_list(spec, "levels")
    if levels is None or len(levels) < 2:
        return False, "pyramid needs at least 2 levels"
    if not all(_need_items(item, ("label",)) for item in levels):
        return False, "pyramid levels need labels"
    return True, ""


def _check_venn(spec: dict) -> tuple[bool, str]:
    sets = _need_list(spec, "sets")
    if sets is None or not 2 <= len(sets) <= 3:
        return False, f"venn needs 2 to 3 sets, got {0 if sets is None else len(sets)}"
    if not all(_need_items(s, ("label",)) for s in sets):
        return False, "venn sets need labels"
    return True, ""


def _check_hierarchy(spec: dict) -> tuple[bool, str]:
    root = spec.get("root")
    if not isinstance(root, dict) or not root.get("label"):
        return False, "hierarchy needs a root with a label"
    return True, ""


def _check_quadrant_plot(spec: dict) -> tuple[bool, str]:
    points = _need_list(spec, "points")
    if points is None or not points:
        return False, "quadrant_plot needs a non-empty points list"
    for point in points:
        if not isinstance(point, dict) or not _num(point.get("x")) or not _num(point.get("y")):
            return False, "quadrant_plot points need numeric x and y"
    return True, ""


def _check_comparison(spec: dict) -> tuple[bool, str]:
    columns = _need_list(spec, "columns")
    if columns is None or len(columns) != 2:
        return False, f"comparison needs exactly 2 columns, got {0 if columns is None else len(columns)}"
    if not all(isinstance(c, dict) and c.get("title") for c in columns):
        return False, "comparison columns need titles"
    return True, ""


def _check_grid(spec: dict) -> tuple[bool, str]:
    columns, cells = spec.get("columns"), _need_list(spec, "cells")
    if not isinstance(columns, int) or columns < 1:
        return False, "grid needs an integer columns value of at least 1"
    if cells is None or not cells:
        return False, "grid needs a non-empty cells list"
    if not all(isinstance(c, dict) for c in cells):
        return False, "grid cells must be mappings"
    return True, ""


def _check_swimlane(spec: dict) -> tuple[bool, str]:
    lanes, periods = _need_list(spec, "lanes"), _need_list(spec, "periods")
    if lanes is None or len(lanes) < 2:
        return False, "swimlane needs at least 2 lanes"
    if not all(isinstance(l, dict) and l.get("label") for l in lanes):
        return False, "swimlane lanes need labels"
    if periods is None or not periods:
        return False, "swimlane needs a non-empty periods list"
    return True, ""


def _check_mountain(spec: dict) -> tuple[bool, str]:
    labels, values = _need_list(spec, "labels"), _need_list(spec, "values")
    if labels is None or values is None:
        return False, "mountain needs labels and values lists"
    if len(labels) != len(values) or len(labels) < 2:
        return False, "mountain needs equal-length labels and values (at least 2)"
    if not all(_num(v) for v in values):
        return False, "mountain values must be numbers"
    return True, ""


def _check_edges(kind: str, node_minimum: int):
    def checker(spec: dict) -> tuple[bool, str]:
        nodes, edges = _need_list(spec, "nodes"), _need_list(spec, "edges")
        if nodes is None or len(nodes) < node_minimum:
            return False, f"{kind} needs at least {node_minimum} nodes"
        if not all(isinstance(n, dict) and n.get("id") for n in nodes):
            return False, f"{kind} nodes need ids"
        if edges is None or not edges:
            return False, f"{kind} needs a non-empty edges list"
        for edge in edges:
            if not isinstance(edge, dict) or not edge.get("from") or not edge.get("to"):
                return False, f"{kind} edges need from and to"
        return True, ""

    return checker


#: The 20 visual kinds and their required shapes (issue 02). The deck
#: documentation list is generated from this table, never hand-copied.
VISUAL_KINDS: dict[str, object] = {
    "bar": _check_bar,
    "line": _check_line,
    "pie": _check_pie,                    # 2 to 5 slices
    "matrix2x2": _check_matrix2x2,        # exactly 4 quadrants
    "funnel": _check_funnel,
    "timeline": _check_timeline,
    "process": _check_sequence("process", 2),
    "chevron": _check_sequence("chevron", 2),
    "pyramid": _check_pyramid,
    "cycle": _check_sequence("cycle", 2),
    "venn": _check_venn,                  # 2 to 3 sets
    "hierarchy": _check_hierarchy,        # root required
    "quadrant_plot": _check_quadrant_plot,
    "comparison": _check_comparison,      # exactly 2 columns
    "journey": _check_sequence("journey", 2),
    "grid": _check_grid,
    "swimlane": _check_swimlane,          # lanes and periods
    "mountain": _check_mountain,
    "network": _check_edges("network", 2),        # edges required
    "decision-flow": _check_edges("decision-flow", 2),  # edges required
}


# ---------------------------------------------------------------------------
# research questions, beats, scaffold
# ---------------------------------------------------------------------------


def load_rqs(file_value: str) -> list[dict]:
    """Load ``rqs.json`` (``[{id, topic, question}]``); raise ValueError on shape."""
    data = json.loads(Path(file_value).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("rqs file must be a non-empty JSON list")
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("every rqs entry needs an id")
    ids = [entry["id"] for entry in data]
    if len(set(ids)) != len(ids):
        raise ValueError("rqs ids must be unique")
    return data


def load_beats(file_value: str) -> list[dict]:
    """Load the beats file (``[{beat, title, connector, rq_ids}]``)."""
    data = json.loads(Path(file_value).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("beats file must be a non-empty JSON list")
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("beat"):
            raise ValueError("every beats entry needs a beat name")
    return data


def beat_skeleton(rqs: list[dict], arc_order: list[str] | None = None) -> list[dict]:
    """The four beat shells in arc order, all ``rq_ids`` empty."""
    order = [beat for beat in (arc_order or DEFAULT_ARC_ORDER) if beat in BEATS]
    for beat in BEATS:
        if beat not in order:
            order.append(beat)
    return [{"beat": beat, "title": "", "connector": "", "rq_ids": []} for beat in order]


def validate_beats(beats: list[dict], rqs: list[dict]) -> tuple[list[str], bool]:
    """Return (tag lines, blocked). An empty beat is legal; it never blocks."""
    tags: list[str] = []
    known = {entry["id"] for entry in rqs}
    assigned: dict[str, int] = {}
    names: set[str] = set()
    for entry in beats:
        name = entry.get("beat") or ""
        if name not in BEATS:
            tags.append(f"[unknown] beat name {name!r} is not one of {', '.join(BEATS)}")
        if name in names:
            tags.append(f"[dup] beat {name!r} appears more than once")
        names.add(name)
        rq_ids = entry.get("rq_ids") or []
        if not isinstance(rq_ids, list):
            tags.append(f"[unknown] beat {name!r} rq_ids must be a list")
            continue
        if not rq_ids:
            tags.append(f"[empty] beat {name!r} carries no RQs (legal; it is skipped)")
        elif not entry.get("title") or not entry.get("connector"):
            tags.append(f"[empty] beat {name!r} carries RQs but is missing a title or connector")
        for rq_id in rq_ids:
            if rq_id not in known:
                tags.append(f"[unknown] {rq_id} is not in the rqs file")
            assigned[rq_id] = assigned.get(rq_id, 0) + 1
    for rq_id, count in assigned.items():
        if count > 1:
            tags.append(f"[dup] {rq_id} is assigned to {count} beats")
    for entry in rqs:
        rq_id = entry["id"]
        if assigned.get(rq_id, 0) == 0:
            tags.append(f"[orphan] {rq_id} is not assigned to any beat")
    blocked = any(
        tag.startswith("[unknown]") or tag.startswith("[dup]") or tag.startswith("[orphan]")
        for tag in tags
    )
    return tags, blocked


def _slide(slide_id: str, kind: str, title: str, **extra) -> dict:
    slide = {"id": slide_id, "kind": kind, "title": title}
    slide.update(extra)
    return slide


def scaffold_outline(
    beats: list[dict],
    rqs: list[dict],
    persona: dict | None = None,
    persona_name: str = "",
    tier: str = "standard",
    key: str = "",
    audience: str = "",
    title: str = "",
    date_text: str = "",
) -> dict:
    """Build the outline JSON (phase 2 structure; the model fills text slots)."""
    ordered = list(beats)
    if persona:
        arc = persona_arc_order(persona)
        ordered.sort(key=lambda entry: arc.index(entry["beat"]) if entry["beat"] in arc else len(arc))

    rqs_by_id = {entry["id"]: entry for entry in rqs}
    slides: list[dict] = [
        _slide("cover", "cover", title or "Research readout", subtitle=key, audience=audience, date=date_text),
        _slide("agenda", "agenda", "Agenda", items=[entry["title"] or entry["beat"] for entry in ordered if entry.get("rq_ids")]),
        _slide("exec-summary", "exec-summary", "Executive summary", category="exec_summary", bullets=[]),
        _slide("background", "content", "Background", category="strategy_framing", text=""),
    ]
    for entry in ordered:
        rq_ids = entry.get("rq_ids") or []
        if not rq_ids:
            continue  # an empty beat is legal and contributes no slides
        beat_name = entry.get("beat") or ""
        slides.append(
            _slide(
                f"section-{beat_name}",
                "content",
                entry.get("title") or beat_name,
                category="findings_depth",
                beat=beat_name,
                text=entry.get("connector") or "",
            )
        )
        for rq_id in rq_ids:
            rq = rqs_by_id.get(rq_id, {})
            question = rq.get("question") or rq_id
            slides.append(
                _slide(f"question-{rq_id}", "question", question, category="findings_depth", rq=rq_id, text="")
            )
            slides.append(
                _slide(
                    f"finding-{rq_id}",
                    "finding",
                    "",
                    category="findings_depth",
                    rq=rq_id,
                    bullets=[],
                    sources=[],
                )
            )
    slides.append(
        _slide("recommendations", "recommendations", "Recommendations", category="next_steps", bullets=[])
    )
    methodology = (persona or {}).get("methodology", "appendix")
    if methodology in ("appendix", "full_section"):
        slides.append(
            _slide("appendix", "appendix", "Appendix", category="appendix", bullets=[])
        )
    slides.append(_slide("end", "end", "Thank you"))

    if persona:
        slides = apply_priority_order(slides, persona.get("slide_priority_order") or [])

    outline = {
        "version": 1,
        "key": key,
        "audience": audience or persona_name,
        "tier": tier,
        "date": date_text,
        "title": title or "Research readout",
        "slides": slides,
    }
    if persona:
        outline["persona"] = persona_name
        outline["cap"] = compute_cap(persona["slide_cap"], tier)
    return outline


def apply_priority_order(slides: list[dict], order: list[str]) -> list[dict]:
    """Stable-reorder slides by the persona ``slide_priority_order``.

    The cover always leads and ``end`` always closes; every other slide is
    bucketed by its ``category`` (a slide without a category keeps its
    position bucket ``""``). Categories named in ``order`` come first in
    that order; unnamed categories follow in first-appearance order.
    """
    head = [s for s in slides if s.get("kind") == "cover"]
    tail = [s for s in slides if s.get("kind") == "end"]
    middle = [s for s in slides if s.get("kind") not in ("cover", "end")]

    buckets: dict[str, list[dict]] = {}
    sequence: list[str] = []
    for slide in middle:
        category = slide.get("category") or ""
        if category not in buckets:
            buckets[category] = []
            sequence.append(category)
        buckets[category].append(slide)

    ordered_categories: list[str] = []
    for category in order:
        if category in buckets and category not in ordered_categories:
            ordered_categories.append(category)
    for category in sequence:
        if category not in ordered_categories:
            ordered_categories.append(category)

    result = list(head)
    for category in ordered_categories:
        result.extend(buckets[category])
    result.extend(tail)
    return result


# ---------------------------------------------------------------------------
# outline lint
# ---------------------------------------------------------------------------


def _slide_body_empty(slide: dict) -> bool:
    kind = slide.get("kind")
    if kind in ("finding", "exec-summary", "bullets", "recommendations", "appendix", "agenda"):
        return not [b for b in (slide.get("bullets") or []) if str(b).strip()] and not [
            i for i in (slide.get("items") or []) if str(i).strip()
        ]
    if kind in ("content", "question"):
        return not str(slide.get("text") or "").strip()
    if kind == "three-col":
        columns = slide.get("columns") or []
        return len(columns) != 3 or any(not (c.get("text") or "").strip() for c in columns if isinstance(c, dict))
    if kind == "stats":
        return not (slide.get("stats") or [])
    if kind == "quote":
        return not str(slide.get("quote") or "").strip() or not str(slide.get("attribution") or "").strip()
    if kind == "diagram":
        ok, _ = validate_visual(slide.get("visual"))
        return not ok
    return False  # cover and end carry no body


def lint_outline(
    outline: dict, persona: dict | None = None, tier: str = ""
) -> tuple[list[str], bool]:
    """Return (lines, blocked); lines are ``ok <check>`` / ``FAIL <check>: ...``."""
    lines: list[str] = []
    blocked = False

    def fail(name: str, detail: str) -> None:
        nonlocal blocked
        blocked = True
        lines.append(f"FAIL {name}: {detail}")

    slides = outline.get("slides") if isinstance(outline, dict) else None
    if not isinstance(slides, list) or not slides:
        fail("structure", "outline must be a mapping with a non-empty slides list")
        return lines, blocked

    kinds = [s.get("kind") for s in slides]
    if kinds[0] != "cover":
        fail("structure", f"first slide must be cover, got {kinds[0]!r}")
    if kinds[-1] != "end":
        fail("structure", f"last slide must be end, got {kinds[-1]!r}")
    if not blocked:
        lines.append("ok structure")

    effective_tier = tier or outline.get("tier") or "standard"
    if persona is not None:
        cap = compute_cap(persona["slide_cap"], effective_tier)
        persona_label = f"{outline.get('persona') or 'persona'} at {effective_tier}"
    else:
        cap = outline.get("cap")
        persona_label = "the outline cap"
        if not isinstance(cap, int) or cap < 1:
            fail("cap", "no persona given and the outline has no usable cap")
            cap = None
    if cap is not None:
        content = [s for s in slides if s.get("kind") in CONTENT_SLIDE_KINDS]
        if len(content) > cap:
            fail("cap", f"{len(content)} content slides exceed the cap of {cap} for {persona_label}")
        else:
            lines.append(f"ok cap ({len(content)} content slides of {cap} for {persona_label})")

    missing_titles = [
        s.get("id") or f"slide {i}"
        for i, s in enumerate(slides)
        if s.get("kind") not in ("cover", "end") and not str(s.get("title") or "").strip()
    ]
    if missing_titles:
        fail("titles", f"slides without a title: {', '.join(missing_titles)}")
    else:
        lines.append("ok titles")

    seen: dict[str, str] = {}
    dupes: list[str] = []
    for slide in slides:
        if slide.get("kind") not in CONTENT_SLIDE_KINDS:
            continue
        title = str(slide.get("title") or "").strip().lower()
        if not title:
            continue
        if title in seen and seen[title] not in dupes:
            dupes.append(title)
        seen.setdefault(title, slide.get("id") or "")
    if dupes:
        fail("duplicate-titles", f"content slides sharing a title: {', '.join(dupes)}")
    else:
        lines.append("ok duplicate-titles")

    question_rqs = {s.get("rq") for s in slides if s.get("kind") == "question"}
    finding_rqs = {s.get("rq") for s in slides if s.get("kind") == "finding"}
    unpaired = sorted(
        (question_rqs - finding_rqs) | (finding_rqs - question_rqs) | {None} & (question_rqs | finding_rqs),
        key=lambda v: str(v),
    )
    if unpaired:
        fail("rq-pairing", f"question and finding slides must come in RQ pairs; unpaired: "
                           f"{', '.join(str(v) for v in unpaired if v is not None) or 'a slide without an rq id'}")
    else:
        lines.append("ok rq-pairing")

    empty_bodies = [s.get("id") or f"slide {i}" for i, s in enumerate(slides) if _slide_body_empty(s)]
    if empty_bodies:
        fail("empty-body", f"slides with unfilled text slots: {', '.join(empty_bodies)}")
    else:
        lines.append("ok empty-body")

    strategic = effective_tier == "strategic"
    weak: list[str] = []
    unnoted: list[str] = []
    for slide in slides:
        if slide.get("kind") != "finding":
            continue
        sources = slide.get("sources") or []
        if not sources:
            weak.append(str(slide.get("id")))
        elif strategic and len(sources) < 2:
            marked = (
                slide.get("preliminary") is True
                or any(PRELIMINARY_RE.search(str(b)) for b in (slide.get("bullets") or []))
                or PRELIMINARY_RE.search(str(slide.get("note") or ""))
            )
            if not marked:
                unnoted.append(str(slide.get("id")))
    if weak:
        fail("finding-sources", f"findings without sources: {', '.join(weak)}")
    else:
        lines.append("ok finding-sources")
    if unnoted:
        fail(
            "strategic-preliminary",
            f"strategic findings under 2 sources missing the '{SINGLE_SOURCE_NOTE}' note: "
            f"{', '.join(unnoted)}",
        )
    elif strategic:
        lines.append("ok strategic-preliminary")

    bad_visuals: list[str] = []
    for slide in slides:
        if "visual" not in slide:
            continue
        ok, reason = validate_visual(slide.get("visual"))
        if not ok:
            bad_visuals.append(f"{slide.get('id')} ({reason})")
    if bad_visuals:
        fail("visual-specs", "; ".join(bad_visuals))
    else:
        lines.append("ok visual-specs")

    return lines, blocked


# ---------------------------------------------------------------------------
# filenames and synthesis parsing
# ---------------------------------------------------------------------------


def deck_filename(audience: str, date_text: str, key: str) -> str:
    """``deck-<audience>-<date>-<key>.pptx``, lowercase."""
    if not audience or not date_text or not key:
        raise ValueError("deck-filename needs audience, date, and key")
    if not FILENAME_DATE_RE.match(date_text.strip()):
        raise ValueError(f"date must be YYYY-MM-DD, got {date_text!r}")
    return f"deck-{audience.strip()}-{date_text.strip()}-{key.strip()}.pptx".lower()


def finding_sources(synthesis_text: str, min_sources: int = 2) -> list[dict]:
    """Per-RQ citation counts from the synthesis markdown."""
    results: list[dict] = []
    current: dict | None = None
    for line in synthesis_text.splitlines():
        match = RQ_HEADING_RE.match(line.strip())
        if match:
            current = {"id": match.group(1).upper(), "sources": [], "count": 0}
            results.append(current)
            continue
        if current is None:
            continue
        for slug in CITE_RE.findall(line):
            if slug not in current["sources"]:
                current["sources"].append(slug)
        current["count"] = len(current["sources"])
    for entry in results:
        entry["preliminary"] = entry["count"] < min_sources
    return results


# ---------------------------------------------------------------------------
# command wrappers
# ---------------------------------------------------------------------------


def _persona_args(args: dict[str, str]) -> tuple[dict, str, dict]:
    """Load persona + optional cache; returns (personas, name, merged persona)."""
    name = (args.get("--persona") or "").strip()
    if not name:
        raise _Usage("load-persona needs --persona")
    personas = load_personas(args.get("--file") or "")
    if name not in personas:
        known = ", ".join(sorted(personas))
        raise _Usage(f"unknown persona {name!r}; known: {known}")
    cached = load_cached_fields(args.get("--cache-dir") or "")
    merged = merge_persona_cache(personas[name], cached.get(name) or {})
    return personas, name, merged


class _Usage(Exception):
    pass


def cmd_load_persona(args: dict[str, str]) -> int:
    _, name, merged = _persona_args(args)
    tier = (args.get("--tier") or "").strip().lower()
    if tier:
        if tier not in TIERS:
            raise _Usage("--tier must be one of " + ", ".join(TIERS))
        merged["tier"] = tier
        merged["cap"] = compute_cap(merged["slide_cap"], tier)
        merged["factor"] = TIER_FACTORS[tier]
    merged["name"] = name
    print(json.dumps(merged, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_list_personas(args: dict[str, str]) -> int:
    personas = load_personas(args.get("--file") or "")
    print(json.dumps(
        [{"name": name, "label": entry.get("label", name)} for name, entry in personas.items()],
        indent=2,
        ensure_ascii=False,
    ))
    return EXIT_OK


def cmd_validate_personas(args: dict[str, str]) -> int:
    try:
        personas = load_personas(args.get("--file") or "")
    except (OSError, ValueError) as exc:
        print(f"deck_helpers: cannot read personas: {exc}", file=sys.stderr)
        return EXIT_FAIL
    problems = validate_personas(personas)
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return EXIT_FAIL
    print("ok personas (" + ", ".join(sorted(personas)) + ")")
    return EXIT_OK


def cmd_slide_plan(args: dict[str, str]) -> int:
    _, name, merged = _persona_args(args)
    tier = (args.get("--tier") or "").strip().lower()
    if not tier:
        raise _Usage("slide-plan needs --tier")
    if tier not in TIERS:
        raise _Usage("--tier must be one of " + ", ".join(TIERS))
    print(json.dumps(slide_plan(merged, name, tier), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_beat_skeleton(args: dict[str, str]) -> int:
    rqs_file = args.get("--rqs-file") or ""
    if not rqs_file:
        raise _Usage("beat-skeleton needs --rqs-file")
    try:
        rqs = load_rqs(rqs_file)
    except (OSError, ValueError) as exc:
        print(f"deck_helpers: cannot read rqs: {exc}", file=sys.stderr)
        return EXIT_FAIL
    arc = list(DEFAULT_ARC_ORDER)
    if args.get("--arc-order"):
        arc = [part.strip() for part in args["--arc-order"].split(",") if part.strip()]
        bad = [beat for beat in arc if beat not in BEATS]
        if bad:
            raise _Usage("arc-order beats must be among " + ", ".join(BEATS) + f"; got {', '.join(bad)}")
    elif args.get("--persona"):
        _, _, merged = _persona_args(args)
        arc = persona_arc_order(merged)
    print(json.dumps(beat_skeleton(rqs, arc), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_validate_beats(args: dict[str, str]) -> int:
    beats_file = args.get("--beats-file") or ""
    rqs_file = args.get("--rqs-file") or ""
    if not beats_file or not rqs_file:
        raise _Usage("validate-beats needs --beats-file and --rqs-file")
    try:
        beats = load_beats(beats_file)
        rqs = load_rqs(rqs_file)
    except (OSError, ValueError) as exc:
        print(f"deck_helpers: cannot read beats input: {exc}", file=sys.stderr)
        return EXIT_FAIL
    tags, blocked = validate_beats(beats, rqs)
    for tag in tags:
        print(tag)
    if not tags:
        print("ok beats (every RQ assigned once, every assigned beat titled)")
    return EXIT_FAIL if blocked else EXIT_OK


def cmd_scaffold(args: dict[str, str]) -> int:
    beats_file = args.get("--beats-file") or ""
    rqs_file = args.get("--rqs-file") or ""
    if not beats_file or not rqs_file:
        raise _Usage("scaffold needs --beats-file and --rqs-file")
    try:
        beats = load_beats(beats_file)
        rqs = load_rqs(rqs_file)
    except (OSError, ValueError) as exc:
        print(f"deck_helpers: cannot read scaffold input: {exc}", file=sys.stderr)
        return EXIT_FAIL
    persona = None
    persona_name = ""
    if args.get("--persona"):
        try:
            _, persona_name, persona = _persona_args(args)
        except _Usage as exc:
            raise exc
    tier = (args.get("--tier") or "standard").strip().lower()
    if tier not in TIERS:
        raise _Usage("--tier must be one of " + ", ".join(TIERS))
    outline = scaffold_outline(
        beats,
        rqs,
        persona=persona,
        persona_name=persona_name,
        tier=tier,
        key=args.get("--key") or "",
        audience=args.get("--audience") or "",
        title=args.get("--title") or "",
        date_text=args.get("--date") or "",
    )
    print(json.dumps(outline, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_lint_outline(args: dict[str, str]) -> int:
    outline_file = args.get("--outline") or ""
    if not outline_file:
        raise _Usage("lint-outline needs --outline")
    try:
        outline = json.loads(Path(outline_file).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"deck_helpers: cannot read outline: {exc}", file=sys.stderr)
        return EXIT_FAIL
    persona = None
    if args.get("--persona"):
        _, _, persona = _persona_args(args)
    lines, blocked = lint_outline(outline, persona=persona, tier=(args.get("--tier") or "").strip().lower())
    for line in lines:
        print(line)
    return EXIT_FAIL if blocked else EXIT_OK


def cmd_write_persona_field(args: dict[str, str]) -> int:
    name = (args.get("--persona") or "").strip()
    field = (args.get("--field") or "").strip()
    raw = args.get("--value")
    file_target = args.get("--file") or ""
    cache_dir = args.get("--cache-dir") or ""
    if not name or not field or raw is None:
        raise _Usage("write-persona-field needs --persona, --field, and --value")
    if bool(file_target) == bool(cache_dir):
        raise _Usage("write-persona-field needs exactly one of --file or --cache-dir")
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    if file_target:
        path = _personas_path(file_target)
        personas = load_personas(file_target)
        if name not in personas:
            raise _Usage(f"unknown persona {name!r}")
        persona = dict(personas[name])
        persona[field] = value
        problems = validate_personas({**personas, name: persona})
        if problems:
            for problem in problems:
                print(f"FAIL {problem}", file=sys.stderr)
            return EXIT_FAIL
        personas[name] = persona
        path.write_text(
            json.dumps({"personas": personas}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"ok wrote {name}.{field} to {path}")
        return EXIT_OK
    path = write_cached_field(cache_dir, name, field, value)
    print(f"ok cached {name}.{field} in {path}")
    return EXIT_OK


def cmd_deck_filename(args: dict[str, str]) -> int:
    audience = args.get("--audience") or ""
    date_text = args.get("--date") or ""
    key = args.get("--key") or ""
    if not audience or not date_text or not key:
        raise _Usage("deck-filename needs --audience, --date, and --key")
    try:
        print(deck_filename(audience, date_text, key))
    except ValueError as exc:
        print(f"deck_helpers: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


def cmd_finding_sources(args: dict[str, str]) -> int:
    synthesis_file = args.get("--synthesis") or ""
    if not synthesis_file:
        raise _Usage("finding-sources needs --synthesis")
    min_sources = 2
    if args.get("--min-sources"):
        try:
            min_sources = int(args["--min-sources"])
        except ValueError:
            raise _Usage("--min-sources needs an integer")
    try:
        text = Path(synthesis_file).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        print(f"deck_helpers: cannot read synthesis: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps(finding_sources(text, min_sources), indent=2, ensure_ascii=False))
    return EXIT_OK


SUBCOMMANDS = {
    "load-persona": cmd_load_persona,
    "list-personas": cmd_list_personas,
    "validate-personas": cmd_validate_personas,
    "slide-plan": cmd_slide_plan,
    "beat-skeleton": cmd_beat_skeleton,
    "validate-beats": cmd_validate_beats,
    "scaffold": cmd_scaffold,
    "lint-outline": cmd_lint_outline,
    "write-persona-field": cmd_write_persona_field,
    "deck-filename": cmd_deck_filename,
    "finding-sources": cmd_finding_sources,
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
        print(f"deck_helpers: unknown subcommand {command!r}", file=sys.stderr)
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
                print(f"deck_helpers: {token} needs a value", file=sys.stderr)
                return EXIT_USAGE
            parsed[token] = args[index + 1]
            index += 1
        else:
            print(f"deck_helpers: unexpected argument {token!r}", file=sys.stderr)
            return EXIT_USAGE
        index += 1
    try:
        return SUBCOMMANDS[command](parsed)
    except _Usage as exc:
        print(f"deck_helpers: {exc}", file=sys.stderr)
        return EXIT_USAGE


# ---------------------------------------------------------------------------
# self-test (offline; tempdirs only -- never writes into the plugin tree)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(main())
