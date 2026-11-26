---
description: "Health-check the plugin harness, prune modules you do not need, or repair a broken install. Use when the user says: 'check the plugin health', 'the plugin is broken', 'shrink the plugin install', 'why is the plugin failing'"
argument-hint: "[check|fix|profile]"
---

Run the plugin's self-check and repair tool. No tracker calls, no network
(except `fix`, which clones the marketplace repo read-only to copy back
missing files).

Grounding: no registered sources serve this command. Index: `references/research-sources.md`.

Input: `$ARGUMENTS`. Default (no argument): `check`.

Steps:

1. Setup: render the canonical config block - `python "${CLAUDE_PLUGIN_ROOT}/lib/prompts.py" render config-setup` - and follow it.
2. Run the doctor with the given mode:

   `python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_doctor.py" <mode>`

   Modes: `check` (default) validates the harness (scripts compile, hook
   wiring resolves, front matter parses, cross-references resolve, schemas
   parse, profile state consistent). `fix` repairs a broken install from
   the marketplace source. `profile <name>` shows a module's paths;
   `profile apply full|mcp|scripting` prunes optional modules from this
   install copy. The doctor refuses to prune inside the marketplace repo
   clone; profiles apply to installs only.
3. Print the doctor's stdout verbatim. Add no prose of your own beyond one
   line naming the mode you ran.
4. If `check` exits nonzero: list each problem line, then run `check`
   again with `fix`: `python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_doctor.py" fix`,
   and print its stdout verbatim. State plainly whether the exit code is 0.