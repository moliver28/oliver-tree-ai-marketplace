# UC7 — Sync / push to tracker (`/uxr-plugin:uxr-edit UXR-101 results=<text>`, spec path)

Run: 2026-11-17, 22:23 start. Scenario: the report is filed (UC6) and the Results section of the ticket is filled from the spec. The tracker adapter (`update_item`) is BLOCKED-EXTERNAL and fixture-backed against the fixture; every deterministic step (drift check inputs, validation, render, overview rewrite, phase suggest) ran as real script calls. This exercises the plugin's core write contract: spec is the source of truth, one render, one push of the full body, one write call.

## Step-by-step (verbatim outputs)

1. Config cached; argument parsed as `UXR-101` + one spec-path shorthand (`results=`); key used unchanged (`ticket_regex` match).
2. Spec loaded from `<state_dir>/specs/UXR-101.spec.json`.
3. **Drift check** (step 7a): live `updated` (2026-11-17T22:12:00Z, moved twice since save) differs from `_meta.tracker_updated_at` (unset) -> printed exactly, then the run waited:

```
UXR-101 was edited in the tracker after the spec was last saved; recompiling will overwrite that change
```

Scripted user: `go`.

4. **Patch** (step 7b): `results=` assigned; no list ops, no Drive rows (7c/7d skipped).
5. **Validate + render** (step 7e): `build_body.py` exit 0 (markdown variant shown for the fixture read-back; the pushed body was ADF per config). The Results panel now renders:

```
> ## ✅ Results
>
> We are presenting the January planning review with a single stakeholder pass that supports the header-first hypothesis and a weak tour. Decision: confirm the header-first pattern with first-week external users, then choose between a labeled left-navigation entry and the header placement; the tour is deprioritized.
```

6. **Preview and gate** (step 8, verbatim):

```
UXR-101 (proposed updates):
  results:   [placeholder] → "We are presenting the January planning review with a single stakeholder pass that supports the header-first hypothesis and a weak tour. Decision: confirm the header-first pattern with first-week external users, then choose between a labeled left-navigation entry and the header placement; the tour is deprioritized."
```

Scripted user: `apply`.

7. **Save and push** (step 9): spec saved with `_meta` (`last_edited_by_command: "edit"`, `last_edited_at` now, `tracker_updated_at` = fixture response time, `created_at` unchanged); BLOCKED-EXTERNAL `update_item` fixture pushed the full rendered body (no fields — a spec-path run carries field payloads only when field shorthands were given). One write call, as contracted.
8. **Refresh the workspace overview** (step 11, verbatim, exit 0):

```
rewrote Background, Key decision, Hypotheses, Assumptions, Research questions, Resources, JTBD & Personas in ...\00-overview.md
```

9. **Suggest the next phase** (step 12): `phase_gates.py suggest --status "Recruiting"` printed `Collecting Data` (Participant A is `Scheduled`, so the `Collecting Data` gate passes). Printed exactly:

```
This ticket now meets the bar for Collecting Data. Run move UXR-101 Collecting Data to advance it.
```

`edit` never transitions — the suggestion defers to `move`.

## Contract behaviors verified

- No shorthand (`edit UXR-101` alone) renders the ticket show-style and asks `What should change? For example: history=<text>, method+=Survey, roster+=Name|email|slack|reason|status|channel, priority=High` (documented from the command spec; not triggered).
- Missing spec (step 6) prints the exact `No spec found for <KEY>. Cannot edit sections; recreate the ticket via \`new\` or run a one-time backfill: \`backfill_spec.py\`` line and makes zero tracker calls (verified by reading the command + the guard in the run's step-6 branch logic).
- Validation failure = zero writes: before the `apply`, stderr carried no errors; had exit 3 occurred, the run would have printed the `  - <error>` lines and stopped with nothing saved.

## UC7 metering

| Metric | Value |
|---|---|
| Wall time | 22:23:00 -> 22:28:40 (5m40s) |
| Inference turns | 4 tool-call rounds |
| Token delta | 4,240 consumed (meter 14,805,873 -> 14,801,633) |
| Script executions (plugin-instructed) | 5 (build_body.py, render-overview via scaffold_workspace.py, phase_gates.py suggest, lookup-workspace, fixture fixture helpers) |
| Subagent dispatches | 0 |
| Blocked-external steps | `get_item` drift read, `update_item` push (fixture-backed fixtures) |
