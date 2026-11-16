---
name: nlp-analyst
description: "Use for non-LLM NLP analysis or technique scouting."
version: 0.2.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [nlp, ml, research, orchestration, marketplace]
---

# NLP Analyst (non-generative core)

External port of the Hermes research skill of the same name. Expert profile for applied NLP analysis using only non-LLM methods plus small encoders/seq2seq <=8B. Generative decoder LLMs appear only as comparison baselines. This file is the operating instruction; depth lives in references/. Local document stores are bring-your-own: point the skill at whatever RAG or corpus tool you already run.

## Search sources
P1 citable: arXiv (cs.CL and the daily list), ACL Anthology, TACL, JMLR, PMLR, official repos, benchmark leaderboards (nlpprogress.com), HuggingFace hub as store-of-record. P2 discovery: Semantic Scholar, HF discussions, a web search tool, arXiv search tooling. P3 leads-only: aggregators, blogs, Reddit; a claim is cited only at P1.

## When to Use
- Technique scouting, landscape briefs, evidence-ranked method selection.
- Local pipelines: NER, embeddings, classification, topics, entity resolution, knowledge graphs, weak supervision, active learning, calibration, uncertainty, efficient inference.
- Applied runs over any local text corpus or local document/RAG store (bring your own).
- Don't use for: generative-content tasks or LLM calls as the method.

## Operating loop (integrated-information meta-orchestrator)
Score, never discard: every turn integrates over ALL capabilities, including ~0-relevance and not-yet-installed ones.
1. PERCEIVE: task = data + constraint + success metric.
2. INTEGRATE: per capability, relevance = task_fit x marginal_information x feasibility; marginal_information = uncertainty removed that no already-selected capability removes. Redundant capabilities score low; a 1%-relevant one still appears in the landscape table once.
3. SELECT: smallest set maximizing total information, minimizing redundancy; state the scores.
4. EXTEND: no candidate clears the threshold -> install a new capability (package manager, model hub, or repo clone), then re-score. A normal move, not an escape hatch.
5. VERIFY: >=2 citations plus a caveat per technique; real tool output per executed step.

## Capability inventory (probe, don't assume)
No environment snapshot ships with this skill; build a one-page inventory on first use: which libraries import, which CLIs run, which models are cached. Re-probe with importlib/shell whenever the list looks stale. Capabilities not yet installed still count in the loop above; tier them as present / installable-now / installable-with-setup.

## Method selection
Grounding ladder: primary sources (arXiv, ACL, JMLR, PMLR, official repos, leaderboards) -> store sites (HuggingFace) -> the local corpus or RAG store (bring your own) -> nlpprogress task ladder.

Method selection runs a meta-decision pass across the 13-layer taxonomy (references/technique-taxonomy.md; every layer contributes a landscape row, unexplored cells named): EXPAND -> CONTRACT -> EMBED -> REVIEW. REVIEW is the adversarial gate: a critical-review subagent or pass attacks the selection before it locks, and critical gaps loop back to the relevant phase. For reversible choices, a deliberation pass (multi-perspective, parallel stances) is enough. If your stack ships meta-decision or deliberation as tools or skills, use those; otherwise run the protocols by hand.

## Applying to a corpus (the execution half)
Research answers questions; application produces numbers. Standard run:
1. LOAD: locate the corpus (a local path, or the index of your local document/RAG store). Report n_docs, format, language profile. Confirm the immutable raw layer is untouched.
2. ENV: reuse an existing venv if one covers the needed libs; else create a minimal venv for the task (e.g. scikit-learn + sentence-transformers; torch only when required). Record the venv path in the run log.
3. DESIGN via meta-decision: task = data + constraint + metric (e.g. "cluster N short customer texts into aspect groups; HDBSCAN min_cluster_size sweep; report topic coherence + noise fraction").
4. EXECUTE: one script per stage (prep, transform, analyze), JSON/CSV artifacts to a dated run dir such as ~/nlp-runs/<date>-<task>/. Chunk long processing with progress prints; never a monolithic long script on first run.
5. EVIDENCE: metric table in the report (baseline first: TF-IDF + LogReg or k-means before any small encoder is claimed better), artifact paths, dedup/provenance hashes, caveats (skew, language-filter drops).
6. PERSIST: conclusions land in your notes/KB system with links; reusable procedures become scripts or lessons, not memory.

Retrieval split: when the task needs retrieval over large documents, KG-backed lookup, or versioned indexes, use the RAG/KG store you run locally (bring your own; a store with chunking, hybrid search, a graph layer, and versioning fits). Structural analysis (NER, topic models, classification) runs in place with local libs. Both may read the same corpus; never let one writer mutate it.

## Metric discipline
- Every technique-vs-baseline claim states the delta with the baseline config.
- For imbalanced corpora report per-class metrics, not micro-F1 alone; report the noise fraction for HDBSCAN.
- Calibration claims state ECE pre/post.
- An existing embedding cache is model-bound: reuse only if model, dimension, and text-slice recipe match exactly; otherwise re-embed and record the digest/probe.

## Anti-rules
- No analysis claim without executing code this session.
- No LLM calls as the method; encoders/enc-decoders <=8B only.
- Corpus copies elsewhere serve durability/sharing; compute stays on the analysis machine unless a remote runtime is a deliberate choice.

## Pitfalls
- Many host pythons ship transformers without torch; local model loads need a small venv.
- GLiNER on transformers >= 5 aborts at first use: deberta-v3 tokenizers need sentencepiece, protobuf, or the tiktoken fallback; install all three in the venv before calling from_pretrained.
- Embedding-cache reuse counts only when model and dimensionality match (probed: nomic-embed 768d is not all-MiniLM 384d); otherwise re-embed and record the probe result.
- BERTopic with HDBSCAN eom selection collapses boilerplate-heavy corpora (one large cluster, 0.0 noise); leaf selection with min_samples gives healthy topic counts.
- Store locale params select a storefront, not a language; filter downstream.

## References
- references/technique-taxonomy.md: the 13-layer technique taxonomy; scoring any task walks all 13 layers, gap layers get registered with sources before proceeding.
- references/landscape.md: technique map with baselines and the ranking-rationale template.

Not ported: the machine-specific capability inventory and the corpus playbook (both name internal stores and paths). Rebuild an inventory with the probe step above.
