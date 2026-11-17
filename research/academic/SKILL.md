---
name: academic
description: "Searches scholarly databases in parallel and layers academic rigor on any answer: peer-review status, evidence hierarchy, and citations. Use when the user says: 'find peer-reviewed research on this', 'back this with academic sources', 'what does the literature say'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [research, academic, citations, evidence]
---

# Academic

## When to load
- User asks for academic, scholarly, peer-reviewed, or evidence-based content
- Writing papers, literature reviews, or research proposals
- Content needs scholarly rigor and proper citations

## When NOT to load
- Casual blog posts without research backing
- Opinion pieces or creative writing
- Internal documents not requiring citations

## Core rules
1. **Always perform web search** using Academic Source Registry
2. **Use a research-paper category filter** when your web search tool supports categories
3. **Select databases per registry**:
   - **Primary** (always): scholar.google.com, semanticscholar.org, arxiv.org, dl.acm.org, openalex.org
   - **Secondary** (domain-conditional): sciencedirect.com, Springer, SAGE, T&F, JSTOR, DOAJ, CORE, ResearchGate
   - **Domain-specific**: PubMed (health), SSRN (social science), IEEE/DBLP (CS), PsycNET (psych), ERIC (education)
   - **Practitioner** (when relevant): NNGroup, HBR, domain-specific professional sources
4. **Run parallel queries** across multiple domain sets to maximize coverage

## Output Requirements
- Cite sources with author, year, and publication
- Distinguish between peer-reviewed and practitioner sources
- Note strength of evidence (meta-analysis > RCT > observational > expert opinion)
- Flag when evidence is limited or conflicting

## Evidence Hierarchy
1. Meta-analyses and systematic reviews
2. Randomized controlled trials
3. Quasi-experimental studies
4. Observational studies
5. Qualitative studies
6. Expert opinion and practitioner sources

## Related skills
- `literature-review` (in this marketplace) — for the full FSM-based systematic literature review protocol.
- For refining drafted academic output, use an iterative-refinement skill if your agent has one.
- For HCI/UXR academic sources, use a UX-research skill if your agent has one.
- For legal/regulatory academic sources, use a legal-research skill if your agent has one.
