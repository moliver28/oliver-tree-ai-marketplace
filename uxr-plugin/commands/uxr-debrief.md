---
description: "Close the loop after one research session: confirm the meeting happened, find and file one git-ignored transcript, write the committed session summary with the research-alignment block, and draft the ticket comment (posts only on approval)"
argument-hint: "<KEY> [--participant=<name>] [--transcript=<path>] [--dry-run] [--check]"
---

Debrief one research session. You confirm the meeting happened, find one
transcript, file it where git cannot commit it, map what the participant
said to the study's research questions, hypotheses, and assumptions, and
draft a short ticket comment. The per-session summary this command writes
is the input the report reads later; its alignment block is a frozen
contract with the report parser.

## Safety rules (read before any step; they override everything below)

1. **People data stays out of git.** The raw transcript and the
   participant key are gitignored. Before any write, run the gitignore
   gate (`scripts/gitignore_gate.py assert-ignored`); exit 3 stops the
   whole run before a single file is written. Never commit, paste into
   the ticket, or send a raw transcript or contact detail.
2. **Drafts only.** The recap comment is shown, never posted, until the
   user replies `go`, `post`, or `yes`. Anything else (`edit`, `cancel`,
   silence) means no post.
3. **Never invent support.** The alignment block only states what the
   transcript shows. An unanswered research question says so, verbatim.
4. **One transcript.** When several copies exist, copy exactly one and
   name the others in the recap.
5. `--dry-run` creates no file, updates no participant-key row, and
   posts no comment; it shows everything a real run would write.
6. `--check` is read-only: it lists stale sessions and stops.

## Inputs

`$ARGUMENTS` is `<KEY>` with any of: `--participant=<name>`,
`--transcript=<path>` (a local file that skips transcript search),
`--dry-run`, `--check`.

## Setup (every run)

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `paths.research_root`, `paths.state_dir`, `org.internal_domains`, `org.notetaker_email`, `comments.footer`, `tracker.ticket_regex`, and the roster statuses under `recruit.statuses.interview`.
2. Read the ticket: summary, body, and dates, via `get_item` in
   `references/tracker.md`.
3. Load the roster from the spec at `<state_dir>/specs/<KEY>.spec.json`
   (never parse the roster from the ticket body). No spec file: tell the
   user to run `backfill_spec.py` first and stop before any write. When
   the spec carries the ask keys, print `Original ask (<ask_source
   date>): <ask_verbatim>` after the load; a pre-ask spec continues
   without the line. Then run the checklist gate - `python
   "${CLAUDE_PLUGIN_ROOT}/lib/checklist_gate.py" check --type
   <qual-interviews | quant-surveys> --spec <spec path> --workspace
   <workspace>` - and print the missing list as gap lines; never block
   (debrief is per-session).

## Phases

| Phase | What you do |
|---|---|
| 0. Check (`--check` only) | List the calendar events of the past 7 days, save them as a JSON array to a temp file, then run `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" check-stale-transcripts --events-json <file> --research-dirs <research_root> --cache-path <state_dir>/stale-transcript-cache.json --window-days 7` plus one `--internal-domain <dns>` per `org.internal_domains` entry. Print its output verbatim, report the sessions with no filed summary, and stop. (The SessionStart hook may later print up to 5 stale titles from that cache while it is under 48 hours old.) |
| 1. Resolve | Pick the participant: filter the roster by `--participant` as a case-insensitive name substring; no flag, take the `Scheduled` rows; still ambiguous, the single remaining row. Two or more matches: list them and ask. Never pick the first. No match or nothing Scheduled: list the rows, or ask for the participant's email and the session date. |
| 2. Verify meeting | List calendar events starting within 30 minutes of the booked slot. Confident = the participant's email is an attendee AND the start is within 30 minutes. One signal only (right person, wrong time, or right time, no participant email): show the candidates and ask. None: stop, or accept `--transcript`. The event title is a tie-breaker only. |
| 3. Find transcript | In order: (1) the call-recording store, when the notetaker (`org.notetaker_email`) attended; (2) a local recorder folder holding a file for the event date; (3) mail search near the event date restricted to the allowlist of senders: Zoom, Otter, Fireflies, Read.ai, Grain, Google Meet or Gemini, and your call recorder - rank candidates on sender, then subject, then date before fetching anything. Follow a Drive link. Never fetch a portal that needs a login. |
| 3b. Dedupe | Rank candidate transcripts: speaker-labeled with a summary, then speaker-labeled, then raw text. Copy exactly one; name the others in the recap. Keep at most 3 source links: the platform recap URL, the mail permalink, the calendar event link. Make the choice with `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" pick-transcript --candidates '<json>'` (each candidate `{"source", "kind", "url"?, "path"?}`, kind one of `speaker-labeled with a summary`, `speaker-labeled`, `raw text`). |
| 4. File | Find the workspace: `python "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold_workspace.py" lookup-workspace --ticket <KEY> --readme <research_root>/README.md` (prints the path; `WORKSPACE_NOT_FOUND` means ask for a path or offer `init`, then stop). Slug = the workspace folder name; date = the session date `YYYY-MM-DD`. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/gitignore_gate.py" assert-ignored --repo <workspace> interviews/raw-transcripts/<slug>-<date>-transcript.txt` plus one path per `workspace.gitignored_paths` entry from the configuration loaded in step 1 (config adds to the hardcoded path); exit 3 stops before any write. Then write the raw transcript to that path with a header listing the source links; write `interviews/<slug>-<date>-summary.md` (committed); add or update the participant's row in `interviews/participant-key.md` (gitignored; columns Name, Role, Account, ARR, Email, Session date as they apply). |
| 5. Enrich | Run this run's ONE model call: read the transcript and the spec (hypotheses and assumptions carry `label` and `text`; research questions are strings), and produce ONE JSON payload - the session paragraph, speaker-labeled quotes copied from the transcript
verbatim (never paraphrased), and per-entry alignment lines (RQ findings, hypothesis stances with a one-line why, assumption stances with a one-line why). Stances are the frozen contract (`Supports` / `Challenges` / `Mixed`; `Holds` / `Breaks` / `Untested`); an unanswered RQ carries an empty finding and the assembly keeps the exact `No direct evidence this session.` wording; never invent support. Assemble the file: `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" assemble-summary --file <summary path> --payload <payload.json>`, then gate it: `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" check-summary --file <summary path>`. Any `WARN` or exit 1 means the payload is corrected and re-assembled before phase 6 - an off-contract stance would silently become a missing verdict in the report. A section that does not parse is flagged in the summary as missing, with the reason, not guessed. |
| 6. Recap | The recap is assembled from the same payload, not re-written: add `recap` to the phase 5 JSON (the one-paragraph session intro, the transcript link and summary path, 2 to 4 plain `What landed:` sentences with no bare codes, the `Not covered:` topics), then run `python "${CLAUDE_PLUGIN_ROOT}/references/debrief_helpers.py" render-recap --file <draft> --payload <payload.json> --date <date> --footer "<comments.footer with {display_name} replaced>"` and gate it with `check-recap`. A failed check means the payload is corrected and re-assembled before anything is shown. Show it, and wait. Post only on `go`, `post`, or `yes`, via `add_comment` in `references/tracker.md`. |
| 7. Index | Optional: when a local search index server is configured, start a sync for the workspace. Say in one line that the sync is optional and starting (or skipped when no server is configured). Never block on it; a failed sync is one warning line. |

