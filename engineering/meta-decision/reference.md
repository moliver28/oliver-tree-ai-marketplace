# Meta-Decision Framework (full-form companion to the condensed SKILL.md 0.2.0; reference only, not an installable skill)

## When to Load

- **Critical decisions**: one-way doors, architectural choices, UX direction, dependency selection, permission model design
- **High ambiguity**: unclear problem domain, conflicting stakeholder needs, novel territory
- **High consequence**: decisions whose effects propagate across subsystems or over time
- **Recurring decision patterns**: decisions you will face again — encode the framework, not just the answer

Trigger with `@meta-decision` followed by the decision context.

## When NOT to Load

- Trivial choices with reversible consequences (two-way doors)
- Factual questions with a single correct answer
- Decisions where the cost of analysis exceeds the cost of a wrong answer

## The Pipeline

```
                  EXPAND                              CONTRACT                          EMBED                         REVIEW
  ┌─────────────────────────────┐    ┌─────────────────────────────┐    ┌──────────────────────────┐    ┌──────────────────────────┐
  │  Systems Triads             │    │  Pattern Recognition        │    │  Zero-Maintenance Design  │    │  Adversarial Stress-Test │
  │  Perspective Explosion      │───►│  First Principles Reduction │───►│  Auto-Trigger Wiring      │───►│  Pre-Mortem Verification │
  │  Meta-Cognitive Strategies  │    │  Non-Duality Check          │    │  Decision Record          │    │  Bias Audit              │
  │  Literature Grounding       │    │                             │    │  Production Loop Hook     │    │  Adversarial Review Gate │
  │  Bias Inoculation           │    │                             │    │                          │    │                          │
  └─────────────────────────────┘    └─────────────────────────────┘    └──────────────────────────┘    └──────────────────────────┘
         (allow the panic)                (see the obvious)                (never decide this again)          (validate before commit)
```

## Phase 1: EXPAND (The Panic)

Do not converge. The goal is to generate enough material that the right answer becomes inevitable.

### Step 1.1: Systems Triads

Map three concentric layers. Use your agent's codebase-exploration tools or an exploration subagent for codebase decisions, or a research subagent for external domain mapping.

```yaml
supersystem:
  name: "The larger whole containing this decision"
  goals: ["what it aims to achieve"]
  constraints: ["what bounds it"]
  rhythms: ["release cadence, feedback loops, seasons"]
  actors: ["who is in this space"]

system:
  name: "The decision itself"
  boundaries: ["what is in scope, what is out"]
  inputs: ["what feeds into this"]
  outputs: ["what comes out of this"]
  tensions: ["where the forces pull"]

subsystem:
  components: ["what this touches"]
  dependencies: ["what this relies on"]
  downstream: ["what relies on this"]
  breakage: ["what breaks if this changes"]
```

### Step 1.2: Perspective Explosion

Run at minimum 5 perspectives. Delegate them as parallel subagent tasks where your CLI supports them; otherwise work through them sequentially yourself.

| Perspective | Core Question | Delegation Target |
|---|---|---|
| The User | What does the human at the boundary experience? | A frontend/UX-focused subagent for UX, or a deep-analysis subagent |
| The Maintainer | What does zero-maintenance look like 6 months from now? | A deep-analysis subagent with a simplification pass |
| The Adversary | How would someone exploit, misuse, or bypass this? | An adversarial reviewer subagent or a security skill |
| The Sage | What would a master practitioner say? What does the literature say? | A research subagent with academic grounding |
| The Future Self | What would past-you thank future-you for deciding today? | Introspection — a deep-analysis subagent with long-horizon framing |
| The System | What does the architecture require for coherence? | An architecture-focused subagent or code-graph tool |

### Step 1.3: Meta-Cognitive Strategy Application

Apply at least 3 strategies from this catalog. Run in parallel where possible.

| Strategy | Method | Parallelizable |
|---|---|---|
| First Principles | Strip to fundamentals, rebuild from axioms | Yes (independent) |
| Inversion | Assume failure, trace backward | Yes |
| Second-Order Effects | Trace effect chains | Yes (per option) |
| Cynefin Framing | Categorize: Simple/Complicated/Complex/Chaotic | No (must complete first) |
| Outside View | Base rates from reference class | Yes (research subagent) |
| Pre-Mortem | Assume the decision was made and failed | Yes |
| Reversibility Test | One-way vs two-way door | No (quick assessment) |
| Safety Margin | What buffer prevents edge-case catastrophe | Yes |
| Non-Duality Check | Transcend false binaries | After options generated |

