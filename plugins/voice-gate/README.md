# Mechanical enforcement: voice-gate shell hook (2026-11-11)

Prompt-level rules alone do not block AI tells. A pre_tool_call shell hook enforces them mechanically.

- Hook: `~/.hermes/agent-hooks/voice-gate.py`, standalone scanner: `voice-check.py`
- Registered in config.yaml (`hooks.pre_tool_call`) of: default (~/.hermes), resume-assistant, hci-blog-writer
  - matchers: `discord|slack|send_message`, `terminal|Terminal|write_file|Write`, `delegate_task`
- Chat sends (discord/slack): outgoing text scanned against the pattern list; one hit = tool call BLOCKED with the offending pattern and a rewrite instruction. Status-token lines ([SILENT], NO-POST, DRAFT-READY, etc.) pass untouched.
- write_file: only public-facing paths (career/, uxr-blog, resumes, posts/, marketing/, personal sites) are scanned.
- terminal: any pandoc/headless-Chrome PDF render demands a `<source>.voice-pass` marker (written by voice-check.py on a clean scan). No marker, no render, no exceptions.
- delegate_task: goals touching resume/cover-letter/portfolio get the enforcement contract appended automatically.
- Every fire logs to `~/.hermes/logs/voice-gate.log` (JSONL events: chat_block, chat_pass, write_block, render_block, delegate_inject, chat_pass).
- Detection core lives in `voice-tells.py` (shared by hook and scanner, so they cannot drift):
- Regex layer: 55 inflection- and variant-aware patterns (contractions, hyphen/spacing variants, tense/plural forms), word-boundary anchored, case-insensitive.
- Vector layer: cosine similarity of the text against 16 embedded tell exemplars (negative parallelism, paradigm-shift inflation, testament/promo copulas, weasel attribution, reassurance kickers, aphorism/antimetabole density, and more) via local Ollama nomic-embed-text. Threshold 0.66: paraphrases hit 0.75-0.83, clean prose measured below 0.63. Latency 13-64 ms warm; a 2.5k-word draft scans in under 1 s. Long prose is chunked on paragraph boundaries (max 12 chunks). Fail-open: if Ollama is down the vector layer logs vec_skip and the regex layer still stands; nothing blocks on an infrastructure miss.
- Rebuild the exemplar cache with `python3 ~/.hermes/agent-hooks/voice-vector-build.py` after editing EXEMPLARS in voice-tells.py.
- False-positive tuning history: 0.62 fired once on a clean resume sentence (sim 0.62); 0.66 cleared it while keeping all paraphrase catches.
- Gateway must be restarted from OUTSIDE the gateway process for config hook changes to activate in multiplexed gateway sessions (launchctl kickstart -k gui/$UID/ai.hermes.gateway).