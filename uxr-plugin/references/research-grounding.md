# Research grounding

The contract for the mandatory `hcd-researcher` review: when the agent
runs, what it receives, what it returns, and what the commands that
dispatch it must do with the result. `hooks/review_gate.py` enforces the
same contract with a reminder (never a denial).

## The agent

`agents/hcd-researcher.md` defines a read-only reviewer with a
human-centered design lens: does this research artifact actually serve the
people who will be studied and the decision it claims to inform? Model
`sonnet`; tools `Read, Grep, Glob, WebSearch, WebFetch`. It writes no
files and calls no tracker tools. It reviews; the requesting command owns
every edit.

Dispatch it with the Task tool, `subagent_type: hcd-researcher`, and name
the two inputs in the prompt:

1. The study's `00-overview.md` (a workspace exists), or the draft spec
   plus the background and decision text (during `/uxr-plugin:uxr-new`,
   before a workspace exists).
2. The target artifact to review: the hypotheses and RQ draft, the
   interview script, the report draft, or the deck outline, depending on
   the calling command.

## When the review is mandatory

- `/uxr-plugin:uxr-new` phase 6: on the decision, hypotheses, and RQs,
  before method selection (phase 7). The build block never runs if the
  review did not run.
- The interview-script review loop (issue 11) dispatches it for concept,
  usability, and onboarding-tour studies, with the script-rigor rider.
- The report review loop (issue 13) and the deck critic slot (issue 12)
  use the same agent and the same output contract.

A one-line decline is the only allowed substitute, and it must be printed
to the user: `Declined hcd-researcher review: <one line why>`.

## Output contract

The agent returns exactly these sections, in this order:

```
Summary
<2 to 3 sentences>

Strengths
- <3 to 5>

Risks
- <3 to 5>

What to change
- <3 to 5, or "None">

findings:
- {claim: <one sentence>, source: <where this came from>, confidence: high|medium|low}
```

`findings:` is a list; every entry carries all three keys. `source` names
the artifact, a file, or a URL the claim rests on. A claim that rests on
outside evidence (something the input artifacts do not contain) needs 2
authoritative sources, or the claim's `source` field must read exactly
`insufficient external evidence`.

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
  `deliverables/`, `scripts/`, `analysis/`, or a numbered root file like
  `09-findings.md`; never `README.md`, `00-overview.md`, `interviews/`,
  `sources/`, `recruitment/`), if no marker exists for the study and this
  session has not been reminded for it yet, the hook prints one reminder
  via `systemMessage` and `additionalContext`. It never sets a
  permission decision and never blocks the write. One reminder per
  session per study.
- The reminder says what the marker proves and what it does not: the
  marker proves the agent ran on this study; it does not prove the
  findings were used. The writer still owes the fold-in or the decline.
- Opt out entirely by creating `~/.claude/.uxr-hcd-gate-off`. The hook
  then prints nothing and writes nothing.

History note (do not copy the reference plugin's 1.13.0 behavior): the
gate once denied writes until the review ran, and users hit friction;
1.14.0 made it a reminder. It stays a reminder.
