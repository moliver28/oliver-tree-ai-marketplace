# Changelog

All notable changes to uxr-plugin. One `## X.Y.Z` heading per release, newest first.

## [0.4.0] - 2026-11-22

### Added

- Persistent researcher (#120): one journal per study key at `<state_dir>/researcher/<KEY>.journal.jsonl`; the SubagentStop branch of `hooks/review_gate.py` appends one line per completed review (the checklist-scoped verdict, the summary, the findings; a pointer-only line when the transcript parse finds nothing), and the new `scripts/researcher_state.py digest --key <KEY> [--last <N>]` prints the bounded prior-reviews pickup that the four dispatch sites (`new` phase 6, report phase 4, the deck Critic, the interview-script review loop) paste into the gate input.
- The tuning harness for the researcher's instructions (#120): `tests/evals/hcd-researcher/` holds 12 seeded-error cases (8 draft-spec, 4 report) with a mechanical scorer that prints the exact verdict line, and `baseline.json` records each run's scores plus the EOL-normalized sha256 of every researcher instruction asset; `scripts/verify.py` rule 13 fails when any of those assets drifts without a PASS run carrying the new hashes. Baseline and first re-run both PASS.
- The verbatim ask (#60): the spec keys `ask_verbatim`, `ask_source`, and optional `ask_uplevels`; `validate_spec` blocks an empty verbatim ask and a byte-equal up-level on a spec saved by the `new` build block (a retro save records the gap instead); `backfill_spec.py` gains the save-time validation (exit 4) and `assert-ask` (`ask OK`, `ask missing (pre-ask spec)`, exit 5 on a real gap); the `Original ask (...)` quote lines join the debrief setup, the report scope card, and the four hcd-gate dispatch inputs; report and deck may quote an up-level but the original ask is never replaced.
- Checklist gate machinery (#53): `lib/checklist_gate.py` loads the one-line item shape and runs the `spec:` / `path:` / `always` probes, `check --type <t> --spec <s> --workspace <d> [--json]` copies the phase-gates exit law, and an absent checklist prints `no checklist for type <t>` with exit 0; the `checklists.enforcement` config key ships with the `record` default; the two standing-mandate ask predicates join `SPEC_CHECKS`, reachable only through checklist items, so no pinned gate output changes. No checklist content files land yet.

### Changed

- The researcher agent definition gains one input item (#120): prior review notes, when present, are claims to re-test against the current artifact, and a prior finding that no longer holds is restated as changed. The tuning harness gates it: the re-run scored `F1 0.28 | recall 1.00 | precision 0.16 | p0 recall 1.00 | verdict PASS`.
- The report methodology line (#56) names the analysis plan actually followed. The rigor-lens fragment, the prompt budget bump, and the script-rigor rider lines were built and then reverted: the third harness run scored `F1 0.25 | recall 0.92 | precision 0.14 | p0 recall 1.00 | verdict FAIL` against the 0.2727 baseline F1 bar, and the contract reverts the instruction edits on a FAIL while the recorded attempt stays in `baseline.json`.

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
