# Changelog

All notable changes to uxr-plugin. One `## X.Y.Z` heading per release, newest first.

## [0.4.0] - 2026-11-22

### Added

- Optional stdio MCP server (`mcp-server/server.py`, Phase 1): newline-delimited JSON-RPC 2.0 for local CLI harnesses (zcode, codex, claude-code, hermes-style runtimes), initialize-handshake era (protocol `2025-06-18`, with `2025-11-25` negotiation), all diagnostics on stderr, stdlib only, no network, no `lib/` imports (shells out only). Curated surface: ten tools (one per shipped script, schemas read from each script's own argument parsing; stdout returned verbatim; 60-second cap; no shell), `references/*.md` + `prompts/*/fragments/*.md` as `text/markdown` resources under `uxr://`, and `commands/*.md` as prompts. No publish or send tool (drafts never send).
- Install command (`mcp-server/install.py`): `install|uninstall|status --harness auto|zcode|codex|claude-code|hermes` with `--force` and `--dry-run`. Writes only the `uxr` entry (zcode `mcp.servers.uxr`, codex `[mcp_servers.uxr]`, claude-code user-scope `mcpServers.uxr`), preserves the file's newline style and every other key, backs up to `<config>.uxr-backup` before the first write, and is idempotent (second run exits 0 as a no-op). `status` runs a real initialize handshake against the configured server (exit 0 healthy, 1 missing, 2 broken handshake, 3 unsupported harness, 4 config error). hermes raises a clear not-wired-yet message after grounding left its config location unconfirmed for this runtime.
- Selftests `tests/uxr_selftests/mcp_server.py` (protocol surface, fixtures only) and `mcp_install.py` (install/idempotence/force/uninstall/backup/status per harness, redirected-home CLI layer, never touching a real config).

### Changed

- Version triple to 0.4.0 (manifest, README, marketplace entry); README gains the MCP server section with the per-harness config table and the law-8 update path.

## [0.3.0] - 2026-11-20

### Changed

- Hook dispatch: one interpreter spawn per multi-hook event (hooks.json rewired through `hooks/dispatch.py`; Stop went from 4 spawns to 1, measured 0.733s to 0.262s per turn).
- Selftest extraction: every `_selftest()` body, selftest-only helper, and fixture constant moved verbatim from the shipped payload to repo-level `tests/uxr_selftests/` (bound to the shipped modules via `tests/uxr_selftests/_harness.py`); the end-user install ships no QA code (~7,700 lines out of the payload). `scripts/smoke_test.py` check 3 discovers selftest targets by residual token plus the repo-level modules; standalone installs record one SKIP.
- Duplicate helpers unified into `lib/util.py` (fail-open config load, UTF-8 stdio forcing, UTC now, path resolve, research roots, workspace find, list parsing, JSON-argument loader family); each site is now an import with unchanged behavior and messages.
- Doc tail: script-rigor.md Part 1 (an unconsumed restatement) removed; intro and recap restatements trimmed in the interview-script skill and four references. All rules, gates, and verbatim strings kept.

## [0.2.0] - 2026-11-18

### Changed

- Efficiency pass (W2): the golden path across the workflow now spends six model calls (evidence signals synthesis, one structured drafts call for the `new` interview's phases 3-5, report narrative, debrief summary, and one checklist-scoped HCD gate per artifact); every previously model-rendered mechanical step (mine/show tables, evidence plan and digest, RQ map, method pick, router intent, recruit slots and replies, review-finding routing, eod drafts) is script-owned and byte-parity gated against the baseline goldens.

### Added

- Lazy-fragment prompt registry (`lib/prompts.py`) with prompt assets under `prompts/` (`config-setup`, `new-intake`, `signals`, `drafts`, `hcd-gate`, `distribution`, `outreach`), each rendered from JSON front matter with condition-matrix fixtures and metering lines (`prompt_id@version fragments=[...] est_tokens=N`).
- Data-driven render helper (`lib/render.py`, CLI folded in W2b): mine table, show card, relative-time ladder, and emoji map are JSON specs in `prompts/render/`.
- Deterministic classifiers (`scripts/classify.py` + `prompts/classify/`): router intent, recruit reply classes, method-shape table, decision-shape gate, review-finding routing.
- Evidence sweep planner and digester (`scripts/evidence_sweep.py`): emits the per-source query plan and compresses raw results into the evidence digest the signals call consumes.
- Journal scripting (`scripts/eod_journal.py`): filter, cap check, facts-only `--auto` template, and the `processed` rewrite; `--polish` opts into one narrative rewrite per ticket.
- Slot picking (`scripts/calendar_prep.py --pick`): deterministic free-gap fits on a 15-minute grid with move candidates.
- RQ-to-hypothesis map with the drop rule (`scripts/trace_prompts.py --rq-map`).
- Scripted spec save/read-back (`scripts/backfill_spec.py save-spec|check-readback`) and debrief summary/recap assembly (`references/debrief_helpers.py assemble-summary|render-recap`).
- Golden parity gates: `tests/goldens/` (baseline artifacts, `DIFFERS`-marked where W1 changed behavior), hash pins, and the parametrized runner `tests/test_parity.py`, wired into the repo verifier.

### Removed

- The `/uxr-new` reference stack (`research-craft.md` deleted; its method table lives in `prompts/classify/methods.json`), the inline eod and new heredocs, the duplicated per-command configuration blocks (one canonical `config-setup` asset), and the duplicated relative-time ladder in `uxr-show`/`uxr-mine`.

## [0.1.0] - 2026-11-09

### Added

- Config contract: `config/org.example.yaml` documents every key; `lib/config.py` loads, merges, validates, and expands it, with a `--selftest`.
- Plugin skeleton: `.claude-plugin/plugin.json` manifest, `commands/` and `skills/` directories, and fail-open hook wiring in `hooks/hooks.json` (SessionStart, SessionEnd, SubagentStop, PreToolUse `Write|Edit`, UserPromptExpansion; missing scripts exit 0).
- SessionStart context hook `hooks/ux_research_context.py`: injects commands, tracker constants, and the routing note once, only inside research folders (research root from config or `UXR_RESEARCH_DIRS`, or `00-overview.md` in the cwd or a parent below `$HOME`); other events, including UserPromptSubmit, print nothing.
- All-local smoke gate `scripts/smoke_test.py`: version triple, command and skill minimums, per-script self-tests, schema checks, front matter with quoted descriptions, the no-tracker-writes rule for `scripts/`, and dash-free recruitment templates.
- CI: `.github/workflows/plugin-ci.yml` runs the smoke test on plugin-path changes plus a non-blocking `claude plugin validate` step.