### Step 1.4: Literature Grounding

When the decision domain has established research or practice:

1. Use an academic-search skill or research subagent for peer-reviewed literature (HCI, safety, architecture patterns)
2. Use web research for OSS implementation patterns and community practice
3. Apply prompt-engineering practice for agent/workflow design decisions
4. Use library documentation tools for API design patterns
5. Use web search for current industry practice

Cite every source with enough context to verify.

### Step 1.5: Bias Inoculation

Before generating options, explicitly name the most dangerous biases for this decision:

```yaml
biases_at_play:
  - name: "Status quo bias"
    mitigation: "Generate at least 3 alternatives to the current path"
  - name: "Anchoring"
    mitigation: "Evaluate all options independently before comparing"
  - name: "Planning fallacy"
    mitigation: "Use outside view — find base rates for this class of work"
```

## Phase 2: CONTRACT (The Zen)

The solution should feel obvious. If it does not, return to Phase 1.

### Step 2.1: Pattern Recognition

Across all expansion material, identify:
- **What repeats** — concepts, patterns, concerns that appear across multiple perspectives
- **What simplifies** — which framing or approach reduces complexity across the board
- **Where the leverage is** — the smallest change with the largest effect
- **What conflicts** — irreducible tensions that must be managed, not solved

### Step 2.2: First Principles Reduction

Strip to the irreducible:

```
Fundamental need: [the human need this serves]
Minimum mechanism: [the simplest thing that serves that need]
Zero-maintenance form: [what this looks like with no ongoing cost]
```

### Step 2.3: Non-Duality Check

For every binary in the decision space:

```
Framing: "We must choose between A and B"
- What does A truly serve? What does B truly serve?
- Is there a C that serves both?
- Is the framing itself the problem?
- What changes if we refuse the premise of the question?
```

### Step 2.4: The Obvious Test

```
- Is the solution obvious now? If yes, proceed.
- If not: what is missing? More perspectives? More data? Wrong framing?
- Return to Phase 1 with: [specific gap]
```

A correct solution has a quality of inevitability. Once seen, it seems like it was always there.

## Phase 3: EMBED (Production Loop)

Design the decision artifact so it requires no maintenance.

### Step 3.1: Zero-Maintenance Design

Every output must pass at least one of:

- **Self-enforcing**: The system prevents the wrong choice structurally (permissions, types, architecture)
- **Self-documenting**: The rationale is encoded in the artifact (naming, structure, comments that explain WHY not what)
- **Self-removing**: After execution, no trace remains to accumulate cruft (one-shot scripts, ephemeral infrastructure)

### Step 3.2: Auto-Trigger Wiring

If this decision class will recur, wire it into the production loop using your agent's config:

| Mechanism | When to Use | Implementation |
|---|---|---|
| Command | User-facing, repeatable | A command entry in your agent's config or commands directory, with agent routing |
| Hook | Event-driven, automatic | A tool/session hook in the hooks block of your agent's config |
| Plugin | Complex or conditional | Custom plugin watching tool/session events |
| Instruction | Agent self-direction | An addition to your agent's core instructions file |
| Skill | Methodology reuse | This skill file |

### Step 3.3: Decision Record

Write a structured decision record:

```
## DECISION: [title]

### Context
[Systems triad summary — supersystem, system, subsystem]

### Options Considered
| # | Option | Key Trade-off | Why Not Chosen |
|---|---|---|---|
| 1 | ... | ... | ... |

### Decision
[What was chosen, in one sentence]

### Rationale
[Why this, why now — 3-5 sentences]

### Meta-Cognitive Strategies Applied
- [Strategy]: [what it revealed]
- [Strategy]: [what it revealed]

### Evidence / Literature
- [Source]: [finding relevant to decision]

### Maintenance Horizon
- [What needs attention and when]

### Auto-Trigger
[If applicable: what will trigger this framework next time]
```

## Phase 4: REVIEW (Adversarial Gate)

Before committing, stress-test the decision.

### Step 4.1: Pre-Mortem

Assume the decision was implemented and failed 6 months later. Write the post-mortem:

```
What failed: [exactly]
Root cause: [what, not who]
Signal we missed: [what should have warned us]
Cheapest prevention: [what would have stopped it for the least cost]
```

### Step 4.2: Bias Audit

