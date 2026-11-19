# UC6 — Analysis flow (`/uxr-plugin:uxr-debrief` + `/uxr-plugin:uxr-report`)

Run: 2026-11-17, 22:06 start (debrief), 22:14 (report). Prerequisite state: Participant A booked Wed 11/18 1:00 PM (roster flipped to `Scheduled` via `roster_apply.py`, exit 0: `update: Participant A Outreach Sent -> Scheduled`); booking event `evt-009` added to the fixture calendar (BLOCKED-EXTERNAL read); a raw transcript fixture exists in a local recorder folder.

## Part A — `/uxr-plugin:uxr-debrief UXR-101 --participant=Participant A`

Setup: config cached; `get_item` fixture (summary/body/dates); spec loaded with the 5-row roster (no backfill needed).

Phase 1 (resolve): `--participant` matches exactly one row (Participant A, Scheduled). Phase 2 (verify meeting): calendar events within 30 minutes of the 13:00 slot -> `evt-009` with `participant.a@example.com` as an attendee -> confident, no ask. Phase 3 (find transcript): search order (1) call-recording store — notetaker did not attend (event has no `notetaker@example.com` attendee); (2) local recorder folder — hit: `2026-11-18-timeline-session.txt` for the event date. Phase 3b (dedupe): verbatim script output (exit 0):

```json
{
  "chosen": {
    "source": "local recorder folder",
    "kind": "raw text",
    "path": "F:/.../baseline-fixtures/recordings/2026-11-18-timeline-session.txt"
  },
  "named_not_copied": []
}
```

Phase 4 (file): `lookup-workspace` -> workspace path; gitignore gate (verbatim, exit 0):

```
  [ok] interviews/raw-transcripts/new-user-navigation-study-timeline-discoverability-q4-2026-2026-11-18-transcript.txt
  [ok] interviews/participant-key.md
  [ok] interviews/raw-transcripts/
gitignore gate: all paths are ignored; writes may proceed
```

Files written: the raw transcript (gitignored copy), the committed summary `interviews/new-user-navigation-study-timeline-discoverability-q4-2026-2026-11-18-summary.md`, and a `participant-key.md` row (Name, Role, Email, Session date). The summary's frozen alignment block (verbatim; every spec RQ/H/A has a line):

```
## Insights → Research Alignment
**Research Questions**
- RQ1 (Where do first-week users look for the timeline?): The header toolbar first — roughly two thirds of first meaningful clicks land in the top bar; the left rail is skimmed later and reads as settings/admin rather than where work lives.
- RQ2 (What does a first-session planning attempt look like?): Discovery in session one predicts planning in session one — users who find the timeline import tasks and set dates immediately; users who never find it build nothing in week one.
**Hypotheses**
- H1 (Header before left navigation): Supports - funnel data cited in session puts the first meaningful click in the header about two thirds of the time, with the left rail skimmed later.
**Assumptions**
- A1 (First-week users want to build a plan in their first session): Holds this session - the want is clearly described, though the evidence is secondhand (the stakeholder reporting user behavior) and it holds only when discovery happens first.
```

<!-- DIFFERS: F2 - W1 fixed this behavior; excluded from byte parity -->
BASELINE FINDING (contract strictness): the first draft of the A1 line used a `Mixed` stance, which is outside the frozen assumption vocabulary (Holds/Breaks/Untested); `report_helpers.py evidence-weight` silently produced `assumption_verdicts: {}` — no error, no warning. The line was rewritten to `Holds this session - ...` and the verdict appeared. Silent-parser behavior: a deterministic vocabulary check in `debrief_helpers.py` would catch this at write time.
<!-- /DIFFERS: F2 -->

Phase 6 (recap): draft verified by `check-recap` (verbatim, exit 0):

```
recap ok: 146 words, heading and sections present, no bare codes
```

Recap shown; scripted user: `go`. BLOCKED-EXTERNAL `add_comment` fixture: the recap is appended to fixture UXR-101 (now 3 comments).

## Part B — `/uxr-plugin:uxr-report UXR-101 --audience=internal --format=html`

Phase 0 (resolve): workspace found; 1 `interviews/*-summary.md`; `analysis/codes.md` non-empty (analyst-written from the session — the plugin owns no analysis command; the model owns insight mapping per `docs/ARCHITECTURE.md` Principle 2). Phase 1 (scope): `get_item` fixture + `00-overview.md` read in parallel; script outputs verbatim:

```
scope-tier -> lite
```

Scope card: type Evaluative, investment SM, groups Onboarding, computed tier lite. Gate -> scripted `go`.

