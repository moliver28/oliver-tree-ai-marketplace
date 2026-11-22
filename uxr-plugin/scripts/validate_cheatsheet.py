#!/usr/bin/env python3
"""Cheat sheet validator: keep docs/cheat-sheet.html in sync with its sources.

The one-page cheat sheet (``docs/cheat-sheet.html``) carries two kinds
of sections: generated sections (marked ``data-generated`` in the HTML)
whose every value must match a source file, and editorial sections
(interview phases, role cards, FAQ) this script never rewrites -- not
even in ``--remediate`` -- unless a checked name inside them changed,
which it cannot, because their names are not checked.

Generated sections and their sources (the reference plugin parsed Jira
field docs directly; this validator reads the config contract and the
command files instead):

- ``commands``   -- ``commands/uxr-*.md``: the command count word and
  every command name.
- ``flags``      -- the ``argument-hint`` front matter of every command
  file: each declared flag appears in the flag table.
- ``shorthands`` -- the ``## Shorthand keys`` table of
  ``commands/uxr-edit.md``: every shorthand key.
- ``fields``     -- ``config/org.example.yaml`` ``fields.*``: every
  field with a ``values`` list, and each value in it.
- ``workflow``   -- the reference phase order in ``lib/phase_gates.py``
  plus every non-empty status vocabulary in
  ``config/org.example.yaml`` (``workflow.*``, ``recruit.statuses.*``).
- ``methods``    -- the ``## Method table`` rows of
  ``prompts/classify/methods.json``.
- ``template``   -- the ``## `` section names of
  ``templates/workspace/00-overview.md``.

Flags::

- ``--verbose``    print one ``[ok]`` line per clean check too.
- ``--remediate``  rebuild each drifted generated section from its
  sources, write the file in place, print one ``FIX: <section>: ...``
  line per repair. Editorial sections are never rewritten. Exit is 1
  whenever drift was found (even though it is now fixed) so callers
  notice; exit 0 when the sheet was already in sync.
- ``--json``       print ``{"file", "ok", "drift_count", "drifts"[,
  "fixed"]}`` instead of prose lines.

An optional positional path overrides the cheat sheet location (the
self-test and ``uxr-cheatsheet`` use it against scratch copies).

Exit codes: 0 in sync, 1 drift found, 2 usage, 4 self-test failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

CHEATSHEET_RELATIVE = Path("docs") / "cheat-sheet.html"
COMMANDS_DIR = PLUGIN_ROOT / "commands"
EDIT_COMMAND = "uxr-edit.md"
CONFIG_FILE = PLUGIN_ROOT / "config" / "org.example.yaml"
PHASE_GATES_FILE = PLUGIN_ROOT / "lib" / "phase_gates.py"
METHODS_FILE = PLUGIN_ROOT / "prompts" / "classify" / "methods.json"
OVERVIEW_FILE = PLUGIN_ROOT / "templates" / "workspace" / "00-overview.md"

GENERATED_SECTIONS = ("commands", "flags", "shorthands", "fields", "workflow", "methods", "template")

FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")
SHORTHAND_RE = re.compile(r"`([a-z][a-z0-9_]*)(\+=|-=|~=|=)")
ARG_HINT_RE = re.compile(r"^argument-hint:\s*(.+)$", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
COUNT_WORD_RE = re.compile(r"(\d+)\s+command")
PHASE_ORDER_RE = re.compile(r"REFERENCE_PHASE_ORDER[^=]*=\s*\(([^)]*)\)", re.DOTALL)
SECTION_RE = {
    name: re.compile(
        r"(<section[^>]*data-generated=\"" + name + r"\"[^>]*>)(.*?)(</section>)",
        re.DOTALL,
    )
    for name in GENERATED_SECTIONS
}
FLAG_ROW_RE = re.compile(r"<tr><td><code>(uxr-[a-z-]+)</code></td><td>(.*?)</td></tr>")


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


def command_files() -> list[Path]:
    """Every command markdown file, sorted by name."""
    if not COMMANDS_DIR.is_dir():
        return []
    return sorted(COMMANDS_DIR.glob("uxr-*.md"))


def command_names() -> list[str]:
    """Command names (file stems, e.g. ``uxr-deck``)."""
    return [path.stem for path in command_files()]


def command_flags() -> dict[str, list[str]]:
    """``{command name: [flags]}`` from each file's ``argument-hint``."""
    result: dict[str, list[str]] = {}
    for path in command_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        match = ARG_HINT_RE.search(text)
        hint = match.group(1) if match else ""
        flags: list[str] = []
        for flag in FLAG_RE.findall(hint):
            if flag not in flags:
                flags.append(flag)
        result[path.stem] = flags
    return result


