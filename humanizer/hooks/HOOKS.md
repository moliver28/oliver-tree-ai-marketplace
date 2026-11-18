# Hook contract (token economy)

The gate runs between generation and delivery. It is deterministic code; it never calls the model to evaluate.

| Outcome | Model tokens spent | What happens |
|---|---|---|
| Pass | 0 | Gate emits `{"status": "pass"}`. Nothing is re-read, nothing re-enters context. |
| Chat nudge (STE on chat output) | <= ~60 | One STE fix line to the assistant before it sends; the user never sees it unless they ask why. Fail-open on scan error. |
| Fail | <= ~200 | Gate emits the hit JSON: distinct patterns (max 5), one span each, one fix line each, plus one instruction block: "REPAIR, DO NOT REWRITE." The model patches the named spans only; the pass is not regenerated and the whole output is not re-emitted. |
| Scan error | 0 | Fail-open: the gate logs and delivers (designed posture; availability misses must not block delivery). |

Surfaces: `--surface chat` = STE layer only, always on (Discord/Slack/agent replies); `--surface public` = tell scan + STE (or the onboarding STE-mode choice). Same token economy per outcome below.

Conditional design rules:

- The hook decides what the model sees. Pass = silence; fail = the minimum repair contract. There is no standing instruction blob in context; pattern knowledge lives in the scan code, not in prompts.
- Feedback names spans, so the model re-reads at most the flagged region; on a patch-capable surface it edits in place instead of writing the full text again.
- Distinct-pattern dedup (one fix line per pattern, not per hit) keeps dense drafts' feedback short.
- Max 5 patterns per pass; anything further waits for the next pass so the repair contract stays small.
- The user still sees only the copy plus `voice: pass` or `voice: N fixes applied`; the JSON and instruction are hook-facing.
