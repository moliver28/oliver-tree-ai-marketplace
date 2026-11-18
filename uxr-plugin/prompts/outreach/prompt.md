---
{
  "id": "outreach",
  "version": 1,
  "vars": ["first_name", "study_title", "session_length", "why_this_recruit", "focus_clause",
           "slots_block", "sender_first_name", "study_short", "initial", "last_name",
           "day_abbrev", "m_d"],
  "vars_source": "spec",
  "when": [],
  "fragments": [
    {"id": "dm-block", "when": "has_slack == true", "file": "fragments/dm-block.md", "budget": 10},
    {"id": "email-block", "file": "fragments/email-block.md", "budget": 5},
    {"id": "hold-titles", "when": "holds == requested", "file": "fragments/hold-titles.md", "budget": 8}
  ],
  "default": "prompt.md",
  "budget": {"max_lines": 40, "max_vars": 14}
}
---
Every field below is verbatim roster/spec data. When a required field is
missing from the roster row (no reason, no work area), stop and say which
field is missing - never invent a why-this-recruit line.

Slot lines offered (from `calendar_prep.py --pick`):

$slots_block

Reply options: `sent`, `edit slack`, `edit email`, `skip`, `go ahead and move <id>`.