def edit_shorthands() -> list[str]:
    """Shorthand keys (``history=``, ``roster+=``, ...) from the edit command."""
    path = COMMANDS_DIR / EDIT_COMMAND
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^## Shorthand keys(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL)
    section = match.group(1) if match else text
    result: list[str] = []
    for key, op in SHORTHAND_RE.findall(section):
        token = key + op
        if token not in result:
            result.append(token)
    return result


def field_values() -> dict[str, list[str]]:
    """``{field: values}`` for fields that declare values, from the config example."""
    try:
        import yaml

        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        return {}
    result: dict[str, list[str]] = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        values = spec.get("values")
        if isinstance(values, list) and values:
            result[str(name)] = [str(value) for value in values]
    return result


def workflow_statuses() -> list[str]:
    """Reference phase names plus every non-empty status list in the config."""
    statuses: list[str] = []
    match = PHASE_ORDER_RE.search(PHASE_GATES_FILE.read_text(encoding="utf-8", errors="replace"))
    if match:
        for name in re.findall(r"\"([^\"]+)\"", match.group(1)):
            if name not in statuses:
                statuses.append(name)
    try:
        import yaml

        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return statuses
    if not isinstance(data, dict):
        return statuses
    workflow = data.get("workflow") or {}
    recruits = (data.get("recruit") or {}).get("statuses") or {}
    candidates: list = []
    if isinstance(workflow, dict):
        candidates.append(workflow.get("initial_status"))
        candidates.extend(workflow.get("phase_order") or [])
        candidates.extend(workflow.get("script_status_candidates") or [])
    if isinstance(recruits, dict):
        for value in recruits.values():
            candidates.extend(value if isinstance(value, list) else [])
    for value in candidates:
        text = str(value) if value else ""
        if text and text not in statuses:
            statuses.append(text)
    return statuses


def method_rows() -> list[tuple[str, str]]:
    """``(dominant RQ shape, method)`` pairs from the method data file."""
    data = json.loads(METHODS_FILE.read_text(encoding="utf-8"))
    return [(str(rule.get("shape", "")), str(rule.get("method", "")))
            for rule in data.get("rules") or []]


def template_sections() -> list[str]:
    """The ``## `` section names of the workspace overview template."""
    text = OVERVIEW_FILE.read_text(encoding="utf-8", errors="replace")
    names: list[str] = []
    for name in HEADING_RE.findall(text):
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# section builders (the generated HTML; also render the shipped document)
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_commands_section(names: list[str]) -> str:
    purposes = {
        "uxr-cheatsheet": "Re-sync this cheat sheet from its sources (validator plus targeted fixes).",
        "uxr-debrief": "Verify the session, file the transcript, write the per-session summary.",
        "uxr-deck": "Generate an audience-shaped slide deck from a finished study.",
        "uxr-edit": "Edit one study ticket with shorthand keys.",
        "uxr-eod": "Draft the end-of-day ticket comments.",
        "uxr-feedback": "File a bug or idea against the plugin repository.",
        "uxr-init": "Scaffold the local study workspace.",
        "uxr-mine": "List my open study tickets.",
        "uxr-move": "Move a study to its next phase, gated on readiness.",
        "uxr-new": "Guided interview that creates a study ticket and workspace.",
        "uxr-notebook": "Upload study files to NotebookLM and run saved prompts.",
        "uxr-onboard": "One-shot onboarding: save the adapters, fields, calculator, and privacy, workspace, and recruit config once.",
        "uxr-recruit": "Fill the study: internal slots or the external funnel.",
        "uxr-report": "Write the stakes-sized research report.",
        "uxr-show": "Render one study ticket.",
        "uxr-stats": "Adoption rollup over session journals.",
        "uxr-trace": "Show the evidence trail for a study, file, source, or project.",
    }
    rows = "\n".join(
        f"<tr><td><code>{_esc(name)}</code></td><td>{_esc(purposes.get(name, 'See the command page.'))}</td></tr>"
        for name in names
    )
    count = len(names)
    return (
        f'<p class="count"><strong>{count} commands</strong>; every name is a '
        f"<code>/uxr-plugin:...</code> slash command.</p>\n"
        f'<table class="grid"><thead><tr><th>Command</th><th>What it does</th></tr></thead>\n'
        f"<tbody>\n{rows}\n</tbody></table>"
    )


