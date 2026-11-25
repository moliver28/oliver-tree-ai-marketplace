#!/usr/bin/env python3
"""Study spec validator, body renderer, and reverse parser (issue 04).

The spec JSON file is the source of truth for a study ticket. This module is
the deterministic core around it:

- ``validate_spec(spec)`` blocks bad content before any write (quality of a
  hypothesis stays model judgment; only hard rules live here).
- ``build_document(spec)`` renders the spec into the configured tracker body
  format: ``adf`` (Jira), ``markdown`` (GitHub, Linear), or ``html`` (Asana).
  The ten template blocks always render in the same order, so the same spec
  always produces a byte-identical body.
- ``assert_full_document(body)`` checks a rendered (or live-read) body for
  the fixed node counts -- exactly 2 panels, 1 Background table, 1 Resources
  collapsed section, 1 research-question list, 1 Recruitment table, 1
  Roster collapsed section (with badges when the roster has rows), and 1
  Checklist. ``document_counts(body)`` returns the raw counts.
- ``spec_from_body(body)`` recovers a partial spec from an old ticket body
  (best effort, never raises). A recovered spec has no ``_meta``; the next
  edit must set ``tracker_updated_at``.
- ``parse_roster_shorthand`` / ``parse_list_shorthand`` turn edit shorthand
  (``roster+=Name|email|...``, ``hypotheses+=Label|Text``,
  ``resources+=Label|Url-or-Text|Share-status|Share-note``) into JSON
  deltas the commands apply to the spec.

Config: body format comes from ``tracker.body_format`` (``markdown`` when
unset or empty), checklist links from ``links.*``, the share-legend domain
from ``org.team_share_domain``, and roster statuses from
``recruit.statuses`` with the issue's two default sets as fallback. Pass
``load_config()`` output so organization values apply; with no config the
shipped defaults are used.

Placeholders: an exact match on one of these strings means "not filled".
They render into unfilled slots and ``validate_spec`` rejects specs that
still contain them in required fields.

"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from . import config as _config  # package context: import lib.spec_blocks
except ImportError:  # direct execution: python lib/spec_blocks.py
    import config as _config  # type: ignore

try:
    from .util import utcnow as _utcnow
except ImportError:  # flat: python lib/spec_blocks.py
    from util import utcnow as _utcnow  # type: ignore

ConfigError = _config.ConfigError

# ---------------------------------------------------------------------------
# placeholders (an exact match means "not filled")
# ---------------------------------------------------------------------------

PLACEHOLDERS: dict[str, str] = {
    "history": "What's the history of this work? What led to it? What's the broader context?",
    "decision": "What is the decision this research will inform? Be specific.",
    "hypotheses": "List the hypotheses this research will test, numbered.",
    "assumptions": "List the assumptions you're making today, numbered.",
    "results": (
        "Once research is complete: What decision are you making and why? "
        "Try to keep it to 2-3 sentences max."
    ),
    "resources": (
        "Add links to relevant docs, decks, prior research, customer artifacts. "
        "Use Drive / Confluence / Jira URLs that are at least viewable by the team."
    ),
    "sample_size": "e.g. 8-12 admins, 15-25 PAC tenants",
    "persona": "Which personas, segments, industries",
    "session_length": "e.g. 45-60 min interviews, ~3 question survey",
    "artifact_link": "Link to script / survey / discussion guide once written",
}

#: The template's three research-question slots.
RQ_PLACEHOLDERS: tuple[str, ...] = (
    "Primary research question",
    "Secondary research question",
    "Tertiary research question",
)

#: Every placeholder text, flattened (used to skip placeholder content).
_ALL_PLACEHOLDERS: frozenset[str] = frozenset(PLACEHOLDERS.values()) | frozenset(RQ_PLACEHOLDERS)

# ---------------------------------------------------------------------------
# roster vocabulary
# ---------------------------------------------------------------------------

ROSTER_FIELDS: tuple[str, ...] = (
    "name",
    "email",
    "slack",
    "title",
    "company",
    "industry",
    "arr",
    "reason",
    "work_area",
    "status",
    "channel",
)

DEFAULT_ROSTER_STATUS = "Potential Candidate"
DEFAULT_ROSTER_CHANNEL = "internal"

#: Interview roster statuses (issue 04); config ``recruit.statuses.interview``
#: overrides this set when it has entries.
DEFAULT_INTERVIEW_STATUSES: tuple[str, ...] = (
    "Potential Candidate",
    "Outreach Sent",
    "No Response",
    "Scheduled",
    "Data Collected",
    "No Show",
    "Cancelled",
)

#: Survey roster statuses (issue 04); config ``recruit.statuses.survey``
#: overrides this set when it has entries.
DEFAULT_SURVEY_STATUSES: tuple[str, ...] = (
    "Potential Candidates",
    "Selected for Distribution",
    "Survey Sent",
    "Reminder Sent",
    "No Response",
    "Disqualified (screener)",
    "Qualified (screener)",
    "Data Collected",
)

SHARE_STATUSES: tuple[str, ...] = ("shared", "private", "unknown")

#: Shorthand fields per list kind (``parse_list_shorthand``).
LIST_SHORTHAND_FIELDS: dict[str, tuple[str, ...]] = {
    "hypotheses": ("label", "text"),
    "assumptions": ("label", "text"),
    "resources": ("label", "url_or_text", "share_status", "share_note"),
}

# ---------------------------------------------------------------------------
# badge colors (words per issue 04; config ``recruit.status_colors`` overrides)
# ---------------------------------------------------------------------------

DEFAULT_STATUS_COLORS: dict[str, str] = {
    "Potential Candidate": "neutral",
    "Potential Candidates": "neutral",
    "Selected for Distribution": "purple",
    "Data Collected": "purple",
    "Outreach Sent": "blue",
    "Survey Sent": "blue",
    "Reminder Sent": "blue",
    "No Response": "yellow",
    "Scheduled": "green",
    "Qualified (screener)": "green",
    "No Show": "red",
    "Cancelled": "red",
    "Disqualified (screener)": "red",
}

#: ADF status colors (the badge words are exactly the ADF color names).
STATUS_COLOR_NAMES: tuple[str, ...] = ("neutral", "purple", "blue", "green", "yellow", "red")

#: Emoji dot per badge color, used in Markdown and HTML badge fallbacks.
EMOJI_DOT: dict[str, str] = {
    "neutral": "\u26aa",    # ⚪
    "purple": "\U0001f7e3", # 🟣
    "blue": "\U0001f535",   # 🔵
    "yellow": "\U0001f7e1", # 🟡
    "green": "\U0001f7e2",  # 🟢
    "red": "\U0001f534",    # 🔴
}

# ---------------------------------------------------------------------------
# _meta
# ---------------------------------------------------------------------------

#: Exactly the six ``_meta`` keys a saved spec may carry. The reference
#: plugin called ``tracker_updated_at`` ``jira_updated_at``; the neutral name
#: is canonical here.
META_KEYS: tuple[str, ...] = (
    "created_at",
    "last_edited_at",
    "last_edited_by_command",
    "tracker_updated_at",
    "session_id",
    "transcript_path",
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _scalar(value: Any) -> str:
    """Return a stripped string for spec string values; anything else is ''."""
    return value.strip() if isinstance(value, str) else ""


def _filled(value: Any, placeholder: str) -> str:
    """Return the spec string, or the placeholder when it is empty."""
    text = _scalar(value)
    return text if text else placeholder


def _cfg(config: Any, section: str, key: str, default: Any = "") -> Any:
    """Read ``config[section][key]`` tolerating missing layers."""
    if not isinstance(config, dict):
        return default
    child = config.get(section)
    if not isinstance(child, dict):
        return default
    value = child.get(key, default)
    return default if value is None else value



def status_set(config: dict | None = None) -> frozenset[str]:
    """Every allowed roster status.

    Config ``recruit.statuses.interview`` / ``.survey`` replace their default
    set when they have entries; ``.recruited`` and ``.early`` pools add to the
    set. With no config the two issue-04 default sets apply.
    """
    statuses = _cfg(config, "recruit", "statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}
    valid: set[str] = set()
    for group, defaults in (
        ("interview", DEFAULT_INTERVIEW_STATUSES),
        ("survey", DEFAULT_SURVEY_STATUSES),
    ):
        configured = [str(v).strip() for v in (statuses.get(group) or []) if str(v).strip()]
        valid.update(configured if configured else defaults)
    for group in ("recruited", "early"):
        valid.update(str(v).strip() for v in (statuses.get(group) or []) if str(v).strip())
    return frozenset(valid)


def status_color(status: str, config: dict | None = None) -> str:
    """Badge color word for a roster status; unknown statuses stay neutral."""
    overrides = _cfg(config, "recruit", "status_colors", {})
    if isinstance(overrides, dict) and status in overrides and str(overrides[status]).strip():
        return str(overrides[status]).strip()
    return DEFAULT_STATUS_COLORS.get(status, "neutral")


def spec_path(key: str, config: dict | None = None) -> Path:
    """Canonical spec file location: ``<state_dir>/specs/<KEY>.spec.json``."""
    if config is None:
        config = _config.load_config()
    state_dir = Path(str(_cfg(config, "paths", "state_dir", "state")))
    return state_dir / "specs" / f"{key}.spec.json"


def make_meta(
    last_edited_by_command: str,
    *,
    created_at: str | None = None,
    last_edited_at: str | None = None,
    tracker_updated_at: str | None = None,
    session_id: str | None = None,
    transcript_path: str | None = None,
) -> dict:
    """Build a ``_meta`` object with exactly the six canonical keys.

    ``session_id`` defaults to ``$CLAUDE_SESSION_ID``; timestamps default to
    now (ISO 8601 UTC). ``tracker_updated_at`` starts unset -- it is filled
    after the tracker write is read back.
    """
    now = _utcnow()
    return {
        "created_at": created_at or now,
        "last_edited_at": last_edited_at or now,
        "last_edited_by_command": last_edited_by_command,
        "tracker_updated_at": tracker_updated_at,
        "session_id": session_id if session_id is not None else os.environ.get("CLAUDE_SESSION_ID"),
        "transcript_path": transcript_path,
    }


# ---------------------------------------------------------------------------
# validate_spec (hard rules only; hypothesis quality is model judgment)
# ---------------------------------------------------------------------------

_LOCAL_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|[.]{1,2}[\\/]|~(?:/|\\|$)|file://)")


def _looks_local(value: str) -> bool:
    """True for strings that look like a local file path (never a valid resource)."""
    text = value.strip()
    if not text:
        return False
    if "\\" in text:
        return True
    return bool(_LOCAL_PATH_RE.match(text))


def validate_spec(spec: Any, config: dict | None = None) -> tuple[bool, list[str]]:
    """Check the hard spec rules; return ``(ok, errors)`` and never raise.

    Rules: the spec is a dict; ``history`` and ``decision`` are not both
    empty and neither equals its placeholder; ``hypotheses`` is a non-empty
    list of ``{label, text}`` with neither part empty nor the placeholder;
    ``research_questions`` is a non-empty list of non-empty strings with no
    placeholder; no ``assumptions[i].text`` equals the placeholder; roster
    rows are dicts with a ``name``, a known ``status`` (default
    ``Potential Candidate``), and a ``channel`` of internal or external
    (default ``internal``); resources are dicts where a ``url`` requires a
    ``share_status`` of shared, private, or unknown, and a local file path
    is never valid; and a spec whose ``_meta.last_edited_by_command`` is
    ``new`` (issue 60) carries a non-empty verbatim ``ask_verbatim`` whose
    ``ask_uplevels`` entries never byte-equal it. A retro save records an
    unrecovered ask instead of blocking, so the rule never fires on it.
    """
    try:
        return _validate_spec(spec, config)
    except Exception as exc:  # rule 8: malformed input never crashes the gate
        return False, [f"validate_spec crashed on malformed input: {exc}"]


def _validate_spec(spec: Any, config: dict | None) -> tuple[bool, list[str]]:
    if not isinstance(spec, dict):
        return False, ["spec is not a JSON object"]
    errors: list[str] = []
    add = errors.append

    history = _scalar(spec.get("history"))
    decision = _scalar(spec.get("decision"))
    if not history and not decision:
        add("history and decision are both empty; fill at least one")
    if history and history == PLACEHOLDERS["history"]:
        add("history is still the placeholder text")
    if decision and decision == PLACEHOLDERS["decision"]:
        add("decision is still the placeholder text")

    hypotheses = spec.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        add("hypotheses must be a non-empty list of {label, text} objects")
    else:
        for index, item in enumerate(hypotheses):
            if not isinstance(item, dict):
                add(f"hypotheses[{index}] is not an object")
                continue
            label = _scalar(item.get("label"))
            text = _scalar(item.get("text"))
            if not label:
                add(f"hypotheses[{index}].label is empty")
            if not text:
                add(f"hypotheses[{index}].text is empty")
            elif text == PLACEHOLDERS["hypotheses"]:
                add(f"hypotheses[{index}].text is still the placeholder text")

    questions = spec.get("research_questions")
    if not isinstance(questions, list) or not questions:
        add("research_questions must be a non-empty list of strings")
    else:
        for index, question in enumerate(questions):
            if not isinstance(question, str) or not question.strip():
                add(f"research_questions[{index}] is not a non-empty string")
            elif question.strip() in RQ_PLACEHOLDERS:
                add(f"research_questions[{index}] is still the placeholder text")

    assumptions = spec.get("assumptions") or []
    if not isinstance(assumptions, list):
        add("assumptions must be a list when present")
    else:
        for index, item in enumerate(assumptions):
            if not isinstance(item, dict):
                add(f"assumptions[{index}] is not an object")
                continue
            if _scalar(item.get("text")) == PLACEHOLDERS["assumptions"]:
                add(f"assumptions[{index}].text is still the placeholder text")

    roster = spec.get("roster") or []
    if not isinstance(roster, list):
        add("roster must be a list when present")
    else:
        allowed = status_set(config)
        for index, row in enumerate(roster):
            if not isinstance(row, dict):
                add(f"roster[{index}] is not an object")
                continue
            if not _scalar(row.get("name")):
                add(f"roster[{index}].name is required")
            status = _scalar(row.get("status")) or DEFAULT_ROSTER_STATUS
            if status not in allowed:
                add(f"roster[{index}].status {status!r} is not an allowed roster status")
            channel = _scalar(row.get("channel")) or DEFAULT_ROSTER_CHANNEL
            if channel not in ("internal", "external"):
                add(f"roster[{index}].channel {channel!r} must be 'internal' or 'external'")

    resources = spec.get("resources") or []
    if not isinstance(resources, list):
        add("resources must be a list when present")
    else:
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                add(f"resources[{index}] is not an object")
                continue
            url = _scalar(resource.get("url"))
            text = _scalar(resource.get("text"))
            share = _scalar(resource.get("share_status"))
            if url and not share:
                add(
                    f"resources[{index}] ({url}) has a url without share_status "
                    "(shared | private | unknown)"
                )
            if share and share not in SHARE_STATUSES:
                add(f"resources[{index}].share_status {share!r} must be shared, private, or unknown")
            for field_name, value in (("url", url), ("text", text)):
                if value and _looks_local(value):
                    add(
                        f"resources[{index}].{field_name} looks like a local file path; "
                        "put the file in Drive (or the tracker) and link it instead"
                    )

    # Issue 60: the original ask is stored verbatim. The rule fires ONLY on a
    # spec saved by the `new` build block (a retro save records the gap
    # instead); fixture specs carry no _meta and never reach it.
    meta = spec.get("_meta")
    if isinstance(meta, dict) and meta.get("last_edited_by_command") == "new":
        ask = spec.get("ask_verbatim")
        if not isinstance(ask, str) or not ask.strip():
            add("ask_verbatim is empty (the original ask must be stored verbatim)")
        uplevels = spec.get("ask_uplevels")
        if isinstance(uplevels, list):
            for index, uplevel in enumerate(uplevels):
                # The str guard keeps an entry with no ``text`` key from
                # firing the replacement error on top of the empty-ask
                # error (issue 133: one misleading second error line).
                if (
                    isinstance(uplevel, dict)
                    and isinstance(uplevel.get("text"), str)
                    and uplevel.get("text") == ask
                ):
                    add("ask_uplevel must not replace the original ask")

    return (not errors), errors


# ---------------------------------------------------------------------------
# internal document model
#
# Inline runs: {"t": "text"|"link"|"badge"|"emoji", ...}
# Blocks: panel, heading, para, table, expand, bullets, numbers, tasks.
# Cells are {"blocks": [...]} so a table cell can hold paragraphs and lists.
# ---------------------------------------------------------------------------


def _run_text(text: str, bold: bool = False, italic: bool = False) -> dict:
    return {"t": "text", "text": text, "bold": bold, "italic": italic}


def _run_link(text: str, href: str) -> dict:
    return {"t": "link", "text": text, "href": href}


def _run_badge(status: str, config: dict | None) -> dict:
    return {"t": "badge", "text": status, "color": status_color(status, config)}


def _run_emoji(char: str, short: str) -> dict:
    return {"t": "emoji", "text": char, "short": short}


def _para(*runs: dict) -> dict:
    return {"t": "para", "runs": list(runs)}


_EMOJI_CLIPBOARD = ("\U0001f4cb", ":clipboard:")
_EMOJI_CHECK = ("\u2705", ":white_check_mark:")
_EMOJI_QUESTION = ("\u2753", ":question:")
_EMOJI_TEAM = ("\U0001f9d1\u200d\U0001f91d\u200d\U0001f9d1", ":people_holding_hands:")

_EXPAND_RESOURCES = "\U0001f4e6 Resources"        # 📦 Resources
_EXPAND_ROSTER = "\U0001f465 Recruitment Roster"  # 👥 Recruitment Roster
_EXPAND_CHECKLIST = "\u270f\ufe0f Checklist"      # ✏️ Checklist

_TABLE_WIDTHS = (160, 600)

#: Checklist item text with the config link slot each item may carry:
#: (text, linked phrase, config key). No link renders when the key is empty.
CHECKLIST_ITEMS: tuple[tuple[str, str, str], ...] = (
    (
        "Scope and prioritize: set UXR Support Level and Assignee with the prioritization calculator.",
        "prioritization calculator",
        "calculator",
    ),
    (
        "Draft the study: write Research Questions, Recruitment Strategy, and the script or survey using the templates folder.",
        "templates folder",
        "templates",
    ),
    (
        "Review and recruit: get it reviewed, then recruit and collect data.",
        "",
        "",
    ),
    (
        "Synthesize and report: summarize, write the report, fill Results, move to Done.",
        "",
        "",
    ),
    (
        "Manage this ticket with the plugin commands.",
        "plugin commands",
        "plugin_repo",
    ),
)


def _checklist_task_runs(config: dict | None) -> list[dict]:
    """The five checklist task items, each as a run list."""
    items: list[dict] = []
    for text, linked_phrase, link_key in CHECKLIST_ITEMS:
        runs: list[dict] = []
        if linked_phrase:
            head, sep, _tail = text.rpartition(linked_phrase)
            link_href = str(_cfg(config, "links", link_key, "") or "")
            if sep and link_href:
                runs.append(_run_text(head))
                runs.append(_run_link(sep, link_href))
                runs.append(_run_text("."))
                items.append(runs)
                continue
        runs.append(_run_text(text))
        items.append(runs)
    return items


def _hypothesis_cell_blocks(spec: dict, config: dict | None) -> list[dict]:
    """The Assumptions & Hypotheses cell: bold labels, numbered lists."""
    hypotheses = [h for h in (spec.get("hypotheses") or []) if isinstance(h, dict)]
    assumptions = [a for a in (spec.get("assumptions") or []) if isinstance(a, dict)]

    def numbereds(entries: list[dict], placeholder: str) -> dict:
        if entries:
            items = [
                [
                    _run_text(f"{_scalar(entry.get('label'))}. ", bold=True),
                    _run_text(_scalar(entry.get("text"))),
                ]
                for entry in entries
            ]
        else:
            items = [[_run_text(placeholder)]]
        return {"t": "numbers", "items": items}

    return [
        _para(_run_text("Hypotheses", bold=True)),
        numbereds(hypotheses, PLACEHOLDERS["hypotheses"]),
        _para(_run_text("Assumptions", bold=True)),
        numbereds(assumptions, PLACEHOLDERS["assumptions"]),
    ]


def _resource_bullets(spec: dict, config: dict | None) -> list[dict]:
    """Resources bullets: ``[<lock> ]<label>: <url | text | (no link)>[ (note)]``."""
    resources = [r for r in (spec.get("resources") or []) if isinstance(r, dict)]
    if not resources:
        return [[_run_text(PLACEHOLDERS["resources"])]]
    domain = str(_cfg(config, "org", "team_share_domain", "") or "").strip() or "team"
    items: list[dict] = []
    has_private = False
    for resource in resources:
        label = _scalar(resource.get("label"))
        url = _scalar(resource.get("url"))
        text = _scalar(resource.get("text"))
        share = _scalar(resource.get("share_status"))
        note = _scalar(resource.get("share_note"))
        runs: list[dict] = []
        if url:
            if share != "shared":
                runs.append(_run_text("\U0001f512 "))  # 🔒 not (yet) shared
            if share == "private":
                has_private = True
            runs.append(_run_text(f"{label}: "))
            runs.append(_run_link(url, url))
        else:
            runs.append(_run_text(f"{label}: "))
            runs.append(_run_text(text if text else "(no link)"))
        if note:
            runs.append(_run_text(f" ({note})"))
        items.append(runs)
    if has_private:
        items.append(
            [
                _run_text(
                    "\U0001f512 = link is not yet shared with the team. Open the file in Drive, "
                    f"click Share, set the {domain} domain to Commenter (or higher) so "
                    "teammates can view."
                )
            ]
        )
    return items


def _roster_table(spec: dict, config: dict | None) -> dict:
    """The Recruitment Roster table with a badge in every Status cell."""
    header = ["Name", "Title", "Company", "Industry", "ARR", "Contact", "Status", "Reason"]
    rows = [[{"blocks": [_para(_run_text(cell))]} for cell in header]]
    roster = [r for r in (spec.get("roster") or []) if isinstance(r, dict)]
    for entry in roster:
        email = _scalar(entry.get("email"))
        slack = _scalar(entry.get("slack"))
        contact = " \u00b7 ".join(part for part in (email, slack) if part)
        status = _scalar(entry.get("status")) or DEFAULT_ROSTER_STATUS
        # Reason and Focus live in separate paragraphs so each format can put
        # the focus line on its own row inside the cell.
        reason_blocks: list[dict] = []
        if _scalar(entry.get("reason")):
            reason_blocks.append(_para(_run_text(_scalar(entry.get("reason")))))
        if _scalar(entry.get("work_area")):
            reason_blocks.append(
                _para(_run_text("Focus: ", bold=True), _run_text(_scalar(entry.get("work_area"))))
            )
        if not reason_blocks:
            reason_blocks.append(_para(_run_text("")))
        cells = [
            {"blocks": [_para(_run_text(_scalar(entry.get("name"))))]},
            {"blocks": [_para(_run_text(_scalar(entry.get("title"))))]},
            {"blocks": [_para(_run_text(_scalar(entry.get("company"))))]},
            {"blocks": [_para(_run_text(_scalar(entry.get("industry"))))]},
            {"blocks": [_para(_run_text(_scalar(entry.get("arr"))))]},
            {"blocks": [_para(_run_text(contact))]},
            {"blocks": [_para(_run_badge(status, config))]},
            {"blocks": reason_blocks},
        ]
        rows.append(cells)
    if len(rows) == 1:  # empty roster: header plus one blank row
        rows.append([{"blocks": [_para(_run_text(""))]} for _ in header])
    return {"t": "table", "rows": rows, "colwidths": None, "header_row": True}


def _document_blocks(spec: dict, config: dict | None) -> list[dict]:
    """The ten template blocks, in the fixed order from issue 04."""
    questions = [
        _scalar(q)
        for q in (spec.get("research_questions") or [])
        if isinstance(q, str) and _scalar(q)
    ]
    if len(questions) < 3:  # the template always shows at least three slots
        questions = questions + list(RQ_PLACEHOLDERS[len(questions):])

    artifact = _scalar(spec.get("artifact_link"))
    artifact_runs: list[dict] = [_run_link(artifact, artifact)] if artifact else [
        _run_text(PLACEHOLDERS["artifact_link"])
    ]

    info_runs = [
        _run_text("Directions: ", bold=True),
        _run_text("Complete the Background & Context sections and relevant data fields "),
        _run_text("BEFORE", bold=True),
        _run_text(" talking with your UX Researcher. Follow the checklist below for more details."),
    ]

    return [
        # 1. info panel
        {"t": "panel", "kind": "info", "blocks": [_para(*info_runs)]},
        # 2. success panel
        {
            "t": "panel",
            "kind": "success",
            "blocks": [
                {
                    "t": "heading",
                    "level": 2,
                    "runs": [_run_emoji(*_EMOJI_CHECK), _run_text(" Results")],
                },
                _para(_run_text(_filled(spec.get("results"), PLACEHOLDERS["results"]))),
            ],
        },
        # 3. background H1
        {
            "t": "heading",
            "level": 1,
            "runs": [_run_emoji(*_EMOJI_CLIPBOARD), _run_text(" Background & Context")],
        },
        # 4. background table (narrow label column, wide content column)
        {
            "t": "table",
            "colwidths": list(_TABLE_WIDTHS),
            "rows": [
                [
                    {"blocks": [_para(_run_text("\u23f1\ufe0f History"))]},
                    {"blocks": [_para(_run_text(_filled(spec.get("history"), PLACEHOLDERS["history"])))]},
                ],
                [
                    {"blocks": [_para(_run_text("\U0001f3af Key Decision"))]},
                    {"blocks": [_para(_run_text(_filled(spec.get("decision"), PLACEHOLDERS["decision"])))]},
                ],
                [
                    {"blocks": [_para(_run_text("\u2757 Assumptions & Hypotheses"))]},
                    {"blocks": _hypothesis_cell_blocks(spec, config)},
                ],
            ],
        },
        # 5. resources collapsed section
        {"t": "expand", "title": _EXPAND_RESOURCES, "blocks": [{"t": "bullets", "items": _resource_bullets(spec, config)}]},
        # 6. research questions H1 + numbered list
        {
            "t": "heading",
            "level": 1,
            "runs": [_run_emoji(*_EMOJI_QUESTION), _run_text(" Research Questions")],
        },
        {"t": "numbers", "items": [[_run_text(q)] for q in questions]},
        # 7. recruitment strategy H1
        {
            "t": "heading",
            "level": 1,
            "runs": [_run_emoji(*_EMOJI_TEAM), _run_text(" Recruitment Strategy")],
        },
        # 8. recruitment table
        {
            "t": "table",
            "colwidths": None,
            "rows": [
                [
                    {"blocks": [_para(_run_text("Target Sample Size"))]},
                    {"blocks": [_para(_run_text(_filled(spec.get("sample_size"), PLACEHOLDERS["sample_size"])))]},
                ],
                [
                    {"blocks": [_para(_run_text("Persona / Customer"))]},
                    {"blocks": [_para(_run_text(_filled(spec.get("persona"), PLACEHOLDERS["persona"])))]},
                ],
                [
                    {"blocks": [_para(_run_text("Length of Session / Survey"))]},
                    {"blocks": [_para(_run_text(_filled(spec.get("session_length"), PLACEHOLDERS["session_length"])))]},
                ],
                [
                    {"blocks": [_para(_run_text("Link to Artifact(s)"))]},
                    {"blocks": [_para(*artifact_runs)]},
                ],
            ],
        },
        # 9. roster collapsed section
        {"t": "expand", "title": _EXPAND_ROSTER, "blocks": [_roster_table(spec, config)]},
        # 10. checklist collapsed section
        {
            "t": "expand",
            "title": _EXPAND_CHECKLIST,
            "blocks": [{"t": "tasks", "items": _checklist_task_runs(config)}],
        },
    ]


# ---------------------------------------------------------------------------
# Markdown renderer (GitHub, Linear)
# ---------------------------------------------------------------------------

_EMOJI_DOTS_ALL = tuple(EMOJI_DOT.values())


def _md_inline(runs: list[dict], cell: bool = False) -> str:
    """Render inline runs as Markdown; ``cell`` adds pipe escaping."""
    parts: list[str] = []
    for run in runs:
        kind = run.get("t")
        if kind == "text":
            text = run.get("text", "")
            if cell:
                text = text.replace("|", "\\|")
            text = text.replace("\n", "<br>" if cell else " ")
            if run.get("bold"):
                core = text.rstrip()
                trail = text[len(core):]
                text = f"**{core}**{trail}" if core else trail
            if run.get("italic"):
                core = text.rstrip()
                trail = text[len(core):]
                text = f"*{core}*{trail}" if core else trail
            parts.append(text)
        elif kind == "link":
            label = run.get("text", "").replace("|", "\\|") if cell else run.get("text", "")
            href = run.get("href", "")
            if label == href:  # a bare URL autolinks; no need for [url](url)
                parts.append(href)
            else:
                parts.append(f"[{label}]({href})")
        elif kind == "badge":
            dot = EMOJI_DOT.get(run.get("color", "neutral"), EMOJI_DOT["neutral"])
            label = run.get("text", "").replace("|", "\\|") if cell else run.get("text", "")
            parts.append(f"{dot} **{label}**")
        elif kind == "emoji":
            parts.append(run.get("text", ""))
    return "".join(parts)


def _md_cell(cell: dict) -> str:
    """Render one table cell; multi-block cells join with ``<br>``."""
    lines: list[str] = []
    for block in cell.get("blocks", []):
        kind = block.get("t")
        if kind == "para":
            lines.append(_md_inline(block.get("runs", []), cell=True))
        elif kind == "numbers":
            for index, item in enumerate(block.get("items", []), start=1):
                lines.append(f"{index}. {_md_inline(item, cell=True)}")
        else:
            lines.append("")
    return "<br>".join(line for line in lines if line != "") or " "


def _md_table(block: dict) -> str:
    rows = block.get("rows", [])
    width = max((len(row) for row in rows), default=1)
    lines: list[str] = []
    if block.get("header_row"):
        # The roster table's first row is the real header; render it as one.
        header_cells = [_md_cell(cell) for cell in rows[0]]
        header_cells += [" "] * (width - len(header_cells))
        lines.append("| " + " | ".join(header_cells) + " |")
        data_rows = rows[1:]
    else:
        lines.append("| " + " | ".join([""] * width) + " |")
        data_rows = rows
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in data_rows:
        cells = [_md_cell(cell) for cell in row]
        cells += [" "] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _md_blockquote(block_lines: list[str]) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in block_lines)


def _render_markdown(blocks: list[dict]) -> str:
    """Render the block list as the Markdown body (no trailing newline)."""
    out: list[str] = []
    for block in blocks:
        kind = block.get("t")
        if kind == "panel":
            child_lines: list[list[str]] = []
            for child in block.get("blocks", []):
                if child.get("t") == "para":
                    child_lines.append(_md_inline(child.get("runs", [])).split("\n"))
                elif child.get("t") == "heading":
                    child_lines.append(
                        ["#" * child.get("level", 1) + " " + _md_inline(child.get("runs", []))]
                    )
            inner: list[str] = []
            for index, lines_of_child in enumerate(child_lines):
                if index:
                    inner.append("")
                inner.extend(lines_of_child)
            out.append(_md_blockquote(inner))
        elif kind == "heading":
            out.append("#" * block.get("level", 1) + " " + _md_inline(block.get("runs", [])))
        elif kind == "para":
            out.append(_md_inline(block.get("runs", [])))
        elif kind == "table":
            out.append(_md_table(block))
        elif kind == "expand":
            body: list[str] = []
            for child in block.get("blocks", []):
                child_kind = child.get("t")
                if child_kind == "table":
                    body.append(_md_table(child))
                elif child_kind == "bullets":
                    body.extend(f"- {_md_inline(item)}" for item in child.get("items", []))
                elif child_kind == "numbers":
                    body.extend(
                        f"{index}. {_md_inline(item)}"
                        for index, item in enumerate(child.get("items", []), start=1)
                    )
                elif child_kind == "tasks":
                    body.extend(f"- [ ] {_md_inline(item)}" for item in child.get("items", []))
            out.append(
                "<details>\n<summary>"
                + block.get("title", "")
                + "</summary>\n\n"
                + "\n".join(body)
                + "\n\n</details>"
            )
        elif kind == "bullets":
            out.append("\n".join(f"- {_md_inline(item)}" for item in block.get("items", [])))
        elif kind == "numbers":
            out.append(
                "\n".join(
                    f"{index}. {_md_inline(item)}"
                    for index, item in enumerate(block.get("items", []), start=1)
                )
            )
        elif kind == "tasks":
            out.append("\n".join(f"- [ ] {_md_inline(item)}" for item in block.get("items", [])))
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# ADF renderer (Jira)
# ---------------------------------------------------------------------------


def _adf_marks(run: dict) -> list[dict]:
    marks: list[dict] = []
    if run.get("bold"):
        marks.append({"type": "strong"})
    if run.get("italic"):
        marks.append({"type": "em"})
    return marks


def _adf_runs(runs: list[dict]) -> list[dict]:
    nodes: list[dict] = []
    for run in runs:
        kind = run.get("t")
        if kind == "text":
            text = run.get("text", "")
            if not text:
                continue
            node: dict = {"type": "text", "text": text}
            marks = _adf_marks(run)
            if marks:
                node["marks"] = marks
            nodes.append(node)
        elif kind == "link":
            marks = [{"type": "link", "attrs": {"href": run.get("href", "")}}]
            nodes.append({"type": "text", "text": run.get("text", ""), "marks": marks})
        elif kind == "badge":
            nodes.append(
                {
                    "type": "status",
                    "attrs": {"text": run.get("text", ""), "color": run.get("color", "neutral")},
                }
            )
        elif kind == "emoji":
            nodes.append(
                {
                    "type": "emoji",
                    "attrs": {"shortName": run.get("short", ""), "text": run.get("text", "")},
                }
            )
    return nodes


def _adf_cell_blocks(blocks: list[dict]) -> list[dict]:
    nodes: list[dict] = []
    for block in blocks:
        kind = block.get("t")
        if kind == "para":
            runs = _adf_runs(block.get("runs", []))
            node = {"type": "paragraph"}
            if runs:
                node["content"] = runs
            nodes.append(node)
        elif kind in ("bullets", "numbers", "tasks"):
            nodes.append(_adf_list(block))
    return nodes


def _adf_list(block: dict) -> dict:
    kind = block.get("t")
    if kind == "tasks":
        items: list[dict] = []
        for runs in block.get("items", []):
            paragraph: dict = {"type": "paragraph"}
            content = _adf_runs(runs)
            if content:
                paragraph["content"] = content
            # The state value below is the Atlassian Document Format taskItem
            # state literal (the other legal value is "DONE"), not unfinished work.
            # verify-allow: stub-marker
            items.append({"type": "taskItem", "attrs": {"state": "TODO"}, "content": [paragraph]})
        return {"type": "taskList", "content": items}
    items = [
        {"type": "listItem", "content": [{"type": "paragraph", "content": _adf_runs(runs)}]}
        for runs in block.get("items", [])
    ]
    if kind == "numbers":
        return {"type": "orderedList", "attrs": {"order": 1}, "content": items}
    return {"type": "bulletList", "content": items}


def _adf_table(block: dict) -> dict:
    colwidths = block.get("colwidths")
    header_row = bool(block.get("header_row"))
    rows: list[dict] = []
    for index, row in enumerate(block.get("rows", [])):
        is_header = header_row and index == 0
        cells: list[dict] = []
        for cell_index, cell in enumerate(row):
            attrs: dict = {}
            if colwidths and cell_index < len(colwidths):
                attrs["colwidth"] = colwidths[cell_index]
            cells.append(
                {
                    "type": "tableHeader" if is_header else "tableCell",
                    "attrs": attrs,
                    "content": _adf_cell_blocks(cell.get("blocks", [])),
                }
            )
        rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "attrs": {"layout": "default"}, "content": rows}


def _render_adf(blocks: list[dict]) -> dict:
    """Render the block list as an ADF document (Atlassian Document Format 1)."""
    content: list[dict] = []
    for block in blocks:
        kind = block.get("t")
        if kind == "panel":
            content.append(
                {
                    "type": "panel",
                    "attrs": {"panelType": block.get("kind", "info")},
                    "content": _adf_cell_blocks(block.get("blocks", [])),
                }
            )
        elif kind == "heading":
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": block.get("level", 1)},
                    "content": _adf_runs(block.get("runs", [])),
                }
            )
        elif kind == "para":
            node = {"type": "paragraph"}
            runs = _adf_runs(block.get("runs", []))
            if runs:
                node["content"] = runs
            content.append(node)
        elif kind == "table":
            content.append(_adf_table(block))
        elif kind == "expand":
            inner: list[dict] = []
            for child in block.get("blocks", []):
                if child.get("t") == "table":
                    inner.append(_adf_table(child))
                elif child.get("t") in ("bullets", "numbers", "tasks"):
                    inner.append(_adf_list(child))
            content.append(
                {
                    "type": "expand",
                    "attrs": {"title": block.get("title", "")},
                    "content": inner,
                }
            )
        elif kind in ("bullets", "numbers", "tasks"):
            content.append(_adf_list(block))
    return {"type": "doc", "version": 1, "content": content}


# ---------------------------------------------------------------------------
# HTML renderer (Asana)
# ---------------------------------------------------------------------------


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html_attr(text: str) -> str:
    return _html_escape(text).replace('"', "&quot;")


def _html_inline(runs: list[dict]) -> str:
    parts: list[str] = []
    for run in runs:
        kind = run.get("t")
        if kind == "text":
            text = _html_escape(run.get("text", ""))
            if run.get("bold"):
                core = text.rstrip()
                trail = text[len(core):]
                text = f"<strong>{core}</strong>{trail}" if core else trail
            if run.get("italic"):
                core = text.rstrip()
                trail = text[len(core):]
                text = f"<em>{core}</em>{trail}" if core else trail
            parts.append(text)
        elif kind == "link":
            parts.append(
                f'<a href="{_html_attr(run.get("href", ""))}">{_html_escape(run.get("text", ""))}</a>'
            )
        elif kind == "badge":
            dot = EMOJI_DOT.get(run.get("color", "neutral"), EMOJI_DOT["neutral"])
            parts.append(f"<strong>{dot} {_html_escape(run.get('text', ''))}</strong>")
        elif kind == "emoji":
            parts.append(_html_escape(run.get("text", "")))
    return "".join(parts)


def _html_cell(cell: dict) -> str:
    """Render one table cell; paragraphs join with ``<br>``, lists nest."""
    parts: list[str] = []
    for block in cell.get("blocks", []):
        kind = block.get("t")
        if kind == "para":
            parts.append(_html_inline(block.get("runs", [])))
        elif kind == "numbers":
            items = "".join(f"<li>{_html_inline(item)}</li>" for item in block.get("items", []))
            parts.append(f"<ol>{items}</ol>")
    return "<br>".join(part for part in parts if part)


def _html_table(block: dict) -> str:
    rows = block.get("rows", [])
    body = []
    for row in rows:
        cells = "".join(f"<td>{_html_cell(cell)}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return "<table>\n" + "\n".join(body) + "\n</table>"


def _render_html(blocks: list[dict]) -> str:
    """Render the block list as Asana-style HTML (collapsed sections are H2s)."""
    out: list[str] = []
    for block in blocks:
        kind = block.get("t")
        if kind == "panel":
            inner = []
            for child in block.get("blocks", []):
                if child.get("t") == "para":
                    inner.append(f"<p>{_html_inline(child.get('runs', []))}</p>")
                elif child.get("t") == "heading":
                    level = child.get("level", 1)
                    inner.append(
                        f"<h{level}>{_html_inline(child.get('runs', []))}</h{level}>"
                    )
            out.append("<blockquote>\n" + "\n".join(inner) + "\n</blockquote>")
        elif kind == "heading":
            level = block.get("level", 1)
            out.append(f"<h{level}>{_html_inline(block.get('runs', []))}</h{level}>")
        elif kind == "para":
            out.append(f"<p>{_html_inline(block.get('runs', []))}</p>")
        elif kind == "table":
            out.append(_html_table(block))
        elif kind == "expand":
            inner = []
            for child in block.get("blocks", []):
                child_kind = child.get("t")
                if child_kind == "table":
                    inner.append(_html_table(child))
                elif child_kind == "bullets":
                    items = "".join(f"<li>{_html_inline(item)}</li>" for item in child.get("items", []))
                    inner.append(f"<ul>\n{items}\n</ul>")
                elif child_kind == "numbers":
                    items = "".join(f"<li>{_html_inline(item)}</li>" for item in child.get("items", []))
                    inner.append(f"<ol>{items}</ol>")
                elif child_kind == "tasks":
                    items = "".join(f"<li>{_html_inline(item)}</li>" for item in child.get("items", []))
                    inner.append(f"<ul>\n{items}\n</ul>")
            out.append(f"<h2>{_html_escape(block.get('title', ''))}</h2>\n" + "\n".join(inner))
        elif kind == "bullets":
            items = "".join(f"<li>{_html_inline(item)}</li>" for item in block.get("items", []))
            out.append(f"<ul>\n{items}\n</ul>")
        elif kind == "numbers":
            items = "".join(f"<li>{_html_inline(item)}</li>" for item in block.get("items", []))
            out.append(f"<ol>{items}</ol>")
        elif kind == "tasks":
            items = "".join(f"<li>{_html_inline(item)}</li>" for item in block.get("items", []))
            out.append(f"<ul>\n{items}\n</ul>")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# public render entry point
# ---------------------------------------------------------------------------


def _resolve_format(config: dict | None, body_format: str | None) -> str:
    fmt = str(body_format or "").strip()
    if not fmt:
        fmt = str(_cfg(config, "tracker", "body_format", "") or "").strip()
    if not fmt:
        fmt = "markdown"
    if fmt not in ("adf", "markdown", "html"):
        raise ValueError(f"body format {fmt!r} is not one of adf, markdown, html")
    return fmt


def build_document(
    spec: Any,
    config: dict | None = None,
    body_format: str | None = None,
) -> dict | str:
    """Render a spec into the tracker body in the configured format.

    Returns a str for ``markdown`` and ``html`` and an ADF document dict for
    ``adf``. Deterministic: the same spec and config always render to a
    byte-identical body. ``body_format`` overrides ``tracker.body_format``;
    when both are unset the body renders as Markdown. Never mutates ``spec``.
    """
    if config is None:
        try:
            config = _config.load_config()
        except ConfigError:
            config = {}
    fmt = _resolve_format(config, body_format)
    source = spec if isinstance(spec, dict) else {}
    blocks = _document_blocks(source, config)
    if fmt == "adf":
        return _render_adf(blocks)
    if fmt == "html":
        return _render_html(blocks)
    return _render_markdown(blocks)


# ---------------------------------------------------------------------------
# document counts / completeness
# ---------------------------------------------------------------------------


def _walk(node: Any) -> list[dict]:
    """Every node of an ADF document, depth-first."""
    nodes: list[dict] = []
    if isinstance(node, dict):
        nodes.append(node)
        for child in node.get("content", []) or []:
            nodes.extend(_walk(child))
    elif isinstance(node, list):
        for child in node:
            nodes.extend(_walk(child))
    return nodes


def _adf_text(node: Any) -> str:
    """Concatenated text of an ADF subtree (status nodes contribute their text)."""
    parts: list[str] = []
    for inner in _walk(node):
        if inner.get("type") == "text":
            parts.append(str(inner.get("text", "")))
        elif inner.get("type") == "status":
            attrs = inner.get("attrs") or {}
            parts.append(str(attrs.get("text", "")))
        elif inner.get("type") == "emoji":
            attrs = inner.get("attrs") or {}
            parts.append(str(attrs.get("text", "")))
    return "".join(parts)


def _adf_top_level(doc: dict, node_type: str) -> list[dict]:
    content = doc.get("content") or []
    return [child for child in content if isinstance(child, dict) and child.get("type") == node_type]


def _adf_table_kind(table: dict) -> str:
    """Classify an ADF table: background, roster, recruitment, or other.

    Classification reads the concatenated text of the first row: the
    background table starts with the History label, the roster table with its
    ``Name`` header, the recruitment table with ``Target Sample Size``.
    """
    rows = table.get("content") or []
    if not rows:
        return "other"
    first_row_text = _adf_text(rows[0]).strip()
    if first_row_text.startswith("\u23f1\ufe0f History"):
        return "background"
    if first_row_text.startswith("Target Sample Size"):
        return "recruitment"
    if first_row_text.startswith("Name"):
        return "roster"
    return "other"


def _adf_roster_rows(table: dict) -> list[str]:
    """Names of the roster table's data rows (header excluded)."""
    rows = table.get("content") or []
    names: list[str] = []
    for row in rows[1:]:
        cells = row.get("content") or []
        if not cells:
            continue
        names.append(_adf_text(cells[0]).strip())
    return names


