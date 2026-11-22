# Other-tracker adapters (read when `tracker.kind` is not `jira`)

Parameter detail for the Linear, GitHub Issues, and Asana columns of the
generic operations table in `tracker.md`, plus the field-kind mapping for
trackers without a configured kind. The listed parameter sets are examples:
an operator-named kind (`other` in onboarding) asks the same six connection
keys. None of it has been live-verified in
this build; treat every parameter as `verify-live` before first use.

## Linear, GitHub, Asana parameters

- **Linear (GraphQL API):** `viewer`; `userLookup` or the users search for
  `find_user`; `issue` query with `id` for `get_item`; `issues` with a
  filter for `search`; `issueCreate` / `issueUpdate` mutations;
  `commentCreate` with a `body`; `issueUpdate` with `stateId` for
  `set_state`, where the id comes from the team's `workflowStates` read in
  the same session.
- **GitHub Issues (`gh` CLI):** `gh api user`; `gh api search/users`;
  `gh issue view <number> --repo <owner/repo> --json <fields>`;
  `gh search issues`; `gh issue create --title --body --label`;
  `gh issue edit`; `gh issue comment --body`. Projects-based fields (the
  mapped kinds below) are read and written with `gh project field-list`,
  `gh project item-list`, and `gh project item-edit`.
- **Asana (REST API):** `GET /users/me`; workspace typeahead or user list;
  `GET /tasks/{gid}`; the workspace search endpoint; `POST /tasks`;
  `PUT /tasks/{gid}`; `POST /tasks/{gid}/stories` for comments (text
  parameter); move to section for `set_state` after reading the project's
  sections.

## Field kind mapping when a tracker lacks a kind

Map each configured field kind onto the tracker's closest mechanism; the
mapping per field lives in `fields.<name>` (`id`), the mechanism choice
here:

| Kind | GitHub Issues | Linear | Asana |
|---|---|---|---|
| `single_select` | Projects single-select field, or label `name:value` | label group | enum custom field |
| `multi_select` | labels | labels | multi-enum custom field |
| `interval` | two date fields (start, target) | two custom dates or cycle | start and due dates |
| `user` | assignees or Projects people field | assignee plus custom user property | custom people field |
| `url` | Projects text field | link attachment | text custom field |
