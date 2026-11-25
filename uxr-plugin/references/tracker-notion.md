# Notion adapter (wave P3; the adapter registry points here)

Parameter detail for `tracker.kind == "notion"`: the Notion column of the
generic operations table in `tracker.md`, bound to the Notion MCP tools
(the official server names each tool after its REST endpoint). The
sync-half module is `lib/adapter_notion.py`; the commands make the Notion
calls and this file holds their parameters. Every per-organization value
comes from `config/org.yaml` through `lib/config.py`. No parameter here
has been live-verified in this build; treat every parameter as
`verify-live` before first use, and re-verify when the Notion API or MCP
server ships changes.

Notion is a database-backed tracker: one study item is one page in the
database, the phase lives in the database's Status property, and the
page carries no number. The knowledge-base area keeps its own separate
declared entry keyed `notion-kb` (same system, different areas = two
entries; see `references/onboarding.md`).

## Connection keys (`tracker.*`)

| Key | Notion meaning | Example shape |
|---|---|---|
| `base_url` | The web root for links; empty means `https://www.notion.so` | `https://www.notion.so` |
| `project_key` | Not a Notion concept; holds the org's key convention when `ticket_regex` uses one, else empty | |
| `workspace_id` | The database id that holds the study items | a 32-digit database id |
| `ticket_regex` | Regex that matches one saved page key; empty means any non-empty key passes | a short-key pattern the team saves on each page |
| `body_format` | Always `markdown`; the rendered body maps into the page content | `markdown` |

The commands read the token from the environment (`NOTION_TOKEN`) or the
MCP session the harness holds; the plugin never stores a token in config.
The integration needs the database shared with it (the Notion connection
step), or every call returns an access error.

## Session rules (every command)

1. Resolve the integration's user once per session (`API-get-self` or
   `GET /users/me`); cache the user id and name. Never hardcode a user
   id.
2. Read the database schema once per session (`GET /databases/{id}`) and
   cache the Status property's option ids; move by option id, never by a
   remembered name.
3. Every comment ends with the `comments.footer`, separated by exactly
   one blank line.
4. Verify every parameter name live before first use (the table below
   pins the documented names and marks the unverified ones
   `verify-live`). Re-verify when the Notion API or MCP server ships
   changes.

## Operations (Notion MCP / API)

| Operation | Tool | Parameters | Notes |
|---|---|---|---|
| `current_user()` | `API-get-self` / `GET /users/me` | none (`verify-live` for the MCP tool name) | Cache the bot or user id and name. |
| `find_user(name)` | `API-get-users` / `GET /users` | optional `query` (`verify-live`); page cursor | Returns the user id the People properties take. |
| `get_item(key, fields, format)` | `API-retrieve-page` / `GET /pages/{id}` | the page id from the saved key (`verify-live`); content reads through the block-children endpoint | Properties carry the fields; the body is the page content. |
| `search(filter)` | `API-post-database-query` / `POST /databases/{id}/query` | `filter`, `page_size` (`verify-live` each); workspace-wide search via `API-post-search` | Keep the page small; first page only in read commands. |
| `create_item(type, title, body, fields)` | `API-post-page` / `POST /pages` | `parent.database_id`, `properties` (title, Status, mapped fields), `children` for content (`verify-live` each) | The properties carry the mapped field payloads; the body goes in as content blocks. |
| `update_item(key, fields, body)` | `API-patch-page` / `PATCH /pages/{id}` | `properties` (`verify-live`); content edits through the block-children patch | Property writes are per-property; the body maps into the page content. |
| `list_state_changes(key)` | the database schema read, `GET /databases/{id}` | none beyond the database id | Notion has no transitions; the Status property holds the options with ids. |
| `set_state(key, state)` | `API-patch-page` / `PATCH /pages/{id}` | the Status property name and the option id from `list_state_changes` in the same session (`verify-live`) | Move by option id, never by a remembered name. |
| `add_comment(key, markdown)` | `API-create-comment` / `POST /comments` | `parent.page_id`, `rich_text` (`verify-live`) | Append the `comments.footer` after one blank line. |
| `item_url(key)` | no call | the page `url` field of the read | Used in every rendered link. |
| `normalize_key(arg)` | no call | the key passes through; Notion pages carry no number | Implemented in `lib/adapter_notion.py` `pull`; validate with `tracker.ticket_regex` when set. The issue-52 mention shows the key and the short title the read returned. |

Pre-ship checklist: before the first tracked change against a live
database, run each call once with its documented parameters, confirm the
response shape, and remove the `verify-live` marks that passed.

## Field payloads this adapter receives

`lib/field_map.py resolve --shorthand "<shorthand>"` prints the payload
as JSON, keyed by the configured field `id`. The command previews this
payload and writes it into the page properties with the calls above. The
per-kind mapping table lives in `references/trackers-other.md`; it stays
the single mapping home. Notion specifics on top of that table: a
`single_select` maps to a select or status property option; a
`multi_select` maps to a multi-select property; `interval` maps onto one
date property's start and end; `user` maps to a People property user id;
`url` maps to a url property; a labels convention maps to a
multi-select property the config names.

Adapter duties before the write:

1. Apply `__op__` wrappers against the live value: read the current
   multi_select value, merge the additions or drop the removals, then
   write the merged list. Never write a wrapper shape to the tracker.
2. Resolve `{"__resolve_user__": token}` with `find_user()` (`me`
   resolves to the cached current user), then write the Notion user id
   shape.
3. The interval payload arrives as the plain object (start and end
   dates); map it onto the configured date property's start and end, and
   pass the values through unparsed.
