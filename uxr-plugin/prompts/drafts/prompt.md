---
{
  "id": "drafts",
  "version": 1,
  "vars": ["ask", "digest", "group", "owner"],
  "when": [],
  "fragments": [
    {"id": "craft-bars", "file": "fragments/craft-bars.md", "budget": 14},
    {"id": "sweep-empty", "when": "evidence_total == 0", "file": "fragments/sweep-empty.md", "budget": 4},
    {"id": "feedback-gap", "when": "feedback_gap == true", "file": "fragments/feedback-gap.md", "budget": 4}
  ],
  "default": "prompt.md",
  "budget": {"max_lines": 60, "max_vars": 7}
}
---
One structured drafting pass for the study request below. Return ONE JSON
object and nothing else - no prose outside the JSON:

{
  "background": "3 to 5 sentences: why now, what already exists (cite the sweep counts and document names by name), who needs the answer, the problem area",
  "resources": [],
  "decision": "one sentence that names what will change because of the study, with an owner",
  "decision_shape": "invest-a-or-b|ship-ga|standardize|other-good|topic-only|validate-only|two-sentences|no-owner",
  "hypotheses": [{"label": "H1", "text": "..."}],
  "assumptions": [{"label": "A1", "text": "..."}]
}

Propose 3 to 5 hypotheses and 2 to 3 assumptions. Every claim is verbatim
bound field data or your own draft: never invent a source result.

Request and answers so far:
$ask

Evidence digest (the only evidence input):
$digest

Owning group: $group
Decision owner: $owner
