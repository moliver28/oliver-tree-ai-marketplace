from _harness import bind

bind("scripts.review_checks", globals())

import tempfile  # selftest-only import (moved from scripts/review_checks.py)

def _internal_validate_flag(flag: object) -> str | None:
    """Mirror of the schema's flag rules for hosts without jsonschema."""
    if not isinstance(flag, dict):
        return "flag is not an object"
    missing = [key for key in FLAG_REQUIRED if key not in flag]
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    unknown = [key for key in flag if key not in FLAG_REQUIRED]
    if unknown:
        return f"unknown keys: {', '.join(unknown)}"
    agent = flag["agent"]
    flag_type = flag["flag_type"]
    if agent not in ("expert-participant", "novice-participant"):
        return f"agent {agent!r} not a reader"
    if flag_type not in FLAG_TYPE_ENUM:
        return f"flag_type {flag_type!r} not in enum"
    if agent == "expert-participant" and flag_type not in EXPERT_TYPES:
        return f"expert-participant cannot emit {flag_type!r}"
    if agent == "novice-participant" and flag_type not in NOVICE_TYPES:
        return f"novice-participant cannot emit {flag_type!r}"
    if flag["severity"] not in SEVERITY_ENUM:
        return f"severity {flag['severity']!r} not in enum"
    if flag["confidence"] not in CONFIDENCE_ENUM:
        return f"confidence {flag['confidence']!r} not in enum"
    if flag["synthetic"] is not True:
        return "synthetic must be true"
    if not isinstance(flag["artifact_grounded"], bool):
        return "artifact_grounded must be a boolean"
    if flag_type == "flat-answer-risk" and flag["confidence"] != "hedged":
        return "flat-answer-risk requires confidence hedged"
    if flag["artifact_grounded"] and flag_type not in (
        "unexecutable-step",
        "artifact-mismatch",
    ):
        return "artifact_grounded true requires an artifact flag type"
    for key in (
        "flag_id",
        "section_anchor",
        "quoted_evidence",
        "why",
        "suggested_minimal_fix",
    ):
        if not isinstance(flag[key], str) or not flag[key]:
            return f"{key} must be a non-empty string"
    return None


def _internal_validate_edit(edit: object) -> str | None:
    """Mirror of the schema's edit rules for hosts without jsonschema."""
    if not isinstance(edit, dict):
        return "edit is not an object"
    missing = [key for key in EDIT_REQUIRED if key not in edit]
    if missing:
        return f"missing required keys: {', '.join(missing)}"
    unknown = [key for key in edit if key not in EDIT_REQUIRED]
    if unknown:
        return f"unknown keys: {', '.join(unknown)}"
    ids = edit["resolves_flag_ids"]
    if not isinstance(ids, list) or len(ids) < 1:
        return "resolves_flag_ids must be a non-empty array"
    if len(set(ids)) != len(ids):
        return "resolves_flag_ids has duplicates"
    if any(not isinstance(i, str) or not i for i in ids):
        return "resolves_flag_ids entries must be non-empty strings"
    if edit["edit_kind"] not in EDIT_KIND_ENUM:
        return f"edit_kind {edit['edit_kind']!r} not in enum"
    if edit["hard_rule_preserved"] not in HARD_RULE_ENUM:
        return f"hard_rule_preserved {edit['hard_rule_preserved']!r} not in enum"
    for key in ("edit_id", "section_anchor"):
        if not isinstance(edit[key], str) or not edit[key]:
            return f"{key} must be a non-empty string"
    for key in ("before_text", "after_text"):
        if not isinstance(edit[key], str):
            return f"{key} must be a string"
    return None


