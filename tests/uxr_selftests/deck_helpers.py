from _harness import bind

bind("references.deck_helpers", globals())

import tempfile  # selftest-only import (moved from references/deck_helpers.py)

def generator_path_from_config(config: dict | None) -> str:
    """The deck generator path; empty means the shipped scripts/deck_render.py."""
    deck = (config or {}).get("deck")
    value = deck.get("generator_path") if isinstance(deck, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def critic_agent_from_config(config: dict | None) -> str:
    """The panel Critic agent id; empty means ``hcd-researcher``."""
    deck = (config or {}).get("deck")
    value = deck.get("critic_agent") if isinstance(deck, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("references/deck_helpers.py selftest")

    # 1. The shipped personas file validates against the required-key contract.
    try:
        personas = load_personas("")
        check("shipped personas file loads", set(personas) == set(CANONICAL_PERSONAS), str(sorted(personas)))
    except (OSError, ValueError) as exc:
        personas = {}
        check("shipped personas file loads", False, str(exc))
    problems = validate_personas(personas)
    check("shipped personas validate", not problems, "; ".join(problems[:3]))
    for name, entry in personas.items():
        for key in REQUIRED_PERSONA_KEYS:
            if key not in entry:
                check(f"{name} carries {key}", False, "missing")
        if entry.get("pe_framing_prompt") is not None:
            check(
                f"{name} shipped pe_framing_prompt is null (cache owns it)",
                _prompt_problems(name, entry["pe_framing_prompt"]) == [],
                "shipped prompt should stay null; the runtime cache fills it",
            )

    # 2. Caps: leadership at strategic tier is 8 (acceptance); lite floor is 3.
    check(
        "leadership strategic cap is 8",
        compute_cap(personas["leadership"]["slide_cap"], "strategic") == 8,
        str(compute_cap(personas["leadership"]["slide_cap"], "strategic")),
    )
    check(
        "leadership lite cap is 3 (the max(3, ...) floor)",
        compute_cap(personas["leadership"]["slide_cap"], "lite") == 3,
        str(compute_cap(personas["leadership"]["slide_cap"], "lite")),
    )
    for name in CANONICAL_PERSONAS:
        base = personas[name]["slide_cap"]
        check(
            f"{name} caps follow max(3, round(base * factor))",
            compute_cap(base, "lite") == max(3, round(base * 0.6))
            and compute_cap(base, "standard") == max(3, round(base * 1.0))
            and compute_cap(base, "strategic") == max(3, round(base * 1.5)),
        )

    # 3. Scaffold over 3 RQs: 3 question slides, 3 finding slides, one
    #    section slide per non-empty beat (acceptance).
    rqs = [
        {"id": "RQ1", "topic": "import", "question": "How do admins import?"},
        {"id": "RQ2", "topic": "labels", "question": "Why do labels confuse?"},
        {"id": "RQ3", "topic": "search", "question": "What blocks search?"},
    ]
    beats = [
        {"beat": "setup", "title": "The team set up", "connector": "We begin here.", "rq_ids": ["RQ1"]},
        {"beat": "conflict", "title": "Friction showed up", "connector": "Then friction.", "rq_ids": ["RQ2"]},
        {"beat": "resolution", "title": "A way through", "connector": "Then relief.", "rq_ids": ["RQ3"]},
        {"beat": "implication", "title": "Empty on purpose", "connector": "", "rq_ids": []},
    ]
    outline = scaffold_outline(beats, rqs)
    kinds = [s["kind"] for s in outline["slides"]]
    check(
        "scaffold: 3 question slides over 3 RQs",
        kinds.count("question") == 3,
        str(kinds),
    )
    check("scaffold: 3 finding slides over 3 RQs", kinds.count("finding") == 3, str(kinds))
    check(
        "scaffold: one section slide per non-empty beat (3 of 4)",
        sum(1 for s in outline["slides"] if s["kind"] == "content" and s.get("beat")) == 3,
    )
    all_beats = [dict(b, rq_ids=[r["id"] for r in rqs][:1]) for b in beats]
    all_beats[3] = dict(beats[3], rq_ids=["RQ3"])
    outline_full = scaffold_outline(all_beats, rqs)
    check(
        "scaffold: 4 non-empty beats give 4 section slides",
        sum(1 for s in outline_full["slides"] if s["kind"] == "content" and s.get("beat")) == 4,
    )

    # 4. Persona scaffold: arc order + priority order + methodology appendix.
    persona = personas["leadership"]
    outline_persona = scaffold_outline(
        beats, rqs, persona=persona, persona_name="leadership", tier="lite", key="abc-42"
    )
    beats_in_order = [s.get("beat") for s in outline_persona["slides"] if s.get("beat")]
    check(
        "leadership scaffold orders beats by its arc (implication first is a beat order, not slide order)",
        len(beats_in_order) == 3,
        str(beats_in_order),
    )
    first_category = outline_persona["slides"][0]["kind"]
    check("scaffold keeps cover first even with a persona", first_category == "cover", first_category)

    # 5. validate-beats: orphan, duplicate, unknown each block; empty is legal.
    _, blocked = validate_beats(beats, rqs)
    check("validate-beats: clean assignment passes", not blocked)
    tags, blocked = validate_beats(
        [dict(beats[0]), dict(beats[1]), dict(beats[2], rq_ids=[])], rqs
    )
    check("validate-beats: orphan RQ blocks", blocked and any(t.startswith("[orphan]") for t in tags), str(tags))
    dup_beats = [
        {"beat": "setup", "title": "t", "connector": "c", "rq_ids": ["RQ1", "RQ2"]},
        {"beat": "conflict", "title": "t", "connector": "c", "rq_ids": ["RQ2", "RQ3"]},
        {"beat": "resolution", "title": "t", "connector": "c", "rq_ids": []},
    ]
    tags, blocked = validate_beats(dup_beats, rqs)
    check("validate-beats: duplicate RQ blocks", blocked and any(t.startswith("[dup]") for t in tags), str(tags))
    unknown_beats = [
        {"beat": "setup", "title": "t", "connector": "c", "rq_ids": ["RQ1", "RQ9"]},
        {"beat": "conflict", "title": "t", "connector": "c", "rq_ids": ["RQ2"]},
        {"beat": "resolution", "title": "t", "connector": "c", "rq_ids": ["RQ3"]},
    ]
    tags, blocked = validate_beats(unknown_beats, rqs)
    check("validate-beats: unknown RQ blocks", blocked and any(t.startswith("[unknown]") for t in tags), str(tags))
    tags, blocked = validate_beats(beats, rqs)
    check(
        "validate-beats: an empty beat is legal (tagged, never a block)",
        not blocked and any(t.startswith("[empty]") for t in tags),
        str(tags),
    )
    tags, blocked = validate_beats(
        [dict(beats[0], title=""), dict(beats[1]), dict(beats[2])], rqs
    )
    check(
        "validate-beats: assigned beat without a title tags [empty] without blocking",
        not blocked and any(t.startswith("[empty]") for t in tags),
        str(tags),
    )

    # 6. lint-outline: 4 content slides block leadership at lite tier (acceptance).
    fat_outline = {
        "version": 1,
        "tier": "lite",
        "persona": "leadership",
        "cap": compute_cap(personas["leadership"]["slide_cap"], "lite"),
        "slides": [
            {"id": "cover", "kind": "cover", "title": "Deck"},
            {"id": "s1", "kind": "exec-summary", "title": "Exec", "bullets": ["one"]},
            {"id": "s2", "kind": "content", "title": "A", "text": "text"},
            {"id": "s3", "kind": "content", "title": "B", "text": "text"},
            {"id": "s4", "kind": "bullets", "title": "C", "bullets": ["x"]},
            {"id": "end", "kind": "end", "title": "End"},
        ],
    }
    lines, blocked = lint_outline(fat_outline, persona=personas["leadership"], tier="lite")
    check(
        "lint-outline: 4 content slides block leadership at lite",
        blocked and any(line.startswith("FAIL cap") for line in lines),
        "; ".join(lines[:2]),
    )
    lines, blocked = lint_outline(fat_outline, persona=personas["leadership"], tier="strategic")
    check(
        "lint-outline: same outline passes at strategic (cap 8)",
        not blocked and any(line.startswith("ok cap") for line in lines),
        "; ".join(lines[:2]),
    )
    thin = dict(fat_outline, slides=fat_outline["slides"][:4] + [fat_outline["slides"][-1]])
    lines, blocked = lint_outline(thin, persona=personas["leadership"], tier="lite")
    check("lint-outline: 3 content slides pass leadership lite", not blocked, "; ".join(lines))

    # 7. lint-outline strategic preliminary note and finding sources.
    strategic_outline = {
        "version": 1,
        "tier": "strategic",
        "slides": [
            {"id": "cover", "kind": "cover", "title": "Deck"},
            {
                "id": "f1",
                "kind": "finding",
                "title": "One source",
                "rq": "RQ1",
                "bullets": ["claim"],
                "sources": ["import-confusion"],
            },
            {"id": "q1", "kind": "question", "title": "Q", "rq": "RQ1", "text": "question"},
            {"id": "end", "kind": "end", "title": "End"},
        ],
    }
    lines, blocked = lint_outline(strategic_outline, tier="strategic")
    check(
        "lint-outline: strategic finding under 2 sources without the note blocks",
        blocked and any(line.startswith("FAIL strategic-preliminary") for line in lines),
        "; ".join(lines[:2]),
    )
    noted = dict(
        strategic_outline,
        slides=[
            strategic_outline["slides"][0],
            dict(strategic_outline["slides"][1], note=SINGLE_SOURCE_NOTE),
            strategic_outline["slides"][2],
            strategic_outline["slides"][3],
        ],
    )
    lines, blocked = lint_outline(noted, tier="strategic")
    check(
        "lint-outline: the note satisfies the strategic check",
        not any(line.startswith("FAIL strategic-preliminary") for line in lines),
        "; ".join(lines[:2]),
    )
    no_sources = dict(
        strategic_outline,
        slides=[
            strategic_outline["slides"][0],
            dict(strategic_outline["slides"][1], sources=[]),
            strategic_outline["slides"][2],
            strategic_outline["slides"][3],
        ],
    )
    lines, blocked = lint_outline(no_sources, tier="strategic")
    check(
        "lint-outline: a finding with zero sources blocks",
        blocked and any(line.startswith("FAIL finding-sources") for line in lines),
        "; ".join(lines[:2]),
    )

    # 8. RQ pairing and duplicate titles.
    unpaired = dict(
        strategic_outline,
        slides=[
            strategic_outline["slides"][0],
            strategic_outline["slides"][1],
            {"id": "q9", "kind": "question", "title": "Q", "rq": "RQ9", "text": "q"},
            strategic_outline["slides"][3],
        ],
    )
    lines, blocked = lint_outline(unpaired, tier="standard")
    check(
        "lint-outline: unpaired question slide blocks",
        blocked and any(line.startswith("FAIL rq-pairing") for line in lines),
        "; ".join(lines[:2]),
    )
    dup_titles = dict(
        strategic_outline,
        slides=[
            strategic_outline["slides"][0],
            strategic_outline["slides"][1],
            {"id": "q1", "kind": "question", "title": "Q", "rq": "RQ1", "text": "q"},
            {"id": "f1b", "kind": "finding", "title": "One source", "rq": "RQ1", "bullets": ["b"], "sources": ["a"]},
            strategic_outline["slides"][3],
        ],
    )
    lines, blocked = lint_outline(dup_titles, tier="standard")
    check(
        "lint-outline: duplicate content titles block",
        blocked and any(line.startswith("FAIL duplicate-titles") for line in lines),
        "; ".join(lines[:2]),
    )

    # 9. Visual kinds: 20 of them; boundary shapes enforced; bad spec is caught.
    check("visual kinds table has exactly 20 kinds", len(VISUAL_KINDS) == 20, str(len(VISUAL_KINDS)))
    check(
        "pie accepts 2 and 5 slices, rejects 1 and 6",
        validate_visual({"kind": "pie", "slices": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]})[0]
        and validate_visual({"kind": "pie", "slices": [{"label": str(i), "value": i} for i in range(5)]})[0]
        and not validate_visual({"kind": "pie", "slices": [{"label": "a", "value": 1}]})[0]
        and not validate_visual({"kind": "pie", "slices": [{"label": str(i), "value": i} for i in range(6)]})[0],
    )
    check(
        "venn rejects 4 sets; matrix2x2 rejects 3 quadrants",
        not validate_visual({"kind": "venn", "sets": [{"label": str(i)} for i in range(4)]})[0]
        and not validate_visual({"kind": "matrix2x2", "quadrants": [{"title": str(i)} for i in range(3)]})[0],
    )
    check(
        "hierarchy needs a root; comparison needs exactly 2 columns",
        not validate_visual({"kind": "hierarchy"})[0]
        and not validate_visual({"kind": "comparison", "columns": [{"title": "a"}]})[0],
    )
    check(
        "a bad visual spec reports a reason (renders as a labeled placeholder)",
        validate_visual({"kind": "pie", "slices": "nope"})[1] != "",
    )
    check(
        "unknown visual kind is invalid",
        not validate_visual({"kind": "sparkline"})[0],
    )

    # 10. deck-filename shape (acceptance vocabulary).
    name = deck_filename("Leadership", "2026-11-09", "ABC-42")
    check(
        "deck-filename is deck-<audience>-<date>-<key>.pptx lowercase",
        name == "deck-leadership-2026-11-09-abc-42.pptx",
        name,
    )
    try:
        deck_filename("leadership", "May 10th", "ABC-42")
        check("deck-filename rejects a non-ISO date", False, "no error")
    except ValueError:
        check("deck-filename rejects a non-ISO date", True)

    # 11. finding-sources parsing and preliminary flag.
    synthesis = (
        "## RQ1 - import\nThe import flow loses people [S:import-confusion] and [S:import-time].\n"
        "## RQ2 - labels\nLabels confuse [S:label-maze].\n"
        "No citations in this tail.\n"
    )
    sources = finding_sources(synthesis, min_sources=2)
    check(
        "finding-sources: counts and order",
        [entry["id"] for entry in sources] == ["RQ1", "RQ2"]
        and sources[0]["count"] == 2
        and sources[1]["count"] == 1,
        json.dumps(sources),
    )
    check(
        "finding-sources: preliminary under the minimum",
        sources[0]["preliminary"] is False and sources[1]["preliminary"] is True,
    )

    # 12. Persona cache writes into the given dir (state-dir at runtime),
    #     never the plugin source tree; load merges it over the file.
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        personas_path = PLUGIN_ROOT / "references" / "personas.json"
        before = personas_path.read_bytes()
        path = write_cached_field(str(cache_dir), "leadership", "pe_framing_prompt", {"role": "skeptic"})
        check("persona cache lands inside the given dir", path.parent == cache_dir, str(path))
        loaded = load_cached_fields(str(cache_dir))
        check(
            "cached prompt merges over the file's null",
            merge_persona_cache(personas["leadership"], loaded.get("leadership") or {})["pe_framing_prompt"]
            == {"role": "skeptic"},
        )
        check(
            "persona cache never touches the source tree",
            personas_path.read_bytes() == before,
        )
        write_cached_field(str(cache_dir), "leadership", "pe_framing_prompt", None)
        cleared = merge_persona_cache(
            personas["leadership"], (load_cached_fields(str(cache_dir)).get("leadership") or {})
        )
        check("a null cache value clears the override", cleared["pe_framing_prompt"] is None)

    # 13. beat-skeleton shells.
    skeleton = beat_skeleton(rqs, ["implication", "setup", "conflict", "resolution"])
    check(
        "beat-skeleton emits the four shells in the requested arc",
        [entry["beat"] for entry in skeleton] == ["implication", "setup", "conflict", "resolution"]
        and all(entry["rq_ids"] == [] for entry in skeleton),
        json.dumps([entry["beat"] for entry in skeleton]),
    )
    skeleton_default = beat_skeleton(rqs)
    check(
        "beat-skeleton default arc is setup, conflict, resolution, implication",
        [entry["beat"] for entry in skeleton_default] == list(DEFAULT_ARC_ORDER),
    )

    # 14. slide-plan card.
    plan = slide_plan(personas["research"], "research", "standard")
    check(
        "slide-plan exposes cap, order, arc, methodology",
        plan["cap"] == 12
        and plan["slide_priority_order"][0] == "methodology_framing"
        and plan["methodology"] == "full_section"
        and plan["arc_order"] == list(DEFAULT_ARC_ORDER),
        json.dumps(plan),
    )

    # 15. Priority ordering buckets (cover leads, end closes).
    ordered = apply_priority_order(outline_persona["slides"], personas["design"]["slide_priority_order"])
    check(
        "apply_priority_order keeps cover first and end last",
        ordered[0]["kind"] == "cover" and ordered[-1]["kind"] == "end",
    )
    categories = [s.get("category") for s in ordered if s.get("category")]
    check(
        "apply_priority_order puts design's visuals group before exec summary",
        categories.index("visuals") < categories.index("exec_summary") if "visuals" in categories and "exec_summary" in categories else True,
        str(categories),
    )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
