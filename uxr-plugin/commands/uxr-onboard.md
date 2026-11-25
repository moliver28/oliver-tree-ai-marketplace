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
   dump (adapter entries, `fields` ids, `priority.*`,
   `prioritization.fields`, `privacy.init_ignore`,
   `workspace.remote_push`, `recruiting.org_chart_paths`), say the saved
   path is in use and re-running with `--recheck` asks again, and end. The
   file absent, or the loader exit 2 (show the error), or `--recheck`: run
   the full interview.
3. Interview. One question per message; end the turn after every ask and
   wait for the plain answer (the ask law). Never invent a value; an empty
   answer takes the documented default. The questions, in order:
   - Issue system: `Which issue system holds your study tickets? (jira / linear / github / gitlab / notion / asana / other)`.
     `other`: ask its name; record it as a declared adapter entry with an
     empty module (absent-sync: the harness works, tracker operations wait
     for the adapter). Leave `tracker.kind` empty for `other` — config
     validation accepts only the shipped kinds, so the recorded entry stays
     declared-unreachable until the adapter module and its kind ship.
     Ask the connection values the system's reference names
     (`references/tracker.md` for jira, `references/tracker-github.md` for
     github, `references/tracker-gitlab.md` for gitlab,
     `references/tracker-notion.md` for notion,
     `references/trackers-other.md` for the rest): base URL,
     workspace id, project key, ticket regex, bare number prefix, body
     format. Every value may stay empty.
   - Knowledge-base system: `Which knowledge-base system should the plugin read? (notion / none / other)`.
     `none`: no KB entry. `notion`: confirm the shipped declared `notion-kb` entry
     (read-only default: pull on, push off; the issues side is the built
     `notion` adapter). `other`: ask its name and
     record a declared entry the same way. The knowledge-base system may
     equal the issue system; the KB entry is then a second, separate
     adapter entry keyed `<kind>-kb` (same system, different areas).
   - Custom fields: `Name the custom fields your issue system holds for research requests, one per line as <name>: <field id> (press enter to keep the shipped empty ids).`
     Record exactly the fields the operator names: fill the matching
     `fields:` entry's `id`, and add an entry with a text kind for a name
     with no shipped row. Never invent a field.
   - Prioritization calculator: show the built-in default from
     `references/onboarding.md` (the GitLab handbook priority calculator:
     six criteria scored 1 to 5, unweighted average, bands; the handbook
     page is cited there). For a shipped issue kind (not `other`), ask
     `Name the fields the calculator reads for the six criteria from your tracker, one per line as <criterion>: <tracker field id or label prefix>: <most urgent> | ... | <least urgent> (a number rule writes number <low> <high>; press enter to skip a criterion).`
     Record exactly the lines given into `prioritization.fields.<issue
     kind>`: `id` from the first slot, `kind: select` with `values` from
     the order tail, or `kind: number` with `low` and `high`. A line
     without the order tail gets exactly one follow-up ask for that
     criterion's order; an empty answer drops the mapping; a line naming
     an input outside the six criteria is refused in one line (the six:
     impact, users, dependency, timeline, alternatives, alignment; other
     inputs belong to the weighted-sum override). Never invent a
     field. Unmapped criteria stay answerable 1 to 5 at scoring time, or
     the walkthrough's calculator step asks at runtime. For `other`,
     skip the ask in one line: the calculator runs on the handbook
     criteria until the system's adapter kind ships. Then ask
     `Use the built-in handbook calculator, or override weights or formula? (built-in / override weights / override formula)`.
     `override weights`: ask `Which input carries which weight? One per line as <input name>: <weight>.`
     (the input names are the operator's own field names; any weight
     switches the calculator to the weighted-sum mode). `override
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
   every existing gate keeps its plain-word ask; the completion gate is
   the deterministic record in `scripts/walkthrough.py`, never readable
   text only. After each used feature, record it:
   - Create: run `new` for one real study request, through its phases,
     then run
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/walkthrough.py" record --feature create --key <KEY>`.
   - Move: run `move <KEY>` one gated phase forward, then run
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/walkthrough.py" record --feature move --key <KEY>`.
   - Calculator: score one real open request with the saved handbook
     preset (or the operator's override) by running
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/prioritize.py" score ...` on
     the request's tracker values; where the tracker cannot supply a
     criterion's field, run with `--ask` so the deterministic numbered
     prompt answers it at runtime (the handbook scale wording prints;
     the answer is recorded and used); show the arithmetic term by term
     and the band. On request, show the support mode on the same request
     (`score --support`, `--ask` collects the per-project judgments;
     levels `UXR to Lead` / `UXR to Support` / `UXR to Review`). Then run
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/walkthrough.py" record --feature calculator --key <KEY>`.
   - Sync: run `edit <KEY> <one shorthand>` and push the body through the
     tracker operations; with the adapter declared but not built, say so
     in one line and skip the push. Then run
     `python "${CLAUDE_PLUGIN_ROOT}/scripts/walkthrough.py" record --feature sync --key <KEY>`.
   A step the operator declines: note it in one line and continue. The
   declined step stays unrecorded, and the gate below keeps the
   walkthrough open until the operator uses it.
   When all four features are used, run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/walkthrough.py" check`.
   Exit 0: print one line, `Walkthrough complete: all four features used.`
   Exit 1: print the script's missing line verbatim, then one line that
   the remaining features finish the walkthrough (use each and re-run the
   check). The completion line never prints on exit 1.
7. Print the saved summary, one line each: issue kind, KB kinds,
   field count, calculator state (built-in handbook preset, or
   overridden, plus the number of mapped criteria), ignore set,
   workspace push state, org-chart connector count. Close with exactly:
   `Onboarding saved. Later runs read config/org.yaml and never re-ask; re-run onboard --recheck to re-ask.`