def _counts_from_adf(doc: dict) -> dict:
    nodes = _walk(doc.get("content") or [])
    tables = [n for n in nodes if n.get("type") == "table"]
    roster_table = next((t for t in tables if _adf_table_kind(t) == "roster"), None)
    roster_names = [name for name in (_adf_roster_rows(roster_table) if roster_table else []) if name]
    expands = [n for n in nodes if n.get("type") == "expand"]
    expand_titles = [str((n.get("attrs") or {}).get("title", "")) for n in expands]
    task_items = [n for n in nodes if n.get("type") == "taskItem"]
    status_nodes = [n for n in nodes if n.get("type") == "status"]
    return {
        "panels": sum(1 for n in nodes if n.get("type") == "panel"),
        "background_tables": sum(1 for t in tables if _adf_table_kind(t) == "background"),
        "recruitment_tables": sum(1 for t in tables if _adf_table_kind(t) == "recruitment"),
        "resources_sections": expand_titles.count(_EXPAND_RESOURCES),
        "roster_sections": expand_titles.count(_EXPAND_ROSTER),
        "checklists": expand_titles.count(_EXPAND_CHECKLIST),
        "rq_lists": len(_adf_top_level(doc, "orderedList")),
        "task_items": len(task_items),
        "status_nodes": len(status_nodes),
        "roster_rows": len(roster_names),
    }