def validate_review_json(instance: object) -> tuple[bool, str]:
    """Validate a reader flag array or writer edit log against the schema.

    Uses ``jsonschema`` with ``references/review-flags.schema.json`` when
    installed; otherwise a built-in mirror of the same rules. Returns
    ``(ok, error)``.
    """
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    schema_doc: dict = {}
    if SCHEMA_PATH.is_file():
        try:
            schema_doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schema_doc = {}
    if jsonschema is not None and schema_doc:
        validator_cls = jsonschema.validators.validator_for(schema_doc)
        validator_cls.check_schema(schema_doc)
        definitions = schema_doc.get("definitions", {})
        if isinstance(instance, list):
            if not instance:
                return True, ""  # an empty array is clean
            looks_flag = all(
                isinstance(item, dict) and "flag_id" in item for item in instance
            )
            # Validate the array against the referenced item definition so
            # errors name the real rule (ownership, hedged confidence) not
            # a generic anyOf mismatch.
            name = "flag_array" if looks_flag else "edit_array"
            subschema = {"$ref": f"#/definitions/{name}", "definitions": definitions}
            validator = validator_cls(subschema)
            errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
            if errors:
                return False, errors[0].message
            return True, ""
        errors = sorted(
            validator_cls(schema_doc).iter_errors(instance), key=lambda e: list(e.path)
        )
        if errors:
            return False, errors[0].message
        return True, ""
    # Built-in mirror (jsonschema missing or schema file unreadable).
    if isinstance(instance, list):
        if not instance:
            return True, ""
        looks_flag = all(
            isinstance(item, dict) and "flag_id" in item for item in instance
        )
        validator = _internal_validate_flag if looks_flag else _internal_validate_edit
        for index, item in enumerate(instance):
            error = validator(item)
            if error:
                return False, f"item {index}: {error}"
        return True, ""
    if isinstance(instance, dict):
        for key, kind in (("flags", _internal_validate_flag), ("edits", _internal_validate_edit)):
            if key in instance and isinstance(instance[key], list):
                for index, item in enumerate(instance[key]):
                    error = kind(item)
                    if error:
                        return False, f"{key}[{index}]: {error}"
        return True, ""
    return False, "instance is neither an array nor an object"


