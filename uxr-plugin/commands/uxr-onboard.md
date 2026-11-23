---
description: "One-shot interactive onboarding: configure adapters, custom fields, the prioritization calculator, and the privacy, workspace, and recruit settings in one guided pass, then read the saved config on every later run"
argument-hint: "[--recheck]"
---

Set the plugin up for this organization once. You ask the operator, write
the answers into `config/org.yaml`, and verify the saved path. Every later
run reads that config and never asks again; the flow rules live in
`references/onboarding.md` (the ask law, the saved-path rule, the adapter
rules, the calculator default, the privacy rule, the workspace git rule,
and the org-chart rule). Read that reference before the first question.

Grounding: no registered sources serve this command (record-keeping; search is a tool, not a ritual). Index: `references/research-sources.md`.

Input: `$ARGUMENTS`. `--recheck` runs the full interview even when a saved
config exists. No argument uses the saved path when it exists.

## Steps

1. Read `references/onboarding.md`.
2. Probe the saved path. Run
   `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print` and check whether
   `config/org.yaml` exists next to `config/org.example.yaml`. The plugin
   is already onboarded when that user file exists and the loader exits 0,
   and `--recheck` is absent: print the resolved onboarding keys from the
   dump (adapter entries, `fields` ids, `priority.*`, `privacy.init_ignore`,
   `workspace.remote_push`, `recruiting.org_chart_paths`), say the saved
   path is in use and re-running with `--recheck` asks again, and end. The
   file absent, or the loader exit 2 (show the error), or `--recheck`: run
   the full interview.
3. Interview. One question per message; end the turn after every ask and
   wait for the plain answer (the ask law). Never invent a value; an empty
   answer takes the documented default. The questions, in order:
   - Issue system: `Which issue system holds your study tickets? (jira / linear / github / asana / other)`.
     `other`: ask its name; record it as a declared adapter entry with an
     empty module (absent-sync: the harness works, tracker operations wait
     for the adapter). Leave `tracker.kind` empty for `other` — config
     validation accepts only the shipped kinds, so the recorded entry stays
     declared-unreachable until the adapter module and its kind ship.
     Ask the connection values the system's reference names
     (`references/tracker.md` for jira, `references/trackers-other.md` for
     the rest): base URL, workspace id, project key, ticket regex, bare
     number prefix, body format. Every value may stay empty.
   - Knowledge-base system: `Which knowledge-base system should the plugin read? (notion / none / other)`.
     `none`: no KB entry. `notion`: confirm the shipped declared entry
     (read-only default: pull on, push off). `other`: ask its name and
     record a declared entry the same way. The knowledge-base system may
     equal the issue system; the KB entry is then a second, separate
     adapter entry keyed `<kind>-kb` (same system, different areas).
   - Custom fields: `Name the custom fields your issue system holds for research requests, one per line as <name>: <field id> (press enter to keep the shipped empty ids).`
     Record exactly the fields the operator names: fill the matching
     `fields:` entry's `id`, and add an entry with a text kind for a name
     with no shipped row. Never invent a field.
   - Prioritization calculator: show the built-in default from
     `references/onboarding.md` (formula and weights), then ask
     `Use the built-in prioritization calculator, or override weights or formula? (built-in / override weights / override formula)`.
     `override weights`: ask `Which input carries which weight? One per line as <input name>: <weight>.`
     (the input names are the operator's own field names). `override
     formula`: ask for the formula string. `built-in` writes nothing.
   - Interview-data ignore set (issue 57): `Which interview-data paths must stay out of git? One per line, or press enter for the default: the whole interviews/ tree.`
     Empty: `privacy.init_ignore` stays `[]`, which covers all interview
     data. A list: save exactly those paths; the participant-identity
     floor always applies on top and is never replaceable.
   - Workspace push (issue 58): `Should study workspaces push their commits to a git remote? (yes / no)`.
     `yes`: ask `Paste the workspace git remote URL.` and save it to
     `workspace.remote` with `workspace.remote_push: true`. `no`: save
     `workspace.remote_push: false` and leave any configured remote as is.
   - Org-chart connectors (issue 50): `Which connectors hold your org chart for the CSM and Alliance Partner search? One path per line, or press enter to skip.`
     Save the paths to `recruiting.org_chart_paths`; empty saves `[]`.
4. Write the answers into `config/org.yaml`. When that file is absent,
   create it as a copy of `config/org.example.yaml` first, then set the
   answered keys on it (the loader deep-merges user values over the
   example, so only the answered keys need writing). Never edit
   `config/org.example.yaml` and never print secret values back.
5. Verify the saved path, in order; stop on the first failure and show
   the error:
   `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print` (exit 0),
   then
   `python "${CLAUDE_PLUGIN_ROOT}/lib/adapters.py" describe --kind <issue kind>`
   (exit 0; a `null` line means declared, not built: absent-sync). For a
   KB entry, describe its kind the same way.
6. Walkthrough. Make the operator use every critical feature once, on
   their own data, in as few interactive steps as each feature allows;
   every existing gate keeps its plain-word ask:
   - Create: run `new` for one real study request, through its phases.
   - Move: run `move <KEY>` one gated phase forward.
   - Calculator: score one real open request with the saved or built-in
     weights; show the arithmetic term by term; on request, take one
     weight override and score it again.
   - Sync: run `edit <KEY> <one shorthand>` and push the body through the
     tracker operations; with the adapter declared but not built, say so
     in one line and skip the push.
   A step the operator declines: note it in one line and continue.
7. Print the saved summary, one line each: issue kind, KB kinds,
   field count, calculator state (built-in or overridden), ignore set,
   workspace push state, org-chart connector count. Close with exactly:
   `Onboarding saved. Later runs read config/org.yaml and never re-ask; re-run onboard --recheck to re-ask.`
