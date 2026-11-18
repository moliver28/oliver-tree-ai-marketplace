# Mechanical enforcement: voice-gate shell hook (2026-11-11)

Prompt-level rules alone do not block AI tells. A pre_tool_call shell hook enforces them mechanically.

- Hook: `~/.hermes/agent-hooks/voice-gate.py`, standalone scanner: `voice-check.py`
- Registered in config.yaml (`hooks.pre_tool_call`) of: default (~/.hermes), resume-assistant, hci-blog-writer
  - matchers: `discord|slack|send_message`, `terminal|Terminal|write_file|Write`, `delegate_task`
- Chat sends (discord/slack): outgoing text scanned against the pattern list; one hit = tool call BLOCKED with the offending pattern and a rewrite instruction. Status-token lines ([SILENT], NO-POST, DRAFT-READY, etc.) pass untouched.
- write_file: only public-facing paths (career/, uxr-blog, resumes, posts/, marketing/, personal sites) are scanned.
- terminal: any pandoc/headless-Chrome PDF render demands a `<source>.voice-pass` marker (written by voice-check.py on a clean scan). No marker, no render, no exceptions.
- delegate_task: goals touching resume/cover-letter/portfolio get the enforcement contract appended automatically.
- Every fire logs to `~/.hermes/logs/voice-gate.log` (JSONL events: chat_block, chat_pass, write_block, render_block, delegate_inject, vec_fallback, vec_hit, vec_collision, vec_skip).
- Detection core lives in `voice-tells.py` (shared by hook and scanner, so they cannot drift):
- Regex layer: 55 inflection- and variant-aware patterns (contractions, hyphen/spacing variants, tense/plural forms), word-boundary anchored, case-insensitive.
- Vector layer: cosine similarity against 18 embedded tell exemplars (negative parallelism, paradigm-shift inflation, testament/promo copulas, weasel attribution, reassurance kickers, aphorism/antimetabole density, and more). Embedders, tried in order:
  - Ollama fast path: local `nomic-embed-text` via `http://localhost:11434/api/embeddings`, warm 13-64 ms on a loaded daemon. Override the endpoint with `VOICE_GATE_OLLAMA_URL`.
  - ONNX availability path: when the daemon misses (down, refused, timed out) the same process falls back lazily to an in-process quantized `bge-small-en-v1.5` int8 model (~35 MB, downloaded from Hugging Face on first use and cached under `<HERMES_HOME>/state/models/`); onnxruntime is imported inside the fallback path only and is never required by CI or the regex layer. One daemon miss is sticky for the process, so warm scans never re-probe it.
  - Exemplar vectors are keyed by backend in `voice-tells-vectors.json` (committed beside the module): embedding spaces are backend-specific and are never mixed; an explicit backend never silently switches.
- Per-class thresholds: the global 0.66 constant is gone. `voice-tells-calibration.json` (committed beside the cache) stores, per backend, one threshold per tell class = background p99 + 0.03 measured on clean repo prose (`voice-vector-build.py --bg` overrides the corpus). Runtime compares each chunk-exemplar similarity against its class threshold only. Background chunks that collide with a threshold are logged warn-mode (`vec_collision`, log-only) and recorded in the calibration table; they never move the formula. Fail output still carries <=5 family-deduped patterns; only the accept/reject boundary moved per class.
- Latency (issue #2 acceptance, daemon-less Windows box, 12-chunk 2.5k-word doc): cold first scan 2.5 s (one-time ONNX session init), warm 130-240 ms, well under the 2 s fail-open timeout.
- Fail-open: if both embedders are unavailable the vector layer logs `vec_skip` and the regex layer still stands; nothing blocks on an infrastructure miss. `VOICE_GATE_VECTOR=off` disables the vector layer explicitly.
- Rebuild the exemplar cache + calibration with `python3 voice-vector-build.py --backend ollama` and `--backend onnx` after editing EXEMPLARS in voice-tells.py (run once per backend; needs Ollama with nomic-embed-text for the first, onnxruntime for the second).
- False-positive tuning history: 0.62 global fired once on a clean resume sentence (sim 0.62); 0.66 global cleared it but left a ~0.05 margin for every class; per-class p99 + 0.03 (0.2.0) gives each tell its own measured boundary, so clean prose of atypically dense style sits well below its nearest threshold.
- Gateway must be restarted from OUTSIDE the gateway process for config hook changes to activate in multiplexed gateway sessions (launchctl kickstart -k gui/$UID/ai.hermes.gateway).
