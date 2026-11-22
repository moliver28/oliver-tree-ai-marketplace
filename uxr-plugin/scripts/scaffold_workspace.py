#!/usr/bin/env python3
"""Scaffold and maintain a local research workspace (issue 08).

``init`` gives each study a local folder with a fixed structure: an
overview that mirrors the ticket, folders for sources, scripts,
interviews, analysis, recruitment, and deliverables, and git rules that
keep participant data out of version control. Every later command (``show``,
``edit``, ``recruit``, ``debrief``, ``report``, ``deck``, ``trace``) finds its
files here.

Subcommands:

- ``slug``            - derive the workspace folder name from title + quarter.
- ``scaffold``        - copy ``templates/workspace`` to the target, fill every
  ``{{TOKEN}}`` in ``.md`` files, add one README index row, and make one
  path-scoped local commit.
- ``lookup-workspace`` - find the workspace path for a ticket via the research
  root's README index.
- ``render-overview``  - rewrite only the spec-owned sections of
  ``00-overview.md`` (Background, Key decision, Hypotheses, Assumptions,
  Research questions, Resources, JTBD & Personas). People keep the other
  sections by hand.
- ``append-outreach-entry`` - insert one outreach log entry after the first
  ``---`` line, newest first.
- ``validate-recruitment`` - check the participants tables (the approved
  two-table shape, or a legacy ``Name`` table) and status values; warn
  with exit 1.

Exit codes: 0 ok, 1 warning or lookup miss, 2 usage error, 3 assertion
failed (a template token survived, a spec block is missing from the
overview template, the target already exists, a README table or overview
section is missing, or the outreach log has no divider).

Token rules: scalar tokens come from ``--mapping`` (a missing value becomes
``TBD``), block tokens render from ``--spec`` (empty lists render italic
notes), computed tokens derive from the spec's method and channel. A token
counts as a survivor only if it was in the template text; a ``{{x}}``
inside spec prose is not a failure.

The resources block shares the ticket renderer's share rules: a resource
with a ``url`` that is not ``shared`` renders a lock prefix, and any
``private`` resource appends the share legend (domain from
``org.team_share_domain``).

Usage::

    python scripts/scaffold_workspace.py slug --title "Invoice export" --quarter q1-2027
    python scripts/scaffold_workspace.py scaffold --template <plugin>/templates/workspace \
        --target <root>/<slug> --mapping '<JSON scalars>' --spec <spec path> \
        --readme <root>/README.md [--no-commit]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import config as _config  # noqa: E402
from lib import spec_blocks  # noqa: E402
from scripts.recruit_funnel import (  # noqa: E402  (the shared recruit law)
    PARTICIPANT_STATUSES,
    participant_header_issues,
)

EXIT_OK = 0
EXIT_WARN = 1
EXIT_USAGE = 2
EXIT_ASSERT = 3

#: Scalar tokens filled from ``--mapping``; a missing value becomes "TBD".
SCALAR_TOKENS: tuple[str, ...] = (
    "STUDY_TITLE",
    "STUDY_SLUG",
    "TICKET_KEY",
    "STATUS",
    "POD",
    "UXR_NAME",
    "PM_NAME",
    "DESIGNER_NAME",
    "EM_NAME",
    "DECISION",
    "RESEARCH_TYPE",
    "METHOD",
    "SAMPLE",
    "PERSONA",
    "SESSION_LENGTH",
    "INVESTMENT",
)

#: Block tokens rendered from the spec.
BLOCK_TOKENS: tuple[str, ...] = (
    "HISTORY",
    "HYPOTHESES_BLOCK",
    "ASSUMPTIONS_BLOCK",
    "RESEARCH_QUESTIONS_BLOCK",
    "RESOURCES_BLOCK",
    "JTBD_REFS",
    "PERSONA_REFS",
    "SLACK_CHANNEL",
)

#: Tokens the scaffold computes from the spec's method and channel.
COMPUTED_TOKENS: tuple[str, ...] = (
    "PARTICIPANTS_TABLE",
    "COLUMN_NOTES",
    "STATUS_VOCABULARY",
    "METHOD_KEY",
    "CHANNEL",
)

#: Sections of ``00-overview.md`` that ``render-overview`` owns; each maps to
#: the block token (or token pair) that fills it.
OWNED_SECTIONS: dict[str, tuple[str, ...]] = {
    "Background": ("HISTORY",),
    "Key decision": ("DECISION",),
    "Hypotheses": ("HYPOTHESES_BLOCK",),
    "Assumptions": ("ASSUMPTIONS_BLOCK",),
    "Research questions": ("RESEARCH_QUESTIONS_BLOCK",),
    "Resources": ("RESOURCES_BLOCK",),
    "JTBD & Personas": ("JTBD_REFS", "PERSONA_REFS"),
}

TOKEN_RE = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")
LOCK = "\U0001F512"  # lock emoji for not-yet-shared resources

README_TABLE_HEADER = "| Project | Ticket | Status | UXR | Files |"
README_TABLE_DELIM = "|---|---|---|---|---|"

GIT_INIT_NAME = "UXR Plugin"
GIT_INIT_EMAIL = "uxr-plugin@local"

METHODS = ("interview", "survey")
CHANNELS = ("internal", "external", "mixed")


# ---------------------------------------------------------------------------
# slug
# ---------------------------------------------------------------------------


def make_slug(title: str, quarter: str, max_body: int = 50) -> str:
    """Derive the workspace slug: lowercase, non-alphanumeric runs become one
    hyphen, trimmed; the body is cut to ``max_body`` at the last hyphen; the
    quarter is appended unless the body already ends with it."""
    body = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    if not body:
        body = "study"
    if len(body) > max_body:
        cut = body[:max_body]
        hyphen = cut.rfind("-")
        body = cut[:hyphen] if hyphen > 0 else cut
        body = body.strip("-") or "study"
    quarter = (quarter or "").lower().strip()
    quarter = re.sub(r"[^a-z0-9-]+", "-", quarter).strip("-")
    if quarter and not body.endswith(quarter):
        body = f"{body}-{quarter}"
    return body


def cmd_slug(args: dict[str, str]) -> int:
    title = args.get("--title")
    quarter = args.get("--quarter")
    if not title:
        print("scaffold_workspace: slug needs --title <title>", file=sys.stderr)
        return EXIT_USAGE
    if not quarter:
        print("scaffold_workspace: slug needs --quarter <q>-<yyyy>", file=sys.stderr)
        return EXIT_USAGE
    try:
        max_body = int(args.get("--max-body") or 50)
    except ValueError:
        print("scaffold_workspace: --max-body must be an integer", file=sys.stderr)
        return EXIT_USAGE
    if max_body < 1:
        print("scaffold_workspace: --max-body must be >= 1", file=sys.stderr)
        return EXIT_USAGE
    print(make_slug(title, quarter, max_body))
    return EXIT_OK


# ---------------------------------------------------------------------------
# token rendering
# ---------------------------------------------------------------------------


def _cfg(config: dict | None, section: str, key: str, default: str = "") -> str:
    if not isinstance(config, dict):
        return default
    child = config.get(section)
    if not isinstance(child, dict):
        return default
    value = child.get(key, default)
    return default if value is None else str(value)


def _md_escape_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").strip()


def _italic(text: str) -> str:
    return f"_{text}_"


def _numbered(entries: list[dict], label_field: str, empty_note: str) -> tuple[str, bool]:
    """``N. **Label.** Text`` lines (hypotheses, assumptions); ``filled`` is
    False for an empty list, which renders the italic note instead."""
    rows = [e for e in entries if isinstance(e, dict)]
    if not any(str(e.get(label_field, "")).strip() for e in rows):
        return _italic(empty_note), False
    lines = []
    for index, entry in enumerate(rows, start=1):
        text = str(entry.get(label_field, "")).strip()
        if not text:
            continue
        label = str(entry.get("label", "")).strip()
        if label:
            lines.append(f"{index}. **{label}.** {text}")
        else:
            lines.append(f"{index}. {text}")
    return "\n".join(lines), bool(lines)


def _share_legend(config: dict | None) -> str:
    domain = _cfg(config, "org", "team_share_domain") or "team"
    return (
        f"{LOCK} = link is not yet shared with the team. Open the file in Drive, "
        f"click Share, set the {domain} domain to Commenter (or higher) so "
        "teammates can view."
    )


def _render_resources(spec: dict, config: dict | None) -> tuple[str, bool]:
    resources = [r for r in (spec.get("resources") or []) if isinstance(r, dict)]
    if not resources:
        return _italic("No resources linked yet."), False
    lines: list[str] = []
    has_private = False
    for resource in resources:
        label = str(resource.get("label", "")).strip() or "(untitled)"
        url = str(resource.get("url", "")).strip()
        text = str(resource.get("text", "")).strip()
        share = str(resource.get("share_status", "")).strip()
        note = str(resource.get("share_note", "")).strip()
        if url:
            prefix = f"[{LOCK} ]" if share != "shared" else ""
            if share == "private":
                has_private = True
            body = f"{prefix}[{label}]({url})"
        else:
            body = f"{label}: {text}" if text else label
        if note:
            body = f"{body} ({note})"
        lines.append(f"- {body}")
    if has_private:
        lines.append(f"- {_share_legend(config)}")
    return "\n".join(lines), True


def _render_refs(entries: object, empty_note: str) -> tuple[str, bool]:
    """``- [label](url) _ring_`` lines for JTBD and persona refs."""
    if not isinstance(entries, list):
        entries = []
    rows = [e for e in entries if isinstance(e, (dict, str)) and str(e).strip()]
    if not rows:
        return _italic(empty_note), False
    lines: list[str] = []
    for entry in rows:
        if isinstance(entry, str):
            lines.append(f"- {entry.strip()}")
            continue
        label = str(entry.get("label", "")).strip()
        url = str(entry.get("url", "")).strip()
        ring = str(entry.get("ring", "")).strip()
        if url:
            line = f"- [{label or url}]({url})"
        else:
            line = f"- {label}"
        if ring:
            line = f"{line} _{ring}_"
        lines.append(line)
    return "\n".join(lines), True


def render_block_tokens(spec: dict, config: dict | None) -> dict[str, tuple[str, bool]]:
    """Render every block token from the spec; returns ``{token: (text, filled)}``."""
    history = str(spec.get("history") or "").strip()
    decision = str(spec.get("decision") or "").strip()
    hyp_text, hyp_filled = _numbered(
        spec.get("hypotheses") or [], "text", "No hypotheses defined yet."
    )
    asm_text, asm_filled = _numbered(
        spec.get("assumptions") or [], "text", "No assumptions defined yet."
    )
    questions = [str(q).strip() for q in (spec.get("research_questions") or []) if str(q).strip()]
    if questions:
        rq_text, rq_filled = (
            "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1)),
            True,
        )
    else:
        rq_text, rq_filled = _italic("No research questions defined yet."), False
    res_text, res_filled = _render_resources(spec, config)
    jtbd_text, jtbd_filled = _render_refs(spec.get("jtbd_refs"), "No JTBD refs linked yet.")
    persona_text, persona_filled = _render_refs(
        spec.get("persona_refs"), "No persona refs linked yet."
    )
    slack = spec.get("slack_channel")
    if isinstance(slack, dict):
        slack_name = str(slack.get("name") or "").strip()
    else:
        slack_name = str(slack or "").strip()
    slack_text = f"#{slack_name}" if slack_name else _italic("No Slack channel yet.")
    return {
        "HISTORY": (history or _italic("No background yet."), bool(history)),
        "DECISION": (decision or _italic("No key decision yet."), bool(decision)),
        "HYPOTHESES_BLOCK": (hyp_text, hyp_filled),
        "ASSUMPTIONS_BLOCK": (asm_text, asm_filled),
        "RESEARCH_QUESTIONS_BLOCK": (rq_text, rq_filled),
        "RESOURCES_BLOCK": (res_text, res_filled),
        "JTBD_REFS": (jtbd_text, jtbd_filled),
        "PERSONA_REFS": (persona_text, persona_filled),
        "SLACK_CHANNEL": (slack_text, bool(slack_name)),
    }


# ---------------------------------------------------------------------------
# computed tokens: method, channel, participants table
# ---------------------------------------------------------------------------


def canonical_method(spec: dict, mapping: dict) -> str:
    """The study's method key: interview or survey, else empty."""
    raw = str((spec or {}).get("method_key") or "").strip().lower()
    if raw in METHODS:
        return raw
    raw = str((mapping or {}).get("METHOD_KEY") or "").strip().lower()
    if raw in METHODS:
        return raw
    text = str((mapping or {}).get("METHOD") or "").lower()
    if "interview" in text:
        return "interview"
    if "survey" in text:
        return "survey"
    return ""


