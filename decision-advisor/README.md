# decision-advisor

Decision-analysis plugin for one-way-door questions: architecture, migrations, permission models, any choice expensive to reverse. Ships the `decision-advisor` agent and the `/decide` command; both run the meta-decision pipeline (Expand, Contract, Embed) and return a structured decision record with evidence, trade-offs, rationale, and a maintenance horizon.

## Install

```
claude plugin marketplace add moliver28/oliver-tree-ai-marketplace
claude plugin install decision-advisor@oliver-tree-ai-marketplace
```

Updates (run after any release note):

```
claude plugin update decision-advisor@oliver-tree-ai-marketplace
```

## Dependency

Pairs with the `engineering/meta-decision` skill in this marketplace (published at `engineering/meta-decision/SKILL.md`, 0.2.0). The agent loads whichever copy of the skill is installed in your skills directory at run time; install the marketplace skill first for the condensed pipeline, and keep `reference.md` next to it for the full form.
