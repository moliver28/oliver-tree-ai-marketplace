# Other-tracker adapters (read when `tracker.kind` is not `jira`)

Parameter detail for the Linear and Asana columns of the generic
operations table in `tracker.md`, plus the field-kind mapping for every
non-Jira tracker. The built GitHub Issues adapter has its own file,
`references/tracker-github.md`; read it when `tracker.kind` is `github`.
The built GitLab Issues adapter has its own file,
`references/tracker-gitlab.md`; read it when `tracker.kind` is `gitlab`.
The built Notion adapter has its own file,
`references/tracker-notion.md`; read it when `tracker.kind` is `notion`.
The listed parameter sets are examples: an operator-named kind (`other`
in onboarding) asks the same six connection keys. None of it has been
live-verified in this build; treat every parameter as `verify-live`
before first use.

## Linear, Asana parameters

- **Linear (GraphQL API):** `viewer`; `userLookup` or the users search for
  `find_user`; `issue` query with `id` for `get_item`; `issues` with a
  filter for `search`; `issueCreate` / `issueUpdate` mutations;
  `commentCreate` with a `body`; `issueUpdate` with `stateId` for
  `set_state`, where the id comes from the team's `workflowStates` read in
  the same session.
- **Asana (REST API):** `GET /users/me`; workspace typeahead or user list;
  `GET /tasks/{gid}`; the workspace search endpoint; `POST /tasks`;
  `PUT /tasks/{gid}`; `POST /tasks/{gid}/stories` for comments (text
  parameter); move to section for `set_state` after reading the project's
  sections.

## Field kind mapping when a tracker lacks a kind

Map each configured field kind onto the tracker's closest mechanism; the
mapping per field lives in `fields.<name>` (`id`), the mechanism choice
here:

| Kind | GitHub Issues | GitLab Issues | Linear | Asana |
|---|---|---|---|---|
| `single_select` | Projects single-select field, or label `name:value` | scoped label `name:value` | label group | enum custom field |
| `multi_select` | labels | labels | labels | multi-enum custom field |
| `interval` | two date fields (start, target) | `start_date` and `due_date` | two custom dates or cycle | start and due dates |
| `user` | assignees or Projects people field | assignee username | assignee plus custom user property | custom people field |
| `url` | Projects text field | label convention or configured custom field | link attachment | text custom field |

## Prioritization inputs per tracker (issue 114)

The calculator (`scripts/prioritize.py`) keys `prioritization.fields` by
`tracker.kind`, so these conventions light up per backend with one shared
code path. The `id` slot of each mapping entry names the tracker-side
source; the value order is the `values` list, low to high.

- **GitHub Issues**: label conventions. The `id` holds the label name or
  prefix; the labels the issue carries are the value (a `labels` rule,
  for example `id: "impact/"`, `values: [impact/low, impact/medium,
  impact/high]`). A Projects single-select field maps as a `select` rule.
- **GitLab**: labels and weights. A weight label maps as a `labels`
  rule; the GitLab issue weight maps as a `number` rule with its bounds
  (`id: "weight"`, `low: 1`, `high: 10`).
- **Notion**: properties. A status or select property maps as a `select`
  rule (`id` holds the property name, `values` the status order); a
  number property maps as a `number` rule.
- **Linear and Asana**: the same two shapes; a label group or enum maps
  as `select`, a numeric field as `number`.

The normalizer maps every rule onto 1 to 3; the law and the recorded
config shape live in `references/onboarding.md`. A backend that cannot
supply an input leaves it out of its mapping; the calculator scores what
the backend supplies.
