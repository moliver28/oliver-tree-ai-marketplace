---
name: iit-hci-integration
description: "Designs system integrations: discovers every agent-CLI component at runtime, maps workflow gaps, wires dual-layer enforcement (instructions plus hooks or permissions). Use when the user says: 'make this trigger automatically', 'audit my setup for gaps', 'wire this workflow end to end'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [integration, automation, hooks, hci]
---

## When to Load

```
@iit-hci-integration
```

Describe any workflow, use case, or integration goal after loading. Examples:
- "Make the review command trigger automatically after pr"
- "I want a daily standup summary workflow"
- "Audit the MCP layer for unused connections"
- "Design a bug triage pipeline from issue to PR"

## Principles

Every integration must be enforced at two layers:

- **Passive enforcement** — instructions, agent guidance, skill documentation. Soft. Guides behavior but can be ignored or overridden.
- **System enforcement** — plugins, hooks, permissions. Hard. Fires regardless of agent or user intent.

Passive tells the system what to do. System makes sure it happens. Use both.

## Phase 1: System Discovery

Read your agent CLI's entire config directory — for example `~/.claude/` for Claude Code, `~/.codex/` for Codex, or your CLI's equivalent — plus any project-level equivalent (for example `.claude/`). Skip any file that doesn't exist — no errors for missing optional files.

| Read these files | To discover | Required? |
|---|---|---|
| Main settings file (e.g. `~/.claude/settings.json`, `~/.codex/config.toml`) | All commands, plugins, MCP servers, permissions, agents, instructions, experimental features | Usually present |
| Hooks configuration (often a `hooks` block in the main settings file) | All tool/session hook definitions | Optional |
| Plugin and team configuration files (whatever your setup uses) | Plugin-specific agents, categories, parallel-team config | Optional |
| Additional tool/plugin config files (e.g. a TUI config) | Tool-specific behavior | Optional |
| `agents/*.md` | Every agent and its triggers, mode, model | May be empty |
| Instruction files (`instructions/*.md`, `AGENTS.md`, or `CLAUDE.md`) | Every instruction file and its purpose | May be empty |
| `plugins/*.js` | Every custom plugin and its hook events | May be empty |
| `skills/*/SKILL.md` | Every skill and its trigger conditions | May be empty |
| `.mcp.json` | Standalone MCP server overrides | Optional |
| Active plan state file (if your setup keeps one) | Current plan and step status | Optional |
| `package.json` | Installed npm dependencies | Optional |

Output: a complete inventory table with name, type, location, and purpose for every component.

## Phase 2: Workflow Mapping

Given the user's described workflow or use case:

1. Parse the workflow into discrete stages (trigger → action → validation → completion)
2. Map each stage onto discovered components — which command, agent, MCP, skill, or hook serves it?
3. Identify **gaps** — stages with no mapped component
4. Identify **overlaps** — stages with multiple redundant components
5. Identify **integration deficits** — stages where components exist but aren't connected

## Phase 3: Integration Design

For each integration deficit, design the connection:

- **Decompose** — break the connection into atomic parts. Each part does exactly one thing.
- **Causal direction** — which component should affect which?
- **Connection mechanism** — best fit from your agent CLI's available features:
  - `command` — user-invoked slash command (e.g. `~/.claude/commands/*.md`, or your CLI's commands directory)
  - `hook` (PostToolUse / PreToolUse / SessionStart / Stop, declared wherever your CLI defines hooks — e.g. the `hooks` block in `~/.claude/settings.json`) — declarative before/after tool events
  - `permission` rule — gate at information boundary (policy-guard hook, PreToolUse deny)
  - `skill` — loadable methodology (`~/.claude/skills/<name>/SKILL.md`, or your CLI's skills directory)
  - `instruction` — always-present agent guidance (your CLI's global instructions file, e.g. `CLAUDE.md` or `AGENTS.md`)
  - `subagent` — delegated specialist (your CLI's agent definitions, e.g. `~/.claude/agents/*.md`)
  - `MCP` — external service integration (`mcpServers` in your CLI's settings, or `.mcp.json`)
  - `plugin` — packaged components for anything the above can't express
- **Information flow** — what data passes through this connection?
- **Enforcement layer** — for each atomic part, choose:
  - `passive` — instruction/skill/agent guidance only. Agent may skip.
  - `system` — plugin/hook/permission. Fires always.
  - `both` — instruction tells agent, plugin enforces. **Preferred for critical paths.**

Select the simplest mechanism that achieves the connection. For critical paths (plan completion, validation, deployment), always use `both` enforcement.

Output a design table with columns: Deficit | Atomic part | Mechanism | Enforcement | Info flow

## Phase 4: Autonomy-HITL Calibration

For each proposed connection, determine where information is sufficient vs insufficient:

| Information state | Appropriate interaction |
|---|---|
| Clear goal + all inputs available + permissions allow | Autonomous — execute without human |
| Goal clear but inputs partial or side effects possible | Suggest with confirmation |
| No goal or task is ambiguous | Ask human for direction |
| Destructive, irreversible, or external impact | Always ask, explain consequences |

Map enforcement layers to autonomy levels:

| Enforcement | Passive-only | System-only | Both |
|---|---|---|---|
| Full autonomy | Agent may forget | Enforced but unguided | Agent knows + can't skip ✅ |
| HITL balanced | Agent may bypass ask | Gate fires but agent confused | Gate fires + agent informed ✅ |

Set permission rules (`allow` / `ask` / `deny`) at the information boundaries. The system runs autonomously until information runs out — that boundary is the HITL gate.

## Phase 5: Implementation

Write the minimal changes in dependency order. For each change, note whether it provides passive or system enforcement:

1. Passive first: instructions, agent guidance, skills (`instructions/*.md`, `agents/*.md`, `skills/*/SKILL.md`)
2. System second: hooks, plugins, permissions, config (hooks block and settings files, `plugins/*.js`)
3. Plan last: your plan-state file — only if creating a multi-step plan

## Phase 6: Verification

For each change, verify both enforcement layers:

- **Passive test**: load the instruction/skill. Does it clearly tell the agent what to do?
- **System test**: trigger the condition. Does the hook/plugin fire regardless of agent behavior?
- **Integration**: trigger the source, confirm the target responds
- **Autonomy**: run with sufficient inputs + permissive permissions — no human prompt
- **HITL**: run with insufficient inputs or restrictive permissions — correct gate fires
- **Regression**: verify existing workflows still work unchanged

Every critical path must pass both passive and system tests.
