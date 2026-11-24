from _harness import bind

import os  # selftest-only import (env-config CLI probes)
import subprocess  # selftest-only import (the CLI probes)
from pathlib import Path  # selftest-only import (the CLI probe path)

bind("scripts.prioritize", globals())

#: the shipped plugin root, two levels up from tests/uxr_selftests/
PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"


def _raises(exc_class, function, *args):
    """Run function; return the exception instance, or None when none raised."""
    try:
        function(*args)
    except exc_class as exc:
        return exc
    except Exception as exc:  # wrong exception class is a failure, not a crash
        return exc
    return None


def _env_cli(*args, **extra_env):
    """Run the shipped CLI with env-injected config; hermetic on any machine."""
    env = dict(os.environ)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "prioritize.py"), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=8, env=env,
    )


def _selftest() -> int:
    """Cover the prioritization calculator laws (issue 114 section 2).

    Zero-config defaults, weight and formula overrides, the normalization
    law per rule kind, the per-backend mapping keyed by tracker kind, the
    unknown-input usage error, and the CLI exit-code contract. No network,
    no writes; config arrives as plain dicts or env overrides.
    """
    print("scripts/prioritize.py test module")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. Zero configuration: the built-in default scores (issue 114 law).
    inputs = resolve_inputs({}, "")
    check(
        "zero-config inputs are the built-in three",
        [(i["name"], i["weight"]) for i in inputs]
        == [("impact", 3.0), ("confidence", 2.0), ("urgency", 1.0)]
        and all(i["rule"] is None for i in inputs),
        repr(inputs),
    )
    check("zero-config formula text is the built-in", formula_text({}, inputs) == BUILTIN_FORMULA,
          formula_text({}, inputs))
    result = score({}, "", {"impact": "3", "confidence": "2", "urgency": "1"})
    check(
        "zero-config score is the weighted sum (14)",
        result["score"] == 14
        and [t["normalized"] for t in result["terms"]] == [3, 2, 1]
        and [t["product"] for t in result["terms"]] == [9, 4, 1],
        repr(result),
    )

    # 2. Weight override honored; an unweighted input carries weight 1.
    weighted = {"priority": {"weights": {"reach": 5, "confidence": 2}}}
    inputs = resolve_inputs(weighted, "")
    check(
        "weight override resolves",
        [(i["name"], i["weight"]) for i in inputs] == [("reach", 5.0), ("confidence", 2.0)],
        repr(inputs),
    )
    result = score(weighted, "", {"reach": "3", "confidence": "2"})
    check("weighted score computes", result["score"] == 19, repr(result["score"]))

    # 3. Formula override honored: names, explicit weights, weight-1 default.
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
    result = score(formed, "", {"reach": "2", "confidence": "3"})
    check("formula score computes", result["score"] == 35, repr(result["score"]))
    check("formula text echoes the override",
          formula_text(formed, inputs) == "reach*4 + confidence", formula_text(formed, inputs))

    # 4. Usage errors (exit 2): unknown input, bad formula, bad weight, bad backend.
    err = _raises(UsageError, score, {}, "", {"impact": "3", "confidence": "2", "urgency": "1", "reach": "1"})
    check("unknown input name raises usage error", isinstance(err, UsageError), repr(err))
    check("unknown-input message names the input", err is not None and "reach" in str(err), repr(err))
    check("duplicate formula name raises", isinstance(
        _raises(UsageError, _parse_formula, "reach + reach*2"), UsageError),
        repr(_raises(UsageError, _parse_formula, "reach + reach*2")))
    check("malformed formula term raises", isinstance(
        _raises(UsageError, _parse_formula, "reach* reach"), UsageError), None)
    check("non-numeric weight raises", isinstance(
        _raises(UsageError, resolve_inputs, {"priority": {"weights": {"reach": "high"}}}, ""),
        UsageError), None)
    check("empty formula string takes the built-in path",
          [i["name"] for i in resolve_inputs({"priority": {"formula": "  "}}, "")]
          == ["impact", "confidence", "urgency"], None)
    check("unknown backend kind raises", isinstance(
        _raises(UsageError, backend_of, {}, "spreadsheet"), UsageError), None)
    check("backend flag wins over tracker.kind",
          backend_of({"tracker": {"kind": "jira"}}, "github") == "github", None)
    check("empty flag falls back to tracker.kind",
          backend_of({"tracker": {"kind": "jira"}}, None) == "jira", None)

    # 5. Per-backend mapping, one assertion per kind where the mapping differs.
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
                    "weight": {"id": "weight", "kind": "number", "low": 1, "high": 10},
                },
                "notion": {
                    "impact": {"id": "Impact", "kind": "select",
                               "values": ["Low", "Medium", "High"]},
                },
            }
        }
    }
    jira = field_rules(per_backend, "jira")
    check("jira rule: select custom field", jira["impact"]["kind"] == "select"
          and jira["impact"]["id"] == "customfield_10130", repr(jira))
    github = field_rules(per_backend, "github")
    check("github rule: labels", github["impact"]["kind"] == "labels"
          and github["impact"]["values"][0] == "impact/low", repr(github))
    gitlab = field_rules(per_backend, "gitlab")
    check("gitlab rule: number weight with bounds", gitlab["weight"]["kind"] == "number"
          and gitlab["weight"]["low"] == 1 and gitlab["weight"]["high"] == 10, repr(gitlab))
    notion = field_rules(per_backend, "notion")
    check("notion rule: select property", notion["impact"]["kind"] == "select"
          and notion["impact"]["id"] == "Impact", repr(notion))
    check("mappings are kind-keyed: github does not see the jira rule",
          field_rules(per_backend, "github").get("impact", {}).get("kind") == "labels"
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

    # 6. Normalization law per rule kind.
    select3 = {"name": "impact", "rule": {"kind": "select", "values": ["Low", "Medium", "High"]}}
    check("select 3 values map 1 2 3",
          [normalize_input(select3, v) for v in ("Low", "Medium", "High")] == [1, 2, 3],
          None)
    check("select matches without case", normalize_input(select3, "HIGH") == 3, None)
    select5 = {"name": "impact", "rule": {"kind": "select", "values": ["a", "b", "c", "d", "e"]}}
    check("select 5 values map proportionally (1 2 2 2 3)",
          [normalize_input(select5, v) for v in ("a", "b", "c", "d", "e")] == [1, 2, 2, 2, 3],
          None)
    select1 = {"name": "impact", "rule": {"kind": "select", "values": ["Only"]}}
    check("select 1 value maps 1", normalize_input(select1, "Only") == 1, None)
    err = _raises(NormalizeError, normalize_input, select3, "Huge")
    check("select off-list value raises value error", isinstance(err, NormalizeError), repr(err))
    labels = {"name": "impact", "rule": {"kind": "labels",
                                         "values": ["impact/low", "impact/medium", "impact/high"]}}
    check("labels: best match wins", normalize_input(labels, "impact/low,impact/high") == 3, None)
    check("labels: single match", normalize_input(labels, "impact/medium") == 2, None)
    err = _raises(NormalizeError, normalize_input, labels, "unrelated")
    check("labels: no match raises value error", isinstance(err, NormalizeError), repr(err))
    bounded = {"name": "weight", "rule": {"kind": "number", "low": 1, "high": 10}}
    check("number with bounds maps linearly",
          normalize_input(bounded, "1") == 1 and normalize_input(bounded, "10") == 3
          and normalize_input(bounded, "5.5") == 2,
          None)
    check("number below low clamps to 1", normalize_input(bounded, "0") == 1, None)
    loose = {"name": "weight", "rule": {"kind": "number"}}
    check("number without bounds rounds and clamps",
          normalize_input(loose, "2.4") == 2 and normalize_input(loose, "9") == 3
          and normalize_input(loose, "0") == 1,
          None)
    norule = {"name": "reach", "rule": None}
    check("no-rule input passes 1 to 3", normalize_input(norule, "2") == 2, None)
    err = _raises(NormalizeError, normalize_input, norule, "4")
    check("no-rule out-of-range raises value error", isinstance(err, NormalizeError), repr(err))
    err = _raises(NormalizeError, normalize_input, norule, "abc")
    check("no-rule non-numeric raises value error", isinstance(err, NormalizeError), repr(err))

    # 7. The CLI contract: usage exit 2, unknown backend exit 2, JSON score.
    probes = [
        ([], 2),
        (["bogus"], 2),
        (["score"], 2),
        (["inputs", "--backend", "spreadsheet"], 2),
    ]
    for argv, want in probes:
        probe = _env_cli(*argv)
        check(f"cli {argv or ['(bare)']} exits {want}", probe.returncode == want,
              f"exit {probe.returncode}: {probe.stderr.strip()[:80]}")
    env_config = {
        "UXR_CONFIG__TRACKER__KIND": "github",
        "UXR_CONFIG__PRIORITY__FORMULA": BUILTIN_FORMULA,
        "UXR_CONFIG__PRIORITIZATION__FIELDS__GITHUB__IMPACT": json.dumps(
            {"id": "impact/", "kind": "labels", "values": ["impact/low", "impact/medium", "impact/high"]}
        ),
    }
    probe = _env_cli("score", "--value", "impact=impact/medium,other", "--value", "confidence=2",
                     "--value", "urgency=1", "--json", **env_config)
    try:
        payload = json.loads(probe.stdout)
        ok = (
            probe.returncode == 0
            and payload["backend"] == "github"
            and payload["score"] == 11
            and payload["terms"][0]["normalized"] == 2
            and payload["formula"] == BUILTIN_FORMULA
        )
        check("cli github-labels score --json", ok, f"exit {probe.returncode}: {probe.stdout[:120]}")
    except Exception as exc:
        check("cli github-labels score --json", False, repr(exc))
    probe = _env_cli("score", "--value", "impact=impact/medium", **env_config)
    check("cli missing input value exits 2", probe.returncode == 2, probe.stderr[:80])
    probe = _env_cli("score", "--value", "reach=3", "--value", "impact=impact/low",
                     "--value", "confidence=1", "--value", "urgency=1", **env_config)
    check("cli unknown input name exits 2", probe.returncode == 2, probe.stderr[:80])
    probe = _env_cli("score", "--value", "impact=unrelated,other", "--value", "confidence=1",
                     "--value", "urgency=1", **env_config)
    check("cli unnormalizable value exits 3", probe.returncode == 3, probe.stderr[:80])
    probe = _env_cli("inputs", "--json", **env_config)
    try:
        payload = json.loads(probe.stdout)
        check("cli inputs --json parses with the label rule",
              probe.returncode == 0 and payload["inputs"][0]["rule"]["kind"] == "labels",
              probe.stdout[:120])
    except Exception as exc:
        check("cli inputs --json parses", False, repr(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
