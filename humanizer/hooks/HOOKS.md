# Hook contract (token economy)

The gate runs between generation and delivery. It is deterministic code; it never calls the model to evaluate.

| Outcome | Model tokens spent | What happens |
|---|---|---|
| Pass | 0 | Gate emits `{"status": "pass"}`. Nothing is re-read, nothing re-enters context. |
| Chat nudge (STE on chat output) | <= ~60 | One STE fix line to the assistant before it sends; the user never sees it unless they ask why. Fail-open on scan error. |
| Fail | <= ~200 | Gate emits the hit JSON: distinct patterns (max 5), one span each, one fix line each, plus one instruction block: "REPAIR, DO NOT REWRITE." The model patches the named spans only; the pass is not regenerated and the whole output is not re-emitted. The family-35 aphorism budget lines (one per over-budget section, then the piece line) ride the same dedup cap: the line names the section and the count, never an AI accusation. |
| Scan error | 0 | Fail-open: the gate logs and delivers (designed posture; availability misses must not block delivery). |
| Advisory signals (v1.1.0: `voice_fit`, `source_fidelity` via `--source`, classifier `p_ai`/`voice_delta`) | 0 | Computed inside the gate process (embedding pass + dot products, no model call); appear as extra fields in the pass/fail JSON only when their learned artifacts exist. Wave H-C adds two band-gated advisory fields, `cycling_pairs` (family 11, chunk-pair divergence) and `compression_profile`; they appear only when the learned state carries the matching bands (`bands` in the runtime state file), so the uncalibrated pass line stays byte-identical. Fidelity/voice-fit cost zero model tokens; the pass stays silent toward the model. Advisory only in 1.1.0: they NEVER change pass/fail. |

Surfaces: `--surface chat` = STE layer only, always on (Discord/Slack/agent replies); `--surface public` = tell scan + STE (or the onboarding STE-mode choice). Same token economy per outcome below.

Conditional design rules:

- The hook decides what the model sees. Pass = silence; fail = the minimum repair contract. There is no standing instruction blob in context; pattern knowledge lives in the scan code, not in prompts.
- Feedback names spans, so the model re-reads at most the flagged region; on a patch-capable surface it edits in place instead of writing the full text again.
- Distinct-pattern dedup (one fix line per pattern, not per hit) keeps dense drafts' feedback short.
- Max 5 patterns per pass; anything further waits for the next pass so the repair contract stays small.
- The user still sees only the copy plus `voice: pass` or `voice: N fixes applied` (with `(fidelity 0.91)` / `(voice-fit 0.72)` appended when the advisory JSON carried those numbers); the JSON and instruction are hook-facing.
- Advisory signals fail open and stay out of the way: absent learned artifacts (centroid, classifier, embed cache) mean absent JSON fields and zero added latency; a missing embedder is logged (`vec_skip`) and never blocks. `--source FILE` embeds the source once into the bounded, hash-keyed disk cache `learned/embed-cache.json` (max 64 entries, oldest dropped, atomic write; key `<backend>:<sha256(text)[:16]>`) so a repeated /voice run on the same draft does not re-embed the source (ruling 1, issue #127).

## Runtime hook adapters (config-driven surfaces)

The gate ships as ONE deterministic scanner (`gate.py --surface chat|public`).
A platform that supports pre-send/pre-write hooks points its hook at the gate;
it never re-implements the pattern list. Which texts get scanned is decided by
the installing user's learned profile, not by anything hard-coded here:

- **Chat sends** (`--surface chat`): the platform's outgoing-message hook pipes
  the reply text to the gate and blocks on exit 4 (repair contract) or sends on
  exit 0. Status-token lines and code-fence bodies pass untouched.
- **Public-facing file writes** (`--surface public`): the platform's write hook
  pipes file content to the gate when the target path is one of the user's
  public surfaces (posts, docs, marketing, career materials). The surface list
  comes from the user's onboarding profile (template section 6) or their learned
  rules; the adapter carries no built-in path regexes.
- **Render marker gate**: a deterministic render step (PDF export and similar)
  may require a `<source>.voice-pass` marker written by `voice_check.py` on a
  clean scan; no marker, no render.
- **Delegation briefs**: when a task touches public prose, the adapter appends
  the enforcement contract (scan before writing or rendering) to the brief.

Every fire logs JSONL events (block/pass/render_block/state_load/state_skip and
the vector-layer events) to the platform's log sink. Fail-open posture is
unchanged: a scan error delivers, never blocks.
