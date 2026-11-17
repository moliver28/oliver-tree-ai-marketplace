---
name: ux-research-tickets
description: "Routes UX research tracker requests to the right plugin command: show, create, edit, move, recruit, and end-of-day updates. Use when the user says: 'my tickets', 'assigned to me', 'create a ticket', 'move this to Done', 'recruiting status', 'end of day update', or names a ticket key like ABC-237."
---

Route a plain request to the right plugin command and run it. This skill
performs no tracker operations itself: it picks the command, and the command
owns every tracker call and gate.

## Setup

1. Read configuration once: run `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print`
   (when `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin
   directory that holds `lib/`, `config/`, and `references/`). Note
   `tracker.kind`, `tracker.project_key`, `tracker.bare_number_prefix`, and
   `tracker.ticket_regex`. Hardcode nothing.
2. Command names map to files: `mine` is `commands/uxr-mine.md`, `show` is
   `commands/uxr-show.md`, and so on for `new`, `edit`, `move`, `recruit`,
   `eod`. Check that the routed command file exists in this build. If it does
   not exist yet, print one line:
   `<name> is not in this build yet; mine and show are available.`
   and stop. Do not substitute a different command.

## Routing table

Pick from the user's words alone.

| Intent signal | Command |
|---|---|
| my tickets, my plate, assigned to me | `mine` |
| show, read, look at, a bare key with read intent | `show <KEY>` |
| create, new, log, open a ticket, "I need to track" | `new` |
| update, edit, fill in, change priority | `edit <KEY>` |
| move, transition, mark as, push to a column | `move <KEY>` |
| recruit, recruiting status, who have we contacted, next wave | `recruit <KEY>` (`--status` for questions, `--external` for customers) |
| end of day, EOD, log today's work | `eod` |

A message that is only a ticket key, or a key with read intent, routes to
`show <KEY>`. Two examples that must run without a clarifying question:
"what's on my plate" runs `mine`; "show me ABC-237" runs `show ABC-237`.

## Running the routed command

Run it as the plugin slash command, `/uxr-plugin:uxr-<name>` with the routed
name and arguments. When slash invocation is not available, read
`commands/uxr-<name>.md` from this plugin and follow it exactly.

## Rules

1. Never ask which command. Pick the most likely one, run it, and offer the
   alternative in one line at the end.
2. A study name or shorthand without a key: `search(filter)` the study project
   by label or summary text, render the `mine` table shape, and let the user
   pick.
3. Do not search other projects. If the user names another project's key, say
   so and ask which `<project_key>` issue they meant.
4. Never create a ticket without a preview. Never transition without showing
   the live state list. The routed command enforces both; the router never
   bypasses a gate.
5. Voice: lead with the result. No em dashes. No throat-clearing.
