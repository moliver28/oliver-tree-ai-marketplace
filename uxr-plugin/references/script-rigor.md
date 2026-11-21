# The hcd-researcher rigor rider (interview scripts)

The format policy every interview script follows lives in
`skills/interview-script/SKILL.md` (steps 5 to 8) and is enforced by
`scripts/review_checks.py`; this file holds only the rider appended to an
`hcd-researcher` dispatch when the researcher agent reviews an interview
script.

Append the following block verbatim to the `hcd-researcher` dispatch
prompt. It applies only to concept testing, usability, and onboarding
tour studies: for other study types the researcher agent is not
dispatched on scripts at all.

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
