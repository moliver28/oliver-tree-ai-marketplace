# Changelog

All notable changes to uxr-plugin. One `## X.Y.Z` heading per release, newest first.

## [0.1.0] - 2026-11-09

### Added

- Config contract: `config/org.example.yaml` documents every key; `lib/config.py` loads, merges, validates, and expands it, with a `--selftest`.
- Plugin skeleton: `.claude-plugin/plugin.json` manifest, `commands/` and `skills/` directories, and fail-open hook wiring in `hooks/hooks.json` (SessionStart, SessionEnd, SubagentStop, PreToolUse `Write|Edit`, UserPromptExpansion; missing scripts exit 0).
- SessionStart context hook `hooks/ux_research_context.py`: injects commands, tracker constants, and the routing note once, only inside research folders (research root from config or `UXR_RESEARCH_DIRS`, or `00-overview.md` in the cwd or a parent below `$HOME`); other events, including UserPromptSubmit, print nothing.
- All-local smoke gate `scripts/smoke_test.py`: version triple, command and skill minimums, per-script self-tests, schema checks, front matter with quoted descriptions, the no-tracker-writes rule for `scripts/`, and dash-free recruitment templates.
- CI: `.github/workflows/plugin-ci.yml` runs the smoke test on plugin-path changes plus a non-blocking `claude plugin validate` step.