_MD_NUMBERED_RE = re.compile(r"^(\d+)\.\s")
_MD_TABLE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_MD_DELIMITER_RE = re.compile(r":?-{2,}:?")


def _md_split_row(line: str) -> list[str]:
    """Split one Markdown table row into cell texts, unescaping ``\\|``."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.replace("\\|", "|").strip() for cell in _MD_TABLE_SPLIT_RE.split(stripped)]


def _md_strip_marks(text: str) -> str:
    """Strip Markdown bold/italic markers from a recovered string."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("**", "").strip()


def _md_strip_badge(text: str) -> str:
    """Strip the emoji dot and bold markers from a recovered status."""
    cleaned = _md_strip_marks(text)
    for dot in _EMOJI_DOTS_ALL:
        if cleaned.startswith(dot):
            return cleaned[len(dot):].strip()
    return cleaned


def _md_blocks_of_lines(lines: list[str], predicate) -> list[list[str]]:
    """Contiguous line groups matching ``predicate``."""
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if predicate(line):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _counts_from_markdown(text: str) -> dict:
    lines = text.splitlines()
    quote_groups = _md_blocks_of_lines(lines, lambda line: line.startswith(">"))
    table_groups = _md_blocks_of_lines(lines, lambda line: line.lstrip().startswith("|"))
    numbered_groups = _md_blocks_of_lines(lines, lambda line: bool(_MD_NUMBERED_RE.match(line)))
    task_lines = [line for line in lines if line.lstrip().startswith("- [ ]")]

    background_tables = 0
    recruitment_tables = 0
    roster_table_lines: list[str] = []
    roster_rows = 0
    for group in table_groups:
        joined = "\n".join(group)
        first_cells = _md_split_row(group[0]) if group else []
        if "\u23f1\ufe0f History" in joined:
            background_tables += 1
        elif first_cells and first_cells[0] == "Name":
            roster_table_lines = group
            # rows[0] header, rows[1] delimiter, rows[2:] data rows
            for row_line in group[2:]:
                cells_in_row = _md_split_row(row_line)
                if cells_in_row and cells_in_row[0]:
                    roster_rows += 1
        elif "Target Sample Size" in joined:
            recruitment_tables += 1

    resources_sections = sum(1 for line in lines if line.strip() == f"<summary>{_EXPAND_RESOURCES}</summary>")
    roster_sections = sum(1 for line in lines if line.strip() == f"<summary>{_EXPAND_ROSTER}</summary>")
    checklists = sum(1 for line in lines if line.strip() == f"<summary>{_EXPAND_CHECKLIST}</summary>")

    status_nodes = 0
    if roster_table_lines:
        joined_roster = "\n".join(roster_table_lines)
        status_nodes = sum(joined_roster.count(dot) for dot in _EMOJI_DOTS_ALL)

    return {
        "panels": len(quote_groups),
        "background_tables": background_tables,
        "recruitment_tables": recruitment_tables,
        "resources_sections": resources_sections,
        "roster_sections": roster_sections,
        "checklists": checklists,
        "rq_lists": len(numbered_groups),
        "task_items": len(task_lines),
        "status_nodes": status_nodes,
        "roster_rows": roster_rows,
    }


