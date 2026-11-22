# MAINTENANCE: official methods (read BEFORE any change)

Any AI or human modifying this repo follows this document first. The rules below are the procedure, not a post-hoc review: build the change to pass them, then the enforcement cannot fail you.

## 1. Read-before-write contract

CLAUDE.md (auto-loaded) points here. Nothing may be edited in this repo before reading: README.md (asset index), PROVENANCE.md (origin ledger), and the section below that matches the change type.

## 2. Manifest law (marketplace format)

- The marketplace root is `.claude-plugin/marketplace.json`. Every user-installable plugin lives at the top level as `<name>/` and MUST carry `.claude-plugin/plugin.json` (name matching the marketplace entry, semver version) and, when it exposes a command, `commands/<command>.md`.
- Bump the plugin's version in BOTH its plugin.json and the marketplace entry in the same edit.
- Skills (mirror copies under `research/`, `engineering/`, `business/`, `hobby/`) always carry `name:` + `description:` frontmatter; they are catalog assets, not plugins, and are not listed in marketplace.json. The voice/writing groups were removed 2026-11-21 (de-personalization); the voice system lives entirely in the humanizer plugin.

## 3. Mirror law

Canonical skill copies live in the Hermes runtime (`~/.hermes/skills/`); this repo mirrors them. A skill edit updates the runtime copy and the mirror in the SAME pass (commit, push, remote tree check). Repo-first edits do not count.

## 4. Provenance law

Before adding any skill: grep its header for `author`, `ported/adapted from`, upstream URLs. Community-derived tooling does not publish, and the DEFAULT disposition is removal: if the marketplace loses coverage by dropping a derivative, we lose the coverage; no rewrite is started without explicit owner approval in chat. If origin is unclear, file an issue tagged `provenance` and stop; you do not decide lineage in-flight, and you do not decide rewrite-or-drop either.

## 5. Token law (gate/hook changes)

Pass = zero tokens delivered to the model. Fail = one repair contract, at most 5 family-deduped patterns, patch-in-place, never a full rewrite. Any hook change keeps those three properties.

## 6. Verification law (the enforcement that should never be needed)

`python3 scripts/verify.py` must exit 0 after every change, and you must verify the remote tree (`gh api .../git/trees/main?recursive=1`), not the local commit. CI runs the same script on every push and PR: `.github/workflows/verify.yml`. A local pre-commit hook runs it before commit (`git config core.hooksPath scripts/hooks` after clone).

## 8. Auto-update law

- Every plugin carries `CHANGELOG.md` with one entry per released version (Keep a Changelog headings, semver). A version bump without a changelog entry fails verification.
- Manifest versions and marketplace.json versions must match exactly; the verifier enforces parity per plugin.
- End users update with `claude plugin update <name>@oliver-tree-ai-marketplace` (marketplace add once; add/install commands live in README). The install section of README.md must always name the update path so consumers never pin a stale version by accident.

## 9. Description law (skill + plugin text)

- Descriptions follow the official Claude Code skill-authoring guide: third person, says WHAT the skill does and WHEN to use it, in one string, max 256 chars for plugins, with two to four real human invocation phrases in quotes (phrases an end user would actually type, not abstract categories).
- Banned in descriptions: category abstractions alone ("Use when managing writing assets"), feature lists without triggers, internal jargon.
- New trigger phrases come from the learned sidecar (below), not invention; seed phrases are hand-written from real user language and revised when the learned log contradicts them.

## 10. Learned invocation terms (zero-LLM loop)

`humanizer/learned/phrases.log` is append-only, written by the /voice command after each successful run: the verbatim $ARGUMENTS line plus a date. This costs zero LLM tokens (a shell redirect, not a model call). During any repo maintenance pass, distill recurring phrasings from the log into the plugin description's trigger-phrase list (dedupe, cap the description at the length limit, keep the change within description law; `humanizer/learn/distill_phrases.py` does the extraction deterministically). The maintenance pass, not the runtime, is the only place the description changes; the gate never spends tokens on vocabulary updates. All humanizer learn tools are deterministic and spend zero model tokens at runtime: `build_voice_profile.py`, `calibrate.py`, `distill_phrases.py`, and `voice_vector_build.py` are plain stdlib scripts; the maintenance pass remains the only description-editing site.

## 7 (renumber 11). Issue law

Anything not implemented NOW becomes a GitHub issue with a scope tag (`provenance`, `onnx`, `detection-thresholds`, `de-personalization`, `descriptions`, `auto-update`) and acceptance criteria. Unimplemented intentions do not live in prose only.

## 12. Organization law (flatten + grouping cap; issue #8, MO ruling 2026-11-17)

Top-level folders are the highest grouping in this repo; there is no grouping layer above or between them, and a `plugins/` grouping dir must not reappear. GROUPING depth is capped at 2:

- Level 1 = top-level groups (e.g. `engineering/`, `research/`) and top-level plugin entries (e.g. `humanizer/`, `decision-advisor/`, `uxr-plugin/`).
- Level 2 = entries inside a group (e.g. `research/academic/`) or a plugin entry itself.
- Entry-internal anatomy (a plugin's own `hooks/`, `references/`, `scripts/`, `commands/`, `.claude-plugin/`; a skill's `references/`) is allowed and NOT new grouping: it is the entry's own structure. A strict repo-wide 2-level cap would outlaw plugin/skill internal anatomy (e.g. the 142-file uxr-plugin tree) and contradict issue #8's own "for all plugins" grouping intent; hence the anatomy exemption.
- Creating a new top-level group OR a new level-2 entry requires explicit owner approval. Mechanically: the entry must be added to the whitelists in `scripts/verify.py` (top-level dir whitelist; per-group level-2 list), so approval is a reviewable code change, not a convention. The verifier fails on any unlisted level-1 dir or unlisted level-2 entry.
- Suggest a new group only if the existing groups are <1% relevant to the content; fold into an existing group otherwise.

## 13. Zero-stub law (MO ruling 2026-11-18)

All plugins and skills contain zero stubs, empty files, or stated-but-unfinished work; `scripts/verify.py` enforces this mechanically (deterministic file/regex checks, no LLM inference): no 0-byte files, no `__pycache__`/`*.pyc` anywhere, no stub markers (TODO, FIXME, XXX, HACK, NotImplementedError, "not implemented", "coming soon", "to be implemented", "stub", ...) in plugin/skill text files, no `pass`-only or `...`-only function bodies in plugin `.py` files, and no dangling catalog/provenance path rows. A legitimately load-bearing construct is whitelisted inline with `# verify-allow: stub-marker` plus a reason (rare and explicit); `catalog.md`/`PROVENANCE.md` are exempt from marker scanning because honest-ledger rows legitimately describe pending states, but their path references must exist on disk. Anything genuinely unfinished is issue law (section 11), not a stub in the tree.

