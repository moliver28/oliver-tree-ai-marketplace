# Research grounding

The law for the mandatory `hcd-researcher` review. The dispatch text itself
is the registry asset `hcd-gate@1` (`python lib/prompts.py render hcd-gate
...`): it carries the deterministic-first fact-check handoff, the
qualitative-residual checklist, the verbatim output sections, and the
checklist-scoped `verdict: {"result": "pass"|"p0", "p0": [...]}` closing
line. `hooks/review_gate.py` enforces the same contract with a reminder
(never a denial).

## The agent

`agents/hcd-researcher.md` defines a read-only reviewer with a
human-centered design lens: does this research artifact actually serve the
people who will be studied and the decision it claims to inform? Model
`sonnet`; tools `Read, Grep, Glob, WebSearch, WebFetch`. It writes no
files and calls no tracker tools. It reviews; the requesting command owns
every edit.

Name the two inputs in the dispatch: the study's `00-overview.md` (or the
draft spec plus the background and decision text during `new`, before a
workspace exists), and the artifact under review.

## When the review is mandatory

- `/uxr-plugin:uxr-new` phase 6: on the decision, hypotheses, and RQs,
  before method selection (phase 7). The build block never runs if the
  gate did not run.
- The report draft (phase 4): one gate per run.
- The interview-script review loop and the deck critic slot use the same
  agent and the same output contract.

A one-line decline is the only allowed substitute, and it must be printed
to the user: `Declined hcd-researcher review: <one line why>`. A `p0`
verdict re-invokes the gate after the fix; everything else folds in.

## Folding the result in

The dispatching command owns the follow-through:

- Fold every "What to change" item and every finding into the artifact,
  or record a one-line decline for that specific item and say why. No
  silent drops: the user sees each finding handled or declined.
- Print the agent's Summary, Risks, and What to change to the user
  verbatim before continuing.

## The marker and the reminder hook

`hooks/review_gate.py` runs on SubagentStop and PreToolUse:

- On SubagentStop for `hcd-researcher`, it writes
  `<workspace>/.sessions/hcd-review-<KEY>.json` with `ran_at`, `agent_id`,
  and `session_id`. That marker is per study, not per artifact.
- On PreToolUse for Write or Edit on a reviewable path (anything under
  `deliverables/`, `scripts/`, `analysis/`, or a numbered root file; never
  `README.md`, `00-overview.md`, `interviews/`, `sources/`,
  `recruitment/`), if no marker exists for the study and this session has
  not been reminded for it yet, the hook prints one reminder via
  `systemMessage` and `additionalContext`. It never blocks a write. One
  reminder per session per study.
- The reminder says what the marker proves and what it does not: the
  marker proves the agent ran on this study; it does not prove the
  findings were used.
- Opt out entirely by creating `~/.claude/.uxr-hcd-gate-off`.

History note: the gate once denied writes until the review ran, and users
hit friction; it has been a reminder since, and it stays a reminder.

## The registered source list

The reviewer's source list is the registry: the law and the condition index live at
`references/research-sources.md`, and one entry file per source lives under
`references/sources/` (R- and A- prefixed ids). When a review checks an outside claim, read the
matching entry file first and fetch its bookmarked page; cite the URL with the claim. Unresolved
ids are recorded, never invented.
