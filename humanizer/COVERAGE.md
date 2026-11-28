# Coverage contract

Contract version: 1.0.0 (2026-11-28). State verified against the shipped code at
base commit d8f476d (the humanizer 1.5.0 line, the wave G6 tip).

This file maps every catalog pattern to a coverage status. It is the drift
anchor for the pattern register: `scripts/verify.py` re-checks every count and
every family in this file against the compiled code. The register in
`hooks/voice_tells.py` is the mechanical mirror of the 35-pattern authority
named in the "Voice-correction authority" section of `SKILL.md`. When the code
moves a count or a family name, update this file in the same commit. The
drift check lives at `tests/humanizer/coverage_contract_check.py`.

## Status vocabulary

- implemented: shipped mechanical code can flag the pattern at delivery time.
- contextual-only: the rewrite contract addresses the pattern; no mechanical
  rule can fire a fail line for it.
- out of scope: the plugin does not address the pattern. No catalog pattern
  holds this status today.

## Plain-language counts

- Compiled register patterns: 98 (ninety-eight)
- Exemplar classes: 22 (twenty-two)
- Compiled register families: 31 (thirty-one)
- Catalog patterns: 35 (thirty-five)
- ASD-STE100 rules: 6 (six)
- Battery families: 4 (four)
- Gate marker words: 20 (twenty)

In words: the register carries ninety-eight patterns in thirty-one families.
Twenty-two catalog rows say implemented, thirteen say contextual-only, and
none says out of scope. The gate adds six plain-language rules and four
battery families to that register.

## Catalog patterns (35)

| Pattern | Family | Status | Evidence |
|---|---|---|---|
| 1. Undue emphasis on significance, legacy, and broader trends | humanizer 1 | implemented | humanizer/hooks/voice_tells.py:216-220 |
| 2. Undue emphasis on notability and media coverage | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 3. Superficial analyses with -ing endings | skill-side | contextual-only | humanizer/SKILL.md:31; humanizer/hooks/gate.py:125-127 |
| 4. Promotional and advertisement-like language | humanizer 4 | implemented | humanizer/hooks/voice_tells.py:221-223 |
| 5. Vague attributions and weasel words | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 6. Outline-like challenges-and-prospects sections | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 7. Overused AI-vocabulary words | banned | implemented | humanizer/hooks/voice_tells.py:140-157 |
| 8. Avoidance of is and are (copula avoidance) | humanizer 8 | implemented | humanizer/hooks/voice_tells.py:224; humanizer/hooks/voice_tells.py:109-110 |
| 9. Negative parallelisms and tailing negations | negative parallelism | implemented | humanizer/hooks/voice_tells.py:102-107; humanizer/hooks/voice_tells.py:111-112 |
| 10. Rule-of-three overuse | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 11. Elegant variation (synonym cycling) | skill-side | contextual-only | humanizer/SKILL.md:31; humanizer/hooks/voice_tells.py:905-936 |
| 12. False ranges | humanizer 12 | implemented | humanizer/hooks/voice_tells.py:207 |
| 13. Passive voice and subjectless fragments | S3 | implemented | humanizer/hooks/gate.py:84; humanizer/hooks/gate.py:130-137 |
| 14. Em dash overuse | em dash | implemented | humanizer/hooks/voice_tells.py:99-100 |
| 15. Overuse of boldface | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 16. Inline-header vertical lists | humanizer 16 | implemented | humanizer/hooks/voice_tells.py:203 |
| 17. Title case in headings | humanizer 17 | implemented | humanizer/hooks/voice_tells.py:204 |
| 18. Emoji decoration | humanizer 18 | implemented | humanizer/hooks/voice_tells.py:205 |
| 19. Curly quotation marks | humanizer 19 | implemented | humanizer/hooks/voice_tells.py:201 |
| 20. Collaborative communication artifacts | chatbot | implemented | humanizer/hooks/voice_tells.py:164-166 |
| 21. Knowledge-limit disclaimers and guesses | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 22. Sycophantic or servile tone | humanizer 22 | implemented | humanizer/hooks/voice_tells.py:170-174 |
| 23. Filler phrases | filler | implemented | humanizer/hooks/voice_tells.py:127-133 |
| 24. Excessive hedging | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 25. Generic positive conclusions | humanizer 25 | implemented | humanizer/hooks/voice_tells.py:176-179 |
| 26. Hyphenated word pair overuse | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 27. Persuasive authority tropes | humanizer 27 | implemented | humanizer/hooks/voice_tells.py:181-183; humanizer/hooks/voice_tells.py:114-117 |
| 28. Signposting and announcements | humanizer 28 | implemented | humanizer/hooks/voice_tells.py:185-189; humanizer/hooks/voice_tells.py:124-126 |
| 29. Fragmented headers | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 30. Writing about the previous version | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 31. Forced punchlines and dramatic fragments | skill-side | contextual-only | humanizer/SKILL.md:31 |
| 32. Rhetorical questions answered immediately | humanizer 32 | implemented | humanizer/hooks/voice_tells.py:191-193 |
| 33. Sentence-opener tics | humanizer 33 | implemented | humanizer/hooks/voice_tells.py:195-197 |
| 34. Reassurance leftovers | humanizer 34 | implemented | humanizer/hooks/voice_tells.py:199 |
| 35. Aphorism budget (the pattern-35 kicker budget) | L10-19 | implemented | humanizer/learn/voice_battery_core.py:283-342; humanizer/hooks/gate.py:170-180 |