def _counts_from_html(text: str) -> dict:
    outside_tables = re.sub(r"<table>.*?</table>", "", text, flags=re.DOTALL)
    roster_table = next(
        (m for m in re.findall(r"<table>.*?</table>", text, flags=re.DOTALL) if "<td>Name</td>" in m),
        "",
    )
    roster_rows = 0
    status_nodes = 0
    if roster_table:
        rows = re.findall(r"<tr>(.*?)</tr>", roster_table, flags=re.DOTALL)
        for row in rows[1:]:
            cells = re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL)
            if cells and cells[0].strip():
                roster_rows += 1
        status_nodes = sum(roster_table.count(dot) for dot in _EMOJI_DOTS_ALL)

    checklist_pos = text.find(_EXPAND_CHECKLIST)
    checklist_ul = text.find("<ul>", checklist_pos) if checklist_pos != -1 else -1
    return {
        "panels": text.count("<blockquote>"),
        "background_tables": sum(
            1 for table in re.findall(r"<table>.*?</table>", text, flags=re.DOTALL)
            if "\u23f1\ufe0f History" in table
        ),
        "recruitment_tables": sum(
            1 for table in re.findall(r"<table>.*?</table>", text, flags=re.DOTALL)
            if "<td>Target Sample Size</td>" in table
        ),
        "resources_sections": text.count(f"<h2>{_EXPAND_RESOURCES}</h2>"),
        "roster_sections": text.count(f"<h2>{_EXPAND_ROSTER}</h2>"),
        "checklists": text.count(f"<h2>{_EXPAND_CHECKLIST}</h2>"),
        "rq_lists": outside_tables.count("<ol>"),
        "task_items": 5 if (checklist_pos != -1 and checklist_ul != -1) else text.count("<li>"),
        "status_nodes": status_nodes,
        "roster_rows": roster_rows,
    }


