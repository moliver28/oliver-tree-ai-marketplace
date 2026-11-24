from _harness import bind

import subprocess  # selftest-only import (the describe CLI probes)
import yaml  # selftest-only import (the shipped example contract, parsed directly)

bind("lib.adapters", globals())
bind("lib.adapter_jira", globals())
import lib.adapter_github as github  # bound under its name: bare names stay jira's
import lib.adapter_gitlab as gitlab  # bound under its name: bare names stay jira's
#: fixtures live at repo level in a checkout; absent in an installed plugin
FIXTURES_DIR = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures"
#: the shipped example contract only; a configured config/org.yaml cannot reach this module
EXAMPLE_CONFIG = yaml.safe_load(
    (PLUGIN_ROOT / "config" / "org.example.yaml").read_text(encoding="utf-8")
)


def _with_kind(kind: str) -> dict:
    """The example config with ``tracker.kind`` set; never mutates the parsed example."""
    config = dict(EXAMPLE_CONFIG)
    config["tracker"] = {**(EXAMPLE_CONFIG.get("tracker") or {}), "kind": kind}
    return config


def _selftest() -> int:
    """Cover the resolver rules, the four Jira operations, the four GitHub and
    GitLab operations, and the describe CLI.

    Absence first (the harness works with the sync half absent), then
    registration, declared-not-built, unknown kind, configured-but-broken,
    connect, pull, push, spec_transform for jira, github, and gitlab, and the KB
    capability shape. No live tracker anywhere: fixture-backed only.
    """
    print("lib/adapters.py + lib/adapter_jira.py test module")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. Absence: the example config ships an empty tracker.kind.
    check("absent-sync: empty kind resolves to None", resolve(EXAMPLE_CONFIG) is None)

    # 2. Registration: kind jira returns the shipped record.
    record = resolve(_with_kind("jira"))
    check(
        "jira record",
        record == {
            "kind": "jira",
            "module": "lib/adapter_jira.py",
            "doc": "references/tracker.md",
            "area": "issues",
            "capabilities": {"pull": True, "push": True, "spec_transform": True},
        },
        repr(record),
    )
    record = resolve(_with_kind("github"))
    check(
        "github record",
        record == {
            "kind": "github",
            "module": "lib/adapter_github.py",
            "doc": "references/tracker-github.md",
            "area": "issues",
            "capabilities": {"pull": True, "push": True, "spec_transform": True},
        },
        repr(record),
    )
    record = resolve(_with_kind("gitlab"))
    check(
        "gitlab record",
        record == {
            "kind": "gitlab",
            "module": "lib/adapter_gitlab.py",
            "doc": "references/tracker-gitlab.md",
            "area": "issues",
            "capabilities": {"pull": True, "push": True, "spec_transform": True},
        },
        repr(record),
    )
    check("github kind is validated (TRACKER_KINDS)", "github" in _config.TRACKER_KINDS)
    check("gitlab kind is validated (TRACKER_KINDS)", "gitlab" in _config.TRACKER_KINDS)
    check(
        "doc pointers exist for every shipped kind",
        all(
            (PLUGIN_ROOT / ADAPTER_DEFAULTS[kind]["doc"]).is_file()
            for kind in ADAPTER_DEFAULTS
        ),
    )

    # 3. Declared-not-built: the shipped linear/asana entries (github and
    # gitlab are built since waves P1/P2; the jira-shape registry entries
    # stay data).
    check("linear (module empty) resolves to None", resolve(_with_kind("linear")) is None)
    check("asana (module empty) resolves to None", resolve(_with_kind("asana")) is None)

    # 4. Unknown kind resolves to None; the shipped declared KB kind too
    # (module empty = declared, not built; issue 114 shipped the notion
    # entry with the read-only default).
    check("unknown kind resolves to None", resolve(_with_kind("no-such-kind")) is None)
    check("notion (declared KB, module empty) resolves to None",
          resolve(_with_kind("notion")) is None)
    check(
        "shipped notion entry mirrors ADAPTER_DEFAULTS (area kb, push off)",
        EXAMPLE_CONFIG.get("adapters", {}).get("notion") == {
            "module": "", "doc": "references/onboarding.md", "area": "kb",
            "capabilities": {"pull": True, "push": False, "spec_transform": False},
        },
        repr(EXAMPLE_CONFIG.get("adapters", {}).get("notion")),
    )
    check("notion kind is validated (TRACKER_KINDS)", "notion" in _config.TRACKER_KINDS)

    # 5. Configured-but-broken is a named ConfigError; empty module stays None.
    broken_section = {"jira": {"module": "lib/__no_such_adapter__.py", "doc": "",
                               "area": "issues", "capabilities": {}}}
    broken = dict(_with_kind("jira"))
    broken["adapters"] = broken_section
    try:
        resolve(broken)
        check("missing module file raises ConfigError", False, "no error raised")
    except ConfigError as exc:
        check("missing module file raises ConfigError", "does not exist" in str(exc), str(exc))
    unimportable = dict(_with_kind("jira"))
    unimportable["adapters"] = {"jira": {"module": "references/tracker.md", "doc": "",
                                         "area": "issues", "capabilities": {}}}
    try:
        resolve(unimportable)
        check("non-importable module raises ConfigError", False, "no error raised")
    except ConfigError as exc:
        check("non-importable module raises ConfigError", "cannot be imported" in str(exc), str(exc))
    empty = dict(_with_kind("jira"))
    empty["adapters"] = {"jira": {"module": "", "doc": "", "area": "issues", "capabilities": {}}}
    check("empty module entry resolves to None", resolve(empty) is None)

    # 6. connect: the example config reports the empty tracker keys.
    facts = connect(EXAMPLE_CONFIG)
    check(
        "connect lists the empty tracker keys",
        facts["missing"] == ["tracker.base_url", "tracker.project_key", "tracker.workspace_id",
                             "tracker.ticket_regex", "tracker.body_format"],
        repr(facts["missing"]),
    )
    check("connect not ready on the example config", facts["ready"] is False)
    filled = dict(EXAMPLE_CONFIG)
    filled["tracker"] = {**EXAMPLE_CONFIG["tracker"], "kind": "jira",
                         "base_url": "https://example.atlassian.net", "project_key": "UX1",
                         "workspace_id": "cloud-id", "ticket_regex": r"\bUX1-\d+\b",
                         "body_format": "adf"}
    check("connect ready when the keys are filled", connect(filled)["ready"] is True)

    # 7. pull: the normalize_key rule in code.
    pull_cfg = dict(EXAMPLE_CONFIG)
    pull_cfg["tracker"] = {**EXAMPLE_CONFIG["tracker"], "bare_number_prefix": "UX1",
                           "ticket_regex": r"\bUX1-\d+\b"}
    check("pull bare number composes the prefix", pull("42", pull_cfg) == {"key": "UX1-42"})
    check("pull regex-valid key passes unchanged", pull("UX1-237", pull_cfg) == {"key": "UX1-237"})
    check("pull invalid key returns the error dict",
          "error" in pull("ZZZ-1", pull_cfg), repr(pull("ZZZ-1", pull_cfg)))
    check("pull empty key returns the error dict", "error" in pull("", pull_cfg))

    # 7b. GitHub connect + pull (wave P1): the same contract, the GitHub
    # key rule. A bare number composes #<n>; no prefix key is needed.
    gh_cfg = dict(EXAMPLE_CONFIG)
    gh_cfg["tracker"] = {**EXAMPLE_CONFIG["tracker"], "kind": "github",
                         "workspace_id": "acme/uxr-research",
                         "base_url": "https://github.com", "body_format": "markdown",
                         "project_key": "UXR", "ticket_regex": r"#\d+"}
    gh_facts = github.connect(gh_cfg)
    check("github connect ready when the keys are filled", gh_facts["ready"] is True)
    check("github connect lists the same five tracker keys when empty",
          github.connect(EXAMPLE_CONFIG)["missing"] == facts["missing"],
          repr(github.connect(EXAMPLE_CONFIG)["missing"]))
    gh_pull = dict(EXAMPLE_CONFIG)
    gh_pull["tracker"] = {**EXAMPLE_CONFIG["tracker"], "ticket_regex": r"#\d+"}
    check("github pull composes a bare number with #", github.pull("42", gh_pull) == {"key": "#42"})
    check("github pull passes a regex-valid key unchanged",
          github.pull("#237", gh_pull) == {"key": "#237"})
    check("github pull invalid key returns the error dict",
          "error" in github.pull("UX1-237", gh_pull), repr(github.pull("UX1-237", gh_pull)))
    check("github pull empty key returns the error dict", "error" in github.pull("", gh_pull))
    check("github display data: the normalized key carries the #num form (issue 52)",
          github.pull("306", gh_pull)["key"] == "#306"
          and github.pull("#306", gh_pull)["key"].lstrip("#").isdecimal())

    # 7c. GitLab connect + pull (wave P2): the same contract, the GitLab
    # key rule. A bare number composes #<n>; no prefix key is needed.
    gl_cfg = dict(EXAMPLE_CONFIG)
    gl_cfg["tracker"] = {**EXAMPLE_CONFIG["tracker"], "kind": "gitlab",
                         "workspace_id": "acme/uxr-research",
                         "base_url": "https://gitlab.com", "body_format": "markdown",
                         "project_key": "UXR", "ticket_regex": r"#\d+"}
    gl_facts = gitlab.connect(gl_cfg)
    check("gitlab connect ready when the keys are filled", gl_facts["ready"] is True)
    check("gitlab connect lists the same five tracker keys when empty",
          gitlab.connect(EXAMPLE_CONFIG)["missing"] == facts["missing"],
          repr(gitlab.connect(EXAMPLE_CONFIG)["missing"]))
    gl_pull = dict(EXAMPLE_CONFIG)
    gl_pull["tracker"] = {**EXAMPLE_CONFIG["tracker"], "ticket_regex": r"#\d+"}
    check("gitlab pull composes a bare number with #", gitlab.pull("42", gl_pull) == {"key": "#42"})
    check("gitlab pull passes a regex-valid key unchanged",
          gitlab.pull("#237", gl_pull) == {"key": "#237"})
    check("gitlab pull invalid key returns the error dict",
          "error" in gitlab.pull("UX1-237", gl_pull), repr(gitlab.pull("UX1-237", gl_pull)))
    check("gitlab pull empty key returns the error dict", "error" in gitlab.pull("", gl_pull))

    if not FIXTURES_DIR.is_dir():
        print("skip: fixture-backed checks (fixtures not shipped at repo level)")
    else:
        # 8. push: one shipped spec fixture; body byte-equal to build_document.
        spec = json.loads(
            (FIXTURES_DIR / "spec" / "uc2-spec.json").read_text(encoding="utf-8")
        )
        result = push(spec, [], EXAMPLE_CONFIG)
        check("push exits 0 on the shipped spec fixture", result["exit"] == 0, result["stderr"])
        expected = _spec_blocks.build_document(spec, config=EXAMPLE_CONFIG)
        check("push body byte-equal to build_document", result["body"] == expected + "\n")
        check("push carries no fields without shorthands", result["fields"] == [])
        refused = push(spec, ["no operator here"], EXAMPLE_CONFIG)
        check("push rejects a bad shorthand with exit 3",
              refused["exit"] == 3 and refused["body"] == "" and refused["fields"] == [],
              repr(refused["stderr"]))

        # 8b. GitHub push (wave P1): the same contract through the github
        # module; the body renders identically (markdown is the default).
        gh_result = github.push(spec, [], EXAMPLE_CONFIG)
        check("github push exits 0 on the shipped spec fixture", gh_result["exit"] == 0, gh_result["stderr"])
        check("github push body byte-equal to build_document",
              gh_result["body"] == _spec_blocks.build_document(spec, config=EXAMPLE_CONFIG) + "\n")
        check("github push carries no fields without shorthands", gh_result["fields"] == [])
        gh_refused = github.push(spec, ["no operator here"], EXAMPLE_CONFIG)
        check("github push rejects a bad shorthand with exit 3",
              gh_refused["exit"] == 3 and gh_refused["body"] == "" and gh_refused["fields"] == [],
              repr(gh_refused["stderr"]))

        # 8c. GitLab push (wave P2): the same contract through the gitlab
        # module; the body renders identically (markdown is the default).
        gl_result = gitlab.push(spec, [], EXAMPLE_CONFIG)
        check("gitlab push exits 0 on the shipped spec fixture", gl_result["exit"] == 0, gl_result["stderr"])
        check("gitlab push body byte-equal to build_document",
              gl_result["body"] == _spec_blocks.build_document(spec, config=EXAMPLE_CONFIG) + "\n")
        check("gitlab push carries no fields without shorthands", gl_result["fields"] == [])
        gl_refused = gitlab.push(spec, ["no operator here"], EXAMPLE_CONFIG)
        check("gitlab push rejects a bad shorthand with exit 3",
              gl_refused["exit"] == 3 and gl_refused["body"] == "" and gl_refused["fields"] == [],
              repr(gl_refused["stderr"]))

        # 9. spec_transform: byte-equal to build_document for both formats,
        # jira, github, and gitlab modules alike (same delegated function).
        for fmt in ("markdown", "adf"):
            check(
                f"spec_transform {fmt} byte-equal to build_document",
                spec_transform(spec, EXAMPLE_CONFIG, body_format=fmt)
                == _spec_blocks.build_document(spec, EXAMPLE_CONFIG, body_format=fmt),
            )
            check(
                f"github spec_transform {fmt} byte-equal to build_document",
                github.spec_transform(spec, EXAMPLE_CONFIG, body_format=fmt)
                == _spec_blocks.build_document(spec, EXAMPLE_CONFIG, body_format=fmt),
            )
            check(
                f"gitlab spec_transform {fmt} byte-equal to build_document",
                gitlab.spec_transform(spec, EXAMPLE_CONFIG, body_format=fmt)
                == _spec_blocks.build_document(spec, EXAMPLE_CONFIG, body_format=fmt),
            )

    # 10. KB shape: capability bits are data; resolve passes them through.
    kb = dict(_with_kind("notion"))
    kb["adapters"] = {"notion": {"module": "lib/adapter_jira.py", "doc": "", "area": "kb",
                                 "capabilities": {"pull": True, "push": False,
                                                  "spec_transform": False}}}
    kb_record = resolve(kb)
    check(
        "kb record passes through resolve unchanged",
        kb_record == {"kind": "notion", "module": "lib/adapter_jira.py", "doc": "",
                      "area": "kb",
                      "capabilities": {"pull": True, "push": False, "spec_transform": False}},
        repr(kb_record),
    )

    # describe CLI: one JSON line for a registered kind, null for absence, usage on 2.
    script = PLUGIN_ROOT / "lib" / "adapters.py"
    probe = subprocess.run(
        [sys.executable, str(script), "describe", "--kind", "jira"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("describe --kind jira exits 0", probe.returncode == 0, probe.stderr)
    try:
        check("describe prints the jira record as one JSON line",
              json.loads(probe.stdout.strip()).get("kind") == "jira", probe.stdout[:120])
    except ValueError as exc:
        check("describe prints the jira record as one JSON line", False, str(exc))
    probe = subprocess.run(
        [sys.executable, str(script), "describe", "--kind", "github"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("describe --kind github exits 0", probe.returncode == 0, probe.stderr)
    try:
        check("describe prints the github record as one JSON line",
              json.loads(probe.stdout.strip()).get("kind") == "github", probe.stdout[:120])
    except ValueError as exc:
        check("describe prints the github record as one JSON line", False, str(exc))
    probe = subprocess.run(
        [sys.executable, str(script), "describe", "--kind", "gitlab"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("describe --kind gitlab exits 0", probe.returncode == 0, probe.stderr)
    try:
        check("describe prints the gitlab record as one JSON line",
              json.loads(probe.stdout.strip()).get("kind") == "gitlab", probe.stdout[:120])
    except ValueError as exc:
        check("describe prints the gitlab record as one JSON line", False, str(exc))
    probe = subprocess.run(
        [sys.executable, str(script), "describe", "--kind", "linear"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("describe --kind linear prints null (absent-sync)",
          probe.returncode == 0 and probe.stdout.strip() == "null", probe.stdout[:120])
    probe = subprocess.run(
        [sys.executable, str(script), "describe"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("describe without --kind exits 2 (usage)", probe.returncode == 2, probe.stderr[:120])

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
