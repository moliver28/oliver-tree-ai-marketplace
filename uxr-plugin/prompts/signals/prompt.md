---
{
  "id": "signals",
  "version": 1,
  "vars": ["topic", "digest"],
  "when": [],
  "fragments": [
    {"id": "feedback-gap", "when": "feedback_gap == true", "file": "fragments/feedback-gap.md", "budget": 4},
    {"id": "tactical-wiki", "when": "tactical == true", "file": "fragments/tactical-wiki.md", "budget": 3}
  ],
  "default": "prompt.md",
  "budget": {"max_lines": 40, "max_vars": 4}
}
---
Study topic: $topic

The digest below is the ONLY evidence input: it already holds per-source hit
counts, compressed titles and owners, and one unavailable line per failed
source. Never ask for or quote raw search results.

Digest:
$digest

Write ONLY the Top signals block, four lines, exactly these prefixes:

- Owning group: <the group the evidence clusters under, from the digest and the ask alone when nothing surfaced>
- Hypotheses in flight: <claims already being tested elsewhere, one line each; "none surfaced (<why>)" when empty>
- Pain strength: high|medium|low <one clause naming the evidence behind the call>
- Stakeholders: <people who own or touch the evidence>

Print nothing before or after the four lines.
