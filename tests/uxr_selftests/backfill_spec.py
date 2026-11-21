from _harness import bind

bind("scripts.backfill_spec", globals())

import spec_blocks  # tests/uxr_selftests/spec_blocks.py: the moved GOLDEN_SPEC/selftest_config home (selftest body stays verbatim)

def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/backfill_spec.py --selftest")

    golden = spec_blocks.GOLDEN_SPEC
    expected_roster = [
        {"name": "Ada Example", "status": "Scheduled"},
        {"name": "Rook Example", "status": "Potential Candidate"},
    ]

    md_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("markdown"))
    code, stdout, _ = run(md_body)
    spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "markdown body recovers history, decision, hypotheses, and RQs",
        code == 0
        and spec.get("history") == golden["history"]
        and spec.get("decision") == golden["decision"]
        and spec.get("hypotheses") == golden["hypotheses"]
        and spec.get("research_questions") == golden["research_questions"],
        f"code={code} spec={json.dumps(spec, ensure_ascii=False)[:200]}",
    )
    check(
        "markdown body recovers the roster with names and statuses",
        spec.get("roster") == expected_roster,
        repr(spec.get("roster")),
    )
    check(
        "recovered spec carries no _meta",
        "_meta" not in spec,
    )

    adf_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("adf"))
    code, stdout, _ = run(json.dumps(adf_body, ensure_ascii=False))
    adf_spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "ADF JSON body recovers the same fields",
        code == 0
        and adf_spec.get("history") == golden["history"]
        and adf_spec.get("hypotheses") == golden["hypotheses"]
        and adf_spec.get("roster") == expected_roster,
        f"code={code} spec={json.dumps(adf_spec, ensure_ascii=False)[:200]}",
    )

    html_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("html"))
    code, stdout, _ = run(html_body)
    html_spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "html body recovers history, hypotheses, and the roster",
        code == 0
        and html_spec.get("history") == golden["history"]
        and html_spec.get("hypotheses") == golden["hypotheses"]
        and html_spec.get("roster") == expected_roster,
        f"code={code} spec={json.dumps(html_spec, ensure_ascii=False)[:200]}",
    )

    code, stdout, _ = run("")
    check("empty input prints {} and exits 0", code == 0 and json.loads(stdout) == {}, f"stdout={stdout!r}")

    placeholder_body = spec_blocks.build_document({}, config=spec_blocks.selftest_config())
    code, stdout, _ = run(placeholder_body)
    check(
        "placeholder-only body recovers nothing",
        code == 0 and json.loads(stdout) == {},
        f"stdout={stdout[:120]!r}",
    )

    for junk in ("}}garbage{{{", "<not html", "plain words only", '{"type": "doc"}'):
        code, stdout, _ = run(junk)
        ok = code == 0 and isinstance(json.loads(stdout), dict)
        check(f"junk input ({junk[:14]!r}) exits 0 with a JSON object", ok, f"code={code}")

    # W2 build-block helpers: save-spec writes _meta; check-readback counts.
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        draft = Path(td) / "draft.json"
        draft.write_text(json.dumps({"study_title": "T", "hypotheses": [
            {"label": "H1", "text": "Falsifiable."}], "research_questions": ["Why?"]}),
            encoding="utf-8")
        os.environ["UXR_CONFIG__PATHS__STATE_DIR"] = str(Path(td) / "state")
        try:
            code = save_spec("T-1", draft)
            saved = Path(td) / "state" / "specs" / "T-1.spec.json"
            meta = json.loads(saved.read_text(encoding="utf-8")).get("_meta", {}) if saved.is_file() else {}
            check("save-spec writes the spec with six _meta keys",
                  code == 0 and len(meta) == 6, f"code={code} meta={sorted(meta)}")
            readback = Path(td) / "readback.md"
            readback.write_text(spec_blocks.build_document(
                json.loads(draft.read_text(encoding="utf-8")),
                config=spec_blocks.selftest_config("markdown")), encoding="utf-8")
            check("check-readback passes a full document", check_readback(readback) == 0)
        finally:
            os.environ.pop("UXR_CONFIG__PATHS__STATE_DIR", None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