def _replace_once(haystack: str, old: str, new: str) -> str:
    assert old in haystack, f"fixture edit target not found: {old!r}"
    return haystack.replace(old, new, 1)


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        suffix = f" ({detail})" if detail and not condition else ""
        print(f"  [{'ok' if condition else 'FAIL'}] {name}{suffix}")
        if not condition:
            failures.append(name)

    cfg = dict(DEFAULT_CONFIG)
    quant = load_canonical_items()
    check("quant-measures.md canonical block parses", bool(quant), "no items found")

    def run(text: str) -> tuple[int, list[Finding]]:
        findings = check_text(text, cfg=cfg, quant_items=quant)
        return _exit_code(findings), findings

    def names(findings: list[Finding]) -> set[str]:
        return {finding.check for finding in findings}

    # 1. Canonical fixture is clean.
    code, findings = run(_fixture())
    check("canonical fixture exits 0", code == EXIT_CLEAN,
          "; ".join(f.render() for f in findings))

    # 2. A 21-word main question blocks.
    question_21 = " ".join(SALTED_QUESTION_21) + "?"
    text = _replace_once(
        _fixture(),
        "4. What else about the approval tools slows you down?",
        f"4. {question_21}",
    )
    code, findings = run(text)
    check("21-word main question exits 3", code == EXIT_BLOCK and "word-cap" in names(findings),
          f"exit {code}")

    # 3. An em dash blocks.
    text = _replace_once(
        _fixture(),
        "*Thanks for making time today.",
        "*Thanks for making time today \u2014 really.",
    )
    code, findings = run(text)
    check("em dash exits 3", code == EXIT_BLOCK and "em-en-dash" in names(findings),
          f"exit {code}")

    # 4. 53 minutes against a 60-minute budget blocks; 50 passes.
    over = _fixture(ci_minutes=22)  # 4 + 10 + 22 + 10 + 5 + 2 = 53
    assert "**Time budget**: 60 min" in over
    code, findings = run(over)
    check("53 minutes vs 60 budget exits 3", code == EXIT_BLOCK and "time-sum" in names(findings),
          f"exit {code}")
    check("53-minute fixture total is 53", "53 min; scripted cap is 52" in
          next((f.detail for f in findings if f.check == "time-sum"), ""),
          "unexpected detail")

    # 5. A yes/no opener warns.
    text = _replace_once(
        _fixture(),
        "4. What else about the approval tools slows you down?",
        "4. Did the approval tools slow you down?",
    )
    code, findings = run(text)
    check("yes/no opener exits 1", code == EXIT_WARN and "yes-no-question" in names(findings),
          f"exit {code}; " + "; ".join(f.render() for f in findings))

    # 6. Unparseable shapes exit 2.
    text = "\n".join(
        line for line in _fixture().splitlines() if not H3_RE.match(line)
    )
    code, findings = run(text)
    check("no ### sections exits 2", code == EXIT_UNPARSEABLE
          and any(f.severity == "structure" for f in findings), f"exit {code}")
    text = _replace_once(_fixture(), "**Time budget**: 60 min\n", "")
    code, findings = run(text)
    check("no time budget line exits 2", code == EXIT_UNPARSEABLE, f"exit {code}")
    text = "\n".join(
        line for line in _fixture().splitlines()
        if "Script Question Map" not in line
    )
    code, findings = run(text)
    check("no RQ map heading exits 2", code == EXIT_UNPARSEABLE, f"exit {code}")

    # 7. Schema: empty array, valid flag, asserted flat-answer-risk fails.
    ok, error = validate_review_json([])
    check("schema: empty flag array passes", ok, error)
    valid_flag = {
        "flag_id": "EXP-1",
        "agent": "expert-participant",
        "flag_type": "over-explanation",
        "severity": "medium",
        "section_anchor": "### 2. Context and Current State (10 min)",
        "quoted_evidence": "An invoice, as you may know, is a document.",
        "why": "The persona approves invoices weekly.",
        "suggested_minimal_fix": "Cut the definition.",
        "synthetic": True,
        "artifact_grounded": False,
        "confidence": "asserted",
    }
    ok, error = validate_review_json([valid_flag])
    check("schema: valid expert flag passes", ok, error)
    bad_flag = dict(valid_flag, flag_type="flat-answer-risk", confidence="asserted")
    ok, error = validate_review_json([bad_flag])
    check("schema: flat-answer-risk with asserted fails", not ok, "validated")
    hedged_flag = dict(valid_flag, flag_type="flat-answer-risk", confidence="hedged")
    ok, error = validate_review_json([hedged_flag])
    check("schema: flat-answer-risk with hedged passes", ok, error)
    cross_flag = dict(valid_flag, agent="novice-participant")
    ok, error = validate_review_json([cross_flag])
    check("schema: novice cannot emit expert flag type", not ok, "validated")
    grounded_flag = {
        "flag_id": "NOV-1",
        "agent": "novice-participant",
        "flag_type": "unexecutable-step",
        "severity": "high",
        "section_anchor": "### 4. Design Walkthrough (10 min)",
        "quoted_evidence": "4. Click 'Export to PDF'.",
        "why": "The manifest has no such control.",
        "suggested_minimal_fix": "Name a control the manifest confirms.",
        "synthetic": True,
        "artifact_grounded": True,
        "confidence": "asserted",
    }
    ok, error = validate_review_json([grounded_flag])
    check("schema: artifact-grounded novice flag passes", ok, error)
    grounded_bad = dict(grounded_flag, agent="expert-participant")
    ok, error = validate_review_json([grounded_bad])
    check("schema: expert cannot emit artifact-grounded flag", not ok, "validated")
    valid_edit = {
        "edit_id": "ED-1",
        "resolves_flag_ids": ["NOV-1"],
        "section_anchor": "### 4. Design Walkthrough (10 min)",
        "before_text": "4. Click 'Export to PDF'.",
        "after_text": "4. Open the export panel.",
        "edit_kind": "sentence-rewrite",
        "hard_rule_preserved": "structure-invariant",
    }
    ok, error = validate_review_json([valid_edit])
    check("schema: valid edit passes", ok, error)
    empty_edit = dict(valid_edit, resolves_flag_ids=[])
    ok, error = validate_review_json([empty_edit])
    check("schema: edit with empty resolves_flag_ids fails", not ok, "validated")
    ok, error = validate_review_json({"flags": [valid_flag], "edits": [valid_edit]})
    check("schema: envelope object passes", ok, error)

    # 8. Header order and heading levels.
    text = _replace_once(
        _fixture(),
        "Jira Ticket: PROJ-482\nPrototype Link: https://example.test/proto/invoice-approval\nUXR: Alex Rivera",
        "UXR: Alex Rivera\nJira Ticket: PROJ-482\nPrototype Link: https://example.test/proto/invoice-approval",
    )
    code, findings = run(text)
    check("header line out of order exits 3",
          code == EXIT_BLOCK and "header-order" in names(findings), f"exit {code}")
    text = "\n".join(
        line for line in _fixture().splitlines()
        if line.strip() != "## Moderator Notes" and "Record the session" not in line
        and "Keep the session" not in line
    )
    code, findings = run(text)
    check("missing Moderator Notes H2 exits 3",
          code == EXIT_BLOCK and "heading-levels" in names(findings), f"exit {code}")

    # 9. Numbering near-misses.
    text = _replace_once(_fixture(), "   a. Who saw it next?", "  a. Who saw it next?")
    code, findings = run(text)
    check("probe indent near-miss exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(), "   a. Where did it stall?", "   a. Where did it stall. Not a question"
    )
    text = _replace_once(
        text,
        "5. [if they mention exports] What were you trying to produce?",
        "5. [if they mention exports] Tell me what you were trying to produce",
    )
    code, findings = run(text)
    check("conditional without ? exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")
    text = _replace_once(_fixture(), "   b. Who unblocked it?", "   c. Who unblocked it?")
    code, findings = run(text)
    check("probe letter gap exits 3",
          code == EXIT_BLOCK and "numbering" in names(findings), f"exit {code}")

    # 10. Survey label with no item text blocks; wording drift warns.
    text = _replace_once(
        _fixture(),
        "**[umux_lite_usability_7_point]. ** This system is easy to use.",
        "**[umux_lite_usability_7_point]. **",
    )
    code, findings = run(text)
    check("survey label with no text exits 3",
          code == EXIT_BLOCK and "survey-label" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(),
        "**[umux_lite_usability_7_point]. ** This system is easy to use.",
        "**[umux_lite_usability_7_point]. ** This system is simple to use.",
    )
    code, findings = run(text)
    check("survey wording drift exits 1",
          code == EXIT_WARN and "survey-wording" in names(findings), f"exit {code}")

    # 11. Double negative warns; RQ coverage gap warns.
    text = _replace_once(
        _fixture(),
        "6. If you owned the approval flow, what would you change first?",
        "6. What did you not like, and what would you never use again?",
    )
    code, findings = run(text)
    check("double negative exits 1",
          code == EXIT_WARN and "double-negative" in names(findings), f"exit {code}")
    text = _replace_once(
        _fixture(), "| RQ2 | Discover Problem | JTBD | 4, 5, 6 |",
        "| RQ2 | Discover Problem | JTBD | see above |",
    )
    code, findings = run(text)
    check("RQ row without script question exits 1",
          code == EXIT_WARN and "rq-coverage" in names(findings), f"exit {code}")

    # 12. Reading-level classification boundaries (no textstat needed).
    check("reading-level grade 9.5 is ok", _classify_grade(9.5, cfg) == "ok")
    check("reading-level grade 10.5 is warn", _classify_grade(10.5, cfg) == "warn")
    check("reading-level grade 12.5 is block", _classify_grade(12.5, cfg) == "block")

    # 13. CLI end to end.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "interview-script-PROJ-482.md"
        path.write_text(_fixture(), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check on canonical fixture exits 0", proc.returncode == EXIT_CLEAN,
              proc.stdout[-300:])
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check"],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check without a path exits 2", proc.returncode == EXIT_UNPARSEABLE,
              f"exit {proc.returncode}")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "check", str(Path(tmp) / "nope.md")],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI check on a missing file exits 2", proc.returncode == EXIT_UNPARSEABLE,
              f"exit {proc.returncode}")

    # 14. Survey mode (issue 53): the four survey checks on the skill's shape.
    def survey_fixture() -> str:
        return "\n".join([
            "# Survey Instrument: Invoice Approvals",
            "",
            "Jira Ticket: PROJ-482",
            "UXR: Alex Rivera",
            "**Time budget**: 15 min",
            "**Burden budget**: 6 questions",
            "**Method**: Survey",
            "**Date drafted**: 2026-11-22",
            "**Drafted from**: ticket PROJ-482",
            "",
            "## Research Questions",
            "",
            "1. How do teams approve invoices today?",
            "",
            "## Routing Map",
            "",
            "- from Q3 [if they use an approval tool] to Q5",
            "",
            "## Survey",
            "",
            "### 1. Context (3 questions)",
            "",
            "1. Which best describes your role?",
            "2. How many invoices does your team handle in a week?",
            "3. [if they use an approval tool] Which tool do you use?",
            "",
            "### 2. Detail (3 questions)",
            "",
            "4. Walk me through the last approval you saw stall.",
            "5. How long did the stall last?",
            "6. What would have prevented the stall?",
            "",
            "## Alternatives",
            "",
            "- Q1: 3 alternatives tried; kept: the role card with five options",
            "- Q2: 2 alternatives tried; kept: the weekly count wording",
            "- Q4: 2 alternatives tried; kept: the walk-through wording",
            "- Q6: 4 alternatives tried; kept: the prevention wording",
            "",
            "## Join and Segmentation Fields",
            "",
            "- Join: org_id from the CRM table; segmentation by team size band.",
            "",
            "## Research Question -> Survey Question Map",
            "",
            "| RQ | Question type | Survey Qs | Stakeholder Value |",
            "|---|---|---|---|",
            "| RQ1 | open + factual | 2, 4, 6 | Surfaces the stall causes |",
            "",
            "## Quality Check",
            "",
            "- Checker: review_checks.py survey exit 0 on this draft.",
            "",
        ])

    findings = check_survey_text(survey_fixture())
    check("survey mode: the canonical instrument is clean",
          _exit_code(findings) == EXIT_CLEAN and not findings,
          repr([f.render() for f in findings])[:200])

    shifted = survey_fixture().replace("### 1. Context (3 questions)",
                                       "### 1. Context (4 questions)")
    findings = check_survey_text(shifted)
    check("survey mode: a section count mismatch blocks",
          _exit_code(findings) == EXIT_BLOCK
          and any(f.check == "burden-count" for f in findings),
          repr([f.render() for f in findings])[:200])

    dead = survey_fixture().replace("- from Q3 [if they use an approval tool] to Q5",
                                    "- from Q3 [if they use an approval tool] to Q9")
    findings = check_survey_text(dead)
    names = {f.check for f in findings}
    check("survey mode: a routing dead end blocks",
          _exit_code(findings) == EXIT_BLOCK and "routing-parse" in names,
          repr([f.render() for f in findings])[:200])

    unmapped = survey_fixture().replace("- from Q3 [if they use an approval tool] to Q5\n", "")
    findings = check_survey_text(unmapped)
    check("survey mode: a conditional question with no routing row blocks",
          any(f.check == "routing-parse" and "unmapped skip path" in f.detail
              for f in findings),
          repr([f.render() for f in findings])[:200])

    under = survey_fixture().replace("- Q4: 2 alternatives tried; kept: the walk-through wording\n", "")
    findings = check_survey_text(under)
    check("survey mode: a core question with no alternatives record blocks",
          any(f.check == "alternatives" and "no alternatives record for Q4" in f.detail
              for f in findings),
          repr([f.render() for f in findings])[:200])

    over = survey_fixture().replace("- Q1: 3 alternatives tried", "- Q1: 6 alternatives tried")
    findings = check_survey_text(over)
    check("survey mode: more than five alternatives blocks",
          any(f.check == "alternatives" and "records 6 alternatives" in f.detail
              for f in findings),
          repr([f.render() for f in findings])[:200])

    uncovered = survey_fixture().replace("| RQ1 | open + factual | 2, 4, 6 | Surfaces the stall causes |",
                                         "| RQ1 | open + factual | none yet | Surfaces the stall causes |")
    findings = check_survey_text(uncovered)
    check("survey mode: an uncovered RQ map row warns",
          _exit_code(findings) == EXIT_WARN and any(f.check == "coverage" for f in findings),
          repr([f.render() for f in findings])[:200])

    bare = "# Survey\n\n## Survey\n\n### 1. A (1 questions)\n\n1. Hi?\n"
    findings = check_survey_text(bare)
    check("survey mode: a missing burden line and map exit 2",
          _exit_code(findings) == EXIT_UNPARSEABLE,
          repr([f.detail for f in findings])[:200])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "survey-instrument-PROJ-482.md"
        path.write_text(survey_fixture(), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "survey", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI survey on the canonical instrument exits 0",
              proc.returncode == EXIT_CLEAN and "review_checks.py survey" in proc.stdout,
              proc.stdout[-300:])
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "survey"],
            capture_output=True, text=True, timeout=30,
        )
        check("CLI survey without a path exits 2", proc.returncode == EXIT_UNPARSEABLE,
              f"exit {proc.returncode}")

    # 15. The check mode still owns the fixture: interview output unchanged.
    findings = check_text(_fixture(), cfg=cfg, quant_items=quant)
    check("check mode on the interview fixture stays clean",
          _exit_code(findings) == EXIT_CLEAN
          and all(f.severity != "block" for f in findings),
          repr([f.render() for f in findings])[:200])

    print(f"review_checks.py selftest")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