Notes on the partial scopes the statuses carry: pattern 3 rides the S5
-ing-chain rule and the pattern-1 importance phrases only in part, so it
stays contextual-only. Pattern 13 rides the S3 passive-voice rule for its
passive half; the subjectless-fragment half stays rewrite-contract. Pattern
11 ships the chunk-grain advisory signal (`cycling_signals`), which never
fires a fail line until the owner calibrates its bands in the state file.
Pattern 35 is a budget counter, not a pattern match: `aphorism_budget_hits`
enforces the skill's own budget (at most one kicker per section, at most
three per piece), with the learned-state aphorism band as the approved
override. Pattern 15 (boldface) has only the pattern-16 list-item neighbor,
so it stays contextual-only.

## Register families outside the catalog numbering (16)

These families come from the de-personalized register and the personal-voice
hard bans. The family column is the exact `_family()` classifier output over
the embedded register; the drift check compares these names byte for byte.

| Family | Status | Evidence |
|---|---|---|
| em dash | implemented | humanizer/hooks/voice_tells.py:99 |
| spaced double hyphen used as a dash | implemented | humanizer/hooks/voice_tells.py:100 |
| negative parallelism | implemented | humanizer/hooks/voice_tells.py:102-105 |
| the 'less about X, more about Y' contrast cliché | implemented | humanizer/hooks/voice_tells.py:106-107 |
| copula | implemented | humanizer/hooks/voice_tells.py:109-110 |
| 'not a X, but a Y' contrast construction | implemented | humanizer/hooks/voice_tells.py:111-112 |
| persuasive | implemented | humanizer/hooks/voice_tells.py:114-117 |
| blog cliché | implemented | humanizer/hooks/voice_tells.py:118-123 |
| signpost | implemented | humanizer/hooks/voice_tells.py:124-126; humanizer/hooks/voice_tells.py:163 |
| filler | implemented | humanizer/hooks/voice_tells.py:127-133 |
| reassurance | implemented | humanizer/hooks/voice_tells.py:135-138 |
| banned | implemented | humanizer/hooks/voice_tells.py:140-157 |
| resume-slop | implemented | humanizer/hooks/voice_tells.py:158-161 |
| slop | implemented | humanizer/hooks/voice_tells.py:162 |
| chatbot | implemented | humanizer/hooks/voice_tells.py:164-166 |
| voice ban | implemented | humanizer/hooks/voice_tells.py:209-213 |

