# {{STUDY_SLUG}} workspace

Claude Code instructions for this study workspace.

- Study: {{STUDY_TITLE}}
- Ticket: {{TICKET_KEY}} (status: {{STATUS}})
- UXR: {{UXR_NAME}}

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
