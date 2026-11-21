# UC1 — Install / onboarding flow (verbatim UX outputs)

Run: 2026-11-17, start 21:39:22, as a fresh user (fresh clone, no org.yaml, no state).
Entry points followed: `uxr-plugin/README.md` (Install / Verify / Configure / Quick start), `hooks/ux_research_context.py` via `hooks/hooks.json`.

## Step 1 — Install (README)

```
claude plugin marketplace add <owner>/<marketplace-repo>
claude plugin install uxr-plugin
# or, during development:
claude --plugin-dir /path/to/uxr-plugin
```

BLOCKED-EXTERNAL: no `claude` CLI binary in the runner environment (`command -v claude` -> not found). `claude plugin validate .` blocked for the same reason. A fresh user with the CLI would get the plugin's SessionStart hook wired by these commands; here the hook was fired directly per `hooks/hooks.json`.

## Step 2 — Verify: `python3 scripts/smoke_test.py` (the authoritative all-local gate)

Pre-configuration (fresh clone, no `config/org.yaml`):

```
  [ok] recruitment and outreach templates hold no em or en dash
smoke: all checks passed (0 skipped)
```

Exit 0.

<!-- DIFFERS: F1 - W1 fixed this behavior; excluded from byte parity -->
Post-configuration (after `config/org.yaml` is filled, see step 3) the same gate FAILS:

```
  [FAIL] lib/field_map.py selftest (exit 4:   [FAIL] shipped example field schema resolves via load_config)
  [FAIL] all script and hook self-tests pass (field_map.py)
smoke FAILED (2 check(s), 0 skipped)
```

Exit 1. Root cause: `lib/field_map.py`'s selftest calls `load_config(environ={})` against the live `config/` files and expects the shipped example's empty pod values ("example select field with empty values accepts any token"); a filled `org.yaml` makes `resolve_shorthand("pod=Anything", ...)` a ResolveError. BASELINE FINDING: the shipped smoke gate is only green on an unconfigured checkout.
<!-- /DIFFERS: F1 -->

## Step 3 — Configure (field collection)

```
cp config/org.example.yaml config/org.yaml
```

Filled with a fictional org (no credentials): tracker kind `jira`, project `UXR`, ticket regex `^UXR-[0-9]+$`, study item type `Study`, 19 configured fields mapped to `customfield_101xx` ids, workflow phase order left empty (reference table ships in `lib/phase_gates.py`), routing for researchers "Jordan Reyes" (uxr) / "Sam Okafor" (manager), org domain `example.com`, research root + state dir set to the baseline run directories, evidence sources `["tracker","drive","feedback","chat","wiki"]`, chat channel `#support-first-week`.

## Step 4 — Quick start (first session inside a research folder)

SessionStart hook fired with event JSON `{"hook_event_name":"SessionStart","cwd":"<research root>","session_id":"baseline-uc1"}`. Verbatim stdout (one line, the injected context):

```
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "UX research workspace detected. uxr-plugin workflows are active. Route study requests via the ux-research-tickets skill or /uxr-plugin:uxr-<command>; config: config/org.yaml."}}
```

Rendered for the user, the injected context block is:

```
UX research workspace detected. uxr-plugin workflows are active. Route study requests via the ux-research-tickets skill or /uxr-plugin:uxr-<command>; config: config/org.yaml.
```

> D3 (MO-approved 2026-11-20): the SessionStart injection is one routing-pointer line. The pre-trim four-line block (commands list, tracker constants, routing note) is by-design different. Commands stay discoverable in the session UI; tracker constants and the routing default are read from config/org.yaml on demand.

Session fired outside any research root prints nothing (verified with `cwd: C:/Windows` -> empty output; gate closed, plugin stays silent as documented).

`python lib/config.py --print` exit 0; first lines:

```
tracker:
  kind: jira
  base_url: https://uxr-example.atlassian.net
  workspace_id: 00000000-1111-4aaa-8bbb-cccccccc0001
  project_key: UXR
```

## UC1 metering

| Metric | Value |
|---|---|
| Wall time | 21:39:22 -> 21:53:40 (14m18s) |
| Inference turns | 10 tool-call rounds |
| Token delta | 15,738 consumed (context meter 14,898,273 -> 14,882,535) |
| Script executions (plugin-instructed) | 5 (smoke_test x3, SessionStart hook x2, config.py --print x1) |
| Subagent dispatches | 0 |
| Blocked-external steps | `claude plugin install` / `claude plugin validate` (CLI absent) — est. ~1.5K tokens + 1 turn (est) |

Step tags: install commands `deterministic`; smoke gate `deterministic`; config field collection `llm-mechanical` (reading the contract and filling values is mechanical; could be a `config init` wizard script); SessionStart injection `deterministic` (pure script, zero inference needed).