## Summary and recap shapes (script-assembled)

`assemble-summary` writes `interviews/<slug>-<date>-summary.md`: the
one-paragraph session summary (length, participant role and context, what
the session was about, the chosen transcript source), the notable quotes
(speaker-labeled, wording kept), then the frozen
`## Insights → Research Alignment` block - one line per spec entry in the
spec's own order, the exact `No direct evidence this session.` and
`Untested this session - <why>.` wording for unanswered entries. The
report parser reads that exact shape; `check-summary` gates it at write
time. `render-recap` writes the recap under 200 words: the
`[uxr-debrief <date>]` first line, the one-paragraph intro, the transcript
link and the summary's relative path, `What landed:` followed by its 2 to
4 plain sentences as one prose line (no bare `RQ2`/`H1` codes), `Not
covered:` followed by the topics as one prose clause (comma-and joined,
one closing period), one blank line, then the `comments.footer`;
`check-recap` gates it. A failed gate means the
payload is corrected and re-assembled - never shown broken. Under
`--dry-run` the recap is shown under a `DRY RUN - nothing posted` heading
and the command stops.

## Failure table (stop cleanly, never advance on bad state)

| State | Action |
|---|---|
| Participant not found or not Scheduled | List rows, or ask for email and date |
| Two or more name matches | List and ask |
| No confident meeting | Ask, or accept `--transcript` |
| No transcript found | Report the searches run, offer `--transcript`, stop |
| Transcript cannot be fetched | Save the recap URL, file the summary with "verbatim not retrieved", continue |
| No workspace | Ask for a path or offer `init`, stop |
| Raw path not ignored | Stop before any write |

## Scripts

| Script | Contract |
|---|---|
| `references/debrief_helpers.py check-stale-transcripts --events-json <file> --research-dirs <root> --cache-path <file> --window-days 7 [--today <date>] [--internal-domain <dns>]` | Flags interview-shaped events (external attendee, or 2-3 attendees; never standup/sync/1:1/weekly/retro/planning/coffee/team-meeting titles) with no `interviews/*-<date>-summary.md`, and writes the `{checked_at, stale: [{title, date}]}` cache. |
| `references/debrief_helpers.py render-appendix --key <participant-key.md> [--arr-file <json>]` | Prints `Name, Role (Account, ARR)` per participant-key row, reading columns by header name; absent parts stay out. Use it when the report asks for the participant appendix. |
| `references/debrief_helpers.py pick-transcript --candidates '<json>'` | Applies the dedupe priority and names the not-copied sources. |
| `references/debrief_helpers.py check-recap --file <draft> --date <date> --footer <md>` | Gates the recap: heading, word cap, no bare `RQ<digit>`/`H<digit>` token, `What landed:`, `Not covered:`, footer last. Exit 1 rewrites. |
| `references/debrief_helpers.py check-summary --file <summary.md>` | Gates the alignment block at write time: every `H` line starts with a contract stance, every `A` line too, and a missing block fails. `WARN` lines plus exit 1 rewrite. |
| `scripts/gitignore_gate.py assert-ignored --repo <workspace> <paths>` | The people-protecting gate; exit 3 stops before any write. |
| `scripts/scaffold_workspace.py lookup-workspace --ticket <KEY> --readme <research_root>/README.md` | Prints the workspace path, or `WORKSPACE_NOT_FOUND` on stderr. |

## Rules of last resort

- Never write any file before the gitignore gate passes in the same run.
- The ticket gets comments only (`add_comment`); the body, status, and
  fields are never touched here.
- Two searches that both fail end the search phase: report what was
  searched, offer `--transcript`, stop. Never widen the sender allowlist.
