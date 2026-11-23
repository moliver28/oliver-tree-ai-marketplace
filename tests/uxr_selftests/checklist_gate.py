"""Checklist gate self-test: the loader, the probe vocabulary, the CLI law, and the standing-mandate predicates (issue 53).

Binds ``lib/checklist_gate.py`` and drives it against a temporary
checklist directory (the canonical directory ships the confirmed
53-content item set; the absent-line law is exercised against an empty
directory override), plus the two ``ask_*`` predicates the standing
mandates ride in ``lib/phase_gates.SPEC_CHECKS``.
"""
from _harness import bind

bind("lib.checklist_gate", globals())

import contextlib  # selftest-only import
import io  # selftest-only import
import tempfile  # selftest-only import

SPEC = {
    "history": "Billing rework shipped last quarter.",
    "decision": "Ship the invoice page, owner: the product trio.",
    "hypotheses": [{"label": "H1", "text": "Falsifiable."}],
    "research_questions": ["Why?"],
    "ask_verbatim": "Fix the invoice export",
    "ask_source": "intake interview, 2026-11-21",
}

CHECKLIST = "\n".join(
    [
        "# Qual interviews (confirmed item set lands later)",
        "",
        "- [ ] Q1 RQs exist. Evidence: spec:research_questions_nonempty. (Source: track-53 A1)",
        "- [ ] Q2 ask stored verbatim. Evidence: spec:ask_verbatim_present. (Source: track-53 A1.4)",
        "- [ ] Q3 ask source recorded. Evidence: spec:ask_source_present. (Source: track-53 A4.3)",
        "- [ ] Q4 codes file exists. Evidence: path:analysis/codes.md. (Source: track-53 A2)",
        "- [ ] Q5 plugin law satisfied. Evidence: always. (Source: track-53 A3)",
        "- [ ] Q6 unknown probe. Evidence: tracker:frobnicate. (Source: track-53 A9)",
        "",
        "Not an item line.",
    ]
)


