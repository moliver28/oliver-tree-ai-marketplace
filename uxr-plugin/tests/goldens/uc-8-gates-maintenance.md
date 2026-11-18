# UC8 — Gate / verify / maintenance commands

Run: 2026-11-17, 22:29 start. Commands: `/uxr-cheatsheet --check`, `/uxr-stats`, `/uxr-eod` (empty + populated journal), `/uxr-trace` (project, ticket, prompts), `/uxr-feedback`, plus the hook chain that feeds the journal (Stop + SessionEnd fires of `session_logger.py` / `provenance.py`). `/uxr-deck` and `/uxr-notebook` are inventoried at the bottom.

## `/uxr-plugin:uxr-cheatsheet --check` (validate only)

`validate_cheatsheet.py --json` exit 0, verbatim:

```json
{
  "file": "F:\\...\\uxr-plugin\\docs\\cheat-sheet.html",
  "ok": true,
  "drift_count": 0,
  "drifts": []
}
```

Printed per the command spec: `Cheat sheet is in sync with its sources (docs/cheat-sheet.html).` and stopped — the whole `--check` run.

## The journal-feeding hooks (Stop + SessionEnd)

A synthetic session transcript (1 user command line, 1 assistant turn with a Write + a tracker tool call) was fed to the plugin's own hooks exactly as a runtime fires them.

- Stop fire of `session_logger.py` -> exit 0, journal row upserted in `work-log-2026-11-17.jsonl`: `{'files_edited_count': 1, 'tracker_tool_calls': 1, 'processed': False, 'commands_used': ['/uxr-edit']}` — but `ticket_keys: []`.
- <!-- DIFFERS: F3 - W1 fixed this behavior; excluded from byte parity -->
BASELINE FINDING (anchored regex): `provenance.ticket_regex(config)` compiles `tracker.ticket_regex` verbatim and runs `finditer` over transcript text. The config contract's documented shape (`^UXR-[0-9]+$`) is anchored, so a key embedded in a sentence never matches and the journal row loses ticket attribution — the session lands in eod's `unlinked` bucket. After changing the config to the unanchored `UXR-[0-9]+` and re-firing the hook, the row carries `ticket_keys: ['UXR-101']`. One config key serves two masters: commands use the regex as a full-match validator (anchors required); the journal walk uses it as a search pattern (anchors poison it).
<!-- /DIFFERS: F3 -->
- `provenance.py` on Stop: exit 0 and intentionally a no-op (its `main` returns immediately in hook mode: "the walk lives in session_logger.py").
- SessionEnd fire -> exit 0, the workspace manifest `.sessions/2026-11-17T22-22-31-08-00.json` written (SessionEnd-only by design; per-turn Stop fires keep only the journal row current — documented in the README as Claude Code-only finalization). Contents: `commands_used ['/uxr-edit']`, 1 output (`deliverables/report-internal-2026-11-17-uxr-101.md`, type file_edit), 0 sources, 0 edges.

## `/uxr-plugin:uxr-eod` — empty journal (verbatim)

`No unposted UX research work for 2026-11-17.`

(the deterministic filter ran first: 0 unprocessed rows; this is the exact one-line stop)

## `/uxr-plugin:uxr-eod` — unlinked variant (anchored-regex journal; verbatim heading)

> No ticket linked
>
> baseline-uc8-session

(Nothing posted for it; `new` offered as the one-line follow-up.)

## `/uxr-plugin:uxr-eod --dry-run` — populated journal (after the regex fix)

Deterministic filter output:

```json
{"active": {"UXR-101": 1}, "unlinked_sessions": [], "readonly_sessions": []}
```

Draft (word-cap verified mechanically: `70 True`), shown under the `DRY RUN - nothing posted` heading:

> [ux-eod 2026-11-17]
>
> One session today: edited UXR-101 from the spec pipeline, filling Results with the January decision summary after the lite report landed. The report deliverable (deliverables/report-internal-2026-11-17-uxr-101.md) was written and its HTML rendered and validated; the tracker body was recompiled and pushed from the spec. Next: confirm the header-first pattern with first-week external users, then move the ticket toward Collecting Data.
>
> _Posted by Claude Code on behalf of Jordan Reyes._

Dry run stops: no posting, no journal rewrite.

## `/uxr-plugin:uxr-stats` (after hook writes; `--days=1`, verbatim + closing line)