def document_counts(body: Any) -> dict | None:
    """Node counts for a rendered body, keyed per the issue-04 template.

    Works on ADF documents (dict) and on rendered Markdown / HTML strings;
    returns ``None`` for anything else.
    """
    try:
        if isinstance(body, dict):
            return _counts_from_adf(body)
        if isinstance(body, str):
            stripped = body.lstrip()
            if stripped.startswith("<"):
                return _counts_from_html(body)
            return _counts_from_markdown(body)
    except Exception:
        return None
    return None


#: The completeness contract with issues 06/08/10: the counts a full document
#: must report. ``status_nodes`` is required only when the roster has rows.
REQUIRED_COUNTS: dict[str, int] = {
    "panels": 2,
    "background_tables": 1,
    "recruitment_tables": 1,
    "resources_sections": 1,
    "roster_sections": 1,
    "checklists": 1,
    "rq_lists": 1,
    "task_items": 5,
}


def assert_full_document(body: Any) -> tuple[bool, list[str]]:
    """Check a rendered body against the template's fixed node counts.

    Returns ``(ok, problems)`` and never raises. A truncated or hand-edited
    body fails with one problem per wrong count.
    """
    try:
        counts = document_counts(body)
        if counts is None:
            return False, ["body is neither rendered text nor an ADF document"]
        problems: list[str] = []
        for key, required in REQUIRED_COUNTS.items():
            found = counts.get(key, 0)
            if found != required:
                problems.append(f"expected {required} {key}, found {found}")
        if counts.get("roster_rows", 0) > 0 and counts.get("status_nodes", 0) < 1:
            problems.append("roster has rows but no status badges")
        return (not problems), problems
    except Exception as exc:
        return False, [f"assert_full_document crashed on malformed input: {exc}"]


