# Tracker adapter

Commands never call a tracker directly: they use the generic operations
table, reading the column for the configured `tracker.kind` (`jira`,
`linear`, `github`, or `asana`). Every per-organization value comes from
`config/org.yaml` through `lib/config.py`; `lib/field_map.py` resolves a
field shorthand (`method=Survey`) into the payload and implements the
routing helpers. Linear/GitHub/Asana detail lives in
`references/trackers-other.md` — read it when `tracker.kind` is not `jira`.

## Session rules (every command)

1. Resolve `current_user()` once per session; cache id, display name, email. Never hardcode a user id.
2. Jira: every tool call needs a `cloudId` from `tracker.workspace_id`; when empty, call `getAccessibleAtlassianResources` once, cache it with the user, and remind the user to set `tracker.workspace_id`.
3. Read `list_state_changes` immediately before any status move; move by transition `id`, never by name or from a remembered list.
4. Every comment ends with the `comments.footer`, separated by exactly one blank line.
5. Verify every MCP parameter name live before first use (the reference plugin shipped two different comment-body parameter names in two commands; this table pins the documented names and marks unverified ones `verify-live`). Re-verify when the tracker announces tool changes.

## Generic operations

One row per operation; use the column for the configured tracker.

| Operation | Jira (Atlassian MCP) | Linear (GraphQL) | GitHub Issues (`gh` CLI) | Asana (REST) |
|---|---|---|---|---|
| `current_user()` | `atlassianUserInfo` | `viewer` query | `gh api user` | `GET /users/me` |
| `find_user(name)` | `lookupJiraAccountId` | `userLookup` / users search | `gh api search/users` | typeahead `GET /workspaces/{gid}/users` |
| `get_item(key, fields, format)` | `getJiraIssue` (`responseContentFormat`: markdown or adf) | `issue` query | `gh issue view --json` | `GET /tasks/{gid}` |
| `search(filter)` | `searchJiraIssuesUsingJql` | `issues` filtered query | `gh search issues` | `GET /workspaces/{gid}/tasks/search` |
| `create_item(type, title, body, fields)` | `createJiraIssue` (`contentFormat: "adf"`) | `issueCreate` mutation | `gh issue create` plus Projects fields | `POST /tasks` |
| `update_item(key, fields, body)` | `editJiraIssue` (replaces the full description) | `issueUpdate` mutation | `gh issue edit` | `PUT /tasks/{gid}` |
| `list_state_changes(key)` | `listJiraIssueTransitions` (MCP v2; v1 name `getTransitionsForJiraIssue`) | team `workflowStates` query | Projects Status field options (`gh project field-list`) or labels | project sections |
| `set_state(key, state)` | `transitionJiraIssue` with the transition `id` | `issueUpdate` with `stateId` | Projects field update (`gh project item-edit`) or label add/remove | `POST /sections/{section_gid}/addTask` |
| `add_comment(key, markdown)` | `addOrEditJiraIssueComment` (MCP v2; v1 name `addCommentToJiraIssue`, body parameter `commentBody`) | `commentCreate` mutation (body) | `gh issue comment --body` | `POST /tasks/{gid}/stories` |
| `item_url(key)` | `<tracker.base_url>/browse/<KEY>` | issue `url` field | issue `url` from `gh issue view --json url` | task `permalink_url` |
| `normalize_key(arg)` | `42` to `<tracker.bare_number_prefix>-42` | `42` to `<team key>-42` | `42` to `#42` in the repo from `tracker.workspace_id` | gid passes through |

`normalize_key` accepts anything matching `tracker.ticket_regex` unchanged;
a bare number gets the `tracker.bare_number_prefix`. A key outside the
study project is refused, never searched.

## Jira parameters (reference tracker)

The current Atlassian MCP server is v2. It renamed two tools that the
reference plugin called by their v1 names; both names are listed so the
command works on either server. Every call carries `cloudId`.

