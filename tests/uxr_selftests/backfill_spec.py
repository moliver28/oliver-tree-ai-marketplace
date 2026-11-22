from _harness import bind

bind("scripts.backfill_spec", globals())

import contextlib  # selftest-only import
import io  # selftest-only import

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
    # W4 issue 60: save-spec validates (the new-command save carries the verbatim
    # ask) and assert-ask checks the saved spec.
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        draft = Path(td) / "draft.json"
        draft.write_text(json.dumps({
            "history": "Billing rework shipped last quarter.",
            "decision": "Ship the invoice page, owner: the product trio.",
            "hypotheses": [{"label": "H1", "text": "Falsifiable."}],
            "research_questions": ["Why?"],
            "ask_verbatim": "Fix the invoice export",
            "ask_source": "intake interview, 2026-11-21",
        }), encoding="utf-8")
        legacy_draft = Path(td) / "legacy-draft.json"
        legacy_draft.write_text(json.dumps({
            "history": "Billing rework shipped last quarter.",
            "decision": "Ship the invoice page, owner: the product trio.",
            "hypotheses": [{"label": "H1", "text": "Falsifiable."}],
            "research_questions": ["Why?"],
        }), encoding="utf-8")
        os.environ["UXR_CONFIG__PATHS__STATE_DIR"] = str(Path(td) / "state")
        try:
            code = save_spec("T-1", draft)
            saved = Path(td) / "state" / "specs" / "T-1.spec.json"
            meta = json.loads(saved.read_text(encoding="utf-8")).get("_meta", {}) if saved.is_file() else {}
            check("save-spec writes the spec with six _meta keys",
                  code == 0 and len(meta) == 6, f"code={code} meta={sorted(meta)}")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = save_spec("T-2", legacy_draft)
            check("a new-command save without the ask exits 4 with the exact line",
                  code == 4
                  and "ask_verbatim is empty (the original ask must be stored verbatim)"
                  in stderr.getvalue(),
                  f"code={code} stderr={stderr.getvalue()!r}")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = save_spec("T-3", legacy_draft, "retro")
            check("a retro save without the ask records the gap and exits 0",
                  code == 0, f"code={code} stderr={stderr.getvalue()!r}")
            readback = Path(td) / "readback.md"
            readback.write_text(spec_blocks.build_document(
                json.loads(draft.read_text(encoding="utf-8")),
                config=spec_blocks.selftest_config("markdown")), encoding="utf-8")
            check("check-readback passes a full document", check_readback(readback) == 0)

            ask_ok = Path(td) / "ask-ok.json"
            ask_ok.write_text(json.dumps({"ask_verbatim": "Fix the invoice export"}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = assert_ask(ask_ok)
            check("assert-ask prints ask OK for a filled ask",
                  code == 0 and stdout.getvalue().strip() == "ask OK", f"code={code} out={stdout.getvalue()!r}")
            pre_ask = Path(td) / "pre-ask.json"
            pre_ask.write_text(json.dumps({"history": "h"}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = assert_ask(pre_ask)
            check("assert-ask prints the pre-ask line for a legacy spec and does not block",
                  code == 0 and stdout.getvalue().strip() == "ask missing (pre-ask spec)",
                  f"code={code} out={stdout.getvalue()!r}")
            empty_ask = Path(td) / "empty-ask.json"
            empty_ask.write_text(json.dumps({"ask_verbatim": "", "ask_source": "unrecovered"}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = assert_ask(empty_ask)
            check("assert-ask exits 5 on a real gap",
                  code == 5 and "must be stored verbatim" in stdout.getvalue(),
                  f"code={code} out={stdout.getvalue()!r}")
        finally:
            os.environ.pop("UXR_CONFIG__PATHS__STATE_DIR", None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
