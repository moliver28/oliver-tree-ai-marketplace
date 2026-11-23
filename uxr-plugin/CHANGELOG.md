# Changelog

All notable changes to uxr-plugin. One `## X.Y.Z` heading per release, newest first.

## [0.5.0] - 2026-11-22

### Added

- The source registry ships (Unit 6; MO gate "confirm, full go" 2026-11-22). `references/research-sources.md` holds only the grounding law (the § 1a text verbatim, including the discovery recipe) plus the 109-row condition index: 8,288 bytes against the 16,000-byte budget, 109 rows against the 120-row cap, rows at most 120 bytes. `references/sources/` holds one file per entry: 109 everyday entries (R-01..R-109, contiguous) and 52 appendix entries (A-01..A-52), each file one compact header line (`R-xx | name | tier | WHEN:`), one-line leaves with (R|C) labels, and `Gate note:` lines; no YAML, no tables; every entry file at most 3,000 bytes, every leaf at most 200. The three approved folds applied (S-10 into R-13, S-11 into R-30, S-72 into R-43) with sequential renumbering and no gaps. R-10 carries the two verified GitLab timepoints (TP2 `0feecc95`, TP3 `c09d75e6`; blob permalinks re-verified HTTP 200 this pass) and the PAIR Guidebook slug was rechecked (HTTP 200 at `/guidebook/`).
- The wiring (build item 11): one Grounding pointer line per command (17 commands) and per skill (3 skills) naming that surface's entries; record-keeping surfaces carry the none-form line (search is a tool, not a ritual). The workspace CLAUDE.md template carries the law paragraph verbatim (919 bytes, inside the 1,000-byte budget). `references/research-grounding.md` points the mandatory reviewer at the registry. Pointer-coverage grep green: every id named in a pointer resolves in the store; R-20 and R-21 are named in the report and deck pointers (review F6).
- The web-tool nudge hook (build item 12): `hooks/web_nudge.py` runs on PreToolUse for WebSearch and WebFetch, reuses the existing `_gate_open` workspace predicate (it fires on any web call inside a uxr workspace), injects the 211-byte nudge line (registered source first; cite the URL with the claim), keeps the catch-every-exception exit-0 contract, and rides `hooks.json` with the same `|| exit 0` law (one interpreter spawn per web event).
- The gate citation check (build item 12): `lib/checklist_gate.py citations --workspace <dir>`, standalone-invocable. An item is outside-knowledge if and only if its Source field names an `R-`/`A-` registry id (grep-checkable, zero classifier variance); that item's `path:` evidence artifact must carry a source line (a URL or a registry id); ids resolve against the `references/sources/` directory; an unresolved id prints a WARNING and never fails the check (promotion never renames). `check` behavior unchanged.
- The grounding-adherence acceptance scaffolding (build item 13; zero payload LOC): `tests/evals/grounding/` ships evals.json (five cases: four golden-path carrier surfaces plus the negative record-keeping case) and a runner that imports the hcd-researcher runner - no copy, so the #132 ground-truth upgrade lands once for both suites - with the suite's one new machinery, the deterministic tool-call-order parser. The offline selftest `tests/uxr_selftests/grounding_budget.py` asserts every byte budget against the shipped files with zero dispatches and joined the parity sweep. The G-case dispatches are NOT run in this wave; the acceptance pass runs them one at a time. Acceptance result 2026-11-22: registry-first held on all four carrier surfaces, the negative record-keeping case held (zero web calls, zero registry fetches), and the run corrected five scorer defects (its corpus omitted the central file and the dispatch text; its gap-line, citation-furniture, and markdown-bullet handling rejected compliant replies).
- Review lens 3 (evidence honesty) of `agents/hcd-researcher.md` names the grounding registry first: `references/research-sources.md` routes to one file per source under `references/sources/`; web tools run only when no registered page covers the claim (acceptance-pass residual of the wave, re-pinned by the recorded PASS tuning run 2026-11-22-registry-lens3, F1 0.28, p0 recall 1.00).

## [0.4.1] - 2026-11-22

### Fixed

- Debt pass (#133, #135, #137): the tuning harness keeps its exit laws (`prepare` reports a plant location it cannot find with one stderr line and exit 3; a valueless `--run-dir` is usage exit 2), the scorer docstring names its second false-alarm trigger as a deliberate extension of the design note, and `record` derives the entry date from the run-dir name so a midnight straddle cannot misdate an entry.
- The verbatim-ask up-level check carries a str guard: an `ask_uplevels` entry with no `text` key no longer draws the replacement error on top of the empty-ask error (#133).
- `validate-recruitment` reads the approved two-table participants shape: headers checked against the approved column sets, statuses against the locked vocabulary, drift advisory at exit 1; the legacy `Name` table stays valid for old workspaces (#135).
- The recruitment README bullet states the shipped law (fixed approved column sets, one table per flow) (#135).
- `recruit_send.py`: an SMTP connect, STARTTLS, or login failure prints one clean scrubbed ERROR line and exits 1 (no host-naming traceback); the participants file keeps its own line endings through a stamp (LF stays LF, CRLF stays CRLF); `--send` with zero sendable rows refuses without an SMTP account (#137).
- The `--send` refusal checks are machine-independent: `load_send_settings` and `run` accept a `config_file` override, and the repo-level tests point it at an empty file (#137).

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
