## Checklist A — Qualitative interviews
Pipeline: A1 → A2 → A6 → A7 → A3 → A4 → A5

### A1 Design, research questions, script
Executor: llm
Summary: one workflow produces the script - input needs, optional concept pass, conditional search before mapping, the research-question map, rules by id, iterate, MO review.

- [ ] A1.1 [llm] Research questions are stated in the spec, and each research question names the product decision it informs, before script work starts. Evidence: spec JSON `research_questions` + `decision` fields. (Source: Kallio et al. 2016, J Adv Nurs 72(12):2954–2965, phase 1 prerequisites; Patton 2008, Utilization-Focused Evaluation 4th ed. — intended users and intended uses; decision tie = MO ruling 2026-11-22.)
- [ ] A1.2 [llm] The script is produced by the plugin's own script-creation skill (`skills/interview-script`), which runs the writing workflow end to end: input needs, process, anti-pattern rule check by id, quality iteration, review with MO. Evidence: `scripts/<script>.md` carries the research-question-to-script map and the workflow record. (Source: MO round-2 rulings 2 and 4; prior grounding: MO Write-a-Script automation, method summary recorded verbatim in track-53-checklist-grounding.md:104-112.)
- [ ] A1.3 [llm] The script covers opening, warm-up, core themes, probes, and closing; questions use the participants' own terms and read from the participant perspective. Evidence: `scripts/<script>.md`. (Source: Kallio et al. 2016 + COREQ item 11; participant-wording half = MO ruling 2026-11-22; registry ids R-I5.)
- [ ] A1.4 [llm] Verbatim capture mandate active: the model never invents, infers, or fabricates participant answers; missing info = ask verbatim or record the gap. Evidence: standing mandate (MO ruling 2026-11-21). No source needed (plugin law). (Source: plugin law.)
- [ ] A1.5 [llm] The research-question map carries, for every research question, its Double Diamond phase tag (Discover Problem, Validate Problem, Discover Solution, Validate Solution) and its matched technique. Evidence: RQ map in `scripts/<script>.md`. (Source: MO Write-a-Script automation, MO ruling 2026-11-22; the same sequence is plugin law in references/script-rigor.md; round-2 merge of round-1 items A1.5 and A1.6 — one map, one probe.)
- [ ] A1.6 [llm] Before any web search, the optional deeper writing pass applies the registry concept families by id — survey, interview, HCI, academic — and records the ids applied. Evidence: concept-pass line in `scripts/<script>.md`. (Source: MO round-2 ruling 5, part 1; the families live in references/writing-rules.md.) (optional)
- [ ] A1.7 [llm] The writing workflow holds: input needs recorded before writing; anti-pattern rules checked by registry id; quality iteration logged in the Quality Check section; the finished script goes to MO review. Evidence: inputs, rules-applied, and Quality Check lines in `scripts/<script>.md`. (Source: MO round-2 ruling 4; the Quality Check loop is plugin law in skills/interview-script/SKILL.md step 9.)
- [ ] A1.8 [llm] Validation law holds: every research question is covered by at least one script question, and the scripted minutes fit the session length with buffer. Evidence: coverage check + time-allocation line in `scripts/<script>.md`. (Source: MO Write-a-Script automation (validation law), MO ruling 2026-11-22; same law in references/script-rigor.md; registry ids R-I4, X-U2.)
- [ ] A1.9 [llm] The grounded web search runs BEFORE research-question mapping, and only when gaps or room for efficiency exist; the search consults registered sources page-first (registry entries in `references/research-sources.md`), and found gaps enter the input needs or the recorded gap list. Evidence: search note linked from `scripts/<script>.md`. (Source: MO round-2 ruling 5, part 2 + the Unit 6 grounding law; supersedes the round-1 blind-spot position, which is retired.)
- [ ] A1.10 [draft] Pilot test of the script is recorded before fielding. Evidence: pilot note. (Source: Kallio et al. 2016, phase 4; MO ruling 2026-11-22 makes it optional.) (optional)

### A2 Participants and ethics
Executor: llm
Summary: sampling and consent are stated and recorded before recruitment closes.

- [ ] A2.1 [draft] Sampling method and participant criteria stated. Evidence: spec JSON. (Source: COREQ item 8.)
- [ ] A2.2 [llm] Consent to recruit is assumed given; the script carries the reminder and the consent language the participant hears. Evidence: consent section in `scripts/<script>.md`. (Source: MO ruling 2026-11-22; echo COREQ item 8.)
- [ ] A2.3 [human] Recording disclosed to participants; consent for recording recorded. Evidence: recruitment/participants.md. (Source: COREQ item 13.)

### A6 Stakeholder review lenses (BEFORE data collection)
Executor: human
Summary: PM, PD, Eng, and optional product leadership review the script before data collection starts; the harness records the entries.

