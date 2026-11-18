---
{
  "id": "hcd-gate",
  "version": 1,
  "vars": ["artifact", "artifact_kind", "factcheck"],
  "vars_source": "state",
  "when": [],
  "fragments": [
    {"id": "residual-checklist", "file": "fragments/residual-checklist.md", "budget": 14},
    {"id": "verdict-contract", "file": "fragments/verdict-contract.md", "budget": 10},
    {"id": "report-lens", "when": "artifact_kind == report", "file": "fragments/report-lens.md", "budget": 6}
  ],
  "default": "prompt.md",
  "budget": {"max_lines": 70, "max_vars": 5}
}
---
Human-centered design review gate for one artifact. Deterministic gates
(numbers, citations, stance vocabulary) already ran; their output is the
factcheck below. Do NOT re-check facts the factcheck already settles: judge
only the qualitative residual.

Artifact under review: $artifact
Artifact kind: $artifact_kind

Deterministic fact-check output (settled; trust it):
$factcheck

Return exactly these sections, in this order (the dispatcher prints them
verbatim to the user):

Summary
<2 to 3 sentences>

Strengths
- <3 to 5>

Risks
- <3 to 5>

What to change
- <3 to 5, or "None">

findings:
- {claim: <one sentence>, source: <artifact, file, or URL>, confidence: high|medium|low}
