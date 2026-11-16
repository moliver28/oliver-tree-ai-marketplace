# Niche probe menu (rate-sheet widening)

Demo-segment categories for building INVERSE/widening rate sheets when a
persona's measured lanes are too narrow. Pick categories the person has NO
data in; 3-5 candidates each; skip anything already rated by any person in
the setup. The menu is a source of categories, not a fixed list: adapt titles
to the person's region/format availability and their existing lanes. Choose
segments matching the personas you serve; the example list below shows the
shape with broad demo families.

## Example segments (broad demo families; generalize per person)

- Book adaptation / romance-fantasy readerships (bridges fairy-tale/fantasy
  lanes)
- Female-friendship dramedy
- 2000s rom-com era (nostalgia + romance)
- Cozy mystery / village-crime formats
- Reality comfort (home, food-travel, makeover; CALM formats only for
  people with a loud/stress sensitivity)
- Fantasy-epic adjacent (prestige book adaptations)
- Nostalgic 90s/2000s comedy
- Female-lead action
- Glossy ensemble drama with appeal-heavy leads
- Quirky mystery comedy
- Comfort work-com (wholesome professional sitcoms)
- Westerns, musicals, heist/caper, legal-political, animation, survival
  reality, international thriller: each as its OWN category row, never mixed,
  because a whole-category nahh is a training artifact worth keeping

## New-lane hunt mode (find MORE lanes request)

When the user asks to find more lanes rather than fill existing ones, label
the sheet H1..Hn: one untested hypothesis per group of 3-4 titles, each with
its reasoning stated in one clause ("is it creatures she loves, or fear
itself?"). Verdict-level answers ("H4 no, H9 yes") are valid results. A
uniform miss becomes a graded negative (with its nuance), not a dead end;
3+ hits near 8 open the lane and the titles seed it. Hypothesis families
worth cycling: format test (reality/doc/anthology), register test (schlock
vs grounded, fear vs creature, cozy vs dark), demo-niche test (from the
segment list above), seasonal gate test (holiday/event lanes). Never hunt a
lane that already has a trained weight.

## Rules

- Whole-category low scores become negatives WITH nuance preserved.
- A category the person "loves most" without rating: use the lane_rules
  aud-proxy pattern instead of a full rate request.
- Carry forward still-unrated titles into the next sheet once; drop after a
  second skip to keep sheets under ~65 rows.
- Keep rated titles out of every later sheet across ALL persons in the
  setup.
