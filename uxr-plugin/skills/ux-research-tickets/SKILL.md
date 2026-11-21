---
name: ux-research-tickets
description: "Route UX research tracker requests to the right command: show, read, create, update, or move tickets; recruitment status; end-of-day updates; and study shorthand names. Use when the user says: 'my tickets', 'create a ticket', 'recruiting status', 'log my EOD'."
---

Route a plain request to the right plugin command and run it. This skill
performs no tracker operations itself: it picks the command, and the command
owns every tracker call and gate.

## Setup

1. Render the canonical block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it. Note `tracker.kind`, `tracker.project_key`, `tracker.bare_number_prefix`, and `tracker.ticket_regex`.
2. Command names map to files: `mine` is `commands/uxr-mine.md`, `show` is
   `commands/uxr-show.md`, and so on for `new`, `edit`, `move`, `recruit`,
   `eod`. Check that the routed command file exists in this build. If it does
   not exist yet, print one line:
   `<name> is not in this build yet; mine and show are available.`
   and stop. Do not substitute a different command.

## Routing

The intent pick is a script, not a guess. Run:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/classify.py" intent "<the user's message>" --prefix <tracker.bare_number_prefix>
```

It prints `{"command", "args", "signal"}` using the keyword table in
`prompts/classify/intents.json` (a bare key, or a key with read intent,
routes to `show <KEY>`). Two examples that must run without a clarifying
question, and their script outputs: "what's on my plate" routes to `mine`;
"show me UXR-237" routes to `show UXR-237`. If the script reports no match
(exit 2), pick the most likely command yourself and say one line why.

## Running the routed command

Run it as the plugin slash command, `/uxr-plugin:uxr-<command>` with the
routed command and the script's `args`. When slash invocation is not
available, read `commands/uxr-<command>.md` from this plugin and follow it
exactly.

## Rules

1. Never ask which command. Pick the most likely one, run it, and offer the
   alternative in one line at the end.
2. A study name or shorthand without a key: `search(filter)` the study project
   by label or summary text, render through `lib/render.py mine`
   (the `commands/uxr-mine.md` shape), and let the user pick.
3. Do not search other projects. If the user names another project's key, say
   so and ask which `<project_key>` issue they meant.
4. Never create a ticket without a preview. Never transition without showing
   the live state list. The routed command enforces both; the router never
   bypasses a gate.
5. Voice: lead with the result. No em dashes. No throat-clearing.