def canonical_channel(spec: dict, mapping: dict) -> str:
    """The study's recruiting channel: internal, external, or mixed, else empty."""
    raw = str((spec or {}).get("channel") or "").strip().lower()
    if raw in CHANNELS:
        return raw
    raw = str((mapping or {}).get("CHANNEL") or "").strip().lower()
    if raw in CHANNELS:
        return raw
    return ""


def participants_columns(method: str, channel: str) -> list[str]:
    """Participants table columns for a method and channel (issue 08)."""
    columns = ["Name", "Title"]
    if channel in ("external", "mixed"):
        columns += ["Company", "ARR"]
    columns += ["Reason", "Email"]
    if channel in ("internal", "mixed"):
        columns += ["Slack"]
    columns += ["Status"]
    if method == "interview":
        columns += ["Session date", "Recording"]
    return columns


def _method_statuses(method: str, config: dict | None) -> list[str]:
    """The status vocabulary for one method, honoring ``recruit.statuses``."""
    configured: dict = {}
    if isinstance(config, dict):
        recruit = config.get("recruit")
        if isinstance(recruit, dict) and isinstance(recruit.get("statuses"), dict):
            configured = recruit["statuses"]
    defaults = {
        "interview": spec_blocks.DEFAULT_INTERVIEW_STATUSES,
        "survey": spec_blocks.DEFAULT_SURVEY_STATUSES,
    }
    values = [str(v).strip() for v in (configured.get(method) or []) if str(v).strip()]
    if not values:
        values = list(defaults.get(method, ()))
    if not values:  # unknown method: the union of both vocabularies
        seen: set[str] = set()
        values = []
        for group in ("interview", "survey"):
            entries = [str(v).strip() for v in (configured.get(group) or []) if str(v).strip()]
            for value in entries or list(defaults.get(group, ())):
                if value not in seen:
                    seen.add(value)
                    values.append(value)
    return values


