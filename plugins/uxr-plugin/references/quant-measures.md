# Quant measures for interview scripts

Verbatim survey items for `interview-script`. Copy the item wording exactly:
every word matters because the item feeds a score that gets compared across
studies. A labeled item in a saved script that differs from this file makes
`scripts/review_checks.py check` exit 1 (survey wording warning).

Pick by study type. Pure discovery gets none: a discovery chat has nothing
to score yet, and scoring it invents precision.

| Study type | Measures |
|---|---|
| Concept testing | `comprehension_self_rated_7_point`, `comprehension_task_success_binary`, `adoption_intent_5_point_regular_use` |
| Usability test | `umux_lite_usability_7_point`, `comprehension_task_success_binary` |
| Onboarding tour | `comprehension_self_rated_7_point`, `umux_lite_usability_7_point` |
| Idea pooling or prioritization | `ideas_rate_then_rank_scale` |
| Discovery or generative | none |

Place each measure at the point of the script where the participant has just
seen the thing it measures: comprehension after the walkthrough, adoption
intent after the concept, rating before ranking. Read the item exactly as
written, then stop talking.

## The measures

### `umux_lite_usability_7_point`

Two items, 7-point agreement scale. Mean of 5 or above is acceptable.

1. "This system's capabilities meet my requirements."
2. "This system is easy to use."

Scale: 1 Strongly disagree to 7 Strongly agree.

### `adoption_intent_5_point_regular_use`

One item, 5-point agreement scale. Mean of 4 or above is positive.

1. "If this were available today, I would use it regularly in my work."

Scale: 1 Strongly disagree to 5 Strongly agree.

### `comprehension_self_rated_7_point`

One item, 7-point scale. Replace the bracket with the feature, flow, or
concept the session covered, and keep the rest of the sentence as written.

1. "How well do you understand how this [feature/flow/concept] works?"

Scale: 1 Not at all to 7 Completely.

### `comprehension_task_success_binary`

Not a fixed sentence: a scenario, a definition check, or a reversal check
the participant either passes or fails. Write the concrete scenario into
the script section where it runs, and record pass or fail per participant.
Example shapes: "Show me where you would export this." or
"True or false: exports keep the original formatting."

### `ideas_rate_then_rank_scale`

Two steps in order: rate each idea, then force a ranking. The rating item
is verbatim; the ranking prompt is verbatim.

1. "For each idea, rate how important it would be to have this in your workflow."
2. "If you could only get three of these, which three matter most, in order?"

Scale: 1 to 5 on the rating, then the top 3 in order.

## Canonical block for the checker

`scripts/review_checks.py` parses this JSON block and compares every
labeled item in the saved script against it. Keep the wording identical to
the items above.

```json
{
  "measures": [
    {
      "key": "umux_lite_usability_7_point",
      "items": [
        "This system's capabilities meet my requirements.",
        "This system is easy to use."
      ],
      "scale": "1 Strongly disagree to 7 Strongly agree",
      "threshold": "mean 5 or above is acceptable"
    },
    {
      "key": "adoption_intent_5_point_regular_use",
      "items": [
        "If this were available today, I would use it regularly in my work."
      ],
      "scale": "1 Strongly disagree to 5 Strongly agree",
      "threshold": "mean 4 or above is positive"
    },
    {
      "key": "comprehension_self_rated_7_point",
      "items": [
        "How well do you understand how this [feature/flow/concept] works?"
      ],
      "scale": "1 Not at all to 7 Completely",
      "threshold": "higher is better; bracket must be replaced in the script"
    },
    {
      "key": "comprehension_task_success_binary",
      "items": [],
      "scale": "pass or fail",
      "threshold": "no fixed wording; write the concrete scenario in the script"
    },
    {
      "key": "ideas_rate_then_rank_scale",
      "items": [
        "For each idea, rate how important it would be to have this in your workflow.",
        "If you could only get three of these, which three matter most, in order?"
      ],
      "scale": "1 to 5, then top 3",
      "threshold": "rated items and top 3 are reported separately"
    }
  ]
}
```
