# Evidence lookup

The query playbook for the `/uxr-plugin:uxr-new` evidence sweep. The sweep
runs every enabled source in ONE parallel batch of tool calls (no waiting
between sources), then prints one synthesis block. Which sources run comes
from `evidence.sources` in the config; chat channels come from
`evidence.chat_channels`. A source whose tool call fails is logged
`<Tool>: unavailable (skipped)` in the synthesis block and the sweep
continues. Never skip a source silently; never retry a failed source twice.

The named sources this playbook defines:

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

A configured key this file does not define is logged
`<key>: unavailable (skipped)`. Jira reference calls (`tracker.kind` is
`jira`): `tracker_recent` and `tracker_topic` use `search(filter)`
(`references/tracker.md`) with `NOT project = <project_key>` plus the
window and an `ORDER BY updated DESC`; `tracker_recent` filters
`assignee = <current user>`, `tracker_topic` searches the topic phrase in
summary and description.

## Per-source notes

- `tracker_recent` (90 days, limit 20): what the requester and the team
  have been logging lately in other projects; it reveals work this study
  would collide with or duplicate.
- `tracker_topic` (180 days, limit 10): prior studies and engineering
  issues about the same topic; each hit is a candidate Resources row and a
  candidate "hypotheses in flight".
- `drive`: full-text search for the topic (limit 15), plus the 25 most
  recently modified files in the team's shared research folders. Record
  doc names and owners; the shareability pass (below) tags every URL.
- `feedback`: the customer feedback store (the reference implementation
  reads an Enterpret knowledge graph). Query the topic, return the
  strongest themes with counts. NEVER skip this source when the topic is
  churn, satisfaction, or adoption, even if the tool is slow; if it fails,
  the synthesis block says so and names the gap the study would carry.
- `chat` (limit 20): search only the channels in `evidence.chat_channels`;
  return threads that name the topic, pain, or a decision in flight.
- `wiki` (180 days, limit 10): skip this source for a tactical study. A
  tactical study answers a build-or-ship question for one team this
  quarter; a strategic study sets direction across quarters, and wiki
  context matters there.
- `jtbd`, `personas`: take the top 3 to 5 jobs or personas that touch the
  topic, each with a ring tag (`internal`, `external`, or `synthetic`).
  These become the spec's `jtbd_refs` and `persona_refs`
  (`{label, url, ring}`). A synthetic persona is never used without the
  user's explicit yes (safety gate).
- `chat_discovery`: find the channels where this study's participants and
  stakeholders talk (channel list search on the topic words, plus
  `routing.group_to_channels` for the group). Propose the best channel as
  the study's `slack_channel` (`{name, id}`) and confirm it with the user.

## Synthesis block

After the batch returns, print one block, nothing between the calls and
this block:

```
## Evidence sweep

| Source | Hits |
|---|---|
| Tracker: your recent items (other projects) | 6 |
| Tracker: topic search (other projects) | 3 |
| Drive | 9 |
| Feedback store | 41 |
| Chat | 12 |
| Wiki | 4 |
| JTBD | 3 |
| Personas | 2 |

- Slack: unavailable (skipped)

Top signals
- Owning group: <group the evidence clusters under>
- Hypotheses in flight: <claims already being tested elsewhere, one line each>
- Pain strength: high | medium | low
- Stakeholders: <people who own or touched the evidence>
```

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
