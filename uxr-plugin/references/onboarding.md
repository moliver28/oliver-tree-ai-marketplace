# Onboarding flow rules (issue 114; the adapter registry points here)

The rules `onboard` follows when it asks, saves, and verifies. The command
holds the flow; this reference holds the rules the flow must keep.

## The ask law

One question per message, verbatim, and the turn ends after every ask.
Every answer goes into config exactly as given; the command never invents
a value, a field name, or a path. An empty answer takes the documented
default. Every gate inside the walkthrough keeps its own plain-word ask.

## The saved path (efficient reuse, MO ruling 2026-11-21)

Onboarding saves the efficient path: once `config/org.yaml` exists and
loads, every later run reads it and asks nothing. Re-running
`onboard --recheck` is the only way to re-ask. The saved path is verified
with two deterministic commands before the walkthrough starts:

- `python lib/config.py --print` (exit 0 prints the resolved config).
- `python lib/adapters.py describe --kind <kind>` (exit 0 prints the
  adapter record as one JSON line, or `null` when the entry is declared
  but not built: absent-sync).

## Adapter selection

The plugin is general: it works with issue systems (jira, linear, github,
gitlab, notion, asana, or an operator-named system) and with
knowledge-base systems, which may be the same system at a different area
(the shipped example demonstrates the pair: Notion is the built issues
entry `notion` and the declared KB entry `notion-kb`).

