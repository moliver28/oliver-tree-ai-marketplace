# Contributing

This repo publishes the Oliver Tree AI marketplace. Every change keeps the marketplace green and the plugins lean. Read MAINTENANCE.md and PROVENANCE.md before your first change. This file defines the bar, the lanes, the gates, and the checklist.

## Contribution bar

A change is accepted when all three conditions hold. First, all three gates pass after every commit (see below). Second, the docs that reference the change are updated in the same edit. Third, every published asset stays origin-clean: assets are authored here, or rewritten from scratch with owner approval. Community derivatives do not publish; PROVENANCE.md is the origin ledger, and the default disposition for one is removal. Never put personal data in commits: no usernames, home paths, tokens, keys, private hostnames, or identifiers of any individual.

## Directory layout

Top-level folders are the highest grouping. There is no grouping layer above them (organization law, MAINTENANCE.md section 12). Plugins live at the top level: `humanizer/`, `voice-gate/`, `decision-advisor/`, `uxr-plugin/`. Skill mirrors live in `business/`, `engineering/`, `hobby/`, `onboarding/`, `research/`, `voice/`, `writing/`. The verifier lives in `scripts/`; the parity harness and baselines live in `tests/`. A new top-level dir, or a new level-2 entry inside a group, requires a whitelist edit in `scripts/verify.py`. That edit is the reviewable owner-approval record.

## Branch model (two lanes)

- `main` is the release lane and the marketplace consumer lane. It carries reviewed work only: gates green, efficiency reviewed, changelog current.
- `develop` is the integration lane. Feature branches cut from `develop` and merge back to it.
- Useful-but-inefficient updates can sit on one feature branch while WIP sits on another. Nothing reaches `main` before the release PR.
- Branch names: `(agent|human)/(feat|fix|chore|docs|refactor)/<kebab-slug>`. Example: `agent/feat/ci-branch-flow`.

## Pull requests

- A feature PR targets `develop`.
- A release PR runs `develop` into `main` and carries the label `mo-review`. This release PR is the efficiency checkpoint; CI arms the efficiency gate on it only.
- Squash-merge every PR. Delete the branch after the merge. A merged branch leaves no residue.

## The three gates (three separate commands, after every commit)

1. Marketplace verify: `python3 scripts/verify.py` (repo root). Exit 0 is required.
2. Plugin smoke: `python3 uxr-plugin/scripts/smoke_test.py` (repo root). Exit 0 is required. A skip is not a fail.
3. Golden parity: `python3 tests/test_parity.py` (repo root). Exit 0 is required.

Run each command on its own, in this order. Do not fold the three into one wrapper. A wrapper hides which gate failed. Where the pre-commit hook is configured (`git config core.hooksPath scripts/hooks`), gate 1 also runs before each commit.

## Efficiency gate (release lane only)

Run `python3 scripts/verify.py --efficiency`, or set env `VERIFY_EFFICIENCY=1`. This mode adds checks over the base checks. The recorded floor lives in `tests/efficiency-baseline.json`, written with the repo's shipped ex-tests counting convention (cited in the file).

- Payload lines: shipped `uxr-plugin/` lines (git-tracked `.py`, `.md`, `.yaml`, `.yml`, ex-tests) against the baseline total and per-dir floor. Tolerance is 0. Any growth FAILs, and the gate lists the growing dirs. To ship growth, record `justifications.payload_growth` in the baseline file in the same PR and argue the growth in the PR body. The release review judges that argument.
- Call budget: the gate reads the golden-path model-call budget declared in the plugin markdown and compares it with `golden_path_model_calls` in the baseline. Growth FAILs unless `justifications.golden_path_growth` records the reason.
- Golden immobility and the 54 hash pins are enforced by `tests/test_parity.py` in every run. The efficiency gate references that check. It does not duplicate it.

CI arms this gate only on `develop` into `main` PRs. Ordinary pushes run the base checks unchanged. When justified growth lands, update the baseline numbers in the same release and clear the justification, so the floor moves with the shipped tree.

## Submission checklist

1. Cut the branch from `develop`.
2. Build the change to pass the bar and the matching MAINTENANCE.md sections.
3. Run the three gates, separately, after every commit. All must exit 0.
4. Plugin change: bump the version in `plugin.json` and `marketplace.json` in the same edit, and add the CHANGELOG entry (manifest law).
5. Update docs that reference the change: README.md, catalog.md, and PROVENANCE.md rows when paths or origins change.
6. Open the PR at the right base (`develop`, or `main` for a release PR with the `mo-review` label).
7. Squash-merge. Delete the branch.

## Mimosa disclosure duty

Mimosa keeps the local scan ledger under `.mimosa/` (machine-local, gitignored). Disclose findings honestly: record them, never suppress them, never edit the ledger to force a pass. Never bypass a gate: `--no-verify` is banned. Agent-authored work says so in the PR body.

## Requires owner action (GitHub settings, not code)

1. Protect `main`: require pull requests and green `marketplace-verify` CI.
2. Protect `develop`: require pull requests and green `marketplace-verify` CI.
3. Set the default PR base branch to `develop`.

## Sentence style

Docs and PR text follow ASD-STE100 wording: one instruction per sentence, short sentences (procedures max 20 words), active voice, concrete verbs.
