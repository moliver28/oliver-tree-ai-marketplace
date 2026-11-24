## Checklist B — Quantitative surveys
Pipeline: B1 → B2 → B3 → B6 → B7 → B4 → B5

### B1 Planning
Executor: llm
Summary: planning records the research questions, the error classes, the survey tool mapping, and the workflow that writes the instrument.

- [ ] B1.1 [llm] Research questions and target population are stated, and each research question names the product decision it informs. Evidence: spec JSON `research_questions` + `decision` fields. (Source: AAPOR Best Practices planning stage; Patton 2008 for the decision tie; decision tie = MO ruling 2026-11-22.)
- [ ] B1.2 [draft] Error thinking recorded: which Total Survey Error classes this design accepts or controls. Evidence: spec JSON. (Source: Groves 2010, POQ 74(5).)
- [ ] B1.3 [llm] Onboarding learns the survey tool in use (Qualtrics and others) and records the research-question to question-type to engagement mapping per type. Evidence: tool-and-mapping note in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22; the onboarding feature rides a follow-up wave — the checklist documents the step now.)
- [ ] B1.4 [llm] The survey is produced by the plugin's own survey-creation skill (the designed counterpart of `skills/interview-script`), which runs the same writing workflow: input needs, process, anti-pattern rule check by id, quality iteration, review with MO. Evidence: workflow record in `scripts/<survey>.md`. (Source: MO round-2 rulings 2 and 8; the survey skill is a build-wave dependency designed in this note.)

### B2 Sample design
Executor: draft
Summary: the sample frame, the sampling method, and the screeners are stated before build.

- [ ] B2.1 [draft] Sampling frame stated and coverage gap named. Evidence: spec JSON. (Source: Groves 2010, coverage error.)
- [ ] B2.2 [draft] Sampling method stated (random, quota, opt-in) and screeners listed. Evidence: spec JSON. (Source: AAPOR Best Practices sample stage.)

### B3 Instrument
Executor: llm
Summary: workflow mapping - input needs = B1.1 to B1.4; process = B3.8 to B3.12 and B3.2 (build-order law); anti-pattern rules by registry id = B3.1, B3.5 to B3.7; iterate = B3.4 and B3.9; review with MO = B6.

- [ ] B3.1 [llm] Question wording is neutral: no leading phrasing. Evidence: question list in `scripts/<survey>.md`. (Source: Pew Research Center, Writing Survey Questions; Krosnick & Presser 2010, pp. 263–313; registry ids X-U2, X-S1.)
- [ ] B3.2 [llm] Questions grouped by topic, logical order, simple first; demographics at the end. Evidence: `scripts/<survey>.md`. (Source: Pew + AAPOR; registry id R-S2.)
- [ ] B3.3 [llm] Respondent burden capped: questionnaire short, and few hard, sensitive, or open questions. Evidence: `scripts/<survey>.md`. (Source: AAPOR Best Practices, "Keep respondent burden low by keeping questionnaires and individual questions short ..."; Dillman, Smyth & Christian 2014, Tailored Design Method 4th ed.)
- [ ] B3.4 [draft] Pretest or cognitive-interview pass recorded before fielding. Evidence: pilot note. (Source: Pew pretest guidance; Willis 2005, Cognitive Interviewing, SAGE; AAPOR Best Practices pilot-test sentence.)
- [ ] B3.5 [llm] Each question supports the four-stage response process: comprehension, retrieval, judgment, response mapping — recall burden bounded, and answer categories fit the judgment asked. Evidence: instrument-review note in `scripts/<survey>.md`. (Source: Tourangeau, Rips & Rasinski 2000, The Psychology of Survey Response, Cambridge University Press.)
- [ ] B3.6 [llm] Satisficing guards hold: no double-barreled items, balanced scales, bounded list lengths, simple task instructions. Evidence: question list in `scripts/<survey>.md`. (Source: Krosnick 1999, Annual Review of Psychology 50:537–567; Krosnick & Presser 2010; registry ids X-S1, X-S2.)
- [ ] B3.7 [draft] Sensitive items carry a stated mitigation: indirect wording or a self-administered mode for the sensitive block. Evidence: sensitive-block note in `scripts/<survey>.md`. (Source: Tourangeau & Yan 2007, Psychological Bulletin 133(5):859–883.)
- [ ] B3.8 [llm] No question asks the respondent for data the org already holds in other fields; the join and embed fields are named for the analysis. Evidence: join-field list in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22; AAPOR Best Practices, "Is a survey alone enough to answer the research questions, or will you also need to use other types of data (e.g., administrative records)?"; registry ids R-S5, X-U1.)
- [ ] B3.9 [llm] Each core question is designed through two to five alternatives; respondent efficiency picks the winner. Evidence: kept-alternatives section in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22; registry id R-S3.)
- [ ] B3.10 [llm] Conditional logic and routing are planned before build: every skip path mapped, no dead ends, irrelevant questions hidden. Evidence: routing map in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22; echo Pew methods guidance on question order — practitioner tier; registry id R-S4.)
- [ ] B3.11 [llm] Every item feeds at least one planned segmentation or grouping path toward the higher-level gestalt insight. Evidence: segmentation map in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22; registry id R-S5.)
- [ ] B3.12 [llm] Every research question is covered by at least one survey question; the research-question-to-question map is recorded. Evidence: coverage map in `scripts/<survey>.md`. (Source: MO ruling 2026-11-22 — the Script↔RQ law names script/survey; echo AAPOR planning stage; registry ids R-S6, R-U2.)