def render_computed_tokens(spec: dict, mapping: dict, config: dict | None) -> dict[str, str]:
    """Render the computed tokens from the spec's method and channel."""
    method = canonical_method(spec, mapping)
    channel = canonical_channel(spec, mapping)
    columns = participants_columns(method, channel)
    header = "| " + " | ".join(columns) + " |"
    delim = "|" + "|".join(["---"] * len(columns)) + "|"
    notes: list[str] = []
    if "Company" in columns:
        notes.append("Company and ARR apply to external participants.")
    if "Slack" in columns:
        notes.append("Slack handle applies to internal colleagues.")
    if "Session date" in columns:
        notes.append("Session date and Recording are filled after each session.")
    return {
        "PARTICIPANTS_TABLE": f"{header}\n{delim}",
        "COLUMN_NOTES": " ".join(notes),
        "STATUS_VOCABULARY": ", ".join(_method_statuses(method, config)),
        "METHOD_KEY": method or "TBD",
        "CHANNEL": channel or "TBD",
    }


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


def _read_spec(path_value: str) -> dict:
    try:
        text = Path(path_value).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise _Usage(f"--spec file cannot be read: {exc}") from exc
    try:
        spec = json.loads(text)
    except ValueError as exc:
        raise _Usage(f"--spec file is not valid JSON: {exc}") from exc
    return spec if isinstance(spec, dict) else {}


