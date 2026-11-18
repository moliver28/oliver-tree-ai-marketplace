# Sources

Every piece of evidence this study cites lives here as one Markdown
file per source, so citations resolve inside the workspace.

File name: `<topic-slug>-<YYYY-MM-DD>.md`. The topic slug is yours to
choose; the date is the artifact's own date, or the retrieval date when
the artifact has none.

Front matter (every field, in this order):

    ---
    slug: <topic-slug>, matches the file name exactly
    type: one of the folders in this directory (see below)
    title: human-readable title
    canonical_url: URL, or empty when the source is local-only
    canonical_id: drive file id, ticket key, or empty
    author: original author or team
    artifact_date: YYYY-MM-DD, or empty when unknown
    retrieved_at: YYYY-MM-DD
    retrieved_by: who retrieved it
    retrieval_method: drive | tracker | chat | web | manual
    size_notes: length or size, e.g. "12 pages" or "45 min"
    related_slugs: [other-slug, ...] when sources belong together
    ---

Source type folders in this directory:

- `doc/` - documents, decks, specs, prior research reports
- `dashboard/` - analytics snapshots and exported charts
- `ticket/` - tracker items and linked engineering work
- `chat/` - discussion threads and channel digests
- `feedback/` - customer feedback excerpts (no personal data in excerpts)
- `web/` - external pages and articles
- `interviews/` - cited interview summaries (the committed ones under
  the workspace-level `interviews/` folder)

Cite inline anywhere in the workspace as `[S:<slug>]`. Add one row per
source to `INDEX.md` in the same change, and never record participant
personal data in a source file.
