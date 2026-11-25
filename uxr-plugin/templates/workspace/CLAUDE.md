# {{STUDY_SLUG}} workspace

Claude Code instructions for this study workspace.

- Study: {{STUDY_TITLE}}
- Ticket: {{TICKET_KEY}} (status: {{STATUS}})
- UXR: {{UXR_NAME}}

Grounding law: never invent an answer. When a step needs knowledge from outside this workspace, pick the matching entry from the condition index in references/research-sources.md and read that entry's file under references/sources/ (one file per entry). Fetch the entry's bookmarked page first (page-first lookup); run an exploratory query only when no registered page covers the need, and register the page you found as a candidate so the next lookup is targeted. Cite the source with the claim: one URL per outside fact, two authoritative sources when a claim rests only on outside evidence. Discovery recipe: read the condition index whole while the file is within its budget; past that size, skip the read and grep the store (`grep -rl <term> references/sources/`). When a step works only on workspace artifacts — spec fields, transcripts, notes, recorded state — no search runs: search is a tool, not a ritual.

Working rules:

1. Participant data never enters git. Do not commit or quote raw
   transcripts, the participant key, or personal contact details in
   tracked files; those paths are gitignored on purpose.
2. Cite evidence inline as `[S:<slug>]`. Every citation resolves to a
   file in `sources/` with full provenance front matter (see
   `sources/README.md`).
3. New evidence goes to `sources/<topic-slug>-<YYYY-MM-DD>.md`; update
   `sources/INDEX.md` in the same change.
4. Keep the table shapes in `analysis/codes.md`,
   `analysis/themes.md`, and `recruitment/participants.md` intact; the
   scripts read them.
5. Files in `.sessions/` are written by the plugin. Do not edit them by
   hand.
6. Drafts never send. Recruiting moves, tracker comments, and posts
   wait for an explicit go from the user.
7. `00-overview.md` mirrors the ticket. The Background, Key decision,
   Hypotheses, Assumptions, Research questions, Resources, and JTBD &
   Personas sections are owned by the spec: update them through
   `edit`, never by hand here.
8. This workspace is a uxr-workspace: commit to `main`; never create
   branches and never open pull requests here. Push to the configured
   remote only when `workspace.remote_push` is true (default false);
   otherwise keep the commits local. The value is having version
   control, not a branch flow.