class _Usage(Exception):
    pass


_PROTECT_START = "\x00"
_PROTECT_END = "\x01"


def _substitute(text: str, replacements: dict[str, str]) -> tuple[str, list[str]]:
    """Replace ``{{TOKEN}}`` occurrences; return (new text, surviving tokens).

    Substituted values are wrapped in sentinel characters while scanning for
    survivors, so a ``{{x}}`` that arrives inside spec prose never counts as
    a template survivor.
    """
    present = set(TOKEN_RE.findall(text))

    def repl(match: re.Match) -> str:
        token = match.group(1)
        if token in replacements:
            return _PROTECT_START + replacements[token] + _PROTECT_END
        return match.group(0)

    new_text = TOKEN_RE.sub(repl, text)
    outside_prose = re.sub(
        _PROTECT_START + ".*?" + _PROTECT_END, "", new_text, flags=re.DOTALL
    )
    survivors = sorted(token for token in present if f"{{{{{token}}}}}" in outside_prose)
    return new_text.replace(_PROTECT_START, "").replace(_PROTECT_END, ""), survivors


def _readme_row_link(key: str, url: str) -> str:
    key = (key or "TBD").strip()
    url = (url or "").strip()
    return f"[{key}]({url})" if url else key


def insert_readme_row(readme: Path, row: str) -> None:
    """Insert one row after the last row of the ``| Project |`` table.

    A missing README is created with the canonical table; an existing README
    without the table raises :class:`_Usage`-free ``SystemExit`` via the
    caller (assertion).
    """
    if readme.exists():
        lines = readme.read_text(encoding="utf-8").splitlines()
        header_index = next(
            (i for i, line in enumerate(lines) if line.strip().startswith("| Project |")),
            None,
        )
        if header_index is None:
            raise AssertionError("README has no '| Project |' table to append to")
        last = header_index
        cursor = header_index + 1
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            last = cursor
            cursor += 1
        lines.insert(last + 1, row)
        readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text(
            "\n".join(["# Research projects", "", README_TABLE_HEADER, README_TABLE_DELIM, row])
            + "\n",
            encoding="utf-8",
        )


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _ensure_identity(repo: Path) -> None:
    """Set a local fallback identity when the repo has none configured."""
    code, name, _ = _git(["config", "user.name"], repo)
    if code != 0 or not name:
        _git(["config", "user.name", GIT_INIT_NAME], repo)
    code, email, _ = _git(["config", "user.email"], repo)
    if code != 0 or not email:
        _git(["config", "user.email", GIT_INIT_EMAIL], repo)


def commit_workspace(target: Path, readme: Path, slug: str, key: str, title: str) -> tuple[int, str]:
    """Make one path-scoped commit (workspace folder + README only).

    Returns ``(exit_code, detail)``; exit 0 committed, exit 1 warns. The
    commit always lands in the repository rooted at the README's parent,
    the research root: when any parent repository surrounds the root (the
    usual repo-checked-out machine), committing there fails on its ignore
    rules and the initial commit silently does not land (F4), so the
    research root is initialized with a fallback identity whenever the
    surrounding repository is not the root itself.
    """
    research_root = readme.parent
    code, top, _err = _git(["rev-parse", "--show-toplevel"], target)
    if code != 0 or Path(top).resolve() != research_root.resolve():
        code, _out, err = _git(["init", "-q"], research_root)
        if code != 0:
            return EXIT_WARN, f"git init failed: {err}"
    repo = research_root
    _ensure_identity(repo)
    rel_target = os.path.relpath(target, repo)
    rel_readme = os.path.relpath(readme, repo)
    code, _out, err = _git(["add", "--", rel_target, rel_readme], repo)
    if code != 0:
        return EXIT_WARN, f"git add failed: {err}"
    message_subject = f"Add {slug} workspace"
    message_body = f"Ticket: {key}\nStudy: {title}"
    code, _out, err = _git(["commit", "-q", "-m", message_subject, "-m", message_body], repo)
    if code != 0:
        return EXIT_WARN, f"git commit failed: {err}"
    return EXIT_OK, ""