- [ ] A6.1 [human] Product Management reviewed the script against its needs and the decisions it informs, before data collection starts. Evidence: one PM entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017, "How to Collaborate with Stakeholders in UX Research".)
- [ ] A6.2 [human] Product Design reviewed the script against its needs and the decisions it informs, before data collection starts. Evidence: one PD entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.)
- [ ] A6.3 [human] Engineering reviewed the script against its needs and the decisions it informs, before data collection starts. Evidence: one Eng entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.)
- [ ] A6.4 [human] Product leadership reviewed the script against its needs and the decisions it informs, before data collection starts. Evidence: one leadership entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.) (optional)

### A7 Pre-launch practice
Executor: draft
Summary: the team practices reporting the research questions against the decisions before launch.

- [ ] A7.1 [draft] Before launch, the team practices reporting the research questions against the decisions and the overall themes. Evidence: practice note in `deliverables/practice-report.md`. (Source: MO ruling 2026-11-22.) (optional; harness-nudged)

### A3 Script quality and field
Executor: llm
Summary: session facts, research-alignment notes, and the saturation call are recorded during field work.

- [ ] A3.1 [llm] Duration and count of interviews recorded. Evidence: spec / journal. (Source: COREQ item 12.)
- [ ] A3.2 [llm] Field notes record how each session informs the research questions and the decisions. Evidence: research-alignment block in `interviews/<slug>-<date>-summary.md`. (Source: MO ruling 2026-11-22; the alignment block is already plugin law in templates/workspace/interviews/README.md; echo COREQ item 14.)
- [ ] A3.3 [draft] Saturation decision recorded (stop rule stated, for example two consecutive interviews with no new themes). Evidence: analysis notes. (Source: COREQ item 20.)

### A4 Data and analysis
Executor: llm
Summary: transcripts land and get verified; theme analysis runs in one declared mode; quotes keep full provenance.

- [ ] A4.0 [llm] Each session transcript is found at its source and downloaded into `interviews/raw-transcripts/` before analysis; the saved path is recorded in the session summary. Evidence: file in `interviews/raw-transcripts/` + path line in `interviews/<slug>-<date>-summary.md`. (Source: MO ruling 2026-11-22; the onboarding step that asks for and saves the transcript path rides a follow-up wave — the checklist documents the step now.)
- [ ] A4.1 [llm] Transcripts verified against recordings. Evidence: transcript-verification note. (Source: COREQ item 13.)
- [ ] A4.2 [draft] Theme analysis runs in one declared mode — inductive, deductive, or hybrid; with or without research-question input — chosen to fit one researcher with one agentic harness (bounded, structured passes; LLM-inference-efficient). Evidence: mode line in `analysis/codes.md`. (Source: Braun & Clarke 2006, Qualitative Research in Psychology 3(2):77–101 — inductive vs deductive; Fereday & Muir-Cochrane 2006, Int J Qualitative Methods 5(1):80–92 — hybrid; one-researcher efficiency = MO ruling 2026-11-22.)
- [ ] A4.3 [llm] Quotations are copied from transcripts verbatim, with full provenance (session, transcript location, timestamp or line) so quote context is findable. Evidence: standing mandate (MO ruling 2026-11-21) + provenance refs on quotes; aligns with COREQ item 25. (Source: MO rulings 2026-11-21 and 2026-11-22; COREQ item 25.)

### A5 Data synthesis
Executor: llm
Summary: take the data you have, answer each research question, inform the decision; write stakeholder recommendations from the persistent info; ground with web search.

- [ ] A5.1 [llm] The synthesis record exists and names each research question's answer from the collected data, and states whether the decision is informed. Evidence: `analysis/synthesis.md`. (Source: MO round-2 ruling 6; the decision-trace lens is plugin law in agents/hcd-researcher.md review lens 1.)
- [ ] A5.2 [draft] Next steps and recommendations for stakeholders are written FROM the persistent stakeholder, org, and product info the system keeps: the spec decision, the tracker PM/PD/Eng fields, the config org and routing identity, and the researcher review journal digest (`scripts/researcher_state.py digest`). Evidence: recommendations section in `analysis/synthesis.md`. (Source: MO round-2 ruling 6; Patton 2008 — intended users and intended uses.)
- [ ] A5.3 [llm] Other previous or ongoing research, usage analytics, and other sources of info are identified to up-level or contextualize the insights. Evidence: sources section in `analysis/synthesis.md`. (Source: MO round-2 ruling 6.) (optional)
- [ ] A5.4 [llm] Web search grounds the synthesis: claims resting on outside evidence carry two authoritative sources, or the exact source "insufficient external evidence"; outside claims cite registered sources (registry entries in `references/research-sources.md`). Evidence: grounding note in `analysis/synthesis.md`. (Source: MO round-2 ruling 6 + the Unit 6 grounding law; the two-source rule is plugin law in agents/hcd-researcher.md review lens 3.)
