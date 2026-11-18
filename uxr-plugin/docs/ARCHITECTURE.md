# Architecture

This plugin turns Claude Code into a research operations assistant for UX researchers (UXRs) and the people they work with: product managers (PMs), product designers, and engineering managers. This page defines the vocabulary that every issue uses, the principles the plugin is built on, and the component map.

## Vocabulary (one name for each thing)

| Term | Meaning |
|---|---|
| **study** | One research project. One study has one ticket, one spec, and one workspace. |
| **ticket** | The tracker item for a study (Jira issue, Linear issue, GitHub issue, Asana task). |
| **ticket key** | The tracker id, for example `ABC-123`. Config holds the regex. |
| **spec** | A JSON file that holds the ticket body content. The spec is the source of truth. The ticket body is a rendering of the spec. |
| **body renderer** | Code that turns a spec into the tracker's rich-text format (Jira ADF, Markdown, Asana HTML). |
| **field** | A structured tracker field (Pod, Research Method, dates, people, links). Fields do not live in the spec. |
| **workspace** | A local folder for one study under the research root (default `~/Documents/Research/<slug>/`). |
| **roster** | The list of recruits in the spec. Each row has a status from a fixed set. |
| **phase** | A workflow status that has a readiness gate (Planned, Writing Script / Survey, Recruiting, and so on). |
| **gate** | A point where the plugin stops and waits for the user. Every create, edit, post, send, and calendar move has a gate. |
| **journal** | A daily JSONL file of research sessions, written by a SessionEnd hook. |
| **provenance** | The record of which sources a session read and which outputs it wrote. |
| **group** | The team or product area field that routes a study to a researcher. The reference plugin calls it "Pod". |

## Principle 1: the spec is the source of truth

1. Content flows one way: interview (model) to spec (JSON) to `validate_spec()` to body renderer to tracker create or update.
2. Every write loads the spec, checks for drift, patches the spec, validates, saves, renders, and pushes the full body. The plugin never patches the ticket body by hand.
3. A validation failure means zero tracker calls and zero file writes.
4. Read the live ticket only for volatile data: status, `updated` time, and fields.

## Principle 2: code owns rules, the model owns judgment

| Code (deterministic scripts, each with a `selftest`) | Model (prompt instructions) |
|---|---|
| Spec validation, body rendering, shorthand parsing | Interview questions and drafts |
| Field payload resolution and enum checks | Evidence reading and synthesis |
| Phase gates | Routing choices and voice |
| Workspace scaffold, slug, file fill | Reply classification |
| Recruitment table, preflight, exclusions | Insight mapping |
| Report tier, verdicts, citation checks, filenames | Narrative text |
| Script hard-rule checks | Script drafting and minimal edits |

The model never recomputes a number that a script prints. The command prints script output verbatim.

## Principle 3: drafts, never sends

The plugin drafts Slack messages, emails, and calendar changes. The user sends them. The one exception is a self-test email to the user's own inbox (issue 10). Every tracker create, update, transition, and comment shows a preview and waits for an approval word.

## Principle 4: fail open for hooks, fail closed for exclusions

- A hook that fails exits 0 and prints nothing. A hook must never block the user's tools.
- A check that protects people (do-not-contact lists, open sales deals, gitignore of participant data) fails closed. If the check cannot run, the action does not run.

## Component map

```
plugin root/
  .claude-plugin/plugin.json
  config/org.yaml            # every org-specific value (this issue)
  commands/                  # one .md per slash command (issues 05 to 14)
  skills/                    # router skill (05), interview-script (11), notebook (12)
  agents/                    # reviewer agents (06, 11, 13)
  hooks/hooks.json + *.py    # issues 02, 09
  lib/                       # tracker adapter (03), spec and renderer (04), gates (07)
  scripts/                   # deterministic CLIs, each with selftest
  templates/workspace/       # study folder template (08)
  state/                     # per-user data, gitignored (specs, journal, events)
```

## The config contract

One config file holds every organization-specific value: `config/org.example.yaml` is the key contract and ships placeholders; `config/org.yaml` (gitignored) holds your real values. Every command, script, and hook reads configuration through one loader, `lib/config.py:load_config()`. No other file holds an organization value. A missing required key raises an error naming the key.