def build_flags_section(flags: dict[str, list[str]]) -> str:
    rows = "\n".join(
        "<tr><td><code>{name}</code></td><td>{flags}</td></tr>".format(
            name=_esc(name),
            flags=_esc(" ".join(values)) if values else "<em>none</em>",
        )
        for name, values in sorted(flags.items())
    )
    return (
        "<p>Flags each command accepts (from the command's "
        "<code>argument-hint</code>; pass values as <code>--flag=value</code>).</p>\n"
        '<table class="grid"><thead><tr><th>Command</th><th>Flags</th></tr></thead>\n'
        f"<tbody>\n{rows}\n</tbody></table>"
    )


def build_shorthands_section(shorthands: list[str]) -> str:
    chips = "".join(f'<code class="chip">{_esc(token)}</code> ' for token in shorthands)
    return (
        "<p>Edit shorthands (from <code>commands/uxr-edit.md</code>): "
        "<code>=</code> sets, <code>+=</code> appends, <code>-=</code> removes, "
        "<code>~=</code> patches one matched row or label.</p>\n"
        f'<p class="chips">{chips}</p>'
    )


def build_fields_section(fields: dict[str, list[str]]) -> str:
    rows = "\n".join(
        "<tr><td><code>{name}</code></td><td>{values}</td></tr>".format(
            name=_esc(name),
            values=_esc(" &#183; ".join(values)),
        )
        for name, values in sorted(fields.items())
    )
    return (
        "<p>Study field values (from <code>config/org.example.yaml</code>; "
        "your <code>org.yaml</code> may extend them).</p>\n"
        '<table class="grid"><thead><tr><th>Field</th><th>Values</th></tr></thead>\n'
        f"<tbody>\n{rows}\n</tbody></table>"
    )


def build_workflow_section(statuses: list[str]) -> str:
    chips = "".join(f'<code class="chip">{_esc(name)}</code> ' for name in statuses)
    return (
        "<p>Study workflow statuses: the reference phase order ships in "
        "<code>lib/phase_gates.py</code>; your <code>workflow.phase_order</code> "
        "replaces it when set. Move gates check readiness before each phase.</p>\n"
        f'<p class="chips">{chips}</p>'
    )


def build_methods_section(rows: list[tuple[str, str]]) -> str:
    body = "\n".join(
        f"<tr><td>{_esc(shape)}</td><td>{_esc(method)}</td></tr>"
        for shape, method in rows
    )
    return (
        "<p>Method rows (from <code>prompts/classify/methods.json</code>): "
        "pick the row for the dominant research question shape.</p>\n"
        '<table class="grid"><thead><tr><th>Dominant RQ shape</th><th>Method</th></tr></thead>\n'
        f"<tbody>\n{body}\n</tbody></table>"
    )


def build_template_section(sections: list[str]) -> str:
    items = "\n".join(f"<li><code>{_esc(name)}</code></li>" for name in sections)
    return (
        "<p>Every study workspace (<code>templates/workspace/00-overview.md</code>) "
        "carries the same sections, in this order:</p>\n"
        f'<ol class="diagram">\n{items}\n</ol>'
    )


def collect_sources() -> dict:
    """Every generated section's source data, read fresh from the repo."""
    return {
        "commands": command_names(),
        "flags": command_flags(),
        "shorthands": edit_shorthands(),
        "fields": field_values(),
        "workflow": workflow_statuses(),
        "methods": method_rows(),
        "template": template_sections(),
    }


BUILDERS = {
    "commands": lambda sources: build_commands_section(sources["commands"]),
    "flags": lambda sources: build_flags_section(sources["flags"]),
    "shorthands": lambda sources: build_shorthands_section(sources["shorthands"]),
    "fields": lambda sources: build_fields_section(sources["fields"]),
    "workflow": lambda sources: build_workflow_section(sources["workflow"]),
    "methods": lambda sources: build_methods_section(sources["methods"]),
    "template": lambda sources: build_template_section(sources["template"]),
}


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def _section_html(html: str, section: str) -> str:
    match = SECTION_RE[section].search(html)
    return match.group(2) if match else ""


