from _harness import bind

bind("lib.config", globals())

import tempfile  # selftest-only import (moved from lib/config.py)
import yaml  # selftest-only import (lib/config.py now imports yaml lazily)

def load_example_config(
    environ: Mapping[str, str] | None = None,
    example_file: str | os.PathLike[str] | None = None,
    user_file: str | os.PathLike[str] | None = None,
) -> dict:
    """Load the shipped example contract only; never the live user file.

    Both layers default to ``config/org.example.yaml``, so selftests
    exercise the shipped contract and a configured ``config/org.yaml``
    cannot flip the smoke gate red (F1: the README order Install ->
    Verify -> Configure must keep verify green after Configure).
    Environment overrides default to none, not to the process
    environment. ``example_file`` and ``user_file`` stay overridable for
    fixture tests.
    """
    return load_config(
        environ=environ if environ is not None else {},
        example_file=example_file if example_file else EXAMPLE_FILE,
        user_file=user_file if user_file else EXAMPLE_FILE,
    )


def _selftest() -> int:
    """Cover the contract, the missing-key error, env overrides, and ~ expansion."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/config.py --selftest")

    # 1. The shipped example file satisfies the full config contract.
    try:
        baseline = load_example_config()
        check("shipped example file satisfies the config contract", True)
    except ConfigError as exc:
        baseline = None
        check("shipped example file satisfies the config contract", False, str(exc))

    # 2. A deleted leaf key raises ConfigError naming the key.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data = yaml.safe_load(EXAMPLE_FILE.read_text(encoding="utf-8"))
        del data["org"]["brand_name"]
        broken = tmp / "broken.example.yaml"
        broken.write_text(yaml.safe_dump(data), encoding="utf-8")
        try:
            load_config(
                environ={},
                example_file=broken,
                user_file=tmp / "absent.org.yaml",
            )
            check("missing leaf key raises ConfigError naming the key", False, "no error raised")
        except ConfigError as exc:
            check("missing leaf key raises ConfigError naming the key", "org.brand_name" in str(exc), str(exc))

    # 3. A deleted whole section raises ConfigError naming the section.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data = yaml.safe_load(EXAMPLE_FILE.read_text(encoding="utf-8"))
        del data["calendar"]
        broken = tmp / "broken.example.yaml"
        broken.write_text(yaml.safe_dump(data), encoding="utf-8")
        try:
            load_config(
                environ={},
                example_file=broken,
                user_file=tmp / "absent.org.yaml",
            )
            check("missing section raises ConfigError naming it", False, "no error raised")
        except ConfigError as exc:
            check("missing section raises ConfigError naming it", "calendar" in str(exc), str(exc))

    # 4. Environment overrides win over file values and parse as JSON.
    if baseline is not None:
        overridden = load_example_config(
            environ={
                "UXR_CONFIG__DEFAULTS__START_WINDOW_DAYS": "30",
                "UXR_CONFIG__ORG__BRAND_NAME": "Selftest Brand",
                "UXR_CONFIG__TRACKER__CLOSED_STATES": '["Done"]',
            }
        )
        check(
            "environment override replaces a scalar (JSON number)",
            overridden["defaults"]["start_window_days"] == 30,
            repr(overridden["defaults"]["start_window_days"]),
        )
        check(
            "environment override replaces a scalar (plain string)",
            overridden["org"]["brand_name"] == "Selftest Brand",
            repr(overridden["org"]["brand_name"]),
        )
        check(
            "environment override replaces a list (JSON list)",
            overridden["tracker"]["closed_states"] == ["Done"],
            repr(overridden["tracker"]["closed_states"]),
        )
        check(
            "overrides do not leak into the next load",
            load_example_config()["defaults"]["start_window_days"] == 90,
        )

    # 5. '~' and ${VAR} in the paths section are expanded.
    if baseline is not None:
        expanded = load_example_config(
            environ={"UXR_CONFIG__PATHS__RESEARCH_ROOT": "~/zcode-config-selftest"}
        )
        expected = os.path.expanduser("~/zcode-config-selftest")
        check(
            "'~' in paths.research_root is expanded",
            expanded["paths"]["research_root"] == expected,
            repr(expanded["paths"]["research_root"]),
        )
        check(
            "'~' literal does not survive expansion",
            not str(expanded["paths"]["research_root"]).startswith("~"),
        )
        expected_state = os.path.expanduser(
            os.path.expandvars("${CLAUDE_PLUGIN_DATA}/state")
        )
        check(
            "paths.state_dir ${VAR} reference is expanded",
            baseline["paths"]["state_dir"] == expected_state,
            repr(baseline["paths"]["state_dir"]),
        )

    # 6. The example-only loader never merges the live user file (F1):
    # equality with a load whose user file cannot exist proves the default
    # user layer is the example, so a configured config/org.yaml cannot
    # reach a selftest and the smoke gate stays green after Configure.
    example_only = load_example_config()
    pure = load_config(
        environ={}, user_file=EXAMPLE_FILE.parent / "org.yaml.selftest-absent"
    )
    check(
        "the example-only loader never merges the live user file",
        example_only == pure,
        f"example-only start_window_days={example_only['defaults']['start_window_days']!r}, "
        f"pure-example start_window_days={pure['defaults']['start_window_days']!r}",
    )

    # 7. The JSON snapshot serves the same config as the yaml path and
    # regenerates when the user file changes (efficiency row 14).
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ex = tmp / "org.example.yaml"
        ex.write_text(EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        user = tmp / "org.yaml"
        user.write_text("defaults:\n  start_window_days: 42\n", encoding="utf-8")
        first = load_config(environ={}, example_file=ex, user_file=user)
        snap = user.with_name("org.snapshot.json")
        check("snapshot written beside the user file", snap.is_file())
        second = load_config(environ={}, example_file=ex, user_file=user)
        check("snapshot load equals the yaml load", first == second)
        user.write_text("defaults:\n  start_window_days: 43\n", encoding="utf-8")
        third = load_config(environ={}, example_file=ex, user_file=user)
        check(
            "snapshot key refreshes after a user-file edit",
            third["defaults"]["start_window_days"] == 43,
            repr(third["defaults"]["start_window_days"]),
        )
        user.write_text("defaults: [unclosed", encoding="utf-8")
        raised = False
        try:
            load_config(environ={}, example_file=ex, user_file=user)
        except ConfigError:
            raised = True
        check("invalid user yaml still raises ConfigError", raised)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
