# UC3 — Ticket / request understanding (`/uxr-plugin:uxr-mine`, `/uxr-plugin:uxr-show`, router skill)

Run: 2026-11-17, 21:54:24 start. All tracker reads fixture-backed from `baseline-fixtures/tracker-export.json` (BLOCKED-EXTERNAL); rendering follows the command specs exactly. "Now" for relative times = 2026-11-17 21:54 UTC.

## Router skill (`ux-research-tickets`) — plain requests

- "what's on my plate" -> routes to `mine` (intent signal "my plate"; skill rule: must run without a clarifying question).
- "show me UXR-101" -> routes to `show UXR-101`.
- Setup per skill: config read (cached), command file existence check passed.

## `/uxr-plugin:uxr-mine` (default, open only)

current_user() cached (Jordan Reyes, 5f1a2b3c4d5e6f7081a2b3c4). search filter (Jira reference): `project = UXR AND assignee = 5f1a2b3c4d5e6f7081a2b3c4 ORDER BY updated DESC` + `AND status not in (Done, Cancelled)`. First page only. Verbatim output:

| Key | Status | Type | Pri | Summary | Updated |
|---|---|---|---|---|---|
| [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101) | Planned | Study | Medium | New user navigation study: timeline discoverability | just now |
| [UXR-102](https://uxr-example.atlassian.net/browse/UXR-102) | In Progress | Study | High | Pricing page first-run study | 3d ago |
| [UXR-103](https://uxr-example.atlassian.net/browse/UXR-103) | Collecting Data | Study | Low | Card sort: information architecture v2 | 5d ago |

3 open

## `/uxr-plugin:uxr-mine all`

Same filter without the status clause (UXR-104 Done now included). Verbatim output:

| Key | Status | Type | Pri | Summary | Updated |
|---|---|---|---|---|---|
| [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101) | Planned | Study | Medium | New user navigation study: timeline discoverability | just now |
| [UXR-102](https://uxr-example.atlassian.net/browse/UXR-102) | In Progress | Study | High | Pricing page first-run study | 3d ago |
| [UXR-103](https://uxr-example.atlassian.net/browse/UXR-103) | Collecting Data | Study | Low | Card sort: information architecture v2 | 5d ago |
| [UXR-104](https://uxr-example.atlassian.net/browse/UXR-104) | Done | Study | Medium | Checkout flow usability benchmark | 1mo ago |

4 total

(UXR-105 is assigned to Sam Okafor and never appears.)

## `/uxr-plugin:uxr-show UXR-101`

Key normalizes via `ticket_regex` (used unchanged). `get_item` markdown (fixture). Verbatim render (emoji shortcodes converted per the command's table):

## [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101) · New user navigation study: timeline discoverability

**Status** Planned · **Type** Study · **Priority** Medium
**Assignee** Jordan Reyes · **Reporter** Sam Okafor
**Updated** just now · **Created** 7d ago
**Labels** new-user-timeline-discoverability, 2026-q4

### UXR fields

| Field | Value |
|---|---|
| Group | Onboarding |
| Research Type | Evaluative |
| Research Method | Internal Interviews |
| UXR Support Level | UXR to Lead |
| Level of Investment | SM |
| Expected Outcomes | Summary of findings |
| Reviewed Status | Needs Review |
| Start Date | 2026-11-17 .. 2026-12-01 |
| Target End | 2026-12-01 |
| UX Researcher | Jordan Reyes |
| Product Manager | Sam Okafor |
| Product Designer | Riley Chen |
| Eng Manager | Morgan Diaz |

### Description

> **Directions:** Complete the Background & Context sections and relevant data fields **BEFORE** talking with your UX Researcher. Follow the checklist below for more details.
>
> > ## ✅ Results
> >
> > Once research is complete: What decision are you making and why? Try to keep it to 2-3 sentences max.
>
> # 📋 Background & Context
>
> |  |  |
> | --- | --- |
> | ⏱️ History | Support sees a steady trickle of 'where is my project plan?' tickets in each account's first week. Product wants to move the timeline entry point into the left navigation; design believes new users look in the header toolbar first. Leadership decides at the January planning review with no evidence in hand. |
> | 🎯 Key Decision | Do we ship the left-navigation timeline entry or invest in a guided tour? Owner: Product Leadership, January planning review. |
> | ❗ Assumptions & Hypotheses | **Hypotheses**<br>1. **H1.** First-week users look for planning features in the header toolbar before the left navigation.<br>2. **H2.** New project managers who find the timeline in their first session build a plan in that session.<br>**Assumptions**<br>1. **A1.** First-week users want to build a plan during their first session. |
>
> <details>
> <summary>📦 Resources</summary>
>
> - Add links to relevant docs, decks, prior research, customer artifacts. Use Drive / Confluence / Jira URLs that are at least viewable by the team.
>
> </details>
>
> # ❓ Research Questions
>
> 1. Where do first-week users look for the timeline when they want to plan?
> 2. What does a first-session planning attempt look like for a new project manager?
> 3. Tertiary research question
>
> # 🧑‍🤝‍🧑 Recruitment Strategy
>
> |  |  |
> | --- | --- |
> | Target Sample Size | 5 internal participants |
> | Persona / Customer | New project manager in their first week on a trial account |
> | Length of Session / Survey | 30 minutes |
> | Link to Artifact(s) | Link to script / survey / discussion guide once written |
>
> <details>
> <summary>👥 Recruitment Roster</summary>
>
> | Name | Title | Company | Industry | ARR | Contact | Status | Reason |
> | --- | --- | --- | --- | --- | --- | --- | --- |
> |   |   |   |   |   |   |   |   |
>
> </details>
>
> <details>
> <summary>✏️ Checklist</summary>
>
> - [ ] Scope and prioritize: set UXR Support Level and Assignee with the [prioritization calculator](https://example.com/research-calculator).
> - [ ] Draft the study: write Research Questions, Recruitment Strategy, and the script or survey using the [templates folder](https://example.com/templates).
> - [ ] Review and recruit: get it reviewed, then recruit and collect data.
> - [ ] Synthesize and report: summarize, write the report, fill Results, move to Done.
> - [ ] Manage this ticket with the [plugin commands](https://github.com/moliver28/oliver-tree-ai-marketplace).
>
> </details>

### Linked issues (1)

**relates to** [UXR-102](https://uxr-example.atlassian.net/browse/UXR-102) · Pricing page first-run study · In Progress

### Comments (2)

**Riley Chen · 12h ago**
Support ticket volume for 'timeline' in week one is stable at about a dozen per week. 👀

**Sam Okafor · 2d ago**
January planning review is the hard deadline. 🚀

## Edge behaviors exercised (spec-mandated outputs)

- `show` with no argument prints exactly `Which issue? (e.g. UXR-42 or just 42)` and stops (PREFIX = UXR from config; verified against the command text).
- A foreign key (`ABC-7`) prints `ABC-7 is in another project; this plugin reads the UXR study project only. Which UXR issue did you mean?` and never searches.
- Bare number `101` normalizes to `UXR-101`.
- Empty `mine` result prints exactly `No open UXR issues assigned to you.` (one line; not triggered by the fixture — documented from the spec).

## UC3 metering

| Metric | Value |
|---|---|
| Wall time | 21:54:24 -> 21:59:40 (5m16s) |
| Inference turns | 3 tool-call rounds |
| Token delta | 4,363 consumed (meter 14,854,857 -> 14,850,494) |
| Script executions (plugin-instructed) | 0 new (config/current_user cached from session; reads fixture-backed) |
| Subagent dispatches | 0 |
| Blocked-external steps | `search(filter)` x2, `get_item` x1 (fixture-backed fixtures) |
