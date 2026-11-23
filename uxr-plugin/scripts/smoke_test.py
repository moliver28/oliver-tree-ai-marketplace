#!/usr/bin/env python3
"""All-local smoke gate for the uxr-plugin.

Run from the repo root: ``python scripts/smoke_test.py``. The gate makes
no network call and writes nothing (no tracker, no chat, no files) --
scripts compute; commands write.

Checks, in order:

1. The version in ``plugin.json``, the README line ``currently vX.Y.Z``,
   and the first CHANGELOG heading are equal.
2. The command count and skill count meet the minimum. Placeholder
   ``.gitkeep`` files count until real commands and skills land; raise
   ``MIN_COMMANDS`` / ``MIN_SKILLS`` as components ship.
3. Every selftest target runs with a 10 second timeout and exits 0.
   Targets: shipped lib/references/hooks/scripts files still carrying the
   ``selftest`` token (residual), plus the repo-level
   ``tests/uxr_selftests/*.py`` modules when present. A standalone install
   (no repo tests/, no residual selftests) records one SKIP.
4. Every JSON schema in ``references/`` passes ``check_schema``
   (skipped when ``jsonschema`` is not installed).
5. Every agent and skill file has YAML front matter that parses, and
   every ``description`` value is quoted. Unquoted colons broke
   ``claude plugin validate`` in the reference plugin.
6. No file in ``scripts/`` contains a tracker write call name (for
   example ``createJiraIssue``). Scripts compute; commands write.
7. Recruitment and outreach templates contain no em dash or en dash.

Exit 0 on pass, 1 on fail. A skip is not a fail.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

#: Minimum shipped commands and skills (check 2). Placeholder ``.gitkeep``
#: files count until real command and skill files land; raise these floors
#: as the components ship (orchestrator bumps at wave 6).
MIN_COMMANDS = 16
MIN_SKILLS = 3

SELFTEST_TIMEOUT_SECONDS = 10

README_VERSION_RE = re.compile(r"currently\s+v(\d+\.\d+\.\d+)")
CHANGELOG_VERSION_RE = re.compile(r"^##\s+\[?(\d+\.\d+\.\d+)\]?")

#: Tracker write call names. Their presence in ``scripts/`` fails check 6:
#: scripts compute, commands write.
TRACKER_WRITE_CALLS = (
    "createJiraIssue",
    "updateJiraIssue",
    "deleteJiraIssue",
    "createLinearIssue",
    "updateLinearIssue",
    "deleteLinearIssue",
    "createGitHubIssue",
    "updateGitHubIssue",
    "deleteGitHubIssue",
    "createAsanaTask",
    "updateAsanaTask",
    "deleteAsanaTask",
    "createTicket",
    "updateTicket",
    "transitionTicket",
    "transitionIssue",
    "addTrackerComment",
    "postTrackerComment",
)

#: Em dash and en dash (check 7).
DASHES = ("\u2014", "\u2013")

_TEMPLATE_SUFFIXES = (".md", ".txt", ".json", ".yaml", ".yml", ".html")
_TEMPLATE_KEYWORDS = ("recruit", "outreach", "wave")

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    suffix = f" ({detail})" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def check_versions() -> None:
    """Check 1: plugin.json == README 'currently vX.Y.Z' == first CHANGELOG heading."""
    manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    manifest_version = str(manifest.get("version", ""))
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    match = README_VERSION_RE.search(readme)
    readme_version = match.group(1) if match else ""
    changelog_version = ""
    for line in (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        match = CHANGELOG_VERSION_RE.match(line)
        if match:
            changelog_version = match.group(1)
            break
    if manifest_version and manifest_version == readme_version == changelog_version:
        record("ok", f"version triple matches ({manifest_version})")
    else:
        record(
            "FAIL",
            "version triple matches",
            f"plugin.json={manifest_version!r} README={readme_version!r} "
            f"CHANGELOG={changelog_version!r}",
        )


def check_component_counts() -> None:
    """Check 2: command and skill counts meet the minimum."""
    commands_dir = PLUGIN_ROOT / "commands"
    skills_dir = PLUGIN_ROOT / "skills"
    command_count = len(list(commands_dir.iterdir())) if commands_dir.is_dir() else 0
    skill_count = (
        len([p for p in skills_dir.rglob("*") if p.is_file()]) if skills_dir.is_dir() else 0
    )
    if command_count >= MIN_COMMANDS:
        record("ok", f"command count {command_count} >= {MIN_COMMANDS}")
    else:
        record(
            "FAIL",
            f"command count {command_count} >= {MIN_COMMANDS}",
            "no commands under commands/ yet",
        )
    if skill_count >= MIN_SKILLS:
        record("ok", f"skill count {skill_count} >= {MIN_SKILLS}")
    else:
        record(
            "FAIL",
            f"skill count {skill_count} >= {MIN_SKILLS}",
            "no skills under skills/ yet",
        )


def _run_selftest(path: Path) -> tuple[bool, str]:
    """Run one script's self-test; accept the flag or the subcommand."""
    proc = None
    for args in (["--selftest"], ["selftest"]):
        try:
            proc = subprocess.run(
                [sys.executable, str(path), *args],
                cwd=str(PLUGIN_ROOT),
                capture_output=True,
                text=True,
                timeout=SELFTEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return False, f"timed out after {SELFTEST_TIMEOUT_SECONDS}s"
        except OSError as exc:
            return False, str(exc)
        if proc.returncode == 0:
            return True, ""
    output = (proc.stderr or proc.stdout or "").strip().splitlines()
    # Surface the failing checks themselves, not just the summary line.
    failed = [line for line in output if "[FAIL]" in line]
    detail = " | ".join(failed[-6:] if failed else output[-3:])
    return False, f"exit {proc.returncode}: {detail or 'no output'}"


def check_selftests() -> None:
    """Check 3: every selftest target passes within 10 seconds.

    Targets are (a) shipped lib/references/hooks/scripts files still
    carrying the ``selftest`` token (residual), plus (b) the repo-level
    ``tests/uxr_selftests/*.py`` modules when present. A standalone install
    (no repo tests/, no residual selftests) records one SKIP, not a FAIL.
    """
    residual = []
    for sub in ("lib", "scripts", "hooks", "references"):
        directory = PLUGIN_ROOT / sub
        if not directory.is_dir():
            continue
        residual.extend(
            p
            for p in sorted(directory.glob("*.py"))
            if p.name != "smoke_test.py"
            and "selftest" in p.read_text(encoding="utf-8", errors="replace")
        )
    extracted_dir = PLUGIN_ROOT.parent / "tests" / "uxr_selftests"
    extracted = (
        [p for p in sorted(extracted_dir.glob("*.py")) if p.name != "_harness.py"]
        if extracted_dir.is_dir()
        else []
    )
    targets = [(p, p.relative_to(PLUGIN_ROOT).as_posix()) for p in residual]
    targets += [(p, p.relative_to(PLUGIN_ROOT.parent).as_posix()) for p in extracted]
    if not targets:
        record("SKIP", "every selftest target passes its self-test", "no selftest targets")
        return
    failures = []
    for path, label in targets:
        ok, detail = _run_selftest(path)
        if ok:
            record("ok", f"{label} selftest")
        else:
            record("FAIL", f"{label} selftest", detail)
            failures.append(label)
    if failures:
        record("FAIL", "all selftest targets pass", ", ".join(failures))


def check_schemas() -> None:
    """Check 4: every JSON schema in references/ passes check_schema."""
    try:
        import jsonschema
    except ImportError:
        record(
            "SKIP",
            "every JSON schema in references/ passes check_schema",
            "jsonschema is not installed",
        )
        return
    references = PLUGIN_ROOT / "references"
    schemas = sorted(references.rglob("*.json")) if references.is_dir() else []
    if not schemas:
        record(
            "SKIP",
            "every JSON schema in references/ passes check_schema",
            "no schema files yet",
        )
        return
    failures = []
    for path in schemas:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            validator = jsonschema.validators.validator_for(schema)
            validator.check_schema(schema)
            record("ok", f"{path.relative_to(PLUGIN_ROOT).as_posix()} schema")
        except Exception as exc:
            record(
                "FAIL",
                f"{path.relative_to(PLUGIN_ROOT).as_posix()} schema",
                str(exc),
            )
            failures.append(path.name)


def _front_matter(text: str) -> str:
    """Return the raw YAML front matter block, or raise ValueError."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("file does not start with a '---' front matter block")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index])
    raise ValueError("front matter block is never closed")


def check_front_matter() -> None:
    """Check 5: agent and skill front matter parses; descriptions are quoted."""
    try:
        import yaml
    except ImportError:
        record(
            "SKIP",
            "agent and skill front matter parses with quoted descriptions",
            "pyyaml is not installed",
        )
        return
    files: list[Path] = []
    agents_dir = PLUGIN_ROOT / "agents"
    if agents_dir.is_dir():
        files.extend(agents_dir.rglob("*.md"))
    skills_dir = PLUGIN_ROOT / "skills"
    if skills_dir.is_dir():
        files.extend(skills_dir.rglob("SKILL.md"))
    files = sorted(set(files))
    if not files:
        record(
            "SKIP",
            "agent and skill front matter parses with quoted descriptions",
            "no agent or skill files yet",
        )
        return
    failures = []
    for path in files:
        label = path.relative_to(PLUGIN_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            block = _front_matter(text)
            data = yaml.safe_load(block)
            if not isinstance(data, dict):
                raise ValueError("front matter must be a mapping")
        except Exception as exc:
            record("FAIL", f"{label} front matter parses", str(exc))
            failures.append(label)
            continue
        record("ok", f"{label} front matter parses")
        unquoted = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("description:"):
                value = stripped[len("description:"):].strip()
                if value and not value.startswith(('"', "'")):
                    unquoted.append(stripped)
        if unquoted:
            detail = "unquoted description: " + "; ".join(unquoted)
            record("FAIL", f"{label} descriptions are quoted", detail)
            failures.append(label)
        else:
            record("ok", f"{label} descriptions are quoted")


def check_no_tracker_writes() -> None:
    """Check 6: no tracker write call name appears in scripts/."""
    scripts_dir = PLUGIN_ROOT / "scripts"
    scripts = (
        [p for p in scripts_dir.glob("*.py") if p.name != "smoke_test.py"]
        if scripts_dir.is_dir()
        else []
    )
    if not scripts:
        record("SKIP", "no tracker write calls in scripts/", "no scripts found")
        return
    offenders = []
    for path in scripts:
        text = path.read_text(encoding="utf-8", errors="replace")
        for call in TRACKER_WRITE_CALLS:
            if call in text:
                offenders.append(f"{path.name} calls {call}")
    if offenders:
        record("FAIL", "no tracker write calls in scripts/", "; ".join(offenders))
    else:
        record("ok", "no tracker write calls in scripts/")


def check_template_dashes() -> None:
    """Check 7: recruitment and outreach templates hold no em or en dash."""
    templates = PLUGIN_ROOT / "templates"
    if not templates.is_dir():
        record(
            "SKIP",
            "recruitment and outreach templates hold no em or en dash",
            "templates/ does not exist yet",
        )
        return
    targeted = [
        path
        for path in sorted(templates.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in _TEMPLATE_SUFFIXES
        and any(
            keyword in path.relative_to(PLUGIN_ROOT).as_posix().lower()
            for keyword in _TEMPLATE_KEYWORDS
        )
    ]
    if not targeted:
        record(
            "SKIP",
            "recruitment and outreach templates hold no em or en dash",
            "no recruitment or outreach templates yet",
        )
        return
    offenders = []
    for path in targeted:
        label = path.relative_to(PLUGIN_ROOT).as_posix()
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            found = [dash for dash in DASHES if dash in line]
            if found:
                offenders.append(f"{label}:{number} uses {found[0]!r}")
    if offenders:
        record("FAIL", "recruitment and outreach templates hold no em or en dash",
               "; ".join(offenders[:5]))
    else:
        record("ok", "recruitment and outreach templates hold no em or en dash")


def main() -> int:
    print("scripts/smoke_test.py")
    checks = (
        check_versions,
        check_component_counts,
        check_selftests,
        check_schemas,
        check_front_matter,
        check_no_tracker_writes,
        check_template_dashes,
    )
    for check in checks:
        try:
            check()
        except Exception as exc:
            record("FAIL", check.__name__, f"unexpected error: {exc}")
    failed = [entry for entry in results if entry[0] == "FAIL"]
    skipped = [entry for entry in results if entry[0] == "SKIP"]
    if failed:
        print(f"smoke FAILED ({len(failed)} check(s), {len(skipped)} skipped)")
        return 1
    print(f"smoke: all checks passed ({len(skipped)} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