## ASD-STE100 rules (6)

The gate carries six plain-language rules. Both surfaces enforce them; the
resume profile exempts bullets and labeled section lines from S1 and filters
the pattern-16 and pattern-17 formatting families (`gate.py:120-121`,
`gate.py:323-330`).

| Rule | Family | Status | Evidence |
|---|---|---|---|
| S1. Sentence length (no sentence over 20 words) | ASD-STE100 | implemented | humanizer/hooks/gate.py:79; humanizer/hooks/gate.py:122-124 |
| S2. Paragraph length (no paragraph over 3 sentences) | ASD-STE100 | implemented | humanizer/hooks/gate.py:80; humanizer/hooks/gate.py:110-113 |
| S3. Passive voice | ASD-STE100 | implemented | humanizer/hooks/gate.py:84; humanizer/hooks/gate.py:130-137 |
| S4. Inflated verb chains | ASD-STE100 | implemented | humanizer/hooks/gate.py:83; humanizer/hooks/gate.py:130-137 |
| S5. -ing chains | ASD-STE100 | implemented | humanizer/hooks/gate.py:125-127 |
| S6. Approved-word discipline | ASD-STE100 | implemented | humanizer/hooks/gate.py:82; humanizer/hooks/gate.py:138-140 |

## Battery families (4)

The battery report carries 85 rows in full (79 per-text spec rows, 3 corpus
rows, 3 method rows; the suite pins the total). Four battery families touch
the coverage surface this contract tracks: the gate marker family, the
family-35 budget row, and the two band-gated advisory method rows of wave
H-C.

| Family | Status | Evidence |
|---|---|---|
| L10-1. Machine marker words | implemented | humanizer/learn/voice_battery_core.py:44-46; humanizer/hooks/gate.py:183-220 |
| L10-18. Chunk-pair divergence (the family-11 signal) | contextual-only | humanizer/hooks/voice_tells.py:905-936; humanizer/hooks/gate.py:280-287 |
| L10-19. Aphorism shapes against the budget (the family-35 counter) | implemented | humanizer/learn/voice_battery_core.py:283-342; humanizer/hooks/gate.py:170-180 |
| L10-20. Compression profile | contextual-only | humanizer/learn/voice_battery_core.py:205-225; humanizer/hooks/gate.py:276-289 |

L10-18 and L10-20 stay contextual-only because both are band-gated advisory
fields: absent learned bands mean no output and no fail line, so no
mechanical rule can fire for them today. The battery's other 81 rows are
report-only measures with their own spec pins in
`tests/humanizer/test_voice_battery.py`; they measure, they never gate.

## Drift law

`scripts/verify.py` enforces this file against the compiled state on every
run. The check requires: the count block above to equal the compiled totals;
exactly the 35 catalog rows, ids 1 to 35, with a status from the vocabulary
and at least one resolvable file:line pointer per row; every compiled
`humanizer N` family to have its catalog row marked implemented; every
implemented row to point into shipped plugin code and to name a compiled
family, an STE rule id, or a battery family id; the register-family names to
match the `_family()` classifier output byte for byte in both directions;
exactly S1 to S6; and exactly the four battery family ids. Removing a row,
editing a count, flipping a mirrored status, or renaming a family fails the
gate deterministically.

## Sources

The seed content is the fourteen-bar coverage walk of 2026-11-27 (the issue
#144 walk artifact), re-verified row by row against the shipped code at the
base commit. The catalog names follow the lineage the authority section
names: the upstream humanizer skill (MIT; see the PROVENANCE.md row) names
patterns 1 to 29 at its v2.5.1 vintage and patterns 30 to 31 at its
continuation vintages; patterns 32 to 35 carry the names our own register
labels and SKILL.md use. The private master skill stays the naming
authority, and attribution stays in PROVENANCE.md.
