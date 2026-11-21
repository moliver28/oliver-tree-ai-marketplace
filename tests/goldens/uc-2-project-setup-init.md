# UC2 — Project setup / init from a research ask (`/uxr-plugin:uxr-new` + `/uxr-plugin:uxr-init`)

Run: 2026-11-17, start 21:48:50. Input: the fixture research ask (a paragraph of notes -> targeted interview: sweep, then gaps only). All times and scripted user replies noted inline. Tracker/Drive/chat/wiki/feedback calls are fixture-backed from fixtures and marked BLOCKED-EXTERNAL.

## Setup + Phase 0 (no user output)

`python lib/config.py --print` exit 0. `current_user()` fixture-backed: Jordan Reyes (account 5f1a2b3c4d5e6f7081a2b3c4). `detect_role("Jordan Reyes", routing)` -> `uxr` (script output).

## Phase 1 — Topic and scope (WAIT)

> Three quick things before I run the evidence sweep:
>
> 1. Working title for the study?
> 2. Which group or area does this belong to (Onboarding, Growth, or Core)?
> 3. Who is the decision owner?

Scripted user: title "New user navigation study: timeline discoverability"; group "Onboarding"; owner "Product Leadership (January planning review)".

## Phase 2 — Evidence sweep (one parallel batch; every source external)

BLOCKED-EXTERNAL: all nine configured sources would call external tools (Atlassian MCP, Drive, feedback store, chat, wiki, JTBD board, personas doc, chat discovery). Each tool call is fixture-backed as failed; the synthesis block follows the playbook's failure format. Per `evidence-lookup.md`, the feedback store must never be silently skipped for an adoption-adjacent topic, so its line names the gap the study carries.

```
## Evidence sweep

| Source | Hits |
|---|---|
| Tracker: your recent items (other projects) | 0 |
| Tracker: topic search (other projects) | 0 |
| Drive | 0 |
| Feedback store | 0 |
| Chat | 0 |
| Wiki | 0 |
| JTBD | 0 |
| Personas | 0 |

- searchJiraIssuesUsingJql: unavailable (skipped)
- Drive: unavailable (skipped)
- Feedback store: unavailable (skipped) — topic is first-run adoption; the study carries a gap: no customer-side pain counts this run
- Chat: unavailable (skipped)
- Wiki: unavailable (skipped)
- jtbd: unavailable (skipped)
- personas: unavailable (skipped)
- chat_discovery: unavailable (skipped)

Top signals
- Owning group: Onboarding (from the ask alone; no evidence to cluster)
- Hypotheses in flight: none surfaced (all sources unavailable)
- Pain strength: low on this run's evidence, named gap — support tickets referenced in the ask are the only pain signal
- Stakeholders: Product Leadership (decision owner), design (competing proposal), support (first-week tickets)
```

## Phase 2.5 — Shareability

No Drive URLs surfaced; no permission tags to read. Nothing to show.

## Phase 3 — Background draft (WAIT)

> Draft background (3-5 sentences):
>
> New users of the project-management web app cannot find the timeline view after signup, and support sees a steady trickle of "where is my project plan?" tickets in each account's first week (per the request; external sources unavailable this run — 0 hits across 8 sources, feedback store gap noted above). Product proposes moving the timeline entry point into the left navigation; design believes new users look in the header toolbar first, and the team has no evidence either way. Product Leadership needs the answer for the January planning review, where they will choose between the navigation change and a guided tour. The Onboarding group owns the first-run experience this study would inform.
>
> Resources: none yet (sweep surfaced no documents).
>
> Edits, or good to continue?

Scripted user: "good".

## Phase 4 — Decision (WAIT)

> One-sentence decision with an owner:
>
> "Do we ship the left-navigation timeline entry or invest in a guided tour? Owner: Product Leadership, January planning review."
>
> This matches a good shape (invest in A or B, one sentence, named owner). Approve, or edit?

Scripted user: "approve".

## Phase 5 — Hypotheses and assumptions (WAIT)

> Proposed set:
>
> - H1. First-week users look for planning features in the header toolbar before the left navigation.
> - H2. New project managers who find the timeline in their first session build a plan in that session.
> - H3. A navigation change increases first-session timeline discovery more than a guided tour.
> - A1. First-week users want to build a plan during their first session.
> - A2. Support's first-week "timeline" tickets indicate real navigation failures, not training gaps.
>
> H3 is falsifiable but restates the decision itself; A2 is checkable but not in scope for stakeholder interviews. Edit, trim, or accept?

Scripted user: "accept for now" (trim happens in the phase 6 review fold-in).

## Phase 6 — Research questions + mandatory hcd-researcher review (WAIT)

