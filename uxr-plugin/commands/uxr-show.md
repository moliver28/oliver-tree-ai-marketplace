---
description: "Show one study ticket: header lines, UXR fields, description, linked issues, and the latest comments"
argument-hint: "<KEY>"
---

Read-only view of one ticket. It calls only the read operations in
`references/tracker.md`: `get_item(key, fields, format)`, `item_url(key)`, and
the `normalize_key(arg)` prefix rule. It never calls `create_item`,
`update_item`, `set_state`, or `add_comment`.

Input: `$ARGUMENTS`: one ticket key or a bare number.

Steps:

1. Read configuration once: run `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`
   (when `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin
   directory that holds `lib/`, `config/`, and `references/`). Note
   `tracker.kind`, `tracker.project_key`, `tracker.bare_number_prefix`,
   `tracker.ticket_regex`, and the `id` of every entry under `fields`. Every
   `<placeholder>` below is filled from that output; hardcode nothing.
2. No argument (empty after trimming): print exactly
   `Which issue? (e.g. <PREFIX>-42 or just 42)`
   where `<PREFIX>` is `tracker.bare_number_prefix`, and stop.
3. Normalize the argument with the `normalize_key` rule
   (`references/tracker.md`), then call `get_item` once with the result:
   - digits only: it becomes `<PREFIX>-<digits>`.
   - matches `tracker.ticket_regex`: it is used unchanged.
   - looks like `<WORD>-<digits>` but fails `tracker.ticket_regex` (a key from
     another project): refuse and ask. Print
     `<ARGUMENT> is in another project; this plugin reads the <project_key> study project only. Which <project_key> issue did you mean?`
     and stop. Never search for it.
   - anything else: print the step 2 question and stop.
4. Call `get_item` once, in Markdown format (Jira:
   `responseContentFormat: markdown`), with the tracker's standard fields plus
   the field `id` of every entry under `fields`. Jira reference for the
   standard fields: `summary, status, issuetype, priority, assignee, reporter,
   created, updated, labels, description, issuelinks, comment`.
5. Render the ticket. Leave out empty blocks. `·` separates the pieces of one
   line. Relative time is from now minus the timestamp, rounded down: under a
   minute `just now`, then `<N>m ago` under an hour, `<N>h ago` under 24
   hours, `<N>d ago` under 7 days, `<N>w ago` under 30 days, `<N>mo ago` under
   a year, otherwise `<N>y ago`. In this order:
   1. `## [<KEY>](<url>) · <summary>` with the link from `item_url(key)`.
   2. `**Status** <status> · **Type** <type> · **Priority** <priority>` on one
      line; drop a piece the ticket does not have.
   3. `**Assignee** <name> · **Reporter** <name>` on one line.
   4. `**Updated** <relative> · **Created** <relative>` on one line.
   5. `**Labels** <labels>` on one line, comma separated.
   6. `### UXR fields` as one table with the header `| Field | Value |`, one
      row per configured field, in this exact order, empty rows dropped:

      | fields key | Row label |
      |---|---|
      | `pod` | Group |
      | `research-type` | Research Type |
      | `method` | Research Method |
      | `support` | UXR Support Level |
      | `investment` | Level of Investment |
      | `outcome` | Expected Outcomes |
      | `reviewed` | Reviewed Status |
      | `start` | Start Date |
      | `target` | Target End |
      | `uxr` | UX Researcher |
      | `pm` | Product Manager |
      | `pd` | Product Designer |
      | `em` | Eng Manager |
      | `script` | Script/Survey |
      | `output` | Output Artifact |
      | `prd` | PRD |
      | `eng` | Eng Issue |
      | `design` | Design Artifact |
      | `feature` | Feature |

      Render values: single_select and single_name as the value; multi_select
      as a comma separated list; user as the display name; interval as
      `<start> .. <end>`, or the single date when start equals end; date as
      `YYYY-MM-DD`; url as `[<url>](<url>)`; text and labels as-is.
   7. `### Description`, then the description body verbatim.
   8. `### Linked issues (n)`, where n is the number of links; one line per
      link: `**<link type>** [<key>](<url>) · <summary> · <status>`
   9. `### Comments (n)`, where n is the total number of comments on the
      ticket; newest first; at most 5. Each comment is `**<author> · <relative time>**`
      on one line with the comment body under it.
6. Convert tracker emoji shortcodes to unicode everywhere in the rendered
   text. Replace any `:name:` shortcode whose emoji you know, for example:

   | Shortcode | Unicode |
   |---|---|
   | `:tada:` | 🎉 |
   | `:white_check_mark:` | ✅ |
   | `:eyes:` | 👀 |
   | `:fire:` | 🔥 |
   | `:rocket:` | 🚀 |
   | `:bulb:` | 💡 |
   | `:warning:` | ⚠️ |
   | `:thinking_face:` | 🤔 |
   | `:pray:` | 🙏 |
   | `:clap:` | 👏 |
   | `:question:` | ❓ |
   | `:heavy_exclamation_mark:` | ❗ |

   Leave a shortcode you cannot map as written.
7. Print no other prose.
