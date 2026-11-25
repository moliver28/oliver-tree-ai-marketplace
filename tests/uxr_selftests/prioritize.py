from _harness import bind

import builtins  # selftest-only import (the runtime-ask probes)
import io  # selftest-only import (the stderr capture for the ask probes)
import os  # selftest-only import (env-config CLI probes)
import subprocess  # selftest-only import (the CLI probes)
import tempfile  # selftest-only import (the --record probe)
from pathlib import Path  # selftest-only import (the CLI probe path)

bind("scripts.prioritize", globals())

#: the shipped plugin root, two levels up from tests/uxr_selftests/
PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"

#: the preset criteria answered all-3s: mean 3.0 -> P3 Nice to Do
ALL_THREES = {name: "3" for name in PRESET_NAMES}

#: the MO-renamed support level labels (2026-11-24); the handbook's
#: metal names never ship
LEVEL_LABELS = ("UXR to Lead", "UXR to Support", "UXR to Review")


def _raises(exc_class, function, *args, **kwargs):
    """Run function; return the exception instance, or None when none raised."""
    try:
        function(*args, **kwargs)
    except exc_class as exc:
        return exc
    except Exception as exc:  # wrong exception class is a failure, not a crash
        return exc
    return None


def _env_cli(*args, stdin_text=None, **extra_env):
    """Run the shipped CLI with env-injected config; hermetic on any machine."""
    env = dict(os.environ)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "prioritize.py"), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=8, env=env,
        input=stdin_text,
    )


#: force the zero-config preset path even on a machine with a user config
PRESET_ENV = {
    "UXR_CONFIG__TRACKER__KIND": "",
    "UXR_CONFIG__PRIORITY__FORMULA": "",
    "UXR_CONFIG__PRIORITY__WEIGHTS": "{}",
    "UXR_CONFIG__PRIORITIZATION__FIELDS__JIRA": "{}",
    "UXR_CONFIG__PRIORITIZATION__FIELDS__GITHUB": "{}",
    "UXR_CONFIG__PRIORITIZATION__FIELDS__GITLAB": "{}",
    "UXR_CONFIG__PRIORITIZATION__FIELDS__NOTION": "{}",
}


class _FakeInput:
    """Replace builtins.input with a scripted answer list (deterministic)."""

    def __init__(self, answers):
        self.answers = list(answers)

    def __call__(self, prompt=""):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class _CaptureErr:
    """Swap sys.stderr for a buffer (the ask prints its prompts there)."""

    def __init__(self):
        self.buffer = io.StringIO()

    def write(self, text):
        self.buffer.write(text)
        return len(text)

    def flush(self):
        return None


def _with_input(answers):
    """Run a probe under the scripted input and a captured stderr; return
    ``(captured_stderr, restore)``."""
    real_input = builtins.input
    real_err = sys.stderr
    builtins.input = _FakeInput(answers)
    capture = _CaptureErr()
    sys.stderr = capture

    def restore():
        builtins.input = real_input
        sys.stderr = real_err

    return capture, restore


