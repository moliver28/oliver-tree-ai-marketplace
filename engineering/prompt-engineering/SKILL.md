---
name: prompt-engineering
description: "Optimizes and rewrites prompts with the COSTAR framework and evidence-based technique selection, preserving user intent and explaining every change. Use when the user says: 'optimize this prompt', 'improve my system prompt', 'rewrite this as a COSTAR prompt'."
version: 0.1.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [prompting, costar, llm, engineering]
---

# Prompt Engineering

## When to load
- User asks to optimize, improve, or rewrite a prompt
- "Act as X" role-based requests
- Designing new instruction sets or agent definitions
- Output quality is inconsistent and prompt structure may be the cause

## When NOT to load
- Simple factual questions
- Tasks where the prompt is already well-structured
- When the issue is model capability, not prompt design

## Core rules
1. **Preserve original user intent** — Never add requirements the user did not imply
2. **Explain every change** — User should understand why each modification was made
3. **Acknowledge when simpler is better** — Not every prompt needs complexity
4. **Think first, format second** — Never front-load structural constraints before reasoning steps (Tam et al., 2024: format restrictions can degrade accuracy by up to 64 percentage points)

## Technique Selection
| Task Type | Technique | When to Use |
|-----------|-----------|-------------|
| Reasoning/Math | Chain-of-Thought | Complex multi-step problems. **Note:** On frontier models, CoT yields only marginal gains at 20-80% additional time cost (Meincke et al., 2025). Use selectively. |
| High-stakes | Self-Consistency | Decisions needing validation |
| Role-based | COSTAR Framework | "Act as X" prompts |
| Ambiguous | Few-shot examples | Unclear format expectations |
| Multi-step | Tree-of-Thought | Non-linear, high-search-space problems where first-path reasoning fails |

## COSTAR Framework
- **C**ontext: Background information and situation
- **O**bjective: What the role should accomplish
- **S**tyle: Writing or communication style
- **T**one: Emotional register and attitude
- **A**udience: Who the output is for
- **R**esponse: Format and structure of output

## Output Format
```
## OPTIMIZED PROMPT
[Rewritten prompt]

## CHANGES MADE
- [Change + rationale]

## TECHNIQUES APPLIED
- [Technique + why]

## INFERRED REQUIREMENTS
- [Implicit need surfaced]
```

## Key Research Findings
- **Format restrictions degrade reasoning** (Tam et al., 2024): Up to 64 percentage point accuracy loss. Think first, format second.
- **Irrelevant context destroys performance** (Levy et al., 2024): Accuracy dropped from 92% to 68% with irrelevant surrounding context. Trim noise ruthlessly.
- **Relevant detail helps** (Liu et al., 2025): Longer prompts with relevant detail improved performance across all tested tasks. Density of relevant context helps; padding destroys.
- **CoT is no longer universally beneficial** (Meincke et al., 2025): On frontier models, explicit CoT yields marginal gains at significant time cost. Default to native model reasoning; add explicit CoT only when output is demonstrably inconsistent.

## Related skills
- For role-based prompt optimization, pair this skill with a role-playing or expert-persona skill if your agent has one.
- For building persistent agent definitions, apply the COSTAR framework to each instruction block, or use an agent-definition skill if your agent has one.
- For iterative prompt improvement, run additional optimization passes on the refined output, or use an iterative-refinement skill if your agent has one.