```
UXR stats (last 1 day(s))

Journal (deduped by session_id, latest ended_at kept)
  distinct_sessions: 1
  command_adoption:
    /uxr-edit: 1
  files_edited_total: 1
  tracker_tool_calls_total: 1
  unprocessed_count: 1

Analytics (consent-gated usage counts; never joined with the journal)
  total_events: 0
  event_type_counts:
    (none)
  tool_failed_by_kind:
    (none)
```

Closing line: `Stats are local to this machine; the usage counts are anonymous and never joined with the journal.`

## `/uxr-plugin:uxr-trace` views

Step-2 no-data gate passed once `.sessions/` existed. Verbatim renders from the hook-written manifests:

`uxr-trace UXR-101`:

> Sessions:
> - new-user-navigation-study-timeline-discoverability-q4-2026 · 2026-11-17T22:22:31-08:00
>
> Sources by type: (none recorded)
>
> Outputs:
> - deliverables/report-internal-2026-11-17-uxr-101.md - file_edit, informed by 0 sources
>
> Relationship counts are a session audit trail, not proof that one source caused one claim.

`uxr-trace --project`: session count 1; date range 2026-11-17T22:22:31-08:00; commands: `/uxr-edit` (1 session); tickets touched: UXR-101; unique sources: none recorded; files produced: the report deliverable (1).

`uxr-trace UXR-101 --prompts`: `trace_prompts.py` stdout verbatim: `[]` (the spec's `_meta.transcript_path` is unset in this harness; the script prints `[]` rather than guessing).

## `/uxr-plugin:uxr-feedback <text>`

Gate shown verbatim (nothing created before `go`):

```
Title:
[uxr-feedback] The tracker search in uxr-mine should page when results exceed one page

Body:
The table in uxr-mine is great but silently drops anything past the first page. A "showing 1-20 of 47" line (or a --page flag) would stop people from thinking studies vanished.
---
Plugin: uxr-plugin v0.1.0
Invoking command: none
```

Scripted user: `go`. BLOCKED-EXTERNAL `gh issue create` (no gh auth in the runner; network send). The fresh-install config has `feedback.repo` empty, so the command's own stop printed: `feedback.repo is not set; add it to config/org.yaml (for example: moliver28/uxr-plugin)` with the manual URL shape `https://github.com/<feedback.repo>/issues/new`. (The name/version line read live from `.claude-plugin/plugin.json` — uxr-plugin v0.1.0.)

## `/uxr-deck` and `/uxr-notebook` (discovered, not run)

- `/uxr-plugin:uxr-deck` — local-runnable but not run in this baseline (out of the 8-use-case scope; a full run needs the 4-member rater panel (3 model passes + 1 hcd dispatch), beat skeleton, outline scaffold, lint, and the pptx generator). Cheap surface check that did run: `deck_helpers.py validate-personas` -> `ok personas (design, leadership, org, product, research)` (exit 0). Estimated full-run cost: ~25-40K injected prompt material + 6-10 turns (est).
- `/uxr-plugin:uxr-notebook` — BLOCKED-EXTERNAL: drives a signed-in desktop browser (NotebookLM); in a headless run the command itself prints that the notebook needs an interactive desktop session and stops before any browser action. Upload-set safety lives in `debrief_helpers.py upload-plan` (not exercised; no notebook ever opened). Estimated cost: 4-8 turns + browser skill context (est).
- Skills not run: `interview-script` (local-runnable; the UC list has no script-writing use case; est. 15-25K injected + 8-12 turns incl. expert/novice participant dry-runs and 2 agent reviews), `notebooklm` (browser skill, blocked-external), `ux-research-tickets` router (exercised in UC3).

## UC8 metering

| Metric | Value |
|---|---|
| Wall time | 22:29:00 -> 22:41:30 (12m30s) |
| Inference turns | 9 tool-call rounds |
| Token delta | 21,262 consumed (meter 14,801,394 -> 14,780,132) |
| Script executions (plugin-instructed) | 12 (validate_cheatsheet, uxr_stats x2, eod filter snippets x2, session_logger x3, provenance x2, trace_prompts, deck_helpers validate-personas, eod draft cap check) |
| Subagent dispatches | 0 |
| Blocked-external steps | `gh issue create` (feedback), NotebookLM browser (command self-stops) |
