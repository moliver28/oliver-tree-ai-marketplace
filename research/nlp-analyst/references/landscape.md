# Non-LLM NLP landscape (grounded 2026-11)

Sources checked 2026-11: spacy.io, github.com/urchade/GLiNER, bertopic.com, maartengr.github.io/BERTopic, arxiv.org (2509.22612, 2602.18487 GLiNER-bi-Encoder), jmlr.org, proceedings.mlr.press.

## Search source ladder (cite P1 only)
- P1 primary: arXiv (incl. cs.CL recent list), ACL Anthology, TACL, JMLR, PMLR, official repos (READMEs = primary docs), leaderboards (nlpprogress.com), HuggingFace hub pages (store-of-record for models/datasets).
- P2 discovery: Semantic Scholar, HF discussions, a web search tool, arXiv search tooling.
- P3 leads-only: blogs, community aggregators, Reddit. Never cited as evidence; use to seed P1 searches.

## Technique map
| Area | Primary | Alternates | Note / caveat |
|---|---|---|---|
| NER (fast) | spaCy (en_core_web_lg/trf) | Stanza, Flair | spaCy trf OntoNotes NER ~89.8; spaCy fastest in production |
| NER (zero-shot/any label) | GLiNER | GLiNER-bi-Encoder | Apache-2.0, CPU-runnable, bi-encoder 61.5 CrossNER, 130x at 1024 labels |
| Relations/claims | GLiNER (joint e+re) | spaCy dependency rules, Stanford OpenIE | relation extraction supported in GLiNER mainstream |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2 baseline) | E5, GTE, bge | small encoders, CPU OK |
| Classification | sklearn linear/LogReg + TF-IDF | transformers encoders fine-tuned | baseline first, encoder only if margin matters |
| Topic modeling | BERTopic (UMAP+HDBSCAN+c-TF-IDF) | LDA (gensim) | BERTopic modular over any embedding model |
| Clustering | HDBSCAN, k-means | agglomerative | density-based handles noise |
| NLI / contradiction | small RoBERTa/DeBERTa NLI heads | | encoder NLI models ~1GB |
| Entity resolution | dedupe: (label, text-hash) + embedding sim | record-linkage libs | matches standard dedupe-key design practice |
| Weak supervision | skweak | snorkel | label-model over noisy heuristics |
| Active learning | small-text | modAL | pairs with small classifiers |
| Calibration/uncertainty | expected calibration error, temperature scaling, MC-dropout/ensembles | conformal prediction | report ECE pre/post |
| KG construction | GLiNER+relation extraction -> networkx | | networkx is lightweight and commonly available |
| Efficient inference | quantized encoders, ONNX runtime | | quantize, don't shrink scope |
| Multilingual tokenization/POS | Stanza | spacy-stanza adapter | Stanford, multilingual strength |

## Baseline-only section (excluded as core method)
GPT/Llama-class generative decoders: use only to set comparison bars; never as the pipeline method.

## Ranking rationale template
score = task_fit (1-5) x marginal_information (deduped info gain) x feasibility (local, license, maintenance). Report each factor per row.