### B6 Stakeholder review lenses (BEFORE fielding)
Executor: human
Summary: PM, PD, Eng, and optional product leadership review the survey before fielding starts; the harness records the entries.

- [ ] B6.1 [human] Product Management reviewed the survey against its needs and the decisions it informs, before fielding starts. Evidence: one PM entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.)
- [ ] B6.2 [human] Product Design reviewed the survey against its needs and the decisions it informs, before fielding starts. Evidence: one PD entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.)
- [ ] B6.3 [human] Engineering reviewed the survey against its needs and the decisions it informs, before fielding starts. Evidence: one Eng entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.)
- [ ] B6.4 [human] Product leadership reviewed the survey against its needs and the decisions it informs, before fielding starts. Evidence: one leadership entry in `stakeholder-review.md`. (Source: MO ruling 2026-11-22 + round-2 ruling 7; practitioner echo NN/g 2017.) (optional)

### B7 Pre-launch
Executor: draft
Summary: the report pipeline and the team rehearse reporting on simulated data before launch.

- [ ] B7.1 [draft] Reporting practice with simulated data runs before launch: the report pipeline renders topline, dispositions, and the limitations section on simulated responses, and the team rehearses reporting the research questions against the decisions. Evidence: simulated-data report in `deliverables/practice-report.md`. (Source: MO ruling 2026-11-22; echo AAPOR Best Practices pilot-test sentence — "all survey procedures (e.g., recruiting respondents, administering the survey, cleaning data) work as intended".)

### B4 Fielding
Executor: llm
Summary: dispositions and nonresponse handling are tracked during fielding.

- [ ] B4.1 [llm] Dispositions tracked with AAPOR disposition codes; response rate computed with a stated RR formula. Evidence: fielding log. (Source: AAPOR Standard Definitions.)
- [ ] B4.2 [draft] Nonresponse handling stated: contact sequence (prenotice, invitation, reminders), incentives, replacement. Evidence: spec / fielding log. (Source: AAPOR fielding stage; Dillman, Smyth & Christian 2014 — the multiple-contact sequence.)

### B5 Reporting and synthesis
Executor: llm
Summary: topline, disclosures, limitations, and the synthesis record close the study.

- [ ] B5.1 [llm] Exact question wording and topline published. Evidence: deliverable. (Source: Pew transparency guidance.)
- [ ] B5.2 [llm] Response rate and dispositions disclosed. Evidence: report. (Source: AAPOR reporting stage.)
- [ ] B5.3 [llm] Limitations section maps the accepted error classes (coverage, sampling, nonresponse, measurement, processing). Evidence: report. (Source: Groves 2010.)
- [ ] B5.4 [llm] The synthesis record exists and names each research question's answer from the collected data, and states whether the decision is informed. Evidence: `analysis/synthesis.md`. (Source: MO round-2 ruling 6, mirrored from A5.1; the decision-trace lens is plugin law in agents/hcd-researcher.md review lens 1.)
- [ ] B5.5 [draft] Next steps and recommendations for stakeholders are written FROM the persistent stakeholder, org, and product info the system keeps: the spec decision, the tracker PM/PD/Eng fields, the config org and routing identity, and the researcher review journal digest (`scripts/researcher_state.py digest`). Evidence: recommendations section in `analysis/synthesis.md`. (Source: MO round-2 ruling 6, mirrored from A5.2; Patton 2008 — intended users and intended uses.)
- [ ] B5.6 [llm] Other previous or ongoing research, usage analytics, and other sources of info are identified to up-level or contextualize the insights. Evidence: sources section in `analysis/synthesis.md`. (Source: MO round-2 ruling 6, mirrored from A5.3; echo AAPOR Best Practices — "Is a survey alone enough ... other types of data (e.g., administrative records)?") (optional)
- [ ] B5.7 [llm] Web search grounds the synthesis: claims resting on outside evidence carry two authoritative sources, or the exact source "insufficient external evidence"; outside claims cite registered sources (registry entries in `references/research-sources.md`). Evidence: grounding note in `analysis/synthesis.md`. (Source: MO round-2 ruling 6 + the Unit 6 grounding law, mirrored from A5.4; the two-source rule is plugin law in agents/hcd-researcher.md review lens 3.)