# ---------------------------------------------------------------------------
# spec_from_body (best-effort reverse parser; never raises)
# ---------------------------------------------------------------------------

_MD_HYP_ITEM_RE = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$")
_MD_PLAIN_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")


def _strip_html_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .strip()
    )


def _placeholder_free(text: str) -> bool:
    """True unless the text is (exactly) a placeholder -- skip those."""
    cleaned = text.strip()
    return bool(cleaned) and cleaned not in _ALL_PLACEHOLDERS


def _spec_from_markdown(text: str) -> dict:
    lines = text.splitlines()
    recovered: dict = {}

    history = decision = ""
    hypotheses: list[dict] = []
    questions: list[str] = []
    roster: list[dict] = []

    mode = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = _md_split_row(line)
            # drop leading/trailing empties from the pipe split
            while cells and cells[0] == "":
                cells.pop(0)
            while cells and cells[-1] == "":
                cells.pop()
            if not cells:
                continue
            if all(_MD_DELIMITER_RE.fullmatch(cell) for cell in cells):
                continue  # GFM column delimiter row, not a data row
            label = cells[0]
            if label.startswith("\u23f1\ufe0f History") and len(cells) > 1:
                history = _md_strip_marks(cells[1])
            elif label.startswith("\U0001f3af Key Decision") and len(cells) > 1:
                decision = _md_strip_marks(cells[1])
            elif label.startswith("\u2757 Assumptions & Hypotheses") and len(cells) > 1:
                for chunk in cells[1].split("<br>"):
                    chunk = chunk.strip()
                    hypothesis_match = _MD_HYP_ITEM_RE.match(chunk)
                    plain_match = _MD_PLAIN_ITEM_RE.match(chunk)
                    if chunk.replace("**", "").strip() == "Hypotheses":
                        mode = "hypotheses"
                        continue
                    if chunk.replace("**", "").strip() == "Assumptions":
                        mode = ""
                        continue
                    if mode == "hypotheses" and hypothesis_match:
                        text_value = hypothesis_match.group(3).strip()
                        if _placeholder_free(text_value):
                            hypotheses.append(
                                {
                                    "label": hypothesis_match.group(2).rstrip(". ").strip(),
                                    "text": text_value,
                                }
                            )
                    elif plain_match and not hypothesis_match and mode == "hypotheses":
                        # bold-less item; keep the text, no label
                        if _placeholder_free(plain_match.group(2)):
                            hypotheses.append({"label": "", "text": plain_match.group(2).strip()})
            elif cells and cells[0] == "Name":
                mode = "roster"
                continue
            if mode == "roster" and cells and cells[0] and cells[0] != "Name":
                status = _md_strip_badge(cells[6]) if len(cells) > 6 else ""
                roster.append({"name": _md_strip_marks(cells[0]), "status": status})
            continue
        if stripped.startswith("#"):
            mode = "questions" if stripped.endswith("Research Questions") and "\u2753" in stripped else ""
            continue
        if stripped == "<details>" or stripped.startswith("<summary>") or stripped == "</details>":
            if stripped != "</details>" or mode != "roster":
                if stripped.startswith("<summary>"):
                    mode = "roster" if _EXPAND_ROSTER in stripped else mode
                continue
        if mode == "questions":
            plain_match = _MD_PLAIN_ITEM_RE.match(stripped)
            if plain_match:
                candidate = plain_match.group(2).strip()
                if _placeholder_free(candidate):
                    questions.append(candidate)
                continue
            if stripped:
                mode = ""

    if _placeholder_free(history):
        recovered["history"] = history
    if _placeholder_free(decision):
        recovered["decision"] = decision
    if hypotheses:
        recovered["hypotheses"] = hypotheses
    if questions:
        recovered["research_questions"] = questions
    if roster:
        recovered["roster"] = roster
    return recovered


