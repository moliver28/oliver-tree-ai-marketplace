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
- ``validate-recruitment`` - check the participants table header and status
  values; warn with exit 1.
- ``selftest``         - exercise every subcommand offline.

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
    python scripts/scaffold_workspace.py selftest
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

    Returns ``(exit_code, detail)``; exit 0 committed, exit 1 warns. When the
    folder is not inside a repository, the README's parent is initialized
    with a fallback identity first.
    """
    code, _top, _err = _git(["rev-parse", "--show-toplevel"], target)
    if code != 0:
        code, _out, err = _git(["init", "-q"], readme.parent)
        if code != 0:
            return EXIT_WARN, f"git init failed: {err}"
    code, top, err = _git(["rev-parse", "--show-toplevel"], target)
    if code != 0:
        return EXIT_WARN, f"git rev-parse failed: {err}"
    repo = Path(top)
    _ensure_identity(repo)
    try:
        rel_target = os.path.relpath(target, repo)
        rel_readme = os.path.relpath(readme, repo)
    except ValueError as exc:
        return EXIT_WARN, f"cannot compute relative paths for the commit: {exc}"
    if rel_readme.startswith(".."):
        return EXIT_WARN, f"README {readme} is outside the repository {repo}"
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


def validate_participants(
    text: str, method: str, channel: str, config: dict | None = None
) -> tuple[int, list[str]]:
    """Check the participants table header and status values.

    Returns ``(exit_code, warnings)``: 0 clean, 1 warnings (header mismatch,
    unknown status), 3 the table is missing entirely.
    """
    warnings: list[str] = []
    lines = text.splitlines()
    header_index = next(
        (
            i
            for i, line in enumerate(lines)
            if line.lstrip().startswith("|") and line.strip().strip("|").split("|")[0].strip() == "Name"
        ),
        None,
    )
    if header_index is None:
        return EXIT_ASSERT, ["participants table not found (no header row starting with Name)"]
    found = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    found = [cell for cell in found if cell]
    expected = participants_columns(method, channel)
    if found != expected:
        warnings.append(
            f"participants table header does not match {method}/{channel}: "
            f"expected {' | '.join(expected)}; found {' | '.join(found)}"
        )
    vocabulary = set(_method_statuses(method, config))
    status_index = next((i for i, cell in enumerate(found) if cell == "Status"), None)
    cursor = header_index + 1
    if cursor < len(lines) and lines[cursor].lstrip().startswith("|") and "---" in lines[cursor]:
        cursor += 1  # the GFM delimiter row; data rows start after it
    for row_line in lines[cursor:]:
        if not row_line.lstrip().startswith("|"):
            break  # the table ended
        cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
        if not any(cells):
            continue
        name = cells[0] if cells else ""
        if status_index is not None and status_index < len(cells):
            status = cells[status_index]
            if status and status not in vocabulary:
                warnings.append(
                    f"unknown status {status!r} for {name!r}; use one of: "
                    + ", ".join(sorted(vocabulary))
                )
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
    print(f"recruitment table matches {method}/{channel}: header and statuses are valid")
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
    if not args_list or args_list[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK if not args_list else EXIT_USAGE
    if args_list[0] == "--selftest" or args_list[0] == "selftest":
        return _selftest()
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


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def _write_template(root: Path, *, with_hypotheses_token: bool = True) -> Path:
    template = root / "template"
    (template / "recruitment").mkdir(parents=True)
    (template / "sources").mkdir()
    hyp_token = "{{HYPOTHESES_BLOCK}}" if with_hypotheses_token else ""
    (template / "00-overview.md").write_text(
        "\n".join(
            [
                "# {{STUDY_TITLE}}",
                "",
                "## Ticket",
                "",
                "- Ticket: {{TICKET_KEY}} ({{STATUS}})",
                "- Link: {{TICKET_URL}}",
                "",
                "## Team",
                "",
                "- UXR: {{UXR_NAME}} Slack: {{SLACK_CHANNEL}}",
                "",
                "## JTBD & Personas",
                "",
                "{{JTBD_REFS}}",
                "",
                "{{PERSONA_REFS}}",
                "",
                "## Background",
                "",
                "{{HISTORY}}",
                "",
                "## Key decision",
                "",
                "{{DECISION}}",
                "",
                "## Hypotheses",
                "",
                hyp_token,
                "",
                "## Assumptions",
                "",
                "{{ASSUMPTIONS_BLOCK}}",
                "",
                "## Research questions",
                "",
                "{{RESEARCH_QUESTIONS_BLOCK}}",
                "",
                "## Resources",
                "",
                "{{RESOURCES_BLOCK}}",
                "",
                "## Method",
                "",
                "- Method: {{METHOD}} key {{METHOD_KEY}} channel {{CHANNEL}}",
                "- Sample: {{SAMPLE}} persona {{PERSONA}} length {{SESSION_LENGTH}}",
                "- Type {{RESEARCH_TYPE}} investment {{INVESTMENT}} pod {{POD}}",
                "- People: pm {{PM_NAME}} pd {{DESIGNER_NAME}} em {{EM_NAME}}",
                "",
                "## Participants",
                "",
                "{{COLUMN_NOTES}}",
                "",
                "{{PARTICIPANTS_TABLE}}",
                "",
                "Statuses: {{STATUS_VOCABULARY}}",
            ]
        ),
        encoding="utf-8",
    )
    (template / "recruitment" / "participants.md").write_text(
        "{{COLUMN_NOTES}}\n\n{{PARTICIPANTS_TABLE}}\n\nStatuses: {{STATUS_VOCABULARY}}\n",
        encoding="utf-8",
    )
    (template / "CLAUDE.md").write_text(
        "# {{STUDY_SLUG}}\n\nStudy {{STUDY_TITLE}} for {{TICKET_KEY}}.\n",
        encoding="utf-8",
    )
    (template / ".gitignore").write_text(
        "interviews/participant-key.md\ninterviews/raw-transcripts/\n.env\n", encoding="utf-8"
    )
    return template


def _five_hypothesis_spec() -> dict:
    return {
        "history": "Support tickets doubled after the billing rework.",
        "decision": "Should the redesigned invoice page ship to all tenants?",
        "hypotheses": [
            {"label": f"H{i}", "text": f"Hypothesis {i} is falsifiable."} for i in range(1, 6)
        ],
        "assumptions": [{"label": "A1", "text": "Admins reconcile invoices monthly."}],
        "research_questions": ["How do admins export invoices today?"],
        "resources": [
            {
                "label": "Prior research",
                "url": "https://example.com/prior",
                "share_status": "shared",
            },
            {
                "label": "Draft deck",
                "url": "https://example.com/deck",
                "share_status": "private",
                "share_note": "ask the author",
            },
        ],
        "jtbd_refs": [{"label": "Get paid fast", "url": "https://example.com/jtbd", "ring": "internal"}],
        "persona_refs": [{"label": "Tenant admin", "url": "https://example.com/persona", "ring": "external"}],
        "slack_channel": {"name": " invoicing ", "id": "C1"},
        "method_key": "interview",
        "channel": "internal",
    }


def _readme_with_table(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Research",
                "",
                README_TABLE_HEADER,
                README_TABLE_DELIM,
                "| [Old study](old-study/) | [OLD-1](https://example.com/old) | Done | Ada | 3 files |",
                "",
                "Notes below the table.",
            ]
        ),
        encoding="utf-8",
    )


def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/scaffold_workspace.py selftest")

    # --- slug ----------------------------------------------------------------
    check("slug lowercases and hyphenates", make_slug("Invoice Export Usability!", "Q1-2027")
          == "invoice-export-usability-q1-2027")
    check("slug collapses non-alphanumeric runs to one hyphen",
          make_slug("Pricing -- & Packaging (v2)", "q3-2026") == "pricing-packaging-v2-q3-2026")
    check("slug trims leading and trailing hyphens", make_slug("  --Admin 42 --", "q2-2026")
          == "admin-42-q2-2026")
    check("slug does not append the quarter twice", make_slug("Billing Q3-2026", "q3-2026")
          == "billing-q3-2026")
    long_title = "Understanding how enterprise tenants reconcile multi-entity invoices across quarters"
    long_slug = make_slug(long_title, "q1-2027", 50)
    body = long_slug.rsplit("-q1-2027", 1)[0]
    check(
        "slug cuts a long body at the last hyphen inside max_body",
        len(long_slug) <= 50 + len("-q1-2027") and body == body.rstrip("-") and "-" in body
        and len(body) <= 50,
        long_slug,
    )
    check("slug falls back to 'study' on a punctuation-only title",
          make_slug("!!!", "q1-2027") == "study-q1-2027")

    # --- block and computed tokens --------------------------------------------
    config = {"org": {"team_share_domain": "example.com"}}
    blocks = render_block_tokens(_five_hypothesis_spec(), config)
    hyp_text = blocks["HYPOTHESES_BLOCK"][0]
    check(
        "hypotheses render as numbered bold-label lines in order",
        hyp_text.splitlines() == [
            "1. **H1.** Hypothesis 1 is falsifiable.",
            "2. **H2.** Hypothesis 2 is falsifiable.",
            "3. **H3.** Hypothesis 3 is falsifiable.",
            "4. **H4.** Hypothesis 4 is falsifiable.",
            "5. **H5.** Hypothesis 5 is falsifiable.",
        ],
        hyp_text,
    )
    check(
        "resources lock private links and append the share legend",
        f"- [{LOCK} ][Draft deck](https://example.com/deck) (ask the author)"
        in blocks["RESOURCES_BLOCK"][0]
        and "- [Prior research](https://example.com/prior)" in blocks["RESOURCES_BLOCK"][0]
        and "set the example.com domain to Commenter" in blocks["RESOURCES_BLOCK"][0],
        blocks["RESOURCES_BLOCK"][0],
    )
    check("refs render label, url, and ring",
          blocks["PERSONA_REFS"][0] == "- [Tenant admin](https://example.com/persona) _external_",
          blocks["PERSONA_REFS"][0])
    check("slack channel renders as a hash name", blocks["SLACK_CHANNEL"][0] == "#invoicing")
    empty = render_block_tokens({}, config)
    check("empty lists render italic notes",
          empty["HYPOTHESES_BLOCK"][0] == "_No hypotheses defined yet._"
          and empty["RESOURCES_BLOCK"][0] == "_No resources linked yet._"
          and empty["SLACK_CHANNEL"] == ("_No Slack channel yet._", False),
          repr(empty["HYPOTHESES_BLOCK"][0]))

    check(
        "survey plus external gives the acceptance columns",
        participants_columns("survey", "external")
        == ["Name", "Title", "Company", "ARR", "Reason", "Email", "Status"],
    )
    check(
        "interview plus internal gives the acceptance columns",
        participants_columns("interview", "internal")
        == ["Name", "Title", "Reason", "Email", "Slack", "Status", "Session date", "Recording"],
    )

    # --- scaffold ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        spec_path = root / "study.spec.json"
        spec_path.write_text(json.dumps(_five_hypothesis_spec()), encoding="utf-8")
        readme = root / "README.md"
        _readme_with_table(readme)
        target = root / "invoice-export-q1-2027"
        mapping = {
            "STUDY_TITLE": "Invoice Export Usability",
            "STUDY_SLUG": target.name,
            "TICKET_KEY": "ABC-42",
            "STATUS": "Planned",
            "POD": "Invoicing",
            "UXR_NAME": "Ada Example",
            "PM_NAME": "PM Example",
            "DESIGNER_NAME": "PD Example",
            "EM_NAME": "EM Example",
            "DECISION": "Ship the redesigned page?",
            "RESEARCH_TYPE": "Evaluative",
            "METHOD": "Internal Interviews",
            "SAMPLE": "8-10 admins",
            "PERSONA": "Tenant admins",
            "SESSION_LENGTH": "45 min",
            "INVESTMENT": "M",
            "TICKET_URL": "https://example.com/browse/ABC-42",
        }
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme),
                "--spec": str(spec_path),
            }
        )
        check("scaffold exits 0", code == EXIT_OK, str(code))

        # Acceptance: no {{ left in any .md file.
        leftovers = [
            str(p) for p in sorted(target.rglob("*.md")) if "{{" in p.read_text(encoding="utf-8")
        ]
        check("no {{ tokens survive in workspace .md files", not leftovers, str(leftovers))

        # Acceptance: 5 hypotheses in order in 00-overview.md.
        overview = (target / "00-overview.md").read_text(encoding="utf-8")
        hyp_start = overview.splitlines().index("## Hypotheses")
        hyp_end = next(
            i for i, line in enumerate(overview.splitlines()[hyp_start + 1:], hyp_start + 1)
            if line.startswith("## ")
        )
        numbered = [
            line for line in overview.splitlines()[hyp_start + 1:hyp_end]
            if re.match(r"^\d+\. \*\*", line)
        ]
        check("5 hypotheses appear in order in 00-overview.md",
              len(numbered) == 5 and numbered[0].startswith("1. **H1.**")
              and numbered[4].startswith("5. **H5.**"), str(numbered))

        # Acceptance: README gets exactly one new row; the table stays contiguous.
        readme_lines = readme.read_text(encoding="utf-8").splitlines()
        table_rows = [
            line for line in readme_lines if line.strip().startswith("|") and "---" not in line
        ]
        new_row = [line for line in table_rows if "Invoice Export Usability" in line]
        check(
            "README gains exactly one row and stays contiguous",
            len(table_rows) == 3
            and len(new_row) == 1
            and "[ABC-42](https://example.com/browse/ABC-42)" in new_row[0]
            and "0 files" in new_row[0]
            and readme_lines.index(table_rows[2]) == readme_lines.index(table_rows[1]) + 1,
            "\n".join(table_rows),
        )

        # Participants table columns for interview/internal (from the spec).
        participants = (target / "recruitment" / "participants.md").read_text(encoding="utf-8")
        header_line = next(
            (line for line in participants.splitlines() if line.startswith("| Name")), ""
        )
        check(
            "spec method/channel drive the participants header (interview, internal)",
            header_line == "| Name | Title | Reason | Email | Slack | Status | Session date | Recording |",
            header_line,
        )

        # Acceptance: git check-ignore succeeds in the new workspace.
        gate = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "gitignore_gate.py"),
             "assert-ignored", "--repo", str(target),
             "interviews/raw-transcripts/x.txt", "interviews/participant-key.md"],
            capture_output=True, text=True, timeout=60,
        )
        check("gitignore gate passes in the scaffolded workspace", gate.returncode == 0,
              gate.stderr.strip())

        # Acceptance: the scaffold commit stages only the workspace and the README.
        code, top, _ = _git(["rev-parse", "--show-toplevel"], target)
        repo = Path(top)
        show = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        committed = sorted(show.stdout.split())
        expected_files = sorted(
            [Path(os.path.relpath(p, repo)).as_posix() for p in target.rglob("*") if p.is_file()]
            + [Path(os.path.relpath(readme, repo)).as_posix()]
        )
        check(
            "the commit stages only the workspace and the README",
            committed == sorted(set(expected_files)),
            f"committed={committed}",
        )
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--",
             str(Path(os.path.relpath(target, repo)).as_posix()),
             str(Path(os.path.relpath(readme, repo)).as_posix())],
            capture_output=True, text=True, timeout=60,
        )
        check("the workspace and README are clean after the scaffold commit",
              status.stdout.strip() == "", status.stdout)

        # Acceptance: a second scaffold to the same target fails.
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme),
                "--spec": str(spec_path),
            }
        )
        check("second scaffold to the same target exits 3", code == EXIT_ASSERT, str(code))
        check("second scaffold adds no README row",
              len([line for line in readme.read_text(encoding="utf-8").splitlines()
                   if "Invoice Export Usability" in line]) == 1)

        # Template missing the hypotheses token fails with exit 3.
        root2 = Path(td) / "second"
        root2.mkdir()
        template2 = _write_template(root2, with_hypotheses_token=False)
        readme2 = root2 / "README.md"
        _readme_with_table(readme2)
        code = cmd_scaffold(
            {
                "--template": str(template2),
                "--target": str(root2 / "ws"),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme2),
                "--spec": str(spec_path),
            }
        )
        check("removing {{HYPOTHESES_BLOCK}} from the template exits 3",
              code == EXIT_ASSERT, str(code))
        check("the failed scaffold leaves no target behind", not (root2 / "ws").exists())

        # Spec prose containing {{x}} is not a failure.
        root3 = Path(td) / "third"
        root3.mkdir()
        template3 = _write_template(root3)
        spec3 = _five_hypothesis_spec()
        spec3["history"] = "Legacy body said {{HISTORY}} once."
        spec_path3 = root3 / "study.spec.json"
        spec_path3.write_text(json.dumps(spec3), encoding="utf-8")
        readme3 = root3 / "README.md"
        _readme_with_table(readme3)
        target3 = root3 / "ws3"
        code = cmd_scaffold(
            {
                "--template": str(template3),
                "--target": str(target3),
                "--mapping": json.dumps(mapping),
                "--readme": str(readme3),
                "--spec": str(spec_path3),
                "--no-commit": "true",
            }
        )
        check("a {{x}} inside spec prose is not a failure", code == EXIT_OK, str(code))
        prose_kept = "{{HISTORY}} once." in (target3 / "00-overview.md").read_text(encoding="utf-8")
        check("the spec prose token stays as prose", prose_kept)

        # Usage errors.
        check("scaffold without --template exits 2",
              cmd_scaffold({"--target": "x", "--readme": "y"}) == EXIT_USAGE)
        check("scaffold with bad mapping JSON exits 2",
              cmd_scaffold({"--template": str(template), "--target": str(root3 / "ws4"),
                            "--readme": str(readme3), "--mapping": "{oops"}) == EXIT_USAGE)
        check("scaffold with an unreadable spec exits 2",
              cmd_scaffold({"--template": str(template), "--target": str(root3 / "ws5"),
                            "--readme": str(readme3), "--spec": str(root3 / "absent.json"),
                            "--no-commit": "true"}) == EXIT_USAGE)

    # --- --no-commit makes no commit ----------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        code = cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(root / "ws"),
                "--mapping": json.dumps({"STUDY_TITLE": "No commit study", "TICKET_KEY": "X-1",
                                         "STUDY_SLUG": "ws",
                                         "TICKET_URL": "https://example.com/X-1"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        check("scaffold --no-commit exits 0 outside a repo", code == EXIT_OK, str(code))
        check("scaffold --no-commit creates no repository", not (root / ".git").exists())

    # --- lookup-workspace ------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        target = root / "lookup-study"
        cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps({"STUDY_TITLE": "Lookup Study", "TICKET_KEY": "ABC-77",
                                         "STUDY_SLUG": "lookup-study", "STATUS": "Planned",
                                         "UXR_NAME": "Ada",
                                         "TICKET_URL": "https://example.com/ABC-77"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        found = find_workspace("ABC-77", readme)
        check("lookup-workspace finds the scaffolded workspace",
              found is not None and found.name == "lookup-study", str(found))
        check("lookup resolves relative to the README",
              found is not None and (found / "00-overview.md").is_file())
        check("lookup misses on an unknown ticket", find_workspace("ABC-999", readme) is None)
        code = cmd_lookup({"--ticket": "ABC-999", "--readme": str(readme)})
        check("lookup miss exits 1", code == EXIT_WARN, str(code))
        check("lookup without --ticket exits 2", cmd_lookup({"--readme": str(readme)}) == EXIT_USAGE)

    # --- render-overview --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        readme = root / "README.md"
        _readme_with_table(readme)
        spec_path = root / "s.json"
        spec_path.write_text(json.dumps(_five_hypothesis_spec()), encoding="utf-8")
        target = root / "render-study"
        cmd_scaffold(
            {
                "--template": str(template),
                "--target": str(target),
                "--mapping": json.dumps({"STUDY_TITLE": "Render Study", "TICKET_KEY": "ABC-8",
                                         "STUDY_SLUG": "render-study", "STATUS": "Planned",
                                         "UXR_NAME": "Ada", "METHOD": "Internal Interviews",
                                         "TICKET_URL": "https://example.com/ABC-8"}),
                "--readme": str(readme),
                "--no-commit": "true",
            }
        )
        overview = target / "00-overview.md"
        before = overview.read_text(encoding="utf-8")
        method_before = next(
            line for line in before.splitlines() if line.startswith("- Method:")
        )
        edited = before.replace("# Render Study", "# Render Study (renamed by hand)")
        overview.write_text(edited, encoding="utf-8")
        spec2 = _five_hypothesis_spec()
        spec2["hypotheses"] = [{"label": "H1", "text": "Only one hypothesis now."}]
        spec2["decision"] = "Updated decision."
        spec_path2 = root / "s2.json"
        spec_path2.write_text(json.dumps(spec2), encoding="utf-8")
        code = cmd_render_overview(
            {"--ticket": "ABC-8", "--readme": str(readme), "--spec": str(spec_path2)}
        )
        after = overview.read_text(encoding="utf-8")
        method_after = next(
            (line for line in after.splitlines() if line.startswith("- Method:")), ""
        )
        check("render-overview exits 0", code == EXIT_OK, str(code))
        check("render-overview rewrites an owned section",
              "Updated decision." in after and "Only one hypothesis now." in after)
        check("render-overview keeps hand-owned sections",
              method_before == method_after and "(renamed by hand)" in after)
        # Missing section is an assertion failure.
        broken = overview.read_text(encoding="utf-8").replace("## Key decision", "## Key call")
        overview.write_text(broken, encoding="utf-8")
        code = cmd_render_overview(
            {"--ticket": "ABC-8", "--readme": str(readme), "--spec": str(spec_path2)}
        )
        check("render-overview with a missing owned section exits 3",
              code == EXIT_ASSERT, str(code))
        check("render-overview on an unknown ticket exits 1",
              cmd_render_overview({"--ticket": "ABC-999", "--readme": str(readme),
                                   "--spec": str(spec_path2)}) == EXIT_WARN)
        check("render-overview without --spec exits 2",
              cmd_render_overview({"--ticket": "ABC-8", "--readme": str(readme)}) == EXIT_USAGE)

    # --- append-outreach-entry -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log = root / "outreach-log.md"
        log.write_text("# Outreach log\n\nNewest first.\n\n---\n", encoding="utf-8")
        code = cmd_append_outreach(
            {
                "--log-path": str(log),
                "--date": "2026-11-09",
                "--name": "Ada Example",
                "--channel": "slack",
                "--status-from": "Potential Candidate",
                "--status-to": "Outreach Sent",
                "--notes": "Asked for 30 minutes.",
                "--slot": ["Tue 10:00", "Wed 14:00"],
                "--hold": ["Tue 10:00"],
                "--action": "Nudge in 2 business days",
            }
        )
        check("append-outreach-entry exits 0", code == EXIT_OK, str(code))
        text = log.read_text(encoding="utf-8")
        divider_index = text.splitlines().index("---")
        check("entry lands right after the first --- line",
              "Ada Example" in text.splitlines()[divider_index + 2], text)
        cmd_append_outreach(
            {
                "--log-path": str(log),
                "--date": "2026-11-10",
                "--name": "Rook Example",
                "--channel": "email",
                "--status-from": "No Response",
                "--status-to": "Scheduled",
            }
        )
        text2 = log.read_text(encoding="utf-8")
        first_entry = text2.splitlines()[text2.splitlines().index("---") + 2]
        check("newest entry is inserted first", "Rook Example" in first_entry, first_entry)
        check("slots and holds render as detail bullets",
              "Slots offered: Tue 10:00; Wed 14:00" in text
              and "Holds placed: Tue 10:00" in text, text)
        broken = root / "broken-log.md"
        broken.write_text("# No divider here\n", encoding="utf-8")
        check("append without a divider exits 3",
              cmd_append_outreach({"--log-path": str(broken), "--date": "2026-01-01",
                                   "--name": "X"}) == EXIT_ASSERT)
        check("append without a date exits 2",
              cmd_append_outreach({"--log-path": str(log), "--name": "X"}) == EXIT_USAGE)
        check("append with a missing log exits 2",
              cmd_append_outreach({"--log-path": str(root / "absent.md"), "--date": "2026-01-01",
                                   "--name": "X"}) == EXIT_USAGE)

    # --- validate-recruitment -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        template = _write_template(root)
        participants = root / "participants.md"
        survey_external = (
            "| Name | Title | Company | ARR | Reason | Email | Status |\n"
            "|---|---|---|---|---|---|---|\n"
            "| Ada | Admin | Example Co | $10k |Exports daily | ada@example.com | Survey Sent |\n"
        )
        participants.write_text("# Participants\n\n" + survey_external, encoding="utf-8")
        check("validate passes on matching survey/external table",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_OK)
        participants.write_text("# Participants\n\n" + survey_external.replace(
            "| Survey Sent |", "| Maybe Later |"), encoding="utf-8")
        check("validate warns (exit 1) on an unknown status",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_WARN)
        participants.write_text(
            "# Participants\n\n| Name | Title |\n|---|---|\n", encoding="utf-8")
        check("validate warns (exit 1) on a header mismatch",
              cmd_validate_recruitment({"--path": str(participants), "--method": "survey",
                                        "--channel": "external"}) == EXIT_WARN)
        participants.write_text("# No table\n", encoding="utf-8")
        check("validate with no table exits 3",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_ASSERT)
        check("validate rejects an unknown method with exit 2",
              cmd_validate_recruitment({"--path": str(participants), "--method": "panel",
                                        "--channel": "internal"}) == EXIT_USAGE)
        check("validate rejects an unknown channel with exit 2",
              cmd_validate_recruitment({"--path": str(participants), "--method": "interview",
                                        "--channel": "partner"}) == EXIT_USAGE)
        check("validate with a missing file exits 2",
              cmd_validate_recruitment({"--path": str(root / "absent.md"), "--method": "interview",
                                        "--channel": "internal"}) == EXIT_USAGE)
        check("acceptance column sets hold",
              participants_columns("survey", "external")
              == ["Name", "Title", "Company", "ARR", "Reason", "Email", "Status"]
              and participants_columns("interview", "internal")
              == ["Name", "Title", "Reason", "Email", "Slack", "Status", "Session date", "Recording"])

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
