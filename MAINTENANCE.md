# MAINTENANCE: official methods (read BEFORE any change)

Any AI or human modifying this repo follows this document first. The rules below are the procedure, not a post-hoc review: build the change to pass them, then the enforcement cannot fail you.

## 1. Read-before-write contract

CLAUDE.md (auto-loaded) points here. Nothing may be edited in this repo before reading: README.md (asset index), PROVENANCE.md (origin ledger), and the section below that matches the change type.

## 2. Manifest law (marketplace format)

- The marketplace root is `.claude-plugin/marketplace.json`. Every user-installable plugin lives under `plugins/<name>/` and MUST carry `.claude-plugin/plugin.json` (name matching the marketplace entry, semver version) and, when it exposes a command, `commands/<command>.md`.
- Bump the plugin's version in BOTH its plugin.json and the marketplace entry in the same edit.
- Skills (mirror copies under `voice/`, `writing/`, `research/`, `engineering/`, `business/`, `hobby/`) always carry `name:` + `description:` frontmatter; they are catalog assets, not plugins, and are not listed in marketplace.json.

## 3. Mirror law

Canonical skill copies live in the Hermes runtime (`~/.hermes/skills/`); this repo mirrors them. A skill edit updates the runtime copy and the mirror in the SAME pass (commit, push, remote tree check). Repo-first edits do not count.

## 4. Provenance law

Before adding any skill: grep its header for `author`, `ported/adapted from`, upstream URLs. Community-derived tooling does not publish. If origin is unclear, file an issue tagged `provenance` and stop; you do not decide lineage in-flight.

## 5. Token law (gate/hook changes)

Pass = zero tokens delivered to the model. Fail = one repair contract, at most 5 family-deduped patterns, patch-in-place, never a full rewrite. Any hook change keeps those three properties.

## 6. Verification law (the enforcement that should never be needed)

`python3 scripts/verify.py` must exit 0 after every change, and you must verify the remote tree (`gh api .../git/trees/main?recursive=1`), not the local commit. CI runs the same script on every push and PR: `.github/workflows/verify.yml`. A local pre-commit hook runs it before commit (`git config core.hooksPath scripts/hooks` after clone).

## 7. Issue law

Anything not implemented NOW becomes a GitHub issue with a scope tag (`provenance`, `onnx`, `detection-thresholds`, `de-personalization`) and acceptance criteria. Unimplemented intentions do not live in prose only.