def _section_exists(html: str, section: str) -> bool:
    return SECTION_RE[section].search(html) is not None


def check_section(section: str, sources: dict, html: str) -> list[dict]:
    """Drift entries for one generated section ([] means in sync)."""
    drifts: list[dict] = []

    def add(kind: str, detail: str, expected, actual) -> None:
        drifts.append({"section": section, "kind": kind, "detail": detail, "expected": expected, "actual": actual})

    inner = _section_html(html, section)
    if _section_exists(html, section) is False:
        add("missing-section", f"the {section} section is missing from the document", section, None)
        return drifts

    if section == "commands":
        names = sources["commands"]
        count_match = COUNT_WORD_RE.search(inner)
        if not count_match or int(count_match.group(1)) != len(names):
            add(
                "count-word",
                "the command count word does not match commands/uxr-*.md",
                f"{len(names)} commands",
                count_match.group(0) if count_match else None,
            )
        for name in names:
            if f"<code>{name}</code>" not in inner:
                add("missing-command", f"command {name} is missing from the section", name, None)
    elif section == "flags":
        rows = {name: cell for name, cell in FLAG_ROW_RE.findall(inner)}
        for name, flags in sorted(sources["flags"].items()):
            if name not in rows:
                add("missing-row", f"no flag table row for {name}", name, None)
                continue
            for flag in flags:
                if flag not in rows[name]:
                    add("missing-flag", f"{name}: flag {flag} is missing from the flag table", flag, None)
    elif section == "shorthands":
        for token in sources["shorthands"]:
            if f"<code class=\"chip\">{token}</code>" not in inner:
                add("missing-shorthand", f"edit shorthand {token} is missing", token, None)
    elif section == "fields":
        for name, values in sorted(sources["fields"].items()):
            if f"<code>{name}</code>" not in inner:
                add("missing-field", f"field {name} is missing from the section", name, None)
                continue
            for value in values:
                if value not in inner:
                    add("missing-value", f"field {name}: value {value!r} is missing", value, None)
    elif section == "workflow":
        for name in sources["workflow"]:
            if name not in inner:
                add("missing-status", f"workflow status {name!r} is missing", name, None)
    elif section == "methods":
        for shape, method in sources["methods"]:
            if shape not in inner or method not in inner:
                add(
                    "missing-method-row",
                    f"method row ({shape} -> {method}) is missing or altered",
                    [shape, method],
                    None,
                )
    elif section == "template":
        for name in sources["template"]:
            if f"<code>{_esc(name)}</code>" not in inner:
                add("missing-template-section", f"template section {name!r} is missing", name, None)
    return drifts


def check_all(sources: dict, html: str) -> list[dict]:
    drifts: list[dict] = []
    for section in GENERATED_SECTIONS:
        drifts.extend(check_section(section, sources, html))
    return drifts


def remediate(html: str, sources: dict) -> tuple[str, list[str]]:
    """Rebuild every drifted generated section; returns (new html, FIX lines)."""
    fixed: list[str] = []
    result = html
    for section in GENERATED_SECTIONS:
        drifts = check_section(section, sources, result)
        if not drifts:
            continue
        rebuilt = BUILDERS[section](sources)
        match = SECTION_RE[section].search(result)
        if match is None:
            continue
        result = result[: match.start(2)] + rebuilt + result[match.end(2):]
        fixed.append(f"FIX {section}: rebuilt from sources ({len(drifts)} drift item(s))")
    return result, fixed


# ---------------------------------------------------------------------------
# document assembly (generated sections + editorial content)
# ---------------------------------------------------------------------------

