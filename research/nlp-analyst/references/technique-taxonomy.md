# NLP technique taxonomy (near-exhaustive, 2026-11-16)

Layered so the orchestrator can score by layer and detect unexplored cells. Anchored on nlpprogress.com, ACL Anthology, discourse-parsing surveys (RST/PDTB/dialogue), semantic-parsing surveys.

## Layer 1: Lexical/morphological
Tokenization (word, subword BPE/unigram, morphological segmentation), stemming, lemmatization, POS tagging, normalization, spell correction, transliteration.

## Layer 2: Syntax
Chunking, constituency parsing (Benepar/Berkeley), dependency parsing (spaCy, Stanza, UD), CCG parsing, constraint/grammar rules.

## Layer 3: Word/sentence semantics
Word sense disambiguation, lexical substitution, semantic similarity (sentence-transformers, E5, bge, LaBSE), paraphrase detection, sense-change over time, frames (VerbNet, FrameNet, PropBank, SRL).

## Layer 4: Compositional semantics
Semantic parsing to executable forms (SQL/text-to-query, SPARQL), AMR, UCCA, DRS parsing, event extraction and schemas, negation/modality scope detection, compositional distributional semantics.

## Layer 5: Reference and document/dialogue structure
Coreference and anaphora resolution (CRAC), entity linking (BLINK, GENRE), discourse parsing (RST, PDTB, dialogue STAC/DISRPT), discourse segmentation, centering, document structure, dialogue state tracking.

## Layer 6: Information extraction and knowledge
NER (classical + GLiNER zero-shot), relation extraction, claim/argument extraction, event coreference, KG construction/completion (TransE/RotatE-class link prediction), temporal normalization, KBQA, retrieval (BM25, dense, hybrid, re-ranking), RAG substrates (retrieval backends with text/AST-aware chunking, hybrid search, KG store, SQL, versioning; bring your own store).

## Layer 7: Probabilistic/representational
Topic models (LDA, BERTopic, CTM), clustering (HDBSCAN), probing, representation geometry, calibration/uncertainty (conformal prediction, MC-dropout, ensembles), Bayesian/PGM methods.

## Layer 8: Structured prediction and supervision regimes
Sequence labeling (CRF, BiLSTM-CRF, transformers), classification across shot regimes, weak supervision (skweak, Snorkel), active learning (small-text), semi/self-supervision, distillation, domain adaptation, annotation projection, multi-task learning.

## Layer 9: Pragmatics and argumentation
Sentiment (document, aspect-based), stance detection, sarcasm/irony markers, argument mining, claim verification/fact checking, bias/framing analysis.

## Layer 10: Generation-adjacent (non-decoder)
Extractive summarization (TextRank, GraphRank), keyword extraction (RAKE, KeyBERT), template generation, rule-based simplification.

## Layer 11: Multilingual
Language ID (fastText, CLD3), code-switching, cross-lingual alignment (mBERT/XLM-R, LaBSE), MT small models (MarianMT, NLLB) as structured-prediction utilities, low-resource morphology.

## Layer 12: Speech/multimodal text-input
ASR as input stage (whisper.cpp), forced alignment, OCR (pymupdf, marker), document layout analysis (LayoutLMv3).

## Layer 13: Evaluation, data, meta-methods
Benchmarks (GLUE-class, CoNLL, CrossNER), intrinsic metrics (BLEU-family, ROUGE, BERTScore over encoders), statistical testing (bootstrap, approximate randomization), IAA (Krippendorff), datasheets, leakage/contamination checks, dedup and corpus hygiene, sampling design.

## Exclusion rule
Decoder-only generative LLMs remain baseline-only. Encoders/encoder-decoders <=8B permitted wherever labeled.

## Exhaustiveness discipline
- Scoring any task: walk ALL 13 layers; each contributes at least one landscape-table row, even at 1% relevance.
- A task spanning a layer not named above registers a gap layer here with sources before proceeding.
