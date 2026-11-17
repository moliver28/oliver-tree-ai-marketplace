---
name: deliberation
description: "Stress-tests one decision through a multi-perspective pipeline: an initial analysis, simulated stakeholder reactions from parallel subagents, and iterative refinement into a balanced conclusion. Use when the user says: 'stress-test this decision', 'what would stakeholders think', 'debate this'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [decisions, deliberation, stakeholders, workflow]
---

# Deliberation

## When to load
- User says "evaluate from multiple perspectives," "stress-test this decision," "what would stakeholders think," "devil's advocate," "debate this"
- Any request for multi-perspective evaluation or decision stress-testing

## When NOT to load
- Single-perspective analysis
- Factual questions with clear answers
- Non-evaluative tasks

## Core rules
1. **Analyst provides the initial analysis**
2. **Persona Simulator generates stakeholder reactions**
3. **Refiner iterates** incorporating those perspectives
4. **Output is a balanced, stress-tested conclusion**

## Pipeline
1. **Analyst** — Produces initial analysis or evaluation
2. **Persona Simulator** — Generates stakeholder/user perspectives and reactions
3. **Refiner** — Iterates on analysis incorporating perspectives
4. **Output** — Balanced, stress-tested conclusion

## Stakeholder Perspectives
Generate reactions from:
- Primary users/beneficiaries
- Secondary stakeholders
- Opposing viewpoints
- Implementation team
- Decision-makers

## Output Format
- Initial analysis summary
- Stakeholder perspectives (each with rationale)
- Objections surfaced
- Refined conclusion incorporating all perspectives
- Remaining uncertainties

## Related skills
- `meta-decision` (in this marketplace) — for a full decision framework whose adversarial review phase pairs with this pipeline.
- `academic` (in this marketplace) — for evidence-backed deliberation.
- For persistent stakeholder personas, use a persona-simulation skill if your agent has one; otherwise generate perspectives inline (Pipeline stage 2).
- For iterative refinement, use an iterative-refinement skill if your agent has one; otherwise iterate manually (Pipeline stage 3).
- For comparing options within deliberation, use an option-comparison skill if your agent has one.
