from _harness import bind

bind("hooks.ux_research_context", globals())

import tempfile  # selftest-only import (moved from hooks/ux_research_context.py)

def _selftest() -> int:
    """Cover the gate, the marker walk, the output shape, and ignored events."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    def run(event: dict, **kwargs) -> str:
        kwargs.setdefault("environ", {})
        return handle_event(event, home=HOME, **kwargs)

    def is_session_start_json(output: str) -> dict:
        if not output or "\n" in output.strip():
            return {}
        try:
            payload = json.loads(output)
        except ValueError:
            return {}
        specific = payload.get("hookSpecificOutput") or {}
        if specific.get("hookEventName") != "SessionStart":
            return {}
        if not isinstance(specific.get("additionalContext"), str):
            return {}
        return specific

    print("hooks/ux_research_context.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        plain = tmp / "plain"
        plain.mkdir()
        root = tmp / "research"
        study = root / "Study A"
        study.mkdir(parents=True)
        env_roots = {ENV_RESEARCH_DIRS: f"{root}{os.pathsep}{tmp / 'other'}"}
        config_root = {"paths": {"research_root": str(root)}}
        start = {"hook_event_name": "SessionStart"}

        # 1. Outside a research root with no marker: no output.
        check(
            "outside a research root prints nothing",
            run({**start, "cwd": str(plain)}) == "",
            "expected empty output",
        )

        # 2. Inside a UXR_RESEARCH_DIRS root: one SessionStart JSON line.
        output = run({**start, "cwd": str(study)}, config=None, environ=env_roots)
        specific = is_session_start_json(output)
        check(
            "UXR_RESEARCH_DIRS root opens the gate",
            bool(specific),
            repr(output[:120]),
        )
        check(
            "output is one SessionStart JSON object with context text",
            bool(specific) and len(specific["additionalContext"]) > 0,
            repr(output[:120]),
        )

        # 3. Inside the config research root: the gate opens too.
        output = run({**start, "cwd": str(study)}, config=config_root)
        check(
            "paths.research_root from the config opens the gate",
            bool(is_session_start_json(output)),
            repr(output[:120]),
        )

        # 4. A folder holding 00-overview.md opens the gate without any root.
        marked = tmp / "marked-study"
        marked.mkdir()
        (marked / OVERVIEW_MARKER).write_text("# overview\n", encoding="utf-8")
        output = run({**start, "cwd": str(marked)})
        specific = is_session_start_json(output)
        check(
            "a cwd with 00-overview.md opens the gate",
            bool(specific),
            repr(output[:120]),
        )
        check(
            "context text is the one routing-pointer line",
            bool(specific) and specific["additionalContext"] == CONTEXT_LINE,
            repr(specific.get("additionalContext", "")[:200]),
        )

        # 5. A parent below $HOME holding the marker opens the gate.
        (HOME / "docs").mkdir(parents=True)
        (HOME / "docs" / OVERVIEW_MARKER).write_text("# overview\n", encoding="utf-8")
        nested = HOME / "docs" / "spring study"
        nested.mkdir()
        check(
            "a parent below $HOME with 00-overview.md opens the gate",
            bool(is_session_start_json(run({**start, "cwd": str(nested)}))),
            "gate stayed closed",
        )

        # 6. The marker at $HOME itself does not open the gate for siblings.
        other = HOME / "unrelated"
        other.mkdir()
        check(
            "$HOME itself holding the marker does not open sibling folders",
            run({**start, "cwd": str(other)}) == "",
            "expected empty output",
        )

        # 7. UserPromptSubmit never injects text, even inside a research root.
        for environ in ({}, env_roots):
            output = handle_event(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "cwd": str(study),
                    "prompt": "summarize the study",
                },
                environ=environ,
                home=HOME,
            )
            check(
                f"UserPromptSubmit prints nothing (environ={'roots' if environ else 'empty'})",
                output == "",
                repr(output[:120]),
            )

        # 8. Other events print nothing.
        for name in ("SessionEnd", "Stop", "PreToolUse"):
            check(
                f"{name} prints nothing",
                handle_event({"hook_event_name": name, "cwd": str(study)},
                             environ=env_roots, home=HOME) == "",
                "expected empty output",
            )

        # 9. Missing hook_event_name is treated as an unknown event.
        check(
            "an event without hook_event_name prints nothing",
            run({"cwd": str(study)}) == "",
            "expected empty output",
        )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