> Research questions and the map:
>
> - RQ1. Where do first-week users look for the timeline when they want to plan? -> traces to H1
> - RQ2. What does a first-session planning attempt look like for a new project manager? -> traces to H2
> - RQ3. What makes the timeline entry discoverable in the left navigation vs the header toolbar? -> traces to H1, H3
>
> Mandatory review: dispatching the hcd-researcher agent (Task tool, subagent_type: hcd-researcher) on the decision, hypotheses, and RQs.

SIMULATED DISPATCH (runner harness has no Task tool; the agent file `agents/hcd-researcher.md` was read and its contract applied literally; counted as 1 subagent event). The agent's return, verbatim shape per `references/research-grounding.md`:

```
Summary
The draft ties every question to a ship-or-invest decision, but two items blur the line between decision and mechanism: H3 restates the decision as a hypothesis, and RQ3 compares two solutions before the study establishes where users actually look. The question set is answerable in five 30-minute stakeholder sessions only if it stays descriptive.

Strengths
- Every RQ traces to a hypothesis and every hypothesis ties to the January decision.
- Hypotheses are falsifiable and single-mechanism.
- The participant-respect lens is clean: no leading wording in the RQs.
- Scope load matches the 30-minute budget once trimmed.

Risks
- H3 collapses "ship vs tour" into a hypothesis; the study cannot run an A/B, so it can only produce mechanism evidence, not the comparative answer.
- RQ3's "vs" framing invites participants to opine on a design they have not seen; that is a survey or usability-test shape, not an interview shape.
- With all external evidence sources unavailable, the background rests on the requester's account alone; treat any hypothesis the sessions fail to touch as untested, not as refuted.
- Sample of internal stakeholders answers "what do insiders observe", which is one step removed from first-week user behavior; the ask's real subject is external.

What to change
- Drop H3: it is the decision restated; the decision gate already owns the comparison.
- Drop RQ3: it traces to H1 and H3; with H3 gone its comparison half is out of scope, and its "where" half duplicates RQ1.
- Keep A2 out of the spec; record it in the ticket history instead.
- Rename the study to name the population ("first-week users"), so the ticket does not promise a comparative verdict it cannot deliver.

findings:
- {claim: H3 restates the decision rather than a mechanism, so no session evidence can resolve it, source: draft hypotheses H1-H3, confidence: high}
- {claim: RQ3's comparative framing exceeds what stakeholder interviews can answer, source: draft RQ1-RQ3, confidence: medium}
- {claim: an internal sample measures observed behavior secondhand, source: sample_size field, confidence: medium}
```

Fold-in: H3, RQ3, and A2 are dropped (each maps to a "What to change" item; no silent drops). The rename suggestion is declined with a one-line reason: the working title is already approved by the decision owner and the ticket summary is fixed at create time. Final set: H1, H2, A1, RQ1, RQ2.

> Revised set above is shown; go-ahead?

Scripted user: "go".

## Phase 7 — Method, sample, investment (WAIT)

Dominant RQ shape: "How or why X happens" -> method table row: External Interviews, 8-12 per segment, 45-60 min. Rules applied: qualitative leads (no survey for a why question).

> - Method: External Interviews. Reason: the RQs ask how first-week users behave, and the behavior is external to the team.
> - Sample size: 8-12 per segment. Session length: 45-60 min. Investment level: M (6-10 external interviews). Research type: Evaluative (a shipping decision).
> - Alternative: Usability Test on the two entry-point designs, 5-8 per design, if a clickable prototype exists by December.
>
> Wait for the pick.

Scripted user override: "Internal Interviews, 5 participants, 30 minutes, investment SM, UXR to Lead — stakeholder pass first because of the January deadline; external wave follows if needed." (Overrides are accepted for any line per phase 8 rules.)

## Phase 8 — Fields, preview, create (WAIT, the last gate)

Routing: role `uxr` -> assignee and UX Researcher are the current user. Field panel, one line each with origin:

> - Group (pod): Onboarding — phase 1 answer
> - Research type: Evaluative — decision shape (shipping decision)
> - Method: Internal Interviews — user override (phase 7)
> - Support level: UXR to Lead — user override (phase 7)
> - Investment: SM — user override (phase 7, up to 5 internal interviews)
> - Expected outcomes: Summary of findings — user override
> - UX Researcher: Jordan Reyes — current user (role uxr)
> - Assignee: Jordan Reyes — current user (role uxr)
> - Priority: Medium — tracker.default_priority
> - Start date: 2026-11-17 .. 2026-12-01 — user override of the default window (today .. today+90d); ends before the January review
> - Labels: new-user-timeline-discoverability, 2026-q4 — topic slug + current quarter

Preview:

