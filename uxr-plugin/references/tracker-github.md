# GitHub Issues adapter (wave P1; the adapter registry points here)

Parameter detail for `tracker.kind == "github"`: the GitHub Issues column
of the generic operations table in `tracker.md`, bound to the `gh` CLI.
The sync-half module is `lib/adapter_github.py`; the commands make the
`gh` calls and this file holds their parameters. Every per-organization
value comes from `config/org.yaml` through `lib/config.py`. No parameter
here has been live-verified in this build; treat every parameter as
`verify-live` before first use, and re-verify when `gh` ships changes.

## Connection keys (`tracker.*`)

| Key | GitHub meaning | Example shape |
|---|---|---|
| `base_url` | The web root for links; empty means `https://github.com` | `https://github.com` or a GitHub Enterprise root |
| `project_key` | Not a GitHub concept; holds the org's key-prefix convention when `ticket_regex` uses one | `UXR` |
| `workspace_id` | The repository that holds the issues, `owner/repo` | `acme/uxr-research` |
| `ticket_regex` | Regex that matches one issue key in text | `^#\d+$` or `\bUXR-\d+\b` with a label convention |
| `body_format` | Always `markdown`; GitHub bodies are Markdown | `markdown` |

`gh` reads the token from the environment (`GH_TOKEN`, `GH_ENTERPRISE_TOKEN`)
or the local `gh auth` login. The plugin never stores a token in config.

## Session rules (every command)

1. Resolve `current_user()` once per session with `gh api user`; cache the
   login, name, and id. Never hardcode a user handle.
2. Read the current labels or Projects fields immediately before any field
   write; merge against the live value, never against a remembered one.
3. Every comment ends with the `comments.footer`, separated by exactly one
   blank line.
4. Verify every parameter name live before first use (the table below pins
   the documented names and marks the unverified ones `verify-live`).
   Re-verify when the `gh` CLI ships changes.

## Operations (gh CLI)

| Operation | Command | Parameters | Notes |
|---|---|---|---|
| `current_user()` | `gh api user` | none | Cache login, name, id. |
| `find_user(name)` | `gh api search/users` | `q` query parameter (`verify-live`), one page | Returns the handle used in assignee fields. |
| `get_item(key, fields, format)` | `gh issue view <number> --repo <owner/repo> --json <fields>` | number without `#`, `--json` field list (`verify-live` per field: `number,title,body,labels,assignees,state,url`) | Read `body` as Markdown. Pass the bare number; keep the `#` out of the CLI argument. |
| `search(filter)` | `gh search issues` | `--repo <owner/repo>`, query text, `--limit` (`verify-live`) | Keep the limit small; first page only in read commands. |
| `create_item(type, title, body, fields)` | `gh issue create` | `--repo`, `--title`, `--body`, one `--label` per label, `--assignee` (`verify-live` each) | `--body` takes the rendered Markdown body. Labels go on in the same call; nothing writes twice. |
| `update_item(key, fields, body)` | `gh issue edit <number>` | `--repo`, `--body`, `--add-label` / `--remove-label`, `--add-assignee` / `--remove-assignee` (`verify-live` each) | The body write replaces the full body: always push the whole rendered body, never a fragment. |
| `list_state_changes(key)` | `gh issue view <number> --json state,labels` or the Projects status field (`gh project field-list`) | `--repo`, field names (`verify-live`) | GitHub has no transitions; a phase move is a label convention or a Projects single-select. |
| `set_state(key, state)` | `gh issue edit <number> --add-label <phase-label>` or `gh project item-edit` (`verify-live`) | the label or field value from `list_state_changes` in the same session | Move by the label or option the config names, never by a remembered one. |
| `add_comment(key, markdown)` | `gh issue comment <number> --body-file <path>` (long bodies) or `gh issue comment <number> --body <text>` | `--repo` (`verify-live` for the body parameter shape) | Append the `comments.footer` after one blank line. Prefer `--body-file` for the rendered body. |
| `item_url(key)` | no call | the `url` field from `gh issue view --json url` | Used in every rendered link. |
| `normalize_key(arg)` | no call | `42` to `#42` in the repo from `tracker.workspace_id` | Implemented in `lib/adapter_github.py` `pull`; validate with `tracker.ticket_regex`. |

Pre-ship checklist: before the first tracked change against a live
repository, run each command once with its documented parameters, confirm
the response shape, and remove the `verify-live` marks that passed.

## Field payloads this adapter receives

`lib/field_map.py resolve --shorthand "<shorthand>"` prints the payload as
JSON, keyed by the configured field `id`. The command previews this payload
and writes it with the commands above. The per-kind mapping table (label
conventions, Projects fields, assignees) lives in
`references/trackers-other.md`; it stays the single mapping home for every
non-Jira tracker.

Adapter duties before the write:

1. Apply `__op__` wrappers against the live value: read the current labels
   or Projects value, merge the additions or drop the removals, then write
   the merged list through `--add-label` / `--remove-label` or one Projects
   edit. Never write a wrapper shape to the tracker.
2. Resolve `{"__resolve_user__": token}` with `find_user()` (`me` resolves
   to the cached current user), then write the GitHub handle shape.
3. The interval payload arrives as the plain object (start and end dates);
   map it onto the two configured date fields or the milestone, and pass
   the values through unparsed.
