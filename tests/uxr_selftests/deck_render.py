from _harness import bind

bind("scripts.deck_render", globals())
def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/deck_render.py selftest")

    # 1. Visual kind rules come from deck_helpers (one source; 20 kinds).
    check("visual kinds are imported from deck_helpers", len(deck_helpers.VISUAL_KINDS) == 20, str(len(deck_helpers.VISUAL_KINDS)))

    # 2. A clean slide lints clean.
    clean_slide = {
        "id": "s1",
        "kind": "bullets",
        "title": "Findings",
        "bullets": ["Admins import per workspace", "Labels confuse new users"],
    }
    boxes, problems = build_layout(clean_slide, 0)
    failures_out = lint_layout([("s1", boxes, problems)])
    check("a clean slide lints clean", not failures_out, "; ".join(failures_out[:2]))

    # 3. Overflow: a body far longer than the box fails.
    crowded = {
        "id": "s2",
        "kind": "bullets",
        "title": "Findings",
        "bullets": [f"Finding {i}: " + "detail " * 60 for i in range(12)],
    }
    boxes, problems = build_layout(crowded, 0)
    failures_out = lint_layout([("s2", boxes, problems)])
    check(
        "an overflowing body produces a FAIL overflow line",
        any(line.startswith("FAIL overflow s2") for line in failures_out),
        "; ".join(failures_out[:2]),
    )

    # 4. Overlap: two boxes sharing space fail.
    overlapping = [
        _text_box("first box", 1.0, 2.0, 4.0, 2.0, BODY_FONT),
        _text_box("second box", 3.0, 3.0, 4.0, 2.0, BODY_FONT),
    ]
    failures_out = lint_layout([("s3", overlapping, [])])
    check(
        "overlapping boxes produce a FAIL overlap line",
        any(line.startswith("FAIL overlap s3") for line in failures_out),
        "; ".join(failures_out[:2]),
    )
    separated = [
        _text_box("first box", 1.0, 2.0, 4.0, 2.0, BODY_FONT),
        _text_box("second box", 6.0, 5.0, 4.0, 2.0, BODY_FONT),
    ]
    failures_out = lint_layout([("s4", separated, [])])
    check("well-separated boxes pass", not failures_out, "; ".join(failures_out))

    # 5. A bad visual spec becomes a labeled placeholder box, never a crash.
    boxes, problems = build_layout({"id": "s5", "kind": "diagram", "title": "D", "visual": {"kind": "sparkline"}}, 0)
    placeholders = [b for b in boxes if str(b.get("text", "")).startswith(PLACEHOLDER_PREFIX)]
    check(
        "a bad visual spec yields one labeled placeholder box",
        len(placeholders) == 1 and "sparkline" in str(placeholders[0].get("text")),
        "; ".join(str(b.get("text")) for b in placeholders),
    )
    boxes, problems = build_layout(
        {"id": "s6", "kind": "diagram", "title": "D", "visual": {"kind": "pie", "slices": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]}}, 0
    )
    check("a valid visual spec yields no placeholder", not problems, str(problems))

    # 6. The outline-level lint surfaces unreadable input as FAIL lines.
    failures_out, _ = lint_outline_file("does-not-exist.json")
    check("unreadable outline becomes a FAIL input line", failures_out and failures_out[0].startswith("FAIL input"))

    # 7. CLI surface: unknown flags are usage errors; render without pptx exits 2.
    check("argument parser reads lint", (_parse_args(["lint", "o.json"]) or ("", {}))[0] == "lint")
    check(
        "argument parser reads render with two positionals",
        (_parse_args(["render", "o.json", "d.pptx"]) or ("", {})) == ("render", {"positional": "o.json", "out": "d.pptx"}),
    )
    check("argument parser rejects unknown flags", _parse_args(["lint", "--png", "o.json"]) is None)

    # 8. Render round trip only when python-pptx is present (skipped otherwise).
    if HAVE_PPTX:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            outline = {"version": 1, "slides": [clean_slide, {"id": "end", "kind": "end", "title": "Thank you"}]}
            target = Path(td) / "deck.pptx"
            errors = render_outline(outline, target)
            check("render writes a .pptx when python-pptx is installed", not errors and target.is_file(), "; ".join(errors))
    else:
        print("  [SKIP] render round trip (python-pptx is not installed)")
        print(f"         {PPTX_INSTALL_HINT}")

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