def _spec_from_adf(doc: dict) -> dict:
    recovered: dict = {}
    content = doc.get("content") or []
    nodes = _walk(content)

    for table in (n for n in nodes if n.get("type") == "table"):
        rows = table.get("content") or []
        if not rows:
            continue
        first_text = _adf_text(rows[0]).strip()
        if first_text.startswith("\u23f1\ufe0f History"):
            for row in rows:
                cells = row.get("content") or []
                if len(cells) < 2:
                    continue
                label = _adf_text(cells[0]).strip()
                value = _adf_text(cells[1]).strip()
                if label.startswith("\u23f1\ufe0f History") and _placeholder_free(value):
                    recovered["history"] = value
                elif label.startswith("\U0001f3af Key Decision") and _placeholder_free(value):
                    recovered["decision"] = value
                elif label.startswith("\u2757 Assumptions"):
                    recovered.setdefault("_hyp_cell", cells[1])
        elif first_text.startswith("Name"):
            roster: list[dict] = []
            for row in rows[1:]:
                cells = row.get("content") or []
                if not cells:
                    continue
                name = _adf_text(cells[0]).strip()
                status = ""
                for node in _walk(cells):
                    if node.get("type") == "status":
                        status = str((node.get("attrs") or {}).get("text", ""))
                        break
                if name:
                    roster.append({"name": name, "status": status})
            if roster:
                recovered["roster"] = roster

    # hypotheses from the background cell's first ordered list
    hyp_cell = recovered.pop("_hyp_cell", None)
    if hyp_cell is not None:
        for node in _walk(hyp_cell):
            if node.get("type") == "orderedList":
                hypotheses: list[dict] = []
                for item in node.get("content") or []:
                    label_parts: list[str] = []
                    text_parts: list[str] = []
                    for run in _walk(item):
                        if run.get("type") != "text":
                            continue
                        marks = {mark.get("type") for mark in (run.get("marks") or [])}
                        if "strong" in marks:
                            label_parts.append(str(run.get("text", "")))
                        else:
                            text_parts.append(str(run.get("text", "")))
                    label = "".join(label_parts).rstrip(". ").strip()
                    text_value = "".join(text_parts).strip()
                    if _placeholder_free(text_value):
                        hypotheses.append({"label": label, "text": text_value})
                if hypotheses:
                    recovered["hypotheses"] = hypotheses
                break

    # research questions from the top-level ordered list
    for node in _adf_top_level(doc, "orderedList"):
        questions = []
        for item in node.get("content") or []:
            candidate = _adf_text(item).strip()
            if _placeholder_free(candidate):
                questions.append(candidate)
        if questions:
            recovered["research_questions"] = questions
        break

    return {
        key: recovered[key]
        for key in ("history", "decision", "hypotheses", "research_questions", "roster")
        if key in recovered
    }


