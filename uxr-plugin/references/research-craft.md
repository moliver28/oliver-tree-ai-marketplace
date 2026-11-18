# Research craft

The quality bar `/uxr-plugin:uxr-new` holds during the interview: what makes
a key decision, a hypothesis, and a research question good, plus the method
table that maps the dominant question shape to a method, a sample, and a
session length. The interview proposes drafts; this file is the bar those
drafts must meet before the user sees them.

## Key decision

The decision is one sentence that names what will change because of the
study. It has an owner.

Good shapes:

- "Should X ship to GA, and under what conditions?"
- "Do we invest in A or B for the next release?"
- "Which of these three onboarding flows do we standardize on?"

Bad shapes (push back and tighten):

- "Understand how users feel about X" (a topic, not a decision; nothing
  changes based on the answer)
- "Validate X" (presupposes the answer; name what happens if the answer is
  no)
- Anything two sentences long, or with no owner

When the user gives a bad shape, propose a tightened version with an owner
and let them edit it.

## Hypotheses and assumptions

Propose 3 to 5 hypotheses and 2 to 3 assumptions, written as `Label. Claim.`

- `H1. Admins configure retention policies per workspace, not per tenant.`
- `A1. The existing import flow stays available during the migration.`

A hypothesis is a falsifiable claim about how the world works that, if it
turns out either way, changes the decision. Push back (with a better
rewrite) on claims that:

- are not falsifiable ("Users want a better experience"),
- mix two mechanisms in one claim ("Users miss the button because the label
  is unclear and mobile layouts hide it"),
- do not tie to the decision (nothing about the decision changes if the
  claim is false).

An assumption is something the team is treating as true today. Label it `A`
and keep it checkable in the same sessions.

## Research questions

Propose 3 to 6 open research questions (RQs). Open means the answer is not
yes or no: start with how, why, what, or which.

Show an RQ-to-hypothesis map, one line per RQ naming which hypothesis (or
hypotheses) it traces to. Drop an RQ that does not trace to any hypothesis,
and say you dropped it and why. A kept RQ that no hypothesis traces to
means a hypothesis is missing; propose the missing hypothesis instead.

## Method table

Read the RQs, pick the dominant shape, and take the row. Show: method,
reason, sample size, session length, investment level, research type, and
one alternative.

| Dominant RQ shape | Method | Sample | Length |
|---|---|---|---|
| How or why X happens | External Interviews | 8-12 per segment | 45-60 min |
| How internal stakeholders think about Y | Internal Interviews | 5-8 across roles | 30-45 min |
| Does design A or B work better for task T | Usability Test or Rapid Design Testing | 5-8 per design | 45-60 min |
| Which concept resonates | Concept Testing | 8-12 | 30-45 min |
| Performance on standard metrics | Usability Benchmark | 15-25 | 45-60 min |
| What proportion do or feel X | Survey | 100+, 300+ cross-segment | 5-10 min |
| How users organize a domain | Card Sort | 15-30 | 20-30 min |
| Can users find content in this structure | Tree Test | 30-50 | 10-20 min |
| What existing literature says | Desk Research | N/A | varies |
| What the feedback corpus says | Data Analytics | full corpus | varies |
| Mixed strategic synthesis | Desk Research + External Interviews | 8-12 + corpus | 4-8 weeks |
| Research alongside iterative design | Design Partnership | embedded | ongoing |

Rules:

1. Qualitative leads, quantitative supplements. Never default to a survey
   for a "why" question.
2. On a tie between two rows, pick the lighter method.

Method names must match the `fields.method` values in the config contract
(Internal Interviews, External Interviews, Survey, Usability Test,
Usability Benchmark, Rapid Design Testing, Concept Testing, Card Sort, Tree
Test, Desk Research, Data Analytics, Design Partnership, ReOp Work, Not
Sure). The two combination rows set `method` to both values; research type
(Generative, Evaluative, Strategic, Other) comes from the decision: a
shipping decision is Evaluative, a direction or opportunity question is
Generative or Strategic.

## Investment scale

One of `0`, `SM`, `M`, `LRG`, `XLG`, `XXLG` (the `fields.investment`
values):

| Level | Size |
|---|---|
| `0` | Holding ticket |
| `SM` | Desk research only, or up to 5 internal interviews |
| `M` | 6 to 10 external interviews, 5 to 8 usability sessions, a card sort, or a survey up to 500 |
| `LRG` | 8 to 12 interviews plus desk research |
| `XLG` | Multi-method, or 3 or more segments |
| `XXLG` | Multi-team, multi-quarter |

The method table drives the default level; mixed or multi-segment shapes
bump one level from the row's base.
