---
name: literature-review
description: "Runs the systematic literature review protocol end to end: scoping, keyword expansion, multi-database search, citation chasing, screening, extraction, synthesis, and PRISMA-style reporting. Use when the user says: 'do a literature review', 'run a systematic review', 'find research gaps'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [research, literature-review, systematic-review, academic]
---

# Literature Review

## When to load
- User asks for "literature review," "lit review," "systematic review," "SLR," "scoping review"
- Surveying existing research on a topic
- Identifying research gaps
- Part of academic writing workflow

## When NOT to load
- General web research (use your agent's research and search tools directly)
- Writing a paper without a literature component
- Market research or competitive analysis

## Core rules
1. **Follow the FSM-based protocol** with states: Scoping → Keyword expansion → Database search → Citation chasing → Screening → Extraction → Synthesis → Reporting
2. **Default to standard depth** unless user specifies otherwise
3. **Transparent search strategy** — Document all databases, keywords, and criteria
4. **Reproducible methodology** — Another researcher should be able to replicate

## Depth Levels
| Level | Scope | Method |
|-------|-------|--------|
| **Quick** | Single-pass search, top results only | Summary synthesis |
| **Standard** | Multi-database search, citation chasing | Structured extraction, narrative synthesis |
| **Exhaustive** | Full systematic protocol, all databases | Bidirectional citation chasing, quality assessment, PRISMA-style reporting |

## Protocol States
1. **Scoping** — Define research question, inclusion/exclusion criteria
2. **Keyword expansion** — Core concepts + synonyms + related terms
3. **Database search** — Run queries across the academic databases available to you
4. **Citation chasing** — Forward (who cited this) and backward (references)
5. **Screening** — Title/abstract → Full-text → Quality assessment
6. **Extraction** — Key findings, methods, sample sizes, limitations
7. **Synthesis** — Group by themes, not by paper
8. **Reporting** — Structured review with transparent methodology

## Related skills
- For lighter-weight academic source searching and citation, use your agent's research tools directly, or a dedicated academic-search skill if your agent has one.
- `meta-decision` and `iit-hci-integration` (in this marketplace) cover related decision-framework and system-integration work.
