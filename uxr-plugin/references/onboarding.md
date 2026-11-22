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
asana, or an operator-named system) and with knowledge-base systems, which
may be the same system at a different area.

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