- The issue system sets `tracker.kind` and the `tracker.*` connection
  keys. Its adapter entry follows the shipped `adapters` section in
  `config/org.example.yaml`: `module` (empty = declared, not built),
  `doc` (the reference holding the system's parameters), `area: issues`,
  and the `capabilities` bits.
- The knowledge-base system gets its own, separate adapter entry with
  `area: kb` and the read-only default (`pull: true`, `push: false`,
  `spec_transform: false`). When the KB system equals the issue system,
  the KB entry is keyed `<kind>-kb` so the two entries never collide
  (same system, different areas = two separate adapter entries).
- A declared entry with an empty module is absent-sync: the harness
  works; the tracker operations wait for the adapter module. Nothing
  prints on the absent path.

## Knowledge-base semantics

For an `area: kb` entry the operations mean: `pull` = query and read
(text plus metadata); `push` = write a page or mirror entry; `connect` =
resolve the workspace and root ids from config; `spec_transform` ships
off (KB pull carries plain text). A `push: false` entry is read-only by
default, and any consumer that attempts a write must refuse it
deterministically before the write is attempted.

## The prioritization calculator (issue 114; MO ruling 2026-11-24)

The calculator's zero-configuration default is the GitLab handbook
priority calculator. Scale wording and bands are cited from:
https://handbook.gitlab.com/handbook/upstream-studios/experience-research/research-prioritization/

Six criteria - impact, users, dependency, timeline, alternatives,
alignment - each scored 1 to 5, 1 = most urgent, per the handbook scale
wording (`scripts/prioritize.py inputs` prints the wording; the runtime
ask prints it too). The aggregation is the unweighted average (sum / 6),
and the average maps onto the bands verbatim:

    mean <= 1.5   P1 Must Do
    mean <= 2.4   P2 Should Do
    mean <= 3.5   P3 Nice to Do
    mean <= 4.5   P4 Backlog
    mean > 4.5    Will Not Do

Both calculators only generate recommendations; the researcher and the
stakeholders agree on the final level (handbook law).

### The per-backend criterion mapping (issue 114 section 2)

`prioritization.fields` maps each criterion to the tracker's field per
tracker kind (the adapter registry selector). Onboarding records it in
the calculator question: one line per mapped criterion, as

    <criterion>: <tracker field id or label prefix>: <most urgent> | ... | <least urgent>

The first slot is the tracker-side source (`id`): a Jira custom field id,
a GitHub or GitLab label name or prefix, or a Notion property name. The
second slot is the ordinal value list, most urgent first; a rule written
as `number <low> <high>` bounds a numeric rule instead. The recorded
entry is `{id, kind, values}` (select rule) or
`{id, kind: number, low, high}`. A line without the value-order tail
gets exactly one follow-up ask for that criterion's order; an empty
answer drops the mapping, and the command never invents a value. A line
naming an input outside the six criteria is refused in one line (the
weighted-sum override is where other inputs live).

The deterministic scorer (`scripts/prioritize.py`) normalizes every
mapped value onto the preset scale, the integers 1 to 5 (1 = most
urgent). The normalization law per rule kind:

- `select`: the value matches one entry of `values` (without case). One
  entry scores 1; otherwise the position maps proportionally:
  `round(1 + 4 * position / (n - 1))`.
- `labels`: the tracker's label set for the criterion arrives as one
  comma-separated list. A label matching a `values` entry scores at its
  position; the highest match wins; no match is a value error.
- `number`: with `low` and `high` the value maps linearly onto 1 to 5;
  without them the value rounds and clamps onto 1 to 5.
- no rule: the criterion is answered 1 to 5 directly at scoring time.

An unknown input name is a usage error (exit 2), never a guess.

### The runtime ask (issue 114; MO ruling 2026-11-24)

A missing tracker field is asked at runtime (`--ask`): one deterministic
numbered prompt 1 to 5 printing that criterion's handbook scale
wording; the answer is recorded and used. The ask is zero-LLM and works
the same under the walkthrough's calculator step. An out-of-range
answer gets one bounded re-ask, then a value error (exit 3); an ended
ask is a value error, never a guess. The prompts print on stderr, so
`--json` output stays parseable. `--record <path>` writes the
deterministic result record (the asked answers and the score) as one
JSON line.

### The support-level mode (issue 114; MO ruling 2026-11-24)

`scripts/prioritize.py score --support` is the handbook's support-level
calculator as a mode of the same script: six per-project judgments, not
tracker fields, collected through the same runtime ask when not
supplied - Type (foundational 3 / problem validation 2 / solution
validation 1), Ownership (yes 3 / somewhat 2 / no 1), Design Support
(study led by UXR 3 / requesting team has designers 2 / no designers
1), Complexity (yes 2 / no 1 / unknown 0), Skill Development (yes 3 /
somewhat 2 / no 1), Confidence (high 3 / medium 2 / low 1). The sum
divides by 16 (the ruling's divisor; the listed maxima sum to 17, so
the all-max judgment lands above 100 percent) and the percentage names
the level with the MO-renamed labels verbatim - the handbook's former
metal names never ship:

- above 80 percent: `UXR to Lead` - the researcher drives the study end
  to end.
- 51 to 80 percent: `UXR to Support` - the researcher takes specified
  tasks within the study.
- 50 percent and below: `UXR to Review` - the researcher is consulted
  and reviews the team's work.

### The weighted-sum override mode

`priority.weights` or `priority.formula` switches the calculator to the
weighted-sum mode (the custom-formula path; the earlier default
`impact*3 + confidence*2 + urgency*1` stays reachable there). Inputs
normalize onto the integers 1 to 3 by the same rule kinds, and the
score is the weighted sum.

## The walkthrough completion record (issue 114 section 3)

The walkthrough makes the operator use every critical feature once:
create an issue, move a checklist, run the prioritization calculator on
their own data, sync a change. The gate behind that law is a script
check, never readable text only. `scripts/walkthrough.py` keeps the
completion record and owns two laws:

- `record --feature <create|move|calculator|sync> --key <KEY>` writes
  one entry per used feature. The command runs right after the feature
  completes; the record carries the feature name and the ticket key, no
  timestamps and no free text, so the record stays a deterministic
  artifact.
- `check` exits 0 only when all four features carry a record. The
  onboarding command prints its walkthrough completion line only on that
  exit, so finishing the walkthrough requires the four features to have
  been used. A declined step stays unrecorded and keeps the walkthrough
  open; the operator finishes it later by using the missing features and
  re-running the check.

The record lives at `<state_dir>/walkthrough.json` under the researcher
state law (`UXR_STATE_DIR`, then `paths.state_dir`; `--state-dir`
overrides). An unresolvable state dir never passes the gate: the record
command exits 3 and the check fails closed (exit 1). A record file that
cannot parse is treated as empty, and the next record write repairs it.
`clear` removes the record for a fresh run.

## The interview-data ignore set (issue 57)

`privacy.init_ignore` is the interview-data part of the `init` gitignore
gate's checked set, saved by onboarding.

- Empty (the shipped default): the set covers ALL interview data; the
  whole `interviews/` tree must be gitignored. This flips the shipped
  default of earlier releases, which ignored only the participant key
  and the raw transcripts.
- Non-empty: exactly the listed paths form the interview-data set.

The participant-identity floor (`interviews/participant-key.md`,
`interviews/raw-transcripts/`) always applies on top and is never
replaceable. `init` passes the effective set to the gitignore gate and
appends its entries to the workspace `.gitignore` before the gate runs,
so the config and the file can never disagree.

## The workspace git rule (issue 58)

Study workspaces (uxr-workspaces) are version control for people who do
not know git: commit to the workspace's main branch; never create
branches and never open pull requests inside a uxr-workspace. The
workspace pushes to its configured remote only when
`workspace.remote_push` is true (default false). The marketplace
repository is not a uxr-workspace; its own contribution flow is
untouched.

## The org-chart connector paths (issue 50)

`recruiting.org_chart_paths` holds the connector paths, saved at
onboarding, that the recruit flow's `--coordinate` step searches for
other teams and accounts that could help recruit. Searching reads the
saved paths first; the list empty means the flow prints one line that
the org chart is not configured and continues. Saving the path once is
what makes every later search efficient.
