# Script format policy and the hcd-researcher rigor rider

Part 1 is the format policy every interview script follows; it condenses
what `skills/interview-script/SKILL.md` and `scripts/review_checks.py`
enforce, in one place for reviewers and dispatch prompts. Part 2 is the
rider appended to an `hcd-researcher` dispatch when the researcher agent
reviews an interview script.

## Part 1: Format policy

Structure (deterministic; the checker blocks on violations):

- One H1: `# Interview Script: <Study Title>`.
- Header lines in order: `<Tracker> Ticket:` (rename per tracker), optional
  `Prototype Link:`, `UXR:`, `PD and-or PM:`. Then the metadata lines
  `**Time budget**: N min`, `**Method**`, `**Date drafted**`,
  `**Drafted from**`.
- H2 sections in order: `## Research Questions`, `## Moderator Notes`,
  `## Script` (with `### N. Title (M min)` sections), then
  `## Research Question → Script Question Map` with columns
  `| RQ | Phase | Technique | Script Qs | Stakeholder Value |`, then
  `## Quality Check`, then when they apply `## Critical-to-Success`,
  `## Quant Measures`, `## Tour Implementation Capture`, and finally
  `## Leadership Read` (3 to 5 bullets).
- Scripted minutes total at most budget minus buffer (defaults: 60 minus 8,
  so 52). The checker blocks a total over that line.

Question rules:

- No yes or no openers; a main question never starts with do, does, did,
  is, are, was, were, can, could, will, would, has, or have.
- At most 20 words per main question; probes are exempt.
- Reading grade 8 to 10 on spoken text and questions.
- No leading, double-barreled, assumptive, or loaded wording; at most one
  negation per main question.
- Open broad question first in each section; the first design question is
  an open reaction; probes sit under their main question; laddering at
  most 3 rungs.
- Moderator cues read `*[Moderator: ...]*`.

Format grammar:

- Spoken text: `**Read Aloud:**` then an italic block.
- Unspoken notes: `- Note: ...`.
- Main questions numbered `N.`; probes lettered and indented `   a.`.
- Conditionals: `N. [criteria] Question?` (always ends in a question mark).
- Survey items: `**[LABEL]. **` then the item text, copied verbatim from
  `references/quant-measures.md`.
- Navigation as a literal path: `Go to 'Settings' > Click 'Integrations'`.

Never use an em dash or en dash anywhere in the script.

## Part 2: hcd-researcher rider

Append the following block verbatim to the `hcd-researcher` dispatch prompt
when the researcher agent reviews an interview script. It applies only to
concept testing, usability, and onboarding tour studies: for other study
types the researcher agent is not dispatched on scripts at all.

```text
Rider: interview script rigor (references/script-rigor.md)

The target artifact is an interview script. In addition to your standard
lens, check:

1. Sequence: the sections move Discover Problem, Validate Problem,
   Discover Solution, Validate Solution, and every research question in
   the map has at least one script question that can answer it.
2. Load: the scripted minutes fit the session length with buffer, and no
   section asks the participant to hold more than one artifact or idea at
   a time.
3. Critical moments: the script schedules the observation each hypothesis
   depends on (the incident retelling, the artifact reaction, the
   comprehension check) at the moment the participant can actually show
   it, and the quant items, when present, sit after the exposure they
   measure.

Then return one extra section after your findings, formatted to paste into
the script unchanged:

Critical-to-Success
- <3 to 5 bullets, each one sentence, each something that must be true in
  the room for this study to answer its decision. Name the section it
  depends on.>
```

The requesting command pastes that block under the script's
`## Critical-to-Success` heading without rewriting it. If the researcher
returns "None", the section reads: `## Critical-to-Success` followed by
`- None flagged by hcd-researcher this draft.` and the loop notes the
decline in one line.
