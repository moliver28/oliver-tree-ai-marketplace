# Evidence lookup

The law for the `/uxr-plugin:uxr-new` evidence sweep. The sweep runs every
enabled source in ONE parallel batch of tool calls (no waiting between
sources) against the query plan `scripts/evidence_sweep.py plan` prints;
`digest` compresses the results into the evidence digest and renders the
synthesis table. A source whose tool call fails is logged
`<Tool>: unavailable (skipped)` in the synthesis block and the sweep
continues. Never skip a source silently; never retry a failed source twice.

Which sources run comes from `evidence.sources` in the config; chat channels
come from `evidence.chat_channels`.

| Config key in `evidence.sources` | Source | Window | Limit |
|---|---|---|---|
| `tracker_recent` | Your recent items in other tracker projects | last 90 days | 20 |
| `tracker_topic` | Topic search in other tracker projects | last 180 days | 10 |
| `drive` | Drive full-text search, plus the 25 most recently modified files | - | 15 + 25 |
| `feedback` | The customer feedback store | - | per store default |
| `chat` | Chat search in the configured channels | - | 20 |
| `wiki` | Wiki search | last 180 days | 10 |
| `jtbd` | Jobs-to-be-done source from `ssot.jtbd_url` | - | top 3-5 |
| `personas` | Personas source from `ssot.personas_url` | - | top 3-5 |
| `chat_discovery` | Chat channel discovery for the study | - | - |

A configured key the plan does not define is logged `<key>: unavailable
(skipped)`. The feedback store is NEVER skipped silently when the topic is
churn, satisfaction, or adoption: the digest names the gap the study
carries. `wiki` is skipped for a tactical study (a build-or-ship question
for one team this quarter; a strategic study sets direction across
quarters). `jtbd` and `personas` results become the spec's `jtbd_refs` and
`persona_refs` (`{label, url, ring}` with ring `internal`, `external`, or
`synthetic`; a synthetic persona is never used without the user's explicit
yes). `chat_discovery` proposes the study's `slack_channel` and the user
confirms it.

## Top signals

The four signals lines are the sweep's one model call (`prompt:
signals@1`), consumed with the digest ONLY - never raw search results.
Pain strength: `high` when the feedback store or chat shows repeated,
recent, unresolved pain on the topic; `medium` when pain appears but is
scattered or old; `low` when the evidence is mostly neutral or absent.
Name the evidence behind the call in one clause.

## Shareability (mandatory, after the sweep)

For every Drive URL that may become a Resources row, read its permissions
before it enters the draft. Tag exactly one of:

- `shared`: the team domain (`org.team_share_domain`) or anyone-with-link
  has Commenter or higher.
- `private`: owner access only.
- `unknown`: the permission check failed. Say the check failed; never
  guess `shared`.

Never change a permission. Ever. If a file is private, the draft keeps it
and the rendered ticket shows it with the lock marker and the legend; the
user decides whether to share it.

Never put a local file path in Resources. The spec validator rejects local
paths. For a local file the user names, search Drive for a match, then ask
about candidates one at a time and require a separate "yes" for each
candidate you link. No answer means no link.

Every Resources row leaves this phase as `{label, url, share_status}` (or
`{label, text, share_status}` when the source has no URL). Share statuses
flow into the spec unchanged; the body renderer turns `private` into the
lock marker and the legend line.
