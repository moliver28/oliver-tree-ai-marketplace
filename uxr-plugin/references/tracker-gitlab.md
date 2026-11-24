# GitLab Issues adapter (wave P2; the adapter registry points here)

Parameter detail for `tracker.kind == "gitlab"`: the GitLab Issues column
of the generic operations table in `tracker.md`, bound to the `glab` CLI.
The sync-half module is `lib/adapter_gitlab.py`; the commands make the
`glab` calls and this file holds their parameters. Every per-organization
value comes from `config/org.yaml` through `lib/config.py`. No parameter
here has been live-verified in this build; treat every parameter as
`verify-live` before first use, and re-verify when `glab` ships changes.

## Connection keys (`tracker.*`)

| Key | GitLab meaning | Example shape |
|---|---|---|
| `base_url` | The web root; empty means `https://gitlab.com`. A self-managed root needs `glab auth login --hostname` once. | `https://gitlab.com` or `https://gitlab.example.com` |
| `project_key` | Not a GitLab concept; holds the org's key-prefix convention when `ticket_regex` uses one | `UXR` |
| `workspace_id` | The full project path that holds the issues | `acme/uxr-research` |
| `ticket_regex` | Regex that matches one issue key in text | `^#\d+$` or `\bUXR-\d+\b` with a label convention |
| `body_format` | Always `markdown`; GitLab bodies are Markdown | `markdown` |

`glab` reads the token from the environment (`GITLAB_TOKEN`, `CI_JOB_TOKEN`)
or the local `glab auth` login. The plugin never stores a token in config.

## Session rules (every command)

1. Resolve `current_user()` once per session with `glab api user`; cache
   the username, name, and id. Never hardcode a username.
2. Read the current labels immediately before any label write; merge
   against the live value, never against a remembered one.
3. Every comment ends with the `comments.footer`, separated by exactly one
   blank line.
4. Verify every parameter name live before first use (the table below pins
   the documented names and marks the unverified ones `verify-live`).
   Re-verify when the `glab` CLI ships changes.

## Operations (glab CLI)

| Operation | Command | Parameters | Notes |
|---|---|---|---|
| `current_user()` | `glab api user` | none | Cache username, name, id. |
| `find_user(name)` | `glab api users` | `username` query parameter (`verify-live`); project-scoped alternative `glab api projects/<id>/members_all` with `query` (`verify-live`) | Returns the username used in assignee fields. |
| `get_item(key, fields, format)` | `glab issue view <number> --repo <namespace/project>` | number without `#`, `--comments` for the thread (`verify-live`); structured reads through `glab api projects/<url-encoded-path>/issues/<iid>` | Read `description` as Markdown. Pass the bare number; keep the `#` out of the CLI argument. |
| `search(filter)` | `glab issue list --repo <namespace/project> --search <text>` | `--search`, `--labels`, `--state`, `--per-page` (`verify-live` each) | Keep the page small; first page only in read commands. |
| `create_item(type, title, body, fields)` | `glab issue create --repo <namespace/project>` | `--title`, `--description`, one `--label` per label, `--assignee` (`verify-live` each) | `--description` takes the rendered Markdown body. Labels go on in the same call; nothing writes twice. |
| `update_item(key, fields, body)` | `glab issue update <number> --repo <namespace/project>` | `--description`, `--add-label` / `--remove-label` (`verify-live` each), `--assignee` | The description write replaces the full body: always push the whole rendered body, never a fragment. |
| `list_state_changes(key)` | `glab issue view <number> --repo <namespace/project>` or `glab api projects/<path>/issues/<iid>` | label fields (`verify-live`) | GitLab has no transitions; `state` is `opened`/`closed`. A phase move is a label convention (scoped labels fit `name:value` phases); weight and milestone ride the issue attributes. |
| `set_state(key, state)` | `glab issue update <number> --add-label <phase-label>` (`verify-live`) or `glab issue close <number>` / `glab issue reopen <number>` | the label from `list_state_changes` in the same session | Move by the label the config names, never by a remembered one. |
| `add_comment(key, markdown)` | `glab issue note <number> --repo <namespace/project> --message <text>` | `--message` (`verify-live` for long bodies; prefer a stdin or file form for the rendered body) | Append the `comments.footer` after one blank line. |
| `item_url(key)` | no call | the `web_url` field of the API/JSON read | Used in every rendered link. |
| `normalize_key(arg)` | no call | `42` to `#42` in the project from `tracker.workspace_id` | Implemented in `lib/adapter_gitlab.py` `pull`; validate with `tracker.ticket_regex`. |

Pre-ship checklist: before the first tracked change against a live
GitLab project, run each command once with its documented parameters,
confirm the response shape, and remove the `verify-live` marks that
passed.

## Field payloads this adapter receives

`lib/field_map.py resolve --shorthand "<shorthand>"` prints the payload as
JSON, keyed by the configured field `id`. The command previews this payload
and writes it with the commands above. The per-kind mapping table lives in
`references/trackers-other.md`; it stays the single mapping home for every
non-Jira tracker. GitLab specifics on top of that table: a
`single_select` maps to a scoped label (`name:value`), a `multi_select`
maps to labels, `interval` maps onto the `start_date` and `due_date`
attributes, `user` maps to the assignee username, and `url` maps to a
label convention or a configured custom field. GitLab issue `weight`
is a paid-tier attribute; the config maps it only when the operator's
tier carries it, and the label convention covers the rest.

Adapter duties before the write:

1. Apply `__op__` wrappers against the live value: read the current
   labels, merge the additions or drop the removals, then write the
   merged list through `--add-label` / `--remove-label`. Never write a
   wrapper shape to the tracker.
2. Resolve `{"__resolve_user__": token}` with `find_user()` (`me` resolves
   to the cached current user), then write the GitLab username shape.
3. The interval payload arrives as the plain object (start and end dates);
   map it onto the issue `start_date` and `due_date` attributes, and pass
   the values through unparsed.
