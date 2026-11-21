End with one final line after the findings list, a checklist-scoped JSON
verdict and nothing else on that line:

verdict: {"result": "pass", "p0": []}
verdict: {"result": "p0", "p0": ["<claim ids or quotes>"]}

Use "p0" only for a defect that invalidates the artifact (an unsupported
core claim, a method that cannot answer its own questions). Everything
else is a What-to-change item, not a p0. The dispatcher re-invokes only on
"p0"; every other item is folded in or declined with one line.