def _spec_from_html(text: str) -> dict:
    recovered: dict = {}

    history_match = re.search(r"\u23f1\ufe0f History</td><td>(.*?)</td>", text, flags=re.DOTALL)
    if history_match and _placeholder_free(_strip_html_tags(history_match.group(1))):
        recovered["history"] = _strip_html_tags(history_match.group(1))
    decision_match = re.search(r"\U0001f3af Key Decision</td><td>(.*?)</td>", text, flags=re.DOTALL)
    if decision_match and _placeholder_free(_strip_html_tags(decision_match.group(1))):
        recovered["decision"] = _strip_html_tags(decision_match.group(1))

    hyp_match = re.search(r"\u2757 Assumptions &amp; Hypotheses</td><td>(.*?)</td>", text, flags=re.DOTALL)
    if hyp_match:
        hypotheses = []
        # The cell holds two lists (hypotheses, then assumptions); the first
        # <ol>...</ol> is the hypotheses list.
        first_list = re.search(r"<ol>(.*?)</ol>", hyp_match.group(1), flags=re.DOTALL)
        if first_list:
            for item in re.finditer(r"<li>(.*?)</li>", first_list.group(1), flags=re.DOTALL):
                strong = re.search(r"<strong>(.*?)</strong>", item.group(1), flags=re.DOTALL)
                if not strong:
                    continue
                label = _strip_html_tags(strong.group(1)).rstrip(". ").strip()
                rest = re.sub(r"<strong>.*?</strong>", "", item.group(1), flags=re.DOTALL)
                text_value = _strip_html_tags(rest)
                if _placeholder_free(text_value):
                    hypotheses.append({"label": label, "text": text_value})
        if hypotheses:
            recovered["hypotheses"] = hypotheses

    rq_match = re.search(
        r"\u2753 Research Questions</h1>\s*<ol>(.*?)</ol>", text, flags=re.DOTALL
    )
    if rq_match:
        questions = [
            candidate
            for candidate in (
                _strip_html_tags(item) for item in re.findall(r"<li>(.*?)</li>", rq_match.group(1), flags=re.DOTALL)
            )
            if _placeholder_free(candidate)
        ]
        if questions:
            recovered["research_questions"] = questions

    roster_table = next(
        (m for m in re.findall(r"<table>.*?</table>", text, flags=re.DOTALL) if "<td>Name</td>" in m),
        "",
    )
    if roster_table:
        roster = []
        for row in re.findall(r"<tr>(.*?)</tr>", roster_table, flags=re.DOTALL)[1:]:
            cells = re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL)
            if not cells or not _strip_html_tags(cells[0]):
                continue
            status = ""
            status_match = re.search(
                r"<strong>(?:[" + "".join(_EMOJI_DOTS_ALL) + r"])\s*(.*?)</strong>",
                row,
                flags=re.DOTALL,
            )
            if status_match:
                status = _strip_html_tags(status_match.group(1))
            roster.append({"name": _strip_html_tags(cells[0]), "status": status})
        if roster:
            recovered["roster"] = roster

    return {
        key: recovered[key]
        for key in ("history", "decision", "hypotheses", "research_questions", "roster")
        if key in recovered
    }


def spec_from_body(body: Any) -> dict:
    """Recover a partial spec from a live ticket body; never raises.

    Recovers ``history``, ``decision``, ``hypotheses``, ``research_questions``,
    and ``roster`` as ``{name, status}`` rows. Placeholder content is skipped.
    The recovered spec has no ``_meta``; the next edit must set
    ``tracker_updated_at``.
    """
    try:
        if isinstance(body, dict):
            return _spec_from_adf(body)
        if isinstance(body, str):
            stripped = body.lstrip()
            if stripped.startswith("<"):
                return _spec_from_html(body)
            if stripped.startswith("{"):
                try:
                    return _spec_from_adf(json.loads(body))
                except ValueError:
                    pass
            return _spec_from_markdown(body)
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# shorthand parsers
# ---------------------------------------------------------------------------


def parse_roster_shorthand(op: str, arg: str) -> dict:
    """Parse a ``roster`` shorthand into a JSON delta; raise ValueError on bad input.

    - ``+=``: ``Name|email|slack|reason|status|channel``; missing parts pad
      with ``""``; empty status becomes ``Potential Candidate``, empty
      channel becomes ``internal``.
    - ``~=``: ``Name|field=value``; one field patched; the command matches
      the name case-insensitively as a substring.
    - ``-=``: ``Name``; the command removes the row whose name matches
      case-insensitively and exactly.
    """
    if not isinstance(arg, str):
        raise ValueError("roster shorthand arg must be a string")
    if op == "+=":
        parts = [part.strip() for part in arg.split("|")]
        if len(parts) > 6:
            raise ValueError(
                "roster+= expects at most 6 '|'-separated parts: Name|email|slack|reason|status|channel"
            )
        parts += [""] * (6 - len(parts))
        name, email, slack, reason, status, channel = parts
        if not name:
            raise ValueError("roster+= needs a name in the first part")
        return {
            "name": name,
            "email": email,
            "slack": slack,
            "reason": reason,
            "status": status or DEFAULT_ROSTER_STATUS,
            "channel": channel or DEFAULT_ROSTER_CHANNEL,
        }
    if op == "~=":
        parts = arg.split("|")
        if len(parts) != 2 or "=" not in parts[1]:
            raise ValueError('roster~= expects "Name|field=value"')
        name = parts[0].strip()
        if not name:
            raise ValueError("roster~= needs a name before the '|'")
        field, _, value = parts[1].partition("=")
        field = field.strip()
        if field not in ROSTER_FIELDS:
            raise ValueError(
                f"unknown roster field {field!r}; fields: {', '.join(ROSTER_FIELDS)}"
            )
        return {"match": name, "set": {field: value.strip()}}
    if op == "-=":
        name = arg.strip()
        if not name or "|" in arg:
            raise ValueError('roster-= expects a bare name (no "|")')
        return {"match": name}
    raise ValueError(f"unknown roster operator {op!r}; use '+=', '~=', or '-='")


def parse_list_shorthand(op: str, arg: str, fields: tuple[str, ...]) -> dict:
    """Parse a list shorthand (hypotheses, assumptions, resources) into a delta.

    ``fields`` is the pipe-string schema, e.g. ``("label", "text")`` or
    ``("label", "url_or_text", "share_status", "share_note")``. For a
    ``url_or_text`` field the value lands in ``url`` when it starts with
    ``http``, otherwise in ``text`` -- never as ``url_or_text``.
    """
    if not isinstance(arg, str):
        raise ValueError("list shorthand arg must be a string")
    if not fields:
        raise ValueError("list shorthand needs a fields schema")
    if op == "+=":
        parts = [part.strip() for part in arg.split("|")]
        if len(parts) > len(fields):
            raise ValueError(
                f"expected at most {len(fields)} '|'-separated parts ({', '.join(fields)})"
            )
        parts += [""] * (len(fields) - len(parts))
        row = dict(zip(fields, parts))
        first = fields[0]
        if not row[first]:
            raise ValueError(f"{first} (the first part) must be non-empty")
        return _remap_url_or_text(row, fields)
    if op == "~=":
        parts = arg.split("|")
        if len(parts) != 2 or "=" not in parts[1]:
            raise ValueError('list~= expects "Label|field=value"')
        label = parts[0].strip()
        if not label:
            raise ValueError("list~= needs a label before the '|'")
        field, _, value = parts[1].partition("=")
        field = field.strip()
        if field not in fields:
            raise ValueError(f"unknown field {field!r}; fields: {', '.join(fields)}")
        return {"match": label, "set": _remap_url_or_text({field: value.strip()}, fields)}
    if op == "-=":
        label = arg.strip()
        if not label or "|" in arg:
            raise ValueError('list-= expects a bare label (no "|")')
        return {"match": label}
    raise ValueError(f"unknown list operator {op!r}; use '+=', '~=', or '-='")


def _remap_url_or_text(row: dict, fields: tuple[str, ...]) -> dict:
    """Move ``url_or_text`` into ``url`` (http...) or ``text`` (anything else).

    The result keeps the schema's key order with ``url``/``text`` in the
    slot ``url_or_text`` occupied, so deltas print stably.
    """
    if "url_or_text" not in fields:
        return row
    value = row.pop("url_or_text", "")
    mapped_key = "url" if value.lower().startswith("http") else "text"
    ordered: dict = {}
    for key in fields:
        if key == "url_or_text":
            ordered[mapped_key] = value
        elif key in row:
            ordered[key] = row[key]
    return ordered


# ---------------------------------------------------------------------------
# golden fixture (shared by the script self-tests; no organization values)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; full doc in this file
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
