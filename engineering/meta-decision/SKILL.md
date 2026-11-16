---
name: meta-decision
description: "One-way-door decisions: EXPAND, CONTRACT, EMBED, REVIEW."
version: 0.2.0
author: Michael Oliver (moliver28)
license: MIT
metadata:
  tags: [decisions, meta-cognitive, orchestration]
---

# Meta-Decision Framework (ported from moliver28/zcode-settings)

## When to Use
- One-way doors: architecture, dependency selection, permission models, methodology choice that propagates across sessions.
- High ambiguity or high consequence; recurring decision classes (encode the framework, not just the answer).
- Don't use for: two-way doors, factual single-answer questions, cost-of-analysis > cost-of-error.

Full-spectrum decision pipeline; phases below.

## Pipeline
1. EXPAND (allow the panic; do not converge):
   - Systems triads: supersystem (goals, constraints, rhythms, actors) / system (boundaries, inputs, outputs, tensions) / subsystem (components, dependencies, downstream, breakage).
   - Perspective explosion, >=5 stances via parallel subagents (one subagent per stance): The User (boundary experience), The Maintainer (zero-maintenance at 6 months), The Adversary (exploit, bypass), The Sage (literature + master practice; use the platform's search tooling), The Future Self (long-horizon), The System (coherence).
   - Meta-cognitive strategies, >=3 applied: first principles, inversion, second-order effects, Cynefin framing, outside view (base rates), pre-mortem, reversibility test, safety margin, non-duality check.
   - Literature grounding: every load-bearing claim cites a verifiable source.
   - Bias inoculation: name the 2-3 dangerous biases (status quo, anchoring, planning fallacy) + mitigations before generating options.
2. CONTRACT (the solution should feel obvious; if not, re-EXPAND with the named gap):
   - Pattern recognition: what repeats, simplifies, leverages, conflicts.
   - First-principles reduction: human need -> minimum mechanism -> zero-maintenance form.
   - Non-duality check: is the A-or-B framing itself the problem? Is there a C serving both?
3. EMBED (never decide this again):
   - Output must be self-enforcing (structure prevents the wrong choice), self-documenting (rationale encoded in artifact), or self-removing (no residue).
   - Persist recurring decisions per your platform's mechanism (memory, config, scheduled job) so they re-fire without a fresh reasoning pass. Hermes users: wire via `skill_manage` (skill) and `cronjob_manage` (scheduled job).
   - Write the decision record: context, options table with why-not-chosen, decision, rationale, strategies applied, evidence, maintenance horizon, auto-trigger.
4. REVIEW (validate before commit):
   - Pre-mortem: assume it failed at 6 months; name failure, root cause, missed signal, cheapest prevention.
   - Bias audit: any option dismissed too fast, favored without evidence, or is the obviousness fatigue?
   - Momus gate: dispatch a critical-review subagent on the record; critical gaps loop back to the relevant phase.
   - Reversibility: reversal cost stated; rollback plan if irreversible.

## Complex decisions
Spawn a perspective ensemble: 4 parallel subagents (user / maintainer / adversary / systems-thinker), synthesize yourself.

## Stance
- Think first, structure second (format constraints before reasoning degrade accuracy).
- Retrieve before reason; cite everything; separate fact / strong inference / speculation.
- Non-duality as operating stance: see past the pair to the whole.
