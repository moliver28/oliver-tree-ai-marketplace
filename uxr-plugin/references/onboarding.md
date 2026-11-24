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

## The prioritization calculator (issue 114)

The calculator scores one research request against the organization's
named inputs. The built-in default needs zero configuration and always
works:

    score = impact*3 + confidence*2 + urgency*1

Each input is answered 1 to 3 (low to high) for the request. Two config
keys override it:

- `priority.weights`: `{<input name>: <weight>}`. The input names are the
  operator's own field names; an input without a weight carries weight 1.
- `priority.formula`: a formula string that replaces the built-in
  formula when set. Empty means the built-in formula.

Both keys ship empty in `config/org.example.yaml`. The walkthrough scores
one real request with the saved or built-in weights and shows the
arithmetic term by term; the operator may take one weight override and
re-score.

### The per-backend input mapping (issue 114 section 2)

`prioritization.fields` holds the calculator's inputs per tracker kind
(the adapter registry selector). Onboarding records it in the calculator
question: one line per input, as

    <input>: <tracker field id or label prefix>: <low> | <medium> | <high>

The first slot is the tracker-side source (`id`): a Jira custom field id,
a GitHub or GitLab label name or prefix, or a Notion property name. The
second slot is the ordinal value list, low to high; a rule written as
`number <low> <high>` bounds a numeric rule instead. The recorded entry
is `{id, kind, values}` (select rule) or `{id, kind: number, low, high}`.
A line without the value-order tail gets exactly one follow-up ask for
that input's order; an empty answer drops the input, and the command
never invents a value.

The deterministic scorer (`scripts/prioritize.py`) normalizes every input
onto one comparable scale, the integers 1 to 3, and sums the weighted
terms. The normalization law per rule kind:

- `select`: the value matches one entry of `values` (without case). One
  entry scores 1; otherwise the position maps proportionally:
  `round(1 + 2 * position / (n - 1))`. Three ordered entries map 1, 2, 3.
- `labels`: the tracker's label set for the field arrives as one
  comma-separated list. A label matching a `values` entry scores at its
  position; the highest match wins; no match is a value error.
- `number`: with `low` and `high` the value maps linearly onto 1 to 3;
  without them the value rounds and clamps onto 1 to 3.
- no rule: the input arrives pre-normalized; it must be 1, 2, or 3.

An unknown input name is a usage error (exit 2), never a guess. If a
backend cannot supply one of the inputs, the onboarding summary names it;
the calculator scores the inputs the backend supplies and never invents
machinery for the rest.

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
