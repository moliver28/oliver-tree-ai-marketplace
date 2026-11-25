# Writing rules registry

The writing law of the plugin in one file. The skills (`interview-script`,
`survey-script`) and the review loop apply rules by id. Checklist items
reference ids. MO's future expansion edits this one file.

Numbering law: ids are stable forever. Appending never renumbers. A retired
rule keeps its id and gains a `deprecated:` note in place. A new rule takes
the next unused number in its family. Nothing restates rule text inline.

Families: R-U and X-U are universal. R-I and X-I are interview. R-S and X-S
are survey. R-H is HCI. R-A is academic. R means requirement; X means
anti-pattern. The artifact kinds: script (interview), survey (instrument).

## Universal requirements (R-U)

- R-U1: Inputs — needs, research questions, decision — are recorded before writing starts.
- R-U2: Every question traces to a research question, and every research question traces to the decision.
- R-U3: The artifact passes the review loop before it leaves draft state.
- R-U4: The finished artifact goes to MO review before it is declared final.

## Universal anti-patterns (X-U)

- X-U1: Asking a respondent for data the org already holds in other fields.
- X-U2: Leading, double-barreled, or loaded wording.
- X-U3: A question no answer can act on — it feeds no decision and no insight.

## Interview requirements (R-I)

- R-I1: Every script question carries its phase tag: Discover Problem, Validate Problem, Discover Solution, Validate Solution.
- R-I2: Every sequenced research question is matched to at least one interview technique.
- R-I3: No yes/no openings; no more than 20 words per main question; grade 8 to 10 reading level.
- R-I4: Coverage law — every research question covered by at least one script question; scripted minutes fit the session with buffer.
- R-I5: The participants' own terms; questions read from the participant perspective.

## Interview anti-patterns (X-I)

- X-I1: More than one negation per main question; assumptive wording.
- X-I2: A section over 15 minutes with no reset transition.

## Survey requirements (R-S)

- R-S1: Neutral wording; balanced scales.
- R-S2: Topic-grouped logical order; simple first; demographics at the end.
- R-S3: Burden cap; each core question designed through two to five alternatives; respondent efficiency picks.
- R-S4: Routing planned before build — every skip path mapped, no dead ends.
- R-S5: Join and embed fields named; every item feeds at least one segmentation path.
- R-S6: Coverage law — every research question covered by at least one survey question.

## Survey anti-patterns (X-S)

- X-S1: Double-barreled or double-negative items.
- X-S2: Unbounded list lengths and long scales that invite satisficing.

## HCI requirements (R-H)

- R-H1: Participant respect — no leading wording; the study only asks what participants can answer.
- R-H2: Method fit — the method answers what the question asks.

## Academic requirements (R-A)

- R-A1: Claims resting on outside evidence carry two authoritative sources, or the exact source "insufficient external evidence".
- R-A2: Claims are falsifiable; every stance line says why in one line.

## Seed provenance

R-U comes from the MO round-2 workflow law. R-I and X-I come from the
Write-a-Script summary and `skills/interview-script/SKILL.md` steps 6 and 5.
R-S and X-S come from the B3 items and their Pew, AAPOR, Krosnick,
Tourangeau, and Dillman sources. R-H comes from the hcd-gate residual
checklist (`prompts/hcd-gate/fragments/residual-checklist.md`) and the
hcd-researcher lens. R-A comes from the hcd-researcher evidence-honesty
lens. Nothing in this file is invented; every rule quotes law the plugin or
MO already holds.