CSS = """
:root { --ink: #1c2430; --muted: #5a6572; --line: #d9dee5; --accent: #0b5fa5; --soft: #f4f7fa; }
* { box-sizing: border-box; }
body { font: 15px/1.5 "Segoe UI", system-ui, sans-serif; color: var(--ink); margin: 0 auto; max-width: 980px; padding: 24px 20px 60px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 28px 0 8px; padding-bottom: 4px; border-bottom: 2px solid var(--line); }
p.lede { color: var(--muted); margin: 0 0 12px; }
section { margin-bottom: 8px; }
table.grid { border-collapse: collapse; width: 100%; margin: 8px 0; }
table.grid th, table.grid td { border: 1px solid var(--line); padding: 6px 9px; text-align: left; vertical-align: top; }
table.grid th { background: var(--soft); }
code { background: var(--soft); border: 1px solid var(--line); border-radius: 3px; padding: 1px 5px; font-size: 13px; }
code.chip { display: inline-block; margin: 2px 4px 2px 0; }
p.count { color: var(--muted); }
ol.diagram { border: 1px solid var(--line); border-radius: 6px; background: var(--soft); padding: 12px 12px 12px 34px; }
ol.diagram li { margin: 3px 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; background: var(--soft); }
.card h3 { margin: 0 0 4px; font-size: 15px; }
.card p { margin: 0; color: var(--muted); font-size: 13.5px; }
details { border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; margin: 6px 0; }
summary { cursor: pointer; font-weight: 600; }
footer { margin-top: 36px; color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--line); padding-top: 10px; }
"""

EDITORIAL_SECTIONS = """
<section id="phases">
<h2>Interview phases (new)</h2>
<p>The <code>new</code> interview moves through these phases; every
listens for edits and never creates without a preview.</p>
<ol>
<li><strong>Scope</strong> - one message, three questions: working title, group or area, decision owner.</li>
<li><strong>Evidence sweep</strong> - every source in one parallel batch; failed sources log one skipped line.</li>
<li><strong>Shareability</strong> - each Drive link tagged shared, private, or unknown; permissions never change.</li>
<li><strong>Background</strong> - a 3 to 5 sentence draft, edited before moving on.</li>
<li><strong>Key decision</strong> - one sentence that names what changes and who owns it.</li>
<li><strong>Hypotheses and assumptions</strong> - 3 to 5 falsifiable hypotheses, 2 to 3 assumptions, as <code>Label. Claim.</code></li>
<li><strong>Research questions</strong> - 3 to 6 open questions with the RQ-to-hypothesis map; the HCD reviewer checks the set.</li>
<li><strong>Method, fields, create</strong> - the method table row, the field panel, a preview, then create and init on your go.</li>
</ol>
</section>

<section id="roles">
<h2>Role cards</h2>
<div class="cards">
<div class="card"><h3>hcd-researcher</h3><p>Human-centered design review of drafts and studies; strengths, risks, and changes with confidence-rated findings.</p></div>
<div class="card"><h3>stakeholder-reviewer</h3><p>Reads a report as one role (PD, EM, PM, Leadership) and returns 3 to 7 cited bullets.</p></div>
<div class="card"><h3>novice-report-reader</h3><p>First-time reader of the rendered report; flags orientation, terms, and dead ends.</p></div>
<div class="card"><h3>research-dataviz-designer</h3><p>Reviews charts and HTML rendering: chart type, contrast, disclosure structure.</p></div>
<div class="card"><h3>expert-participant</h3><p>Synthetic expert user for script dry runs; flags over-explanation and redundant questions.</p></div>
<div class="card"><h3>novice-participant</h3><p>Synthetic first-time user; flags unfamiliar terms and ambiguous instructions.</p></div>
<div class="card"><h3>script-writer</h3><p>Applies the reviewers' minimal fixes to the interview script without changing structure.</p></div>
</div>
</section>

<section id="faq">
<h2>FAQ</h2>
<details open><summary>Where does my data live?</summary>
<p>Study specs live in <code>&lt;state_dir&gt;/specs/</code>, session journals in
<code>&lt;state_dir&gt;</code>, and per-study files in the workspace folder
<code>init</code> creates. Participant keys and raw transcripts are
gitignored and never committed.</p></details>
<details><summary>Why does everything arrive as a draft?</summary>
<p>Comments, chat messages, mail, decks, and publishes wait for your
explicit <code>go</code>. The plugin computes; you decide.</p></details>
<details><summary>What is the spec file?</summary>
<p>The JSON source of truth for a study ticket (<code>&lt;state_dir&gt;/specs/&lt;KEY&gt;.spec.json</code>).
Edits patch it, validate it, and push the rendered body in one write.</p></details>
<details><summary>How is a deck produced?</summary>
<p>From an outline JSON by the deck generator with a geometry lint.
The <code>.pptx</code> is always regenerated, never hand-edited, and
holds no raster images.</p></details>
<details><summary>What broke the cheat sheet?</summary>
<p>Nothing should: <code>uxr-cheatsheet</code> re-syncs this page from
its sources on demand and never rewrites the editorial sections.</p></details>
</section>
"""