| Operation | Tool | Parameters | Notes |
|---|---|---|---|
| `current_user()` | `atlassianUserInfo` | none beyond `cloudId` (`verify-live`) | Cache the account id, display name, email. |
| `find_user(name)` | `lookupJiraAccountId` | `cloudId`, name or email query (`verify-live` for the query parameter name) | Returns the account id used in user fields. |
| `get_item(key, fields, format)` | `getJiraIssue` | `cloudId`, `issueIdOrKey`, `fields` (`verify-live`), `responseContentFormat` (`markdown` or `adf`) | Read with `markdown`; fall back to `adf` only when the command must edit rich content. |
| `search(filter)` | `searchJiraIssuesUsingJql` | `cloudId`, `jql`, paging parameters (`verify-live`: `limit` or `maxResults`) | Keep limit small; first page only in read commands. |
| `create_item(...)` | `createJiraIssue` | `cloudId`, `projectKey`, `summary`, `issueTypeId`, `description`, `contentFormat: "adf"`, plus field parameters (`verify-live` each) | Set `tracker.study_item_type` as the type. |
| `update_item(...)` | `editJiraIssue` | `cloudId`, `issueIdOrKey`, fields or `update` parameter (`verify-live`), description parameter (`verify-live`) | The description write replaces the full body: always push the whole rendered body, never a fragment. |
| `list_state_changes(key)` | v2 `listJiraIssueTransitions`; v1 `getTransitionsForJiraIssue` | `cloudId`, `issueIdOrKey` | Call right before every move. |
| `set_state(key, state)` | `transitionJiraIssue` | `cloudId`, `issueIdOrKey`, transition `id` (`verify-live` for the id parameter name) | Id comes from `list_state_changes` in the same session. |
| `add_comment(key, markdown)` | v2 `addOrEditJiraIssueComment`; v1 `addCommentToJiraIssue` | `cloudId`, `issueIdOrKey`, `commentBody`, `contentFormat` (v1 schema, documented 2025-08; v2 body parameter name `verify-live`) | The v1 body parameter is `commentBody`, not `body`: this is the exact mismatch the reference plugin hit. Append the `comments.footer` after one blank line. |
| `item_url(key)` | no tool | `<tracker.base_url>/browse/<KEY>` | Used in every rendered link. |
| `normalize_key(arg)` | no tool | prefix rule from `tracker.bare_number_prefix` | Validate with `tracker.ticket_regex`. |

Pre-ship checklist: before the first tracked change against a live Jira
site, run each tool once with its documented parameters, confirm the
response shape, and remove the `verify-live` marks that passed.

## Field payloads this adapter receives

`lib/field_map.py resolve --shorthand "<shorthand>"` prints the payload as
JSON, keyed by the configured field `id`. The command previews this payload
and writes it with the tools above.

| Field kind | Payload shape |
|---|---|
| `single_select` | `{id: {"value": v}}` |
| `multi_select` | `{id: [{"value": v}, ...]}` on replace; `{id: {"__op__": "add" or "remove", "values": [{"value": v}, ...]}}` on `+=` / `-=` |
| `single_name` | `{id: {"name": v}}` |
| `interval` | Jira: the JSON string `{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}`; any other tracker: the equivalent object |
| `date` | `"YYYY-MM-DD"` |
| `labels` | `{id: [label, ...]}` on replace; `{id: {"__op__": "add" or "remove", "values": [label, ...]}}` on signed or `+=` / `-=` tokens |
| `url`, `text` | the trimmed string |
| `user` | `{id: {"__resolve_user__": token}}` |

Adapter duties before the write:

1. Apply `__op__` wrappers against the live value: read the current
   multi_select or labels value, merge the additions or drop the removals,
   then write the merged list. Never write a wrapper shape to the tracker.
2. Resolve `{"__resolve_user__": token}` with `find_user()` (`me` resolves
   to the cached current user), then write the tracker's user shape (Jira
   account id, Linear user id, GitHub handle, Asana gid).
3. The interval payload for Jira is already the JSON string the tracker
   expects; pass it through unparsed.

## Researcher routing (config-driven; used by `new`)

Routing lives in `config/org.yaml` under `routing`; commands never carry it
in prose. `lib/field_map.py` implements the two helpers.

1. **Role detection** - `detect_role(current_user().display_name, routing)`
   returns `uxr` or `manager` on a hit in `routing.researchers` (matched
   without case); anything else returns `stakeholder`.
2. **Researcher resolution** - `resolve_researcher(group, routing)` walks
   `routing.group_to_area` to an area, then `routing.area_to_researcher`
   to `{"primary": name, "fallbacks": [names]}`. The command offers the
   fallback chain when the user marks the primary as out of office. An
   unknown group, or an area with no researcher, routes to
   `routing.default_researcher` and the command prints the first entry of
   the returned `notes` verbatim: it names the group, and says to update
   the routing map.
3. **Default fields by role** - role `uxr`: assignee and UX Researcher are
   the current user. Roles `manager` and `stakeholder`: both go to the
   researcher for the group, from step 2. The tracker sets the reporter to
   the caller; the plugin never writes the reporter.
