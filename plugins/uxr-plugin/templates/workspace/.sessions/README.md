# Sessions

Automatic session journals and provenance files land here. This folder
is the bridge between Claude Code sessions and this study workspace.

- `provenance.jsonl` - one line per session: sources read, outputs
  written, and the relationships between them.
- `<ended-at>.json` - per-session manifest (commands used, files edited,
  tickets touched).
- `sources-index.json` - machine-readable index of sources cited this
  session.

The plugin hooks write these files; never edit them by hand. Brief
drafts (`gather-brief-*.md`, `deck-collect-brief-*.md`) are gitignored
on purpose: they are working files, not provenance.
