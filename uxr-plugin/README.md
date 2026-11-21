# uxr-plugin

UX research operations plugin for Claude Code, currently v0.2.0.

One plugin for the research lifecycle: study tickets, specs, recruitment, interview scripts, reports, and decks. Code owns the rules (deterministic scripts; their offline selftests live in the repo's tests/uxr_selftests/); the model owns judgment. Drafts, never sends. Hooks fail open; exclusions fail closed. See docs/ARCHITECTURE.md for the vocabulary and principles.

## Install

From a marketplace, once one is published for this plugin:

```bash
claude plugin marketplace add <owner>/<marketplace-repo>
claude plugin install uxr-plugin
```

During development, load the plugin in place from a checkout:

```bash
claude --plugin-dir /path/to/uxr-plugin
```

Install paths may contain spaces; every hook command quotes the script path for exactly that reason.

## Verify

```bash
claude plugin validate .          # manifest and component paths
python3 scripts/smoke_test.py     # the authoritative all-local gate
```

The smoke test makes no network call. It checks the version triple (manifest, README, CHANGELOG), command and skill minimums, the selftest suite (`tests/uxr_selftests/` in a checkout; skipped in a standalone install), JSON schemas, front matter, the no-tracker-writes rule for `scripts/`, and dash-free recruitment templates. Exit 0 on pass.

## Configure

The config contract ships placeholders for every key. Copy it once and fill in your organization's real values (the copy is gitignored):

```bash
cp config/org.example.yaml config/org.yaml
```

Fill the values by hand from the contract comments (there is no wizard); verify the result with `python3 lib/config.py --print`, which dumps the resolved configuration and fails loudly on a missing key. Every command, script, and hook reads configuration through that one loader, `lib/config.py:load_config()`; environment overrides use `UXR_CONFIG__SECTION__KEY=value`.

## Quick start

1. Configure `config/org.yaml` (or export `UXR_RESEARCH_DIRS`, entries separated by the platform path separator).
2. Open a Claude Code session inside a study folder -- any folder under a research root, or any folder (or a parent below your home directory) holding `00-overview.md`.
3. The SessionStart hook injects a short context block: the commands, the tracker constants, and the routing note. Outside research folders the plugin stays silent.

## Commands

| Command | What it does |
|---|---|
| `/uxr-new` | Guided interview with evidence sweep; validates the spec, then creates the ticket |
| `/uxr-mine` | Your open studies (closed states excluded; `all` to include them) |
| `/uxr-show KEY` | One ticket rendered from spec order, UXR fields first, newest 5 comments |
| `/uxr-edit KEY` | Edit via shorthand; drift check, validate, diff-preview gate, full-body push |
| `/uxr-move KEY PHASE` | Phase transitions gated on ticket readiness (`check` shows blockers) |
| `/uxr-init KEY` | Local study workspace from `templates/workspace/` (spec guard, gitignore gate) |
| `/uxr-recruit KEY` | Roster statuses, outreach drafts, calendar holds, fail-closed preflight |
| `/uxr-debrief KEY` | File the transcript, insight recap, upload plan (dry-run first) |
| `/uxr-notebook KEY` | NotebookLM stage prompts (browser skill; sign-in stop, never credentials) |
| `/uxr-report KEY` | Tiered report, HTML render with citation checks, one HCD gate, publish |
| `/uxr-deck KEY` | Persona-capped deck outline and pptx scaffold (`--dry-run` first) |
| `/uxr-cheatsheet` | Cheat sheet rebuilt from sources; drift check with explicit `go` |
| `/uxr-eod` | End-of-day draft from today's journal (dry-run; nothing posts automatically) |
| `/uxr-trace KEY` | Provenance: sources read, outputs written, per journal + transcripts |
| `/uxr-stats` | Usage stats from journal + analytics (offline) |
| `/uxr-feedback` | File plugin feedback as a GitHub issue after explicit `go` |

All are plugin-namespaced in practice (`/uxr-plugin:uxr-new`) since Claude Code namespaces plugin commands under the plugin name.

## Hooks

Wiring lives in `hooks/hooks.json`. Every hook command is the same polyglot, fail-open chain -- valid in both POSIX sh (Claude Code) and Windows cmd.exe (the ZCode runtime on Windows runs hook command strings through cmd.exe, where the previous POSIX-only wrapper could not execute at all):

```
python "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py" || python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py" || exit 0
```

`python` is preferred (the Windows interpreter name), `python3` covers POSIX-only systems, and any total failure -- interpreter missing, script missing, script error -- exits 0, which both harnesses read as "skip, never block".

| Event | Matcher | Script | Built in issue |
|---|---|---|---|
| SessionStart | - | `ux_research_context.py` | 02 |
| SessionStart | - | `analytics_flush.py` | 09 |
| SessionEnd | - | `session_logger.py` (timeout 15) | 09 |
| SubagentStop | - | `review_gate.py`, `analytics.py` | 06, 09 |
| PreToolUse | `Write\|Edit` | `review_gate.py` | 06 |
| UserPromptExpansion | - | `analytics.py` | 09 |
| Stop | - | `session_logger.py`, `review_gate.py`, `provenance.py`, `analytics.py` | 06, 09 |
| UserPromptSubmit | - | `analytics.py` | 09 |

Hook contract: read the event JSON from stdin, catch every exception, exit 0 on any error, print nothing unless the event contract asks for output, and set an explicit `timeout` on any hook that does file work. Hooks built in later issues are wired now; the fail-open wrapper keeps the missing scripts harmless.

## Runtime compatibility

`hooks/hooks.json` carries the Claude Code event set plus additive entries for the events the ZCode runtime supports (verified against the runtime current at each release); every hook accepts either event name, and nothing Claude Code uses was removed.

On current ZCode runtimes the following hook UX works: the session journal upserts its row on `Stop` (one row per session, updated in place, the analytics summary emitted once), the HCD review gate writes its review marker from the `Stop` transcript scan and still reminds on `PreToolUse` (a Stop fire never overwrites a marker a SubagentStop wrote on Claude Code), and analytics records slash commands on `UserPromptSubmit` plus the `SessionStart` flush (where Claude Code fires both `UserPromptSubmit` and `UserPromptExpansion` for one command, a short same-session dedup window keeps the count at one).

Still Claude Code-only: the true `SessionEnd` final write of the workspace manifests (per-turn `Stop` fires keep the journal row current without them) and the `SubagentStop` agent-dispatch counter, which has no ZCode event. Acceptable: `Stop` fires each turn, so the journal stays current without `SessionEnd`. Commands, skills, agents, scripts, and all deterministic behavior are runtime-independent. Re-check support after runtime updates (`zcode plugins install` prints unsupported-event diagnostics per plugin).

## Development

- Every selftest module in `tests/uxr_selftests/` (repo checkout) passes offline; a standalone install ships no selftest code.
- `python3 scripts/smoke_test.py` is the pre-commit and CI gate.
- CI (`.github/workflows/plugin-ci.yml`) runs the smoke test plus a non-blocking `claude plugin validate` step (the CLI may require auth in CI; the smoke gate is authoritative). The workflow fires when this repo is used standalone; GitHub only reads workflows from a repository root's `.github/workflows/`, so when the plugin is vendored at a nested path the file is inert there and the local smoke gate is the authoritative check.
