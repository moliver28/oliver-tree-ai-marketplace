---
name: llm-integration
description: "Hardens scripts that call LLM chat APIs: JSON-mode fallbacks, token-budget retries, and quality gates on generated text. Use when the user says: 'the LLM call returns empty content', 'why does my script fail against LM Studio', 'add a gate that catches bad drafts'."
version: 0.1.0
author: Daneel curator
license: MIT
metadata:
  hermes:
    tags: [llm, api, lm-studio, local-inference, http, json-mode]
tags: [llm, api, lm-studio, local-inference, http, json-mode]
---

# LLM HTTP integration pitfalls

## When to Use
- Writing or debugging scripts that POST to OpenAI-compatible chat endpoints (LM Studio, Ollama, cloud relays).
- Building programmatic quality gates for LLM-generated text (drafts, extracts, synthesis).

Rules for calling LLM APIs from scripts, from verified debugging on LM Studio with reasoning models.

## Calling local OpenAI-compatible servers
- Send `response_format` json_object ONLY after probing: LM Studio rejects it (wants json_schema or text). Wrap the first call so it falls back to removing the field when the error body mentions response_format.
- Reasoning models return `content: ""` with `finish_reason: "length"` when max_tokens is consumed by reasoning_content. Never treat empty content as model failure on first occurrence: check finish_reason. If length-capped, retry with a multiplied budget (4x) before giving up.
- Salvage pattern: when still length-capped, the final JSON block usually exists inside reasoning_content. Regex-extract the outermost `{...}` from it before failing the call.
- Model auto-detection: fetch `/v1/models`, prefer ids matching a small-chat pattern (9B-class), exclude embedding models by name hints.

## Draft-generation gates (text outputs)
- Gate generated drafts programmatically before delivery: sentence-count cap, required-citation-token check against supplied context, banned-phrase list.
- One bounded re-ask on gate failure, then human review is final. Never loop on gate failures.

## Local few-shot classifiers (SetFit sidecar)
- Read references/local-few-shot-trainer-quirks.md BEFORE writing any SetFit training or eval script: API facts (body_learning_rate, tensor predictions), the separate-eval-script pattern, hard-negative mining, and threshold tables.

## Test patterns
- Build per-script test suites against temp fixtures; one deliberately-bad sample (banned terms, below-floor evidence, unresolved citations) demonstrates gate drops visibly in output.
- A dry-run mode that produces no side-effect writes must not record state files used by the real run for idempotency, or a dry-run followed by a real run silently skips everything.