> - Item type: Study
> - Summary: New user navigation study: timeline discoverability
> - People: assignee Jordan Reyes, UX Researcher Jordan Reyes
> - Labels: new-user-timeline-discoverability, 2026-q4
> - Fields: pod=Onboarding, research-type=Evaluative, method=Internal Interviews, support=UXR to Lead, investment=SM, outcome=Summary of findings, start=2026-11-17 .. 2026-12-01, priority=Medium
> - Body structure (ten blocks, one line each): Directions panel; Results panel; Background & Context table (History, Key Decision, Assumptions & Hypotheses); Resources details block; Research Questions list; Recruitment Strategy table (sample, persona, session length, artifact link); Recruitment Roster table; Checklist; Task items (5); Status notes
> - Resources with a passed share check: 0

Scripted user: "create".

## Build, validate, persist

1. Spec assembled (fixture `uc2-spec-draft.json`).
2. `build_body.py` exit 0 (ADF per `tracker.body_format`); markdown variant rendered via the documented `UXR_CONFIG__TRACKER__BODY_FORMAT` env override for the fixture tracker's read-back.
3. BLOCKED-EXTERNAL `create_item` fixture: fixture UXR-101 stores the pushed body, labels, and fields.
4. Read-back verify: `spec_blocks.assert_full_document` -> `{'panels': 2, 'background_tables': 1, 'recruitment_tables': 1, 'resources_sections': 1, 'roster_sections': 1, 'checklists': 1, 'rq_lists': 1, 'task_items': 5, 'status_nodes': 0, 'roster_rows': 0}` -> `counts OK`.
5. Spec saved: `<state_dir>/specs/UXR-101.spec.json` with the six `_meta` keys via `spec_blocks.make_meta("new")`.
6. Printed: `Created [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101)` — then ran `init UXR-101` in the same turn.

## `init UXR-101`

1. Config read (cached). 2. Spec guard: spec present, loaded. 3. `get_item` summary/status only (fixture): Planned. 4. Slug script: `new-user-navigation-study-timeline-discoverability-q4-2026`. 5. Target folder absent. 6. Plan shown:

> - Ticket: [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101), status Planned
> - Folder: `<research_root>/new-user-navigation-study-timeline-discoverability-q4-2026`
> - UXR: Jordan Reyes · Group: Onboarding · Sync target: local only
> - File tree: `00-overview.md`, `CLAUDE.md`, `.gitignore`, `.claude/settings.json`, `.sessions/`, `analysis/`, `deliverables/`, `interviews/`, `recruitment/`, `scripts/`, `sources/` (one folder per source type plus `interviews/`)
>
> Proceed? (yes / edit path / cancel)

Scripted user: "yes".

7. Scaffold output (verbatim):

```
<!-- DIFFERS: F4 - W1 fixed this behavior; excluded from byte parity -->
scaffold_workspace: warning: git add failed: The following paths are ignored by one of your .gitignore files:
.zcode
hint: Use -f if you really want to add them.
hint: Turn this message off by running
hint: "git config advice.addIgnoredFile false"
scaffolded F:\...\baseline-research\new-user-navigation-study-timeline-discoverability-q4-2026; the commit did not land
```

Exit 1 (warn). Environment note: the baseline research root sits inside another git repo whose `.gitignore` excludes `.zcode/`; the scaffold's `git add` refused the paths and skipped the commit. A standalone research root (the documented case) would `git init` the root and commit cleanly — the script's own fallback. All template files, dotfiles, and the research-root `README.md` index row were written correctly. BASELINE FINDING: scaffolding inside a parent git repo leaves the workspace uncommitted with only a warning.
<!-- /DIFFERS: F4 -->

8. Gitignore gate (verbatim):

```
  [ok] interviews/raw-transcripts/x.txt
  [ok] interviews/participant-key.md
  [ok] interviews/participant-key.md
  [ok] interviews/raw-transcripts/
gitignore gate: all paths are ignored; writes may proceed
```

Exit 0. 9. `workspace.remote` unset -> local only, no push. 10. Next steps:

> - `show UXR-101` - open the study view
> - `edit UXR-101` - change sections from shorthand
> - `recruit UXR-101` - fill the roster and outreach log
> - `trace --project` - the evidence trail for this workspace
> - `notebook UXR-101` - upload the overview and summaries

## UC2 metering

| Metric | Value |
|---|---|
| Wall time | 21:48:50 -> 21:53:30 (4m40s) |
| Inference turns | 12 tool-call rounds |
| Token delta | 24,699 consumed (meter 14,881,320 -> 14,856,621) |
| Script executions (plugin-instructed) | 7 (config.py --print, field_map detect_role, build_body.py x2, spec save snippet, read-back verify, scaffold slug, scaffold scaffold, gitignore_gate; count 8 including fixture-backed-create helper) |
| Subagent dispatches | 1 (hcd-researcher, simulated inline — no Task tool in runner harness) |
| Blocked-external steps | evidence sweep (9 sources, fixture-backed with unavailable lines); `create_item`; `get_item` reads (fixture-backed) |
