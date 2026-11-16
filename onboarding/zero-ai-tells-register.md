# Zero-AI-Tells Register

The enforcement rulebook behind the /voice plugin and the voice-gate. Owner order, 2026-11-11/12 (Michael Oliver); this doc is the portable copy of his canonical Notion register. Every public-facing word passes this register plus the voice profile. End users: keep this list, replace Michael-specific hard bans with your own; the machine checks are in `plugins/humanizer/hooks/gate.py` and `plugins/voice-gate/voice-tells.py`.

## How Enforcement Runs

- Regex layer: pattern list in `plugins/voice-gate/voice-tells.py` (word-boundary anchored, inflection-tolerant). Public copy also passes the tell scan via the /voice gate; the repair contract patches flagged phrases in place.
- Vector layer (on machines with a local embedder or Ollama): 18 tell exemplar families embedded locally; reworded tells get caught by cosine similarity, not keyword matching. Fail-open on service outage.
- Chat output always passes the STE layer (ASD-STE100: sentence/paragraph length, active voice, no filler chains or vague intensifiers). Public copy runs tell scan + STE per the onboarding STE-mode choice.
- Voice fidelity: rewrites draw only on the onboarding profile and the provided text; missing context is marked `[note: needs source]`, never invented.

## The Register (37 patterns)

1. Significance inflation: stands/serves as, testament, pivotal, crucial, key moment, underscores importance, reflects broader, marks a shift, evolving landscape
2. Notability hammering: has been cited in X, Y, Z without context; active social media presence
3. Fake depth -ing tails: highlighting, underscoring, ensuring, reflecting, showcasing, contributing to
4. Promotional language: boasts, vibrant, rich (figurative), nestled, in the heart of, groundbreaking, renowned, breathtaking
5. Vague attribution: experts argue, industry reports, observers have cited
6. Formulaic Challenges-and-Prospects sections
7. AI vocabulary: additionally, crucial, delve, enhance, foster, garner, highlight (verb), interplay, intricate, key, pivotal, showcase, valuable, vibrant
8. Marketing/blog cliches: at the end of the day, when it comes to, deep dive (before analysis), game-changer, double down, circle back, make no mistake, it turns out, let me be clear, unpack, lean into
9. Negative parallelism: It's not just X, it's Y / not merely / not simply; tailing negation fragments
10. Rule-of-three padding
11. Synonym cycling (elegant variation)
12. False ranges (from X to Y where there is no scale)
13. Passive voice and subjectless fragments
14. Em dash overuse (never; use comma, period, colon, parentheses)
15. Mechanical boldface
16. Inline-header vertical lists (Labeled: sentence)
17. Title Case in headings
18. Emojis in headings and bullets
19. Curly quotation marks
20. Collaborative chatbot artifacts (I hope this helps, let me know, would you like)
21. Knowledge-cutoff disclaimers
22. Sycophantic tone (great question, you're absolutely right)
23. Filler phrases (in order to, due to the fact that, at this point in time, has the ability to)
24. Excessive hedging
25. Generic positive conclusions
26. Hyphenated word-pair overuse (data-driven, cross-functional, real-time chains)
27. Persuasive authority tropes (the real question is, at its core, in reality, fundamentally)
28. Signposting (let's dive in, here's what you need to know)
29. Fragmented headers (generic sentence restating the heading)
30. Forced metaphors and figurative overwriting (garden/ecosystem cliches; metaphors explained after use)
31. Dramatic fragmentation and punchy kickers (staccato X. And Y., mic-drop closers)
32. Rhetorical questions answered a beat later
33. Sentence-opener tics (So, Look, adverb openers Interestingly/Notably/Crucially, hedged I think on facts)
34. Reassurance kickers (and that's okay, no shame in, you're not alone)
35. APHORISM DENSITY: at most one kicker per section and two to three per piece; one antimetabole inversion max; no coined multiword metaphor hammered five-plus times as a motif; no fragment section openers. Density, not the construction, is the tell.
36. Teaser handoffs: sections that close on a cliffhanger line previewing the next section ("someone is filling it"; "X shows what that costs, with dates attached"; "it deserves a real answer"). Carry transitions in the next section's first sentence of evidence instead. Max two teaser closers per piece.
37. Performed candor: meta-asides that announce precision or honesty ("to be precise", "a cost worth stating", "let me be honest"). State the caveat plainly as a fact about the claim.

## Hard bans (voice-level, always)

- Words: leverage, unlock, supercharge, game-changer, journey, robust (say strong), synergy, delve, tapestry, delight, best-in-class, passionate about, results-driven, proven track record, spearheaded, dynamic professional, world-class, cutting-edge, revolutionary
- Phrases: In today's rapidly evolving landscape; Let's dive in; it's worth noting; I hope this helps; feel free to reach out
- Constructions: It's not X. It's Y. and all cousins; em dashes under any circumstance (non-negotiable)
- Resumes and letters: committed first-person ownership verbs (led, built, ran, standardized, cut), plain declarative evidence, no hedged ownership where the record supports direct ownership

## Scope

Public-facing surfaces get the scan every time, without being asked: blogs, LinkedIn and short-form, syndication submissions, artifact pages, personal and client sites, community posts under your name, product and waitlist pages, marketing kits, career materials. Private memos to yourself need no scan. If the text leaves the machine, scan first.

---

Authored for the Oliver Tree AI Marketplace, 2026-11-16, from the owner's canonical register (Notion, Meta-Agent Master Prompt subpage, patterns 1-35 dated 2026-11-11, patterns 36-37 added 2026-11-12).