def build_document() -> str:
    """The full cheat sheet page: generated sections from live sources."""
    sources = collect_sources()
    sections = {
        "commands": BUILDERS["commands"](sources),
        "flags": BUILDERS["flags"](sources),
        "shorthands": BUILDERS["shorthands"](sources),
        "fields": BUILDERS["fields"](sources),
        "workflow": BUILDERS["workflow"](sources),
        "methods": BUILDERS["methods"](sources),
        "template": BUILDERS["template"](sources),
    }
    body = f"""
<section id="commands" data-generated="commands">
{sections['commands']}
</section>

<section id="flags" data-generated="flags">
{sections['flags']}
</section>

<section id="shorthands" data-generated="shorthands">
{sections['shorthands']}
</section>

<section id="fields" data-generated="fields">
{sections['fields']}
</section>

<section id="workflow" data-generated="workflow">
{sections['workflow']}
</section>

{EDITORIAL_SECTIONS}

<section id="methods" data-generated="methods">
{sections['methods']}
</section>

<section id="template" data-generated="template">
{sections['template']}
</section>
"""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>UX research plugin cheat sheet</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n"
        "<h1>UX research plugin cheat sheet</h1>\n"
        '<p class="lede">One page for every command, flag, shorthand, field value, '
        "workflow status, method row, and workspace section. Generated sections "
        "re-sync from their sources with <code>uxr-cheatsheet</code>.</p>\n"
        f"{body}\n"
        "<footer>Generated sections carry <code>data-generated</code> and are "
        "checked by <code>scripts/validate_cheatsheet.py</code>; the interview "
        "phases, role cards, and FAQ are editorial.</footer>\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_sheet(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _print_lines(drifts: list[dict], fixed: list[str], verbose: bool) -> None:
    if verbose:
        for section in GENERATED_SECTIONS:
            if not any(d["section"] == section for d in drifts):
                print(f"[ok] {section}")
    for drift in drifts:
        expected = drift["expected"]
        print(f"DRIFT {drift['section']}: {drift['detail']} (expected: {expected})")
    for line in fixed:
        print(line)
    if not drifts and not fixed:
        print("cheat sheet is in sync with its sources")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        pass  # bare invocation: run the default check
    elif args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK
    verbose = "--verbose" in args
    remediate_flag = "--remediate" in args
    json_flag = "--json" in args
    positional = [a for a in args if not a.startswith("--")]
    unknown = [a for a in args if a.startswith("--") and a not in ("--verbose", "--remediate", "--json")]
    if unknown or len(positional) > 1:
        print(f"validate_cheatsheet: unknown argument(s): {' '.join(unknown + positional[1:])}", file=sys.stderr)
        print("usage: validate_cheatsheet.py [--verbose] [--remediate] [--json] [path]", file=sys.stderr)
        return EXIT_USAGE
    path = Path(positional[0]).expanduser() if positional else PLUGIN_ROOT / CHEATSHEET_RELATIVE
    if not path.is_file():
        print(f"validate_cheatsheet: cheat sheet not found: {path}", file=sys.stderr)
        return EXIT_USAGE

    sources = collect_sources()
    html = _load_sheet(path)
    drifts = check_all(sources, html)
    fixed: list[str] = []
    if drifts and remediate_flag:
        new_html, fixed = remediate(html, sources)
        if fixed:
            path.write_text(new_html, encoding="utf-8")
    if json_flag:
        payload: dict = {
            "file": str(path),
            "ok": not drifts,
            "drift_count": len(drifts),
            "drifts": drifts,
        }
        if remediate_flag:
            payload["fixed"] = fixed
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_lines(drifts, fixed, verbose)
    return EXIT_DRIFT if drifts else EXIT_OK


# ---------------------------------------------------------------------------
# self-test (offline; writes only into a tempdir)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(main())
