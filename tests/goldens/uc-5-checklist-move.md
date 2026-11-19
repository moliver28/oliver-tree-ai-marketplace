# UC5 — Checklist creation + moving a checklist item (`/uxr-plugin:uxr-move`)

Run: 2026-11-17, 22:02:49 end. Mapping note: the plugin's checklist surface is the ticket body's `✏️ Checklist` block (created by `/uxr-new` at UC2, rendered verbatim in UC3 — five items: Scope and prioritize / Draft the study / Review and recruit / Synthesize and report / Manage this ticket with the plugin commands). "Moving a checklist item" is `/uxr-move KEY PHASE`: the body checklist items describe exactly the phase order `move` advances, and each move's readiness gate is the plugin's check of the corresponding checklist stage. `list_state_changes` and `set_state` are fixture-backed from the fixture (BLOCKED-EXTERNAL); the readiness gate runs as real script calls.

## Move 1 — `/uxr-plugin:uxr-move UXR-101` (no target)

`get_item` fixture (status Planned, 15 fields, body, URL). `list_state_changes` fixture (live list per fixture transition map). Verbatim:

> UXR-101 is currently **Planned**. Available moves:
>
> 1. Writing Script / Survey
> 2. Blocked

Scripted user: `writing script /survey` (substring, case- and whitespace-normalized match against "Writing Script / Survey" — exactly one hit).

## Readiness gate (real `phase_gates.py check`, exit 0)

```json
{
  "target": "Writing Script / Survey",
  "gated": true,
  "ok": true,
  "missing": []
}
```

Requirement met: `field:research_method` (customfield_10141 = Internal Interviews).

## Transition + output

BLOCKED-EXTERNAL `set_state` fixture (transition id 21 from the live list). Verbatim, the only output line:

> Moved [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101) to **Writing Script / Survey**.

## Move 2 — `/uxr-plugin:uxr-move UXR-101 Recruiting`

Live list (fixture): `UXR-101 is currently **Writing Script / Survey**. Available moves: 1. Recruiting 2. Blocked 3. Planned`. Name resolves. Real gate (exit 0):

```json
{
  "target": "Recruiting",
  "gated": true,
  "ok": true,
  "missing": []
}
```

Requirements met: `field:research_method` + `spec:roster_nonempty` (5 rows) + `spec:recruitment_strategy_filled` (sample, persona, session length all filled). Transition fixture (id 41). Verbatim output:

> Moved [UXR-101](https://uxr-example.atlassian.net/browse/UXR-101) to **Recruiting**.

## Move 3 — the blocked move (`/uxr-plugin:uxr-move UXR-101 Collecting Data`)

Live list: Recruiting -> 1. Collecting Data, 2. Blocked. Name resolves. Real gate (exit 1 = blocked; verbatim JSON):

```json
{
  "target": "Collecting Data",
  "gated": true,
  "ok": false,
  "missing": [
    {
      "item": "spec check failed: roster_has_scheduled",
      "fix": "roster~=Name|status=Scheduled"
    }
  ]
}
```

Rendered per the command spec (one line per missing item; `set_state` never called):

> missing: spec check failed: 'roster_has_scheduled' -> run edit UXR-101 roster~=Name|status=Scheduled

Command stops; nothing offered beyond the fix line until the user changes something. (The fix is real: no roster row is `Scheduled` yet — outreach went out in UC4 but nobody has replied.)

## Edge behaviors exercised (spec-mandated)

- Out-of-range number (`move UXR-101 9`): "not one of the shown moves" -> list shown again, ask. (Documented from the command spec; fixture list has 2-3 moves.)
- Ambiguous name match -> only matching lines renumbered and re-asked; no hit -> "not an available move from here" + list + stop.
- `move` never writes the spec file: the spec on disk is byte-identical before and after every run in this use case (verified by re-reading the file).

## UC5 metering

| Metric | Value |
|---|---|
| Wall time | 21:59:45 -> 22:03:10 (3m25s) |
| Inference turns | 4 tool-call rounds |
| Token delta | 6,546 consumed (meter 14,834,308 -> 14,827,762) |
| Script executions (plugin-instructed) | 3 (phase_gates.py check x3; plus fixture fixture helpers) |
| Subagent dispatches | 0 |
| Blocked-external steps | `list_state_changes` x3, `set_state` x2 (fixture-backed fixtures) |