def cmd_scaffold(args: dict[str, object]) -> int:
    template_value = str(args.get("--template") or "")
    target_value = str(args.get("--target") or "")
    mapping_value = str(args.get("--mapping") or "")
    readme_value = str(args.get("--readme") or "")
    spec_value = str(args.get("--spec") or "")
    no_commit = bool(args.get("--no-commit"))

    if not template_value or not target_value or not readme_value:
        print(
            "scaffold_workspace: scaffold needs --template, --target, and --readme",
            file=sys.stderr,
        )
        return EXIT_USAGE
    template = Path(template_value).expanduser()
    target = Path(target_value).expanduser()
    readme = Path(readme_value).expanduser()
    if not template.is_dir():
        print(f"scaffold_workspace: template directory not found: {template}", file=sys.stderr)
        return EXIT_USAGE
    if target.exists():
        print(
            f"scaffold_workspace: target already exists: {target}", file=sys.stderr
        )
        return EXIT_ASSERT
    try:
        mapping = json.loads(mapping_value) if mapping_value else {}
    except ValueError as exc:
        print(f"scaffold_workspace: --mapping is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not isinstance(mapping, dict):
        print("scaffold_workspace: --mapping must be a JSON object", file=sys.stderr)
        return EXIT_USAGE
    spec: dict = {}
    if spec_value:
        try:
            spec = _read_spec(spec_value)
        except _Usage as exc:
            print(f"scaffold_workspace: {exc}", file=sys.stderr)
            return EXIT_USAGE
    try:
        config = _config.load_config()
    except _config.ConfigError:
        config = {}

    blocks = render_block_tokens(spec, config)
    computed = render_computed_tokens(spec, mapping, config)
    replacements: dict[str, str] = {}
    for token in SCALAR_TOKENS:
        value = mapping.get(token)
        text = "" if value is None else str(value).strip()
        replacements[token] = text or "TBD"
    # Extra mapping keys (for example TICKET_URL) fill their own tokens.
    for token, value in mapping.items():
        if token not in replacements and not isinstance(value, (dict, list)):
            text = str(value).strip()
            replacements[str(token)] = text or "TBD"
    for token, (text, _filled) in blocks.items():
        replacements[token] = text
    replacements.update(computed)
    replacements["STUDY_SLUG"] = str(mapping.get("STUDY_SLUG") or target.name)

    shutil.copytree(template, target)

    # Fill every {{TOKEN}} in .md files; fail (3) if a template token survives.
    overview_template_text = (template / "00-overview.md").read_text(encoding="utf-8")
    survivors: list[str] = []
    for path in sorted(target.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        new_text, file_survivors = _substitute(text, replacements)
        for token in file_survivors:
            survivors.append(f"{path.relative_to(target).as_posix()}: {token}")
        path.write_text(new_text, encoding="utf-8")
    if survivors:
        shutil.rmtree(target, ignore_errors=True)
        print(
            "scaffold_workspace: template tokens survived substitution; refusing to keep "
            "a half-filled workspace:",
            file=sys.stderr,
        )
        for survivor in survivors:
            print(f"  - {survivor}", file=sys.stderr)
        return EXIT_ASSERT

    # Fail (3) if a filled spec block is missing from the template's overview.
    missing_blocks = [
        token
        for token, (_text, filled) in blocks.items()
        if filled and f"{{{{{token}}}}}" not in overview_template_text
    ]
    if missing_blocks:
        shutil.rmtree(target, ignore_errors=True)
        print(
            "scaffold_workspace: the template's 00-overview.md is missing spec blocks "
            "that have content; refusing to drop spec data:",
            file=sys.stderr,
        )
        for token in missing_blocks:
            print(f"  - {{{{{token}}}}}", file=sys.stderr)
        return EXIT_ASSERT

    # Add one README index row.
    title = str(mapping.get("STUDY_TITLE") or "TBD").strip() or "TBD"
    key = str(mapping.get("TICKET_KEY") or "TBD").strip() or "TBD"
    status = str(mapping.get("STATUS") or "TBD").strip() or "TBD"
    uxr = str(mapping.get("UXR_NAME") or "TBD").strip() or "TBD"
    ticket_url = str(mapping.get("TICKET_URL") or "").strip()
    row = (
        f"| [{_md_escape_cell(title)}]({target.name}/) "
        f"| {_md_escape_cell(_readme_row_link(key, ticket_url))} "
        f"| {_md_escape_cell(status)} "
        f"| {_md_escape_cell(uxr)} "
        f"| 0 files |"
    )
    try:
        insert_readme_row(readme, row)
    except AssertionError as exc:
        shutil.rmtree(target, ignore_errors=True)
        print(f"scaffold_workspace: {exc}", file=sys.stderr)
        return EXIT_ASSERT

    if no_commit:
        print(f"scaffolded {target} (no commit requested)")
        return EXIT_OK

    code, detail = commit_workspace(target, readme, target.name, key, title)
    if code != EXIT_OK:
        print(f"scaffold_workspace: warning: {detail}", file=sys.stderr)
        print(f"scaffolded {target}; the commit did not land")
        return EXIT_WARN
    print(f"scaffolded {target} and committed (workspace folder + README only)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# lookup-workspace
# ---------------------------------------------------------------------------

_LINK_TEXT_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _table_rows(lines: list[str]) -> list[tuple[str, str]]:
    """The ``(title, workspace_href)`` rows of the README project table."""
    header_index = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("| Project |")),
        None,
    )
    if header_index is None:
        return []
    rows: list[tuple[str, str]] = []
    cursor = header_index + 1
    while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
        cells = [cell.strip() for cell in lines[cursor].strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] != "---":
            match = _LINK_TEXT_RE.search(cells[0])
            href = match.group(2) if match else ""
            rows.append((cells[0], href))
        cursor += 1
    return rows


def find_workspace(ticket: str, readme: Path) -> Path | None:
    """Resolve a ticket key to its workspace folder via the README index."""
    if not readme.is_file():
        return None
    ticket_clean = ticket.strip().lower()
    for _title, href in _table_rows(readme.read_text(encoding="utf-8").splitlines()):
        row_path = (readme.parent / href).resolve() if href else None
        if row_path is None:
            continue
        marker = row_path / "00-overview.md"
        if marker.is_file():
            try:
                text = marker.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                if line.strip().startswith("- Ticket:") and ticket_clean in line.lower():
                    return row_path
                if line.startswith("# ") and ticket_clean in line.lower():
                    return row_path
    return None


def cmd_lookup(args: dict[str, str]) -> int:
    ticket = args.get("--ticket") or ""
    readme_value = args.get("--readme") or ""
    if not ticket:
        print("scaffold_workspace: lookup-workspace needs --ticket <KEY>", file=sys.stderr)
        return EXIT_USAGE
    if not readme_value:
        print("scaffold_workspace: lookup-workspace needs --readme <path>", file=sys.stderr)
        return EXIT_USAGE
    readme = Path(readme_value).expanduser()
    workspace = find_workspace(ticket, readme)
    if workspace is None:
        print("WORKSPACE_NOT_FOUND", file=sys.stderr)
        return EXIT_WARN
    print(str(workspace))
    return EXIT_OK


# ---------------------------------------------------------------------------
# render-overview
# ---------------------------------------------------------------------------


def _render_section(token_names: tuple[str, ...], blocks: dict[str, tuple[str, bool]]) -> str:
    parts = [blocks[token][0] for token in token_names]
    return "\n\n".join(part for part in parts if part)


def render_overview_text(overview: str, spec: dict, config: dict | None) -> tuple[str, list[str]]:
    """Rewrite only the spec-owned sections; returns (new text, rewritten names)."""
    blocks = render_block_tokens(spec, config)
    lines = overview.splitlines()
    rewritten: list[str] = []
    for section, token_names in OWNED_SECTIONS.items():
        heading = f"## {section}"
        start = next(
            (i for i, line in enumerate(lines) if line.strip() == heading),
            None,
        )
        if start is None:
            raise AssertionError(f"00-overview.md has no '{heading}' section")
        end = start + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        body = _render_section(token_names, blocks).split("\n")
        replacement = [heading, ""] + body + [""]
        lines[start:end] = replacement
        rewritten.append(section)
    return "\n".join(lines) + "\n", rewritten


def cmd_render_overview(args: dict[str, str]) -> int:
    ticket = args.get("--ticket") or ""
    readme_value = args.get("--readme") or ""
    spec_value = args.get("--spec") or ""
    if not ticket or not readme_value or not spec_value:
        print(
            "scaffold_workspace: render-overview needs --ticket, --readme, and --spec",
            file=sys.stderr,
        )
        return EXIT_USAGE
    readme = Path(readme_value).expanduser()
    workspace = find_workspace(ticket, readme)
    if workspace is None:
        print("WORKSPACE_NOT_FOUND", file=sys.stderr)
        return EXIT_WARN
    overview = workspace / "00-overview.md"
    if not overview.is_file():
        print(f"scaffold_workspace: no 00-overview.md in {workspace}", file=sys.stderr)
        return EXIT_ASSERT
    try:
        spec = _read_spec(spec_value)
    except _Usage as exc:
        print(f"scaffold_workspace: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = _config.load_config()
    except _config.ConfigError:
        config = {}
    try:
        new_text, rewritten = render_overview_text(
            overview.read_text(encoding="utf-8"), spec, config
        )
    except AssertionError as exc:
        print(f"scaffold_workspace: {exc}", file=sys.stderr)
        return EXIT_ASSERT
    overview.write_text(new_text, encoding="utf-8")
    print(f"rewrote {', '.join(rewritten)} in {overview}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# append-outreach-entry
# ---------------------------------------------------------------------------


def render_outreach_entry(
    date: str,
    name: str,
    channel: str = "",
    status_from: str = "",
    status_to: str = "",
    notes: str = "",
    slots: list[str] | None = None,
    holds: list[str] | None = None,
    action: str = "",
) -> list[str]:
    """The log entry lines: one headline bullet, then optional detail bullets."""
    headline = f"- **{date}** {name}"
    context = " via " + channel if channel else ""
    transition = ""
    if status_from or status_to:
        transition = f": {status_from or '?'} -> {status_to or '?'}"
    lines = [headline + context + transition]
    if notes:
        lines.append(f"  - Notes: {notes}")
    if slots:
        lines.append("  - Slots offered: " + "; ".join(slots))
    if holds:
        lines.append("  - Holds placed: " + "; ".join(holds))
    if action:
        lines.append(f"  - Next action: {action}")
    return lines


def append_outreach_entry_lines(log_text: str, entry_lines: list[str]) -> str:
    """Insert entry lines after the first ``---`` divider (newest first)."""
    lines = log_text.splitlines()
    divider = next((i for i, line in enumerate(lines) if line.strip() == "---"), None)
    if divider is None:
        raise AssertionError("no '---' divider line to insert after")
    lines[divider + 1:divider + 1] = [""] + entry_lines + [""]
    return "\n".join(lines) + "\n"


def cmd_append_outreach(args: dict[str, object]) -> int:
    log_value = str(args.get("--log-path") or "")
    date = str(args.get("--date") or "")
    name = str(args.get("--name") or "")
    if not log_value or not date or not name:
        print(
            "scaffold_workspace: append-outreach-entry needs --log-path, --date, and --name",
            file=sys.stderr,
        )
        return EXIT_USAGE
    log_path = Path(log_value).expanduser()
    if not log_path.is_file():
        print(f"scaffold_workspace: outreach log not found: {log_path}", file=sys.stderr)
        return EXIT_USAGE
    slots = [str(v).strip() for v in (args.get("--slot") or []) if str(v).strip()]
    holds = [str(v).strip() for v in (args.get("--hold") or []) if str(v).strip()]
    entry_lines = render_outreach_entry(
        date=date,
        name=name,
        channel=str(args.get("--channel") or "").strip(),
        status_from=str(args.get("--status-from") or "").strip(),
        status_to=str(args.get("--status-to") or "").strip(),
        notes=str(args.get("--notes") or "").strip(),
        slots=slots,
        holds=holds,
        action=str(args.get("--action") or "").strip(),
    )
    try:
        new_text = append_outreach_entry_lines(log_path.read_text(encoding="utf-8"), entry_lines)
    except AssertionError as exc:
        print(f"scaffold_workspace: {exc}", file=sys.stderr)
        return EXIT_ASSERT
    log_path.write_text(new_text, encoding="utf-8")
    print(f"appended outreach entry for {name} ({date}) to {log_path}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# validate-recruitment
# ---------------------------------------------------------------------------


def _is_delimiter_row(line: str) -> bool:
    """True for a GFM table delimiter row (``|---|---|``)."""
    body = line.strip().replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
    return line.lstrip().startswith("|") and body == ""


def _table_blocks(lines: list[str]) -> list[tuple[int, list[int]]]:
    """One ``(header_index, row_indexes)`` pair per Markdown table block.

    A block starts at the first ``|`` line and ends at the first
    following non-``|`` line; the GFM delimiter row is not a data row.
    """
    blocks: list[tuple[int, list[int]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        header_index = index
        cursor = index + 1
        if cursor < len(lines) and _is_delimiter_row(lines[cursor]):
            cursor += 1  # the GFM delimiter row; data rows start after it
        row_indexes: list[int] = []
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            row_indexes.append(cursor)
            cursor += 1
        blocks.append((header_index, row_indexes))
        index = cursor
    return blocks


def _participant_variant(cells: list[str]) -> list[str]:
    """The header-drift lines for a ``participant id`` header (issue 135).

    An exact header match returns an empty list; a drifted header is
    checked against both approved sets and the closer set reports (ties
    report internal). The lines are advisory; each names its variant.
    """
    internal = participant_header_issues(cells, "internal")
    external = participant_header_issues(cells, "external")
    if not internal or not external:
        return []
    return external if len(external) < len(internal) else internal


def validate_participants(
    text: str, method: str, channel: str, config: dict | None = None
) -> tuple[int, list[str]]:
    """Check the participants tables and their status values.

    The approved shape (issue 51) is two fixed tables, one per flow,
    each header starting with ``participant id``: headers are checked
    against the approved column sets and statuses against the locked
    vocabulary. A legacy single table whose first header cell is
    ``Name`` is still checked against the method and channel columns.
    Returns ``(exit_code, warnings)``: 0 clean, 1 warnings (header
    drift, unknown status), 3 no participants table at all.
    """
    warnings: list[str] = []
    lines = text.splitlines()
    found = False
    for header_index, row_indexes in _table_blocks(lines):
        cells = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
        cells = [cell for cell in cells if cell]
        lower = [cell.lower() for cell in cells]
        if lower and lower[0] == "participant id":
            found = True
            warnings.extend(_participant_variant(cells))
            status_index = next((i for i, cell in enumerate(lower) if cell == "status"), None)
            for row_index in row_indexes:
                row_cells = [
                    cell.strip() for cell in lines[row_index].strip().strip("|").split("|")
                ]
                if not any(row_cells):
                    continue
                status = ""
                if status_index is not None and status_index < len(row_cells):
                    status = row_cells[status_index]
                if status and status.lower() not in PARTICIPANT_STATUSES:
                    participant = row_cells[0] if row_cells else ""
                    warnings.append(
                        f"unknown status {status!r} for participant {participant!r}; use one "
                        f"of: {', '.join(PARTICIPANT_STATUSES)}"
                    )
        elif lower and lower[0] == "name":
            found = True
            expected = participants_columns(method, channel)
            if cells != expected:
                warnings.append(
                    f"participants table header does not match {method}/{channel}: "
                    f"expected {' | '.join(expected)}; found {' | '.join(cells)}"
                )
            vocabulary = set(_method_statuses(method, config))
            status_index = next((i for i, cell in enumerate(cells) if cell == "Status"), None)
            for row_index in row_indexes:
                row_cells = [
                    cell.strip() for cell in lines[row_index].strip().strip("|").split("|")
                ]
                if not any(row_cells):
                    continue
                name = row_cells[0] if row_cells else ""
                if status_index is not None and status_index < len(row_cells):
                    status = row_cells[status_index]
                    if status and status not in vocabulary:
                        warnings.append(
                            f"unknown status {status!r} for {name!r}; use one of: "
                            + ", ".join(sorted(vocabulary))
                        )
    if not found:
        return EXIT_ASSERT, [
            "participants table not found (no header row starting with 'participant id' or 'Name')"
        ]
    if warnings:
        return EXIT_WARN, warnings
    return EXIT_OK, []


def cmd_validate_recruitment(args: dict[str, str]) -> int:
    path_value = args.get("--path") or ""
    method = (args.get("--method") or "").strip().lower()
    channel = (args.get("--channel") or "").strip().lower()
    if not path_value or not method or not channel:
        print(
            "scaffold_workspace: validate-recruitment needs --path, --method, and --channel",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if method not in METHODS:
        print(
            f"scaffold_workspace: --method must be one of {', '.join(METHODS)}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if channel not in CHANNELS:
        print(
            f"scaffold_workspace: --channel must be one of {', '.join(CHANNELS)}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    path = Path(path_value).expanduser()
    if not path.is_file():
        print(f"scaffold_workspace: participants file not found: {path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = _config.load_config()
    except _config.ConfigError:
        config = {}
    code, warnings = validate_participants(path.read_text(encoding="utf-8"), method, channel, config)
    if code == EXIT_ASSERT:
        for warning in warnings:
            print(f"scaffold_workspace: {warning}", file=sys.stderr)
        return EXIT_ASSERT
    for warning in warnings:
        print(f"  [warn] {warning}")
    if code == EXIT_WARN:
        print(f"recruitment table needs attention ({len(warnings)} warning(s))")
        return EXIT_WARN
    print("recruitment participants table: headers and statuses are valid")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

REPEAT_FLAGS = ("--slot", "--hold")


def _parse_args(argv: list[str]) -> tuple[str, dict[str, object]]:
    if not argv:
        return "", {}
    subcommand = argv[0]
    args: dict[str, object] = {}
    index = 1
    while index < len(argv):
        token = argv[index]
        if token.startswith("--"):
            if "=" in token:
                flag, _, value = token.partition("=")
            else:
                flag = token
                if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
                    index += 1
                    value = argv[index]
                else:
                    value = "true"
            if flag in REPEAT_FLAGS:
                args.setdefault(flag, []).append(value)
            else:
                args[flag] = value
        else:
            print(f"scaffold_workspace: unexpected argument {token!r}", file=sys.stderr)
            return subcommand, {}
        index += 1
    return subcommand, args


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args_list[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    subcommand, args = _parse_args(args_list)
    handlers = {
        "slug": cmd_slug,
        "scaffold": cmd_scaffold,
        "lookup-workspace": cmd_lookup,
        "render-overview": cmd_render_overview,
        "append-outreach-entry": cmd_append_outreach,
        "validate-recruitment": cmd_validate_recruitment,
    }
    handler = handlers.get(subcommand)
    if handler is None:
        print(f"scaffold_workspace: unknown subcommand {subcommand!r}", file=sys.stderr)
        return EXIT_USAGE
    try:
        return handler(args)
    except _Usage as exc:
        print(f"scaffold_workspace: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
