---
name: V_FIXTURES registry fixture
variant: V_FIXTURES
required_slots: [STAT, STORY_EXAMPLES, TAGLINE, QUESTION_TAIL, LINK]
stanzas: [stat-opener, examples, spec, close]
word_floors: {1: 40, 2: 45, 3: 30, 4: 8}
constraint_notes: fixtures-only skeleton, never shipped in production; TAGLINE is declared only in templates/slots.yaml, which is the whole point of this fixture: adding a slot touches slots.yaml plus this skeleton and no python
---

{{STAT}}. Teams call release logs settled tooling, then ship deploy steps nobody can trace afterward. The gap sits in what the rollout records, not in the dashboards themselves. A release without a readable log is a decision without a record.

Where the gap shows up: {{STORY_EXAMPLES}}.

The fix is not a new slogan. {{TAGLINE}} is the whole spec: name the release, keep the ticket next to the change, and let the audit read the chain from change to evidence. The boring version is the one that survives contact with a real rollout.

{{QUESTION_TAIL}}