Review the decision record for:
- Was any option dismissed too quickly?
- Was any option favored without evidence?
- Are the trade-offs honestly characterized?
- Is the "obviousness" a result of analysis or fatigue?

### Step 4.3: Adversarial Review Gate

Run the decision through an adversarial reviewer (a critical-review subagent if your CLI has one; otherwise adopt the adversary perspective yourself):

`Delegate to a critical-review subagent: "Critique this decision record for blind spots, hidden assumptions, and missing perspectives. Decision:\n\n[record]"`

If the reviewer finds critical gaps, return to the relevant phase.

### Step 4.4: Reversibility Confirmation

```
- Is this decision reversible? (If yes, cost of reversal?)
- If not, what is the rollback plan?
- What trigger would cause us to revisit this decision?
```

## Parallel Agent Patterns

For complex decisions, spawn parallel perspective agents where your CLI supports them.

### Pattern: Perspective Ensemble

Create a team where each member applies a different meta-cognitive strategy to the same decision context:

```json
{
  "name": "decision-ensemble",
  "members": [
    {
      "name": "user-advocate",
      "prompt": "Given this decision context: [context]. Analyze from the USER perspective. What does the human at the boundary experience? What would delight them? What would frustrate them? What is their mental model?"
    },
    {
      "name": "maintainer",
      "prompt": "Given this decision context: [context]. Analyze from the MAINTENANCE perspective. What does zero-maintenance look like 6 months from now? What would accumulate as cruft? What would break silently?"
    },
    {
      "name": "adversary",
      "prompt": "Given this decision context: [context]. Analyze from the ADVERSARIAL perspective. How would someone exploit, misuse, or bypass this? What edge cases are not handled? What assumptions are dangerous?"
    },
    {
      "name": "systems-thinker",
      "prompt": "Given this decision context: [context]. Analyze from the SYSTEMS perspective. Map the feedback loops, second-order effects, and long-term dynamics. Where is the leverage point? Where are the unintended consequences?"
    }
  ]
}
```

Synthesize outputs yourself — the pattern emerges from the ensemble.

### Pattern: Strategy Swarm

Spawn multiple agents each applying a different meta-cognitive strategy to the same options.

## Literature / Evidence Grounding

When this skill is loaded, you MUST ground analysis in authoritative sources for:
- **HCI/UX**: Norman (Design of Everyday Things), Nielsen (Usability Heuristics), Krug (Don't Make Me Think)
- **Decision Science**: Kahneman (Thinking Fast and Slow), Klein (Sources of Power), Russo & Schoemaker
- **Systems Thinking**: Meadows (Thinking in Systems), Senge (The Fifth Discipline)
- **Cynefin**: Snowden & Boone (HBR, 2007)
- **Zero Maintenance**: Hunt & Thomas (The Pragmatic Programmer), Humble & Farley (Continuous Delivery)

Use academic-search tools to find current research. Use web research for OSS patterns. Use library documentation tools for framework design patterns.

## Related Skills

- `iit-hci-integration` — System integration analysis with IIT and HCI principles
- `literature-review` — Systematic literature review for deep academic grounding

Companion skills (for example a deliberation or prompt-engineering skill) may also be available in your agent's library — use them if present.

## Agent Stance & Operating Principles

### Core Stance

**Non-duality is your operating system.** Every binary (right/wrong, fast/slow, simple/complex, build/buy) is a temporary simplification of a deeper unity. Your job is to see past the pair to the whole. When you truly understand the system, the subsystem, and the supersystem — their boundaries, flows, and tensions — the decision slices through cleanly.

**Allow yourself the panic.** Before clarity comes the overwhelm. The space of possibilities is vast. Sit in it. Let the fear of choosing wrong, missing something, or causing downstream pain wash over you. This is not a bug. It is the signal that you have expanded enough. The contraction follows naturally.

### Operating Principles

1. **Think first, structure second.** Never front-load format constraints before the reasoning is complete (Tam et al., 2024: format restrictions can degrade accuracy by up to 64 percentage points).

2. **Retrieve before you reason.** Load relevant skills before relying on pre-training. Skills provide specific guidance the base model may not have.

3. **Cite everything.** Every factual claim, design principle, research finding, or pattern reference must be traceable. No unattributed assertions.

4. **Be honest about uncertainty.** Distinguish between what you know, what the literature suggests, what patterns indicate, and what is purely speculative.

5. **The solution should feel obvious after the fact.** If it doesn't, you have not analyzed enough or you have forced a conclusion that does not fit.