def _selftest() -> int:
    failures: list[str] = []

    def check(name, condition, detail=""):
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/checklist_gate.py self-test")

    # --- loader: only the documented line shape parses -------------------------
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        checklists = tmp / "checklists"
        checklists.mkdir()
        (checklists / "qual-interviews.md").write_text(CHECKLIST, encoding="utf-8")
        items = load_items(checklists / "qual-interviews.md")
        check(
            "the loader parses exactly the item lines",
            len(items) == 6
            and items[0]["id"] == "Q1"
            and items[0]["evidence"] == "spec:research_questions_nonempty"
            and items[0]["source"] == "track-53 A1",
            repr(items)[:160],
        )
        check("no checklist for the file is absent", load_items(checklists / "absent.md") == [])

        # --- probe vocabulary ----------------------------------------------------
        spec = dict(SPEC)
        check(
            "spec probes run the phase_gates predicates",
            probe_ok("spec:research_questions_nonempty", spec, tmp)
            and probe_ok("spec:ask_verbatim_present", spec, tmp)
            and probe_ok("spec:ask_source_present", spec, tmp),
            "expected all three to pass",
        )
        no_ask = {k: v for k, v in spec.items() if not k.startswith("ask_")}
        check(
            "the ask predicates fail without the ask keys",
            not probe_ok("spec:ask_verbatim_present", no_ask, tmp)
            and not probe_ok("spec:ask_source_present", no_ask, tmp),
            "expected both to fail",
        )
        (tmp / "analysis").mkdir()
        (tmp / "analysis" / "codes.md").write_text("codes\n", encoding="utf-8")
        (tmp / "analysis" / "empty.md").write_text("", encoding="utf-8")
        check(
            "path probes need an existing non-empty file",
            probe_ok("path:analysis/codes.md", spec, tmp)
            and not probe_ok("path:analysis/missing.md", spec, tmp)
            and not probe_ok("path:analysis/empty.md", spec, tmp),
            "expected exists/non-empty behavior",
        )
        check(
            "the always probe is satisfied and unknown probes fail closed",
            probe_ok("always", spec, tmp) and not probe_ok("tracker:frobnicate", spec, tmp),
            "expected always pass, unknown fail",
        )

        # --- check_type result shape ---------------------------------------------
        result = check_type("qual-interviews", spec, tmp, checklists_dir=checklists)
        check(
            "the gate result carries type, items, ok, and the missing list",
            result["type"] == "qual-interviews"
            and len(result["items"]) == 6
            and result["ok"] is False
            and [m["item"] for m in result["missing"]] == ["Q6"],
            repr(result["missing"]),
        )
        check(
            "missing entries carry item, evidence, and the fix (empty for a non-spec probe)",
            result["missing"][0]["evidence"] == "tracker:frobnicate"
            and result["missing"][0]["fix"] == "",
            repr(result["missing"]),
        )
        (tmp / "analysis" / "codes.md").unlink()
        result = check_type("qual-interviews", spec, tmp, checklists_dir=checklists)
        check("a dropped evidence file moves its item to the missing list",
              [m["item"] for m in result["missing"]] == ["Q4", "Q6"], repr(result["missing"]))

        empty_dir = tmp / "empty-checklists"
        empty_dir.mkdir()
        result = check_type("quant-surveys", spec, tmp, checklists_dir=empty_dir)
        check(
            "an empty checklist yields zero items and a full pass",
            result == {"type": "quant-surveys", "items": [], "ok": True, "missing": []},
            repr(result),
        )

        # --- CLI law: 0 pass / 1 not ready / 2 usage ------------------------------
        spec_file = tmp / "spec.json"
        spec_file.write_text(json.dumps(spec), encoding="utf-8")
        (tmp / "analysis" / "codes.md").write_text("codes\n", encoding="utf-8")
        passing_checklist = "\n".join(
            [
                "- [ ] S1 RQs exist. Evidence: spec:research_questions_nonempty. (Source: track-53 B1)",
                "- [ ] S2 plugin law satisfied. Evidence: always. (Source: track-53 B2)",
            ]
        )
        (checklists / "quant-surveys.md").write_text(passing_checklist, encoding="utf-8")

        def cli(*args):
            buffer, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(err):
                code = main(list(args))
            return code, buffer.getvalue(), err.getvalue()

        # the shipped canonical directory carries the confirmed 53-content item set
        for type_name, want in (("method-selection", 5), ("qual-interviews", 29),
                                ("quant-surveys", 32)):
            shipped = load_items(CHECKLIST_DIR / f"{type_name}.md")
            check(f"the shipped {type_name} checklist parses {want} items",
                  len(shipped) == want, f"found {len(shipped)}")
        code, out, _err = cli("check", "--type", "qual-interviews", "--spec", str(spec_file), "--workspace", str(tmp))
        check("the CLI runs the shipped canonical checklist instead of the absent line",
              code == 1 and "no checklist for type" not in out,
              f"code={code} out={out[:80]!r}")
        # an empty directory override keeps the absent law: missing file prints it, exit 0
        import lib.checklist_gate as _cgate  # selftest-only handle for the dir override
        saved_dir = _cgate.CHECKLIST_DIR
        try:
            _cgate.CHECKLIST_DIR = empty_dir
            code, out, _err = cli("check", "--type", "qual-interviews", "--spec", str(spec_file), "--workspace", str(tmp))
            check("the CLI prints the absent line and exits 0 for an empty checklist directory",
                  code == 0 and out.strip() == "no checklist for type qual-interviews",
                  f"code={code} out={out!r}")
        finally:
            _cgate.CHECKLIST_DIR = saved_dir
        # a parameterized directory drives the populated cases
        saved_dir = _cgate.CHECKLIST_DIR
        try:
            _cgate.CHECKLIST_DIR = checklists
            code, out, _err = cli("check", "--type", "qual-interviews", "--spec", str(spec_file),
                                  "--workspace", str(tmp))
            check("the CLI prints one missing line and exits 1 when an item lacks evidence",
                  code == 1 and out.splitlines() == ["missing: Q6 (evidence: tracker:frobnicate)"],
                  f"code={code} out={out!r}")
            code, out, _err = cli("check", "--type", "quant-surveys", "--spec", str(spec_file),
                                  "--workspace", str(tmp))
            check("the CLI exits 0 and prints nothing on a full pass",
                  code == 0 and out.strip() == "", f"code={code} out={out!r}")
            code, out, _err = cli("check", "--type", "qual-interviews", "--spec", str(spec_file),
                                  "--workspace", str(tmp), "--json")
            parsed = json.loads(out) if out.strip().startswith("{") else {}
            check("the CLI --json prints the gate result and exits 1 when items are missing",
                  code == 1 and parsed.get("type") == "qual-interviews" and parsed.get("ok") is False
                  and [m["item"] for m in parsed.get("missing", [])] == ["Q6"],
                  f"code={code} out={out[:120]!r}")
        finally:
            _cgate.CHECKLIST_DIR = saved_dir
        code, out, err = cli("check", "--type", "qual-interviews")
        check("the CLI exits 2 on missing arguments", code == 2 and "--workspace" in err, f"code={code}")
        code, out, _err = cli("bogus")
        check("the CLI exits 2 on an unknown command", code == 2, f"code={code}")

    # --- standing-mandate predicates live in SPEC_CHECKS -------------------------
    check(
        "the two ask predicates are in SPEC_CHECKS",
        "ask_verbatim_present" in _phase_gates.SPEC_CHECKS
        and "ask_source_present" in _phase_gates.SPEC_CHECKS,
        sorted(_phase_gates.SPEC_CHECKS),
    )
    check(
        "the reference requirements table stays untouched by the new predicates",
        all(
            "ask_verbatim_present" not in entries and "ask_source_present" not in entries
            for entries in _phase_gates.REFERENCE_REQUIREMENTS.values()
        ),
        repr(_phase_gates.REFERENCE_REQUIREMENTS),
    )

    if failures:
        print(f"self-test FAILED ({len(failures)} check(s))")
        return 4
    print("self-test: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