def _selftest() -> int:
    """Cover the prioritization calculator laws (issue 114 section 2, MO
    ruling 2026-11-24).

    The GitLab handbook default preset (six criteria, 1 to 5, unweighted
    mean, the five bands verbatim), weight and formula overrides in the
    weighted-sum mode, the normalization law per rule kind and scale, the
    per-backend mapping keyed by tracker kind, the runtime ask (recorded
    and used, zero-LLM), the support mode with the renamed level labels,
    the unknown-input usage error, and the CLI exit-code contract. No
    network; the --record probe writes only under the machine temp dir.
    """
    print("scripts/prioritize.py test module")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. Zero configuration: the handbook preset is the default (MO ruling).
    inputs = resolve_inputs({}, "")
    check(
        "zero-config inputs are the six handbook criteria",
        [(i["name"], i["weight"], i["scale"]) for i in inputs]
        == [(name, 1.0, 5) for name in PRESET_NAMES]
        and all(i["rule"] is None for i in inputs),
        repr(inputs),
    )
    check("preset criteria are the handbook six",
          PRESET_NAMES == ("impact", "users", "dependency", "timeline",
                           "alternatives", "alignment"), repr(PRESET_NAMES))
    check("zero-config mode is preset", mode_of({}) == "preset", None)
    check("zero-config formula text is the handbook mean",
          formula_text({}, inputs) == PRESET_FORMULA, formula_text({}, inputs))
    check("preset formula names all six criteria unweighted",
          PRESET_FORMULA == "mean(impact, users, dependency, timeline, "
          "alternatives, alignment)", PRESET_FORMULA)
    result = score({}, "", ALL_THREES)
    check(
        "preset all-3s scores mean 3 into P3 Nice to Do",
        result["mode"] == "preset" and result["mean"] == 3
        and result["band"] == "P3 Nice to Do" and result["total"] == 18,
        repr(result),
    )
    check("preset result cites the handbook source", result["source"] == PRESET_URL
          and "handbook.gitlab.com" in result["source"], repr(result.get("source")))

    # 2. The five bands, names verbatim, boundaries included (MO ruling).
    check("band names and bounds verbatim",
          PRESET_BANDS == ((1.5, "P1 Must Do"), (2.4, "P2 Should Do"),
                           (3.5, "P3 Nice to Do"), (4.5, "P4 Backlog"),
                           (None, "Will Not Do")), repr(PRESET_BANDS))
    check("band_of: 1.5 is P1 (the boundary itself)",
          band_of(1.5) == "P1 Must Do", band_of(1.5))
    check("band_of: 2.4 is P2, 2.5 is P3",
          band_of(2.4) == "P2 Should Do" and band_of(2.5) == "P3 Nice to Do", None)
    check("band_of: 3.5 is P3, 3.6 is P4",
          band_of(3.5) == "P3 Nice to Do" and band_of(3.6) == "P4 Backlog", None)
    check("band_of: 4.5 is P4, above is Will Not Do",
          band_of(4.5) == "P4 Backlog" and band_of(4.5001) == "Will Not Do"
          and band_of(5.0) == "Will Not Do", None)
    nine = score({}, "", {name: "1" for name in PRESET_NAMES[:3]}
                 | {name: "2" for name in PRESET_NAMES[3:]})
    check("score-driven band: sum 9 is mean 1.5 -> P1 Must Do",
          nine["total"] == 9 and nine["mean"] == 1.5
          and nine["band"] == "P1 Must Do", repr(nine["band"]))
    worst = score({}, "", {name: "5" for name in PRESET_NAMES[:4]}
                  | {name: "4" for name in PRESET_NAMES[4:]})
    check("score-driven band: sum 28 is mean ~4.67 -> Will Not Do",
          worst["total"] == 28 and worst["band"] == "Will Not Do", repr(worst["band"]))

    # 3. Overrides stay reachable: weights or formula switch to the
    #    weighted-sum mode (the custom-formula path; scale 1 to 3).
    check("weights-only sets the sum mode",
          mode_of({"priority": {"weights": {"reach": 5}}}) == "sum", None)
    weighted = {"priority": {"weights": {"reach": 5, "confidence": 2}}}
    inputs = resolve_inputs(weighted, "")
    check(
        "weight override resolves in the sum mode at scale 3",
        [(i["name"], i["weight"], i["scale"]) for i in inputs]
        == [("reach", 5.0, 3), ("confidence", 2.0, 3)],
        repr(inputs),
    )
    result = score(weighted, "", {"reach": "3", "confidence": "2"})
    check("weighted score computes (19)", result["mode"] == "sum"
          and result["score"] == 19, repr(result.get("score")))
    formed = {"priority": {"formula": "reach*4 + confidence", "weights": {"confidence": 9}}}
    inputs = resolve_inputs(formed, "")
    check(
        "formula override: explicit term weight wins over weights",
        [(i["name"], i["weight"]) for i in inputs] == [("reach", 4.0), ("confidence", 9.0)],
        repr(inputs),
    )
    formed2 = {"priority": {"formula": "reach*4 + confidence"}}
    check(
        "formula term without weight and without weights carries 1",
        [i["weight"] for i in resolve_inputs(formed2, "")] == [4.0, 1.0],
        repr(resolve_inputs(formed2, "")),
    )
    check("formula text echoes the override",
          formula_text(formed, inputs) == "reach*4 + confidence", None)
    check("the dropped default formula stays reachable as a custom formula",
          score({"priority": {"formula": "impact*3 + confidence*2 + urgency*1"}}, "",
                {"impact": "3", "confidence": "2", "urgency": "1"})["score"] == 14, None)
    check("empty formula string takes the preset path",
          mode_of({"priority": {"formula": "  "}}) == "preset", None)
    check("empty weights mapping takes the preset path",
          mode_of({"priority": {"weights": {}}}) == "preset", None)

    # 4. Usage errors (exit 2): unknown input, bad formula, bad weight,
    #    bad backend, non-criterion mapping name in preset mode.
    err = _raises(UsageError, score, {}, "", dict(ALL_THREES, reach="1"))
    check("unknown input name raises usage error", isinstance(err, UsageError), repr(err))
    check("unknown-input message names the input", err is not None and "reach" in str(err), repr(err))
    check("duplicate formula name raises", isinstance(
        _raises(UsageError, _parse_formula, "reach + reach*2"), UsageError), None)
    check("malformed formula term raises", isinstance(
        _raises(UsageError, _parse_formula, "reach* reach"), UsageError), None)
    check("non-numeric weight raises", isinstance(
        _raises(UsageError, resolve_inputs, {"priority": {"weights": {"reach": "high"}}}, ""),
        UsageError), None)
    check("unknown backend kind raises", isinstance(
        _raises(UsageError, backend_of, {}, "spreadsheet"), UsageError), None)
    check("backend flag wins over tracker.kind",
          backend_of({"tracker": {"kind": "jira"}}, "github") == "github", None)
    check("empty flag falls back to tracker.kind",
          backend_of({"tracker": {"kind": "jira"}}, None) == "jira", None)
    stray = {"prioritization": {"fields": {"jira": {"reach": {"kind": "number", "low": 1, "high": 5}}}}}
    err = _raises(UsageError, resolve_inputs, stray, "jira")
    check("preset mode: non-criterion mapping name raises", isinstance(err, UsageError), repr(err))
    check("non-criterion message names the criteria", err is not None
          and "reach" in str(err) and "alignment" in str(err), repr(err))
    check("sum mode has no non-criterion constraint",
          [i["name"] for i in resolve_inputs(
              {"priority": {"weights": {"reach": 2}},
               "prioritization": {"fields": {"jira": stray["prioritization"]["fields"]["jira"]}}},
              "jira")] == ["reach"], None)

    # 5. Per-backend mapping, one assertion per kind where the mapping
    #    differs; rules attach to preset criteria at scale 5.
    per_backend = {
        "prioritization": {
            "fields": {
                "jira": {
                    "impact": {"id": "customfield_10130", "kind": "select",
                               "values": ["Low", "Medium", "High"]},
                },
                "github": {
                    "impact": {"id": "impact/", "kind": "labels",
                               "values": ["impact/low", "impact/medium", "impact/high"]},
                },
                "gitlab": {
                    "timeline": {"id": "weight", "kind": "number", "low": 1, "high": 10},
                },
                "notion": {
                    "users": {"id": "Reach", "kind": "select",
                              "values": ["All", "Large", "Medium", "Small", "Few"]},
                },
            }
        }
    }
    jira = resolve_inputs(per_backend, "jira")
    rule = next(i["rule"] for i in jira if i["name"] == "impact")
    check("jira rule: select custom field on the preset criterion",
          rule is not None and rule["kind"] == "select"
          and rule["id"] == "customfield_10130", repr(rule))
    check("jira unmapped criteria stay answerable 1 to 5",
          next(i for i in jira if i["name"] == "alignment")["rule"] is None
          and next(i for i in jira if i["name"] == "alignment")["scale"] == 5, None)
    github = resolve_inputs(per_backend, "github")
    rule = next(i["rule"] for i in github if i["name"] == "impact")
    check("github rule: labels", rule["kind"] == "labels"
          and rule["values"][0] == "impact/low", repr(rule))
    gitlab = resolve_inputs(per_backend, "gitlab")
    rule = next(i["rule"] for i in gitlab if i["name"] == "timeline")
    check("gitlab rule: number weight with bounds",
          rule["kind"] == "number" and rule["low"] == 1 and rule["high"] == 10, repr(rule))
    notion = resolve_inputs(per_backend, "notion")
    rule = next(i["rule"] for i in notion if i["name"] == "users")
    check("notion rule: select property with five values",
          rule["kind"] == "select" and rule["id"] == "Reach"
          and len(rule["values"]) == 5, repr(rule))
    check("mappings are kind-keyed: github does not see the jira rule",
          next(i for i in github if i["name"] == "impact")["rule"]["kind"] == "labels"
          and "customfield" not in str(field_rules(per_backend, "github")), None)
    check("unknown kind maps to no rules", field_rules(per_backend, "linear") == {}, None)
    check("empty section maps to no rules",
          field_rules({"prioritization": {"fields": {}}}, "jira") == {}, None)
    err = _raises(UsageError, field_rules,
                  {"prioritization": {"fields": {"jira": {"impact": {"kind": "select"}}}}}, "jira")
    check("select rule without values raises (named)", isinstance(err, UsageError), repr(err))
    err = _raises(UsageError, field_rules,
                  {"prioritization": {"fields": {"jira": {"impact": {"kind": "stars"}}}}}, "jira")
    check("unknown rule kind raises", isinstance(err, UsageError), repr(err))
    scored = score(per_backend, "jira",
                   {"impact": "Medium", "users": "3", "dependency": "2",
                    "timeline": "4", "alternatives": "4", "alignment": "5"})
    jira_terms = {t["input"]: t["normalized"] for t in scored["terms"]}
    check("mapped values normalize at scale 5 (jira select -> 3)",
          jira_terms["impact"] == 3 and scored["mode"] == "preset", repr(jira_terms))
    scored_gl = score(per_backend, "gitlab",
                      {"impact": "2", "users": "3", "dependency": "2",
                       "timeline": "8", "alternatives": "4", "alignment": "5"})
    gl_terms = {t["input"]: t["normalized"] for t in scored_gl["terms"]}
    check("gitlab number bounds map linearly onto 1..5 (8 in 1..10 -> 4)",
          gl_terms["timeline"] == 4, repr(gl_terms))
    check("select 3 values map 1 3 5 at scale 5",
          [normalize_input({"name": "impact", "scale": 5,
                            "rule": {"kind": "select", "values": ["Low", "Medium", "High"]}}, v)
           for v in ("Low", "Medium", "High")] == [1, 3, 5], None)
    check("labels best match wins at scale 5",
          normalize_input({"name": "impact", "scale": 5,
                           "rule": {"kind": "labels",
                                    "values": ["impact/low", "impact/medium", "impact/high"]}},
                          "impact/low,impact/high") == 5, None)
    check("select 5 values map 1 2 3 4 5",
          [normalize_input(next(i for i in notion if i["name"] == "users"), v)
           for v in ("All", "Large", "Medium", "Small", "Few")] == [1, 2, 3, 4, 5], None)
    bounded = {"name": "timeline", "scale": 5, "rule": {"kind": "number", "low": 1, "high": 10}}
    check("number bounds map linearly onto 1 to 5",
          normalize_input(bounded, "1") == 1 and normalize_input(bounded, "10") == 5
          and normalize_input(bounded, "5.5") == 3, None)
    check("number below low clamps to 1", normalize_input(bounded, "0") == 1, None)
    loose = {"name": "timeline", "scale": 5, "rule": {"kind": "number"}}
    check("number without bounds rounds and clamps onto 1 to 5",
          normalize_input(loose, "2.4") == 2 and normalize_input(loose, "9") == 5
          and normalize_input(loose, "0") == 1, None)
    check("select matches without case",
          normalize_input({"name": "impact", "scale": 5,
                           "rule": {"kind": "select", "values": ["Low", "Medium", "High"]}},
                          "HIGH") == 5, None)
    err = _raises(NormalizeError, normalize_input, bounded, "abc")
    check("unnormalizable value raises value error", isinstance(err, NormalizeError), repr(err))

    # 6. The runtime ask: deterministic numbered prompt printing the
    #    handbook scale wording; recorded and used; zero-LLM.
    err_buf, restore = _with_input(["2", "3", "1", "2", "4", "2"])
    try:
        asked = ask_missing_preset(resolve_inputs({}, ""))
    finally:
        restore()
    check("ask returns every criterion's answer",
          asked == {"impact": "2", "users": "3", "dependency": "1",
                    "timeline": "2", "alternatives": "4", "alignment": "2"}, repr(asked))
    check("ask prompts print the handbook scale wording (on stderr)",
          "Critical Impact - major risks" in err_buf.buffer.getvalue()
          and "What is the business impact" in err_buf.buffer.getvalue()
          and "No timeline pressure" in err_buf.buffer.getvalue(),
          err_buf.buffer.getvalue()[:80])
    result = score({}, "", dict(asked), asked=asked)
    check("asked answers are recorded in the result",
          result["asked"] == list(PRESET_NAMES), repr(result.get("asked")))
    check("asked answers are used (mean 2.3333 -> P2)",
          result["mean"] == 2.3333 and result["band"] == "P2 Should Do", repr(result["mean"]))
    err_buf, restore = _with_input(["9", "3"])
    try:
        asked = ask_missing_preset([next(i for i in resolve_inputs({}, "")
                                         if i["name"] == "users")])
    finally:
        restore()
    check("out-of-range answer gets one bounded re-ask, then sticks",
          asked == {"users": "3"}
          and err_buf.buffer.getvalue().count("answer 1-5") == 2, repr(asked))
    err_buf, restore = _with_input(["nope", "nah"])
    try:
        err = _raises(NormalizeError, ask_missing_preset,
                      [next(i for i in resolve_inputs({}, "") if i["name"] == "users")])
    finally:
        restore()
    check("refused twice is a value error naming the criterion",
          isinstance(err, NormalizeError) and "users" in str(err), repr(err))
    err_buf, restore = _with_input([])
    try:
        err = _raises(NormalizeError, ask_missing_support)
    finally:
        restore()
    check("an ended ask is a value error, never a guess",
          isinstance(err, NormalizeError) and "ended without an answer" in str(err), repr(err))
    err_buf, restore = _with_input(["3"])
    try:
        asked = ask_missing_support(skip={"type", "ownership", "complexity",
                                          "skill", "confidence"})
    finally:
        restore()
    check("support ask skips the supplied criteria",
          asked == {"design": "3"}
          and err_buf.buffer.getvalue().count("answer 1-3") == 1, repr(asked))
    support_rule_input = {"name": "impact", "scale": 5,
                          "rule": {"kind": "select", "values": ["Low", "Medium", "High"]}}
    err_buf, restore = _with_input(["Medium"])
    try:
        asked = ask_missing_preset([support_rule_input])
    finally:
        restore()
    check("mapped criterion accepts a tracker value at the ask",
          asked == {"impact": "Medium"}, repr(asked))
    check("asked tracker value normalizes through the rule",
          score(per_backend, "jira",
                {"impact": "Medium", "users": "3", "dependency": "3",
                 "timeline": "3", "alternatives": "3", "alignment": "3"},
                asked={"impact": "Medium"})["terms"][0]["normalized"] == 3, None)
    check("asked numbered answer bypasses the rule at its own scale",
          score(per_backend, "jira",
                {"impact": "3", "users": "3", "dependency": "3", "timeline": "3",
                 "alternatives": "3", "alignment": "3"},
                asked={"impact": "3"})["terms"][0]["normalized"] == 3, None)

    # 7. Support mode: the handbook criteria and points, sum / 17 (the
    #    total possible), the MO-renamed labels (never the metal names).
    check("support total possible is 17 (divisor correction 2026-11-24)",
          SUPPORT_TOTAL == 17, repr(SUPPORT_TOTAL))
    check("total possible equals the summed maxima (3+3+3+2+3+3)",
          SUPPORT_TOTAL == sum(max(points for _, points in c["choices"])
                               for c in SUPPORT_CRITERIA), None)
    check("support criteria are the handbook six",
          SUPPORT_NAMES == ("type", "ownership", "design", "complexity",
                            "skill", "confidence"), repr(SUPPORT_NAMES))
    check("type points: foundational 3 / problem validation 2 / solution validation 1",
          [support_points("type", c)[0] for c in
           ("foundational", "problem validation", "solution validation")] == [3, 2, 1], None)
    check("ownership points: yes 3 / somewhat 2 / no 1",
          [support_points("ownership", c)[0] for c in ("yes", "somewhat", "no")] == [3, 2, 1], None)
    check("design points: led by uxr 3 / has designers 2 / no designers 1",
          [support_points("design", c)[0] for c in
           ("study led by uxr", "requesting team has designers", "no designers")] == [3, 2, 1],
          None)
    check("complexity points: yes 2 / no 1 / unknown 0",
          [support_points("complexity", c)[0] for c in ("yes", "no", "unknown")] == [2, 1, 0], None)
    check("skill points: yes 3 / somewhat 2 / no 1",
          [support_points("skill", c)[0] for c in ("yes", "somewhat", "no")] == [3, 2, 1], None)
    check("confidence points: high 3 / medium 2 / low 1",
          [support_points("confidence", c)[0] for c in ("high", "medium", "low")] == [3, 2, 1], None)
    check("choice answers match without case and take numbers",
          support_points("type", "Foundational")[0] == 3
          and support_points("type", "2")[0] == 2, None)
    err = _raises(NormalizeError, support_points, "type", "aggressive")
    check("off-list support value raises value error", isinstance(err, NormalizeError), repr(err))
    check("boundary 80.0 is UXR to Support", support_level(80.0) == "UXR to Support", None)
    check("boundary just above 80 is UXR to Lead",
          support_level(80.01) == "UXR to Lead" and support_level(100.0) == "UXR to Lead", None)
    check("boundary 51 is UXR to Support",
          support_level(51.0) == "UXR to Support"
          and support_level(50.01) == "UXR to Support", None)
    check("boundary 50.0 is UXR to Review",
          support_level(50.0) == "UXR to Review" and support_level(0.0) == "UXR to Review", None)
    check("the level labels are the MO renames", LEVEL_LABELS == tuple(
        label for label, _ in SUPPORT_LEVELS), repr(SUPPORT_LEVELS))
    shipped = (PLUGIN_ROOT / "scripts" / "prioritize.py").read_text(encoding="utf-8")
    check("the metal names never ship",
          all(metal not in shipped for metal in ("Gold", "Silver", "Bronze")), None)
    check("each level names its behavior in one doc line",
          "drives the study end to end" in shipped
          and "takes specified tasks within the study" in shipped
          and "consulted and reviews" in shipped, None)
    best = support_score({"type": "foundational", "ownership": "yes",
                          "design": "study led by uxr", "complexity": "yes",
                          "skill": "yes", "confidence": "high"})
    check("the all-max judgment is sum 17 -> exactly 100% -> UXR to Lead",
          best["total"] == 17 and best["percent"] == 100.0
          and best["level"] == "UXR to Lead", repr(best["percent"]))
    hundred = support_score({"type": "foundational", "ownership": "yes",
                             "design": "study led by uxr", "complexity": "yes",
                             "skill": "yes", "confidence": "medium"})
    check("sum 16 -> 94.12% -> UXR to Lead",
          hundred["total"] == 16 and hundred["percent"] == 94.12
          and hundred["level"] == "UXR to Lead", repr(hundred["percent"]))
    lead_edge = support_score({"type": "foundational", "ownership": "yes",
                               "design": "study led by uxr", "complexity": "yes",
                               "skill": "somewhat", "confidence": "low"})
    check("sum 14 -> 82.35% -> UXR to Lead (the real landing above 80)",
          lead_edge["total"] == 14 and lead_edge["percent"] == 82.35
          and lead_edge["level"] == "UXR to Lead", repr(lead_edge["level"]))
    mid = support_score({"type": "foundational", "ownership": "yes",
                         "design": "study led by uxr", "complexity": "yes",
                         "skill": "no", "confidence": "low"})
    check("sum 13 -> 76.47% -> UXR to Support",
          mid["total"] == 13 and mid["percent"] == 76.47
          and mid["level"] == "UXR to Support", repr(mid["level"]))
    edge = support_score({"type": "problem validation", "ownership": "somewhat",
                          "design": "requesting team has designers", "complexity": "yes",
                          "skill": "yes", "confidence": "low"})
    check("sum 12 -> 70.59% -> UXR to Support",
          edge["total"] == 12 and edge["percent"] == 70.59
          and edge["level"] == "UXR to Support", repr(edge["level"]))
    support_edge = support_score({"type": "foundational", "ownership": "somewhat",
                                  "design": "no designers", "complexity": "no",
                                  "skill": "no", "confidence": "low"})
    check("sum 9 -> 52.94% -> UXR to Support (the real landing above 50)",
          support_edge["total"] == 9 and support_edge["percent"] == 52.94
          and support_edge["level"] == "UXR to Support", repr(support_edge["level"]))
    floor = support_score({"type": "problem validation", "ownership": "no",
                           "design": "requesting team has designers", "complexity": "no",
                           "skill": "no", "confidence": "low"})
    check("sum 8 -> 47.06% -> UXR to Review (the highest Review landing)",
          floor["total"] == 8 and floor["percent"] == 47.06
          and floor["level"] == "UXR to Review", repr(floor["level"]))
    full = {name: "1" for name in SUPPORT_NAMES}
    err = _raises(UsageError, support_score, dict(full, reach="1"))
    check("unknown support criterion raises usage error", isinstance(err, UsageError), repr(err))
    err = _raises(UsageError, support_score, {"type": "1"})
    check("missing support criteria raise usage error naming them",
          isinstance(err, UsageError) and "ownership" in str(err), repr(err))

    # 8. The CLI contract: usage exit 2, unknown backend exit 2, JSON
    #    score, the preset ask over a pipe, the support ask + record.
    probes = [
        ([], 2),
        (["bogus"], 2),
        (["score"], 2),
        (["inputs", "--backend", "spreadsheet"], 2),
        (["inputs", "--ask"], 2),
    ]
    for argv, want in probes:
        probe = _env_cli(*argv, **PRESET_ENV)
        check(f"cli {argv or ['(bare)']} exits {want}", probe.returncode == want,
              f"exit {probe.returncode}: {probe.stderr.strip()[:80]}")
    answers = "".join(f"{n}\n" for n in ("2", "3", "1", "2", "4", "2"))
    probe = _env_cli("score", "--ask", "--json", stdin_text=answers, **PRESET_ENV)
    try:
        payload = json.loads(probe.stdout)
        ok = (
            probe.returncode == 0
            and payload["mode"] == "preset"
            and payload["mean"] == 2.3333
            and payload["band"] == "P2 Should Do"
            and payload["asked"] == list(PRESET_NAMES)
        )
        check("cli preset --ask scores over a pipe", ok,
              f"exit {probe.returncode}: {probe.stdout[:120]} {probe.stderr[:80]}")
    except Exception as exc:
        check("cli preset --ask scores over a pipe", False, repr(exc))
    record_dir = tempfile.mkdtemp(prefix="uxr-prioritize-probe-")
    record_path = str(Path(record_dir) / "calculator-ask.json")
    support_answers = "".join(f"{n}\n" for n in ("1", "1", "1", "1", "2", "1"))
    probe = _env_cli("score", "--support", "--ask", "--record", record_path, "--json",
                     stdin_text=support_answers, **PRESET_ENV)
    try:
        payload = json.loads(probe.stdout)
        recorded = json.loads(Path(record_path).read_text(encoding="utf-8"))
        ok = (
            probe.returncode == 0
            and payload["mode"] == "support"
            and payload["total"] == 16
            and payload["percent"] == 94.12
            and payload["level"] == "UXR to Lead"
            and recorded["level"] == "UXR to Lead"
            and recorded["record_format"] == 1
            and recorded["asked"] == list(SUPPORT_NAMES)
        )
        check("cli support --ask records a deterministic file", ok,
              f"exit {probe.returncode}: {probe.stdout[:120]} {probe.stderr[:80]}")
    except Exception as exc:
        check("cli support --ask records a deterministic file", False, repr(exc))
    probe = _env_cli("score", "--support", "--ask", stdin_text="9\n9\n",
                     **PRESET_ENV)
    check("cli support ask refusing twice exits 3", probe.returncode == 3,
          f"exit {probe.returncode}: {probe.stderr.strip()[:80]}")
    env_formula = dict(PRESET_ENV)
    env_formula["UXR_CONFIG__PRIORITY__FORMULA"] = "impact*3 + confidence*2 + urgency*1"
    probe = _env_cli("score", "--value", "impact=3", "--value", "confidence=2",
                     "--value", "urgency=1", "--json", **env_formula)
    try:
        payload = json.loads(probe.stdout)
        check("cli custom formula override stays reachable (sum mode, exit 0)",
              probe.returncode == 0 and payload["mode"] == "sum"
              and payload["score"] == 14
              and payload["formula"] == "impact*3 + confidence*2 + urgency*1",
              probe.stdout[:120])
    except Exception as exc:
        check("cli custom formula override stays reachable", False, repr(exc))
    probe = _env_cli("score", "--ask", "--json", stdin_text="", **env_formula)
    check("cli --ask in the sum mode exits 2 (the shipped usage error)",
          probe.returncode == 2, f"exit {probe.returncode}: {probe.stderr.strip()[:80]}")
    probe = _env_cli("score", "--value", "reach=3", "--value", "impact=2",
                     "--value", "users=2", "--value", "dependency=2",
                     "--value", "timeline=2", "--value", "alternatives=2",
                     "--value", "alignment=2", **PRESET_ENV)
    check("cli unknown input name exits 2", probe.returncode == 2, probe.stderr[:80])
    probe = _env_cli("score", "--value", "impact=6", "--value", "users=2",
                     "--value", "dependency=2", "--value", "timeline=2",
                     "--value", "alternatives=2", "--value", "alignment=2", **PRESET_ENV)
    check("cli out-of-scale value exits 3", probe.returncode == 3, probe.stderr[:80])
    probe = _env_cli("inputs", "--json", **PRESET_ENV)
    try:
        payload = json.loads(probe.stdout)
        check("cli inputs --json parses with the preset law",
              probe.returncode == 0 and payload["mode"] == "preset"
              and len(payload["inputs"]) == 6
              and payload["inputs"][0]["scale"] == 5, probe.stdout[:120])
    except Exception as exc:
        check("cli inputs --json parses with the preset law", False, repr(exc))
    probe = _env_cli("inputs", "--support", "--json", **PRESET_ENV)
    try:
        payload = json.loads(probe.stdout)
        check("cli inputs --support --json parses",
              probe.returncode == 0 and payload["mode"] == "support"
              and payload["possible"] == 17
              and len(payload["criteria"]) == 6, probe.stdout[:120])
    except Exception as exc:
        check("cli inputs --support --json parses", False, repr(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