Phase 2 (gather): workspace analysis files read; prior studies (tracker/Drive/wiki), feedback store, chat, and calendar are BLOCKED-EXTERNAL — each logged `<Tool>: unavailable (skipped)` in the gather brief ``.sessions/gather-brief-UXR-101-2026-11-17.md`` (gitignored path verified by the gate). Gate -> `go`.

Phase 3 (synthesize): script outputs verbatim:

```json
{
  "rq_coverage": { "RQ1": 1.0, "RQ2": 1.0 },
  "hypothesis_verdicts": { "Header before left navigation": "Supported" },
  "assumption_verdicts": { "First-week users want to build a plan in their first session": "Holds" },
  "sessions_tallied": 1,
  "sessions_with_alignment_block": 1
}
```

Bias check (`classify-themes`, verbatim):

```
| Theme | Origin | RQs supporting | Fragile? |
|---|---|---|---|
| Header toolbar is where first-week users look first | participant-emergent | - | yes |
| Left navigation reads as admin, not work | participant-emergent | - | yes |
| Timeline discovery gates first-session planning | participant-emergent | - | yes |
Researcher-framed: 0. Emergent: 3. Single-RQ conclusions: 1, 2, 3.
```

(Note: the classifier read the themes table's Origin column as participant-emergent; the codes table carries the Researcher-framed/Emergent split. Findings and verdicts copied verbatim into the draft; the single-source caveat `single source; treat as preliminary` appended to the implication.) Gate -> `go`.

Phase 4 (draft): lite narrative written to the tier spec (Key Findings 175 words / 5 bullets 1 citation each, Implications 63, Next Steps 32; `word-count-sections` output — no section OVER):

```json
{ "Key Findings": 175, "Implications": 63, "Next Steps": 32, "Distribution": 61 }
```

Mandatory `hcd-researcher` review: SIMULATED dispatch (1 event) per `agents/hcd-researcher.md` + `references/research-grounding.md`; its Summary/Risks/What-to-change printed to the user verbatim in the live run; fold-in: the single-source preliminary caveat was already present (no further change), one-line decline recorded for the suggestion to add a methodology section (lite tier caps sections by the tier spec). Optional stakeholder reviewer: not requested.

Phase 5 (create): `report-filename` -> `report-internal-2026-11-17-uxr-101.md`; `check-citations` -> `[{"slug": "2026-11-18-participant-a", "found": true}]`; gitignore gate -> exit 0 (output under Part A gate, same paths plus the gather brief); deliverable written with the exact front matter (slug/ticket/tier/audience/date/hypotheses/sources_cited). HTML render + check verbatim:

```
rendered ...\report-internal-2026-11-17-uxr-101.html (5840 bytes)
check: all checks passed
```

Review loop (SIMULATED dispatches x2: novice-report-reader + research-dataviz-designer, one parallel batch, per the schema): pass 1 returned one minor content finding (nrr-01 dead-ends: next steps carry no owner) and an empty findings list from the dataviz reviewer; routed to the Markdown, owners added, re-rendered (`5919 bytes`, `check: all checks passed`). Review file `deliverables/report-review-2026-11-17-UXR-101.md` written with the finding marked Resolved and the final line `PASS`. Publish and Drive upload: not requested (publish never automatic; requires explicit `go`; BLOCKED-EXTERNAL here).

Phase 6 (distribute): lite tier -> ticket comment draft only (verbatim, shown, waits for user):

> [uxr-report 2026-11-17] Lite report filed at deliverables/report-internal-2026-11-17-uxr-101.md (HTML rendered and validated). Headline: header-first confirmed in a stakeholder pass (Supported), discovery gates first-session planning, tour recall near zero. Single session; treat as preliminary. Next: confirm with first-week external users before the January review.
>
> _Posted by Claude Code on behalf of Jordan Reyes._

Scripted user: `skip` (draft shown, not posted — the run ends with it unposted; nothing sends without the user).

## UC6 metering

| Metric | Value |
|---|---|
| Wall time | 22:06:00 -> 22:22:30 (16m30s) |
| Inference turns | 13 tool-call rounds |
| Token delta | 21,026 consumed (meter 14,827,140 -> 14,806,114) |
| Script executions (plugin-instructed) | 12 (pick-transcript, gitignore_gate x2, check-recap, evidence-weight x2, codebook-codes, classify-themes, report-filename, check-citations, word-count-sections, report_html render x2, validate_report_html x2, roster_apply booking flip) |
| Subagent dispatches | 4 simulated (hcd-researcher x2 — new + report, novice-report-reader, research-dataviz-designer; no Task tool in runner harness) |
| Blocked-external steps | calendar read (meeting verify), `add_comment` x2 (recap posted via fixture; report comment left unposted), prior-study/feedback/chat/calendar gathers, publish/Drive upload (not requested) |
