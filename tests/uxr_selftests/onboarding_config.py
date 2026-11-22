from _harness import bind

import subprocess  # selftest-only import (the CLI probe)
import yaml  # selftest-only import (the shipped example contract, parsed directly)

bind("lib.config", globals())

#: the shipped example contract only; a configured config/org.yaml cannot reach this module
EXAMPLE_CONFIG = yaml.safe_load(
    (PLUGIN_ROOT / "config" / "org.example.yaml").read_text(encoding="utf-8")
)


def _selftest() -> int:
    """Cover the W3 onboarding config surfaces (issues 114, 57, 58, 50).

    The shipped key contract carries every key onboarding names, the KB
    kind validates, and the interview-data ignore-set rule holds in code
    and through the CLI. No network, no writes.
    """
    print("lib/config.py onboarding surfaces test module")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. Every key onboarding names ships in the contract and REQUIRED_KEYS.
    for dotted in ("privacy.init_ignore", "workspace.remote_push",
                   "recruiting.org_chart_paths", "priority.weights", "priority.formula"):
        check(f"required key {dotted}", dotted in REQUIRED_KEYS)
        section, _, key = dotted.partition(".")
        check(
            f"example ships {dotted}",
            isinstance(EXAMPLE_CONFIG.get(section), dict) and key in EXAMPLE_CONFIG[section],
        )

    # 2. The KB kind validates and ships declared-not-built, read-only.
    check("notion kind is validated (TRACKER_KINDS)", "notion" in TRACKER_KINDS)
    notion = EXAMPLE_CONFIG.get("adapters", {}).get("notion", {})
    check(
        "notion entry is declared, not built (area kb)",
        notion.get("module") == "" and notion.get("area") == "kb",
        repr(notion),
    )
    check(
        "notion read-only default (pull on, push off)",
        notion.get("capabilities", {}).get("pull") is True
        and notion.get("capabilities", {}).get("push") is False,
        repr(notion.get("capabilities")),
    )

    # 3. init_ignore_set: the default covers all interview data (issue 57
    # flip); a non-empty list passes through in order; blanks drop; a
    # missing section takes the default.
    check("empty init_ignore -> interviews/", init_ignore_set(EXAMPLE_CONFIG) == ("interviews/",))
    listed = dict(EXAMPLE_CONFIG)
    listed["privacy"] = {"init_ignore": ["interviews/raw-transcripts/", "interviews/participant-key.md"]}
    check(
        "non-empty init_ignore passes through in order",
        init_ignore_set(listed) == ("interviews/raw-transcripts/", "interviews/participant-key.md"),
        repr(init_ignore_set(listed)),
    )
    blank = dict(EXAMPLE_CONFIG)
    blank["privacy"] = {"init_ignore": ["", "interviews/notes/"]}
    check("blank entries drop", init_ignore_set(blank) == ("interviews/notes/",))
    check("missing privacy section -> default", init_ignore_set({}) == ("interviews/",))

    # 4. The CLI prints the effective set, one path per line, exit 0.
    probe = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "lib" / "config.py"), "--init-ignore-set"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=10,
    )
    check("--init-ignore-set exits 0", probe.returncode == 0, probe.stderr)
    check("--init-ignore-set prints interviews/", probe.stdout.strip() == "interviews/", probe.stdout[:80])

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
