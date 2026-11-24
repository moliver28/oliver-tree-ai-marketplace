from _harness import bind

import json as _json  # selftest-only import (record content pins)
import os  # selftest-only import (the no-state-dir probe env)
import subprocess  # selftest-only import (the CLI probes)
import tempfile  # selftest-only import (hermetic state dirs)
from pathlib import Path  # selftest-only import (record file paths)

bind("scripts.walkthrough", globals())

#: the shipped plugin root, two levels up from tests/uxr_selftests/
PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"

#: env for CLI probes with no resolvable state dir, whatever the machine has:
#: UXR_STATE_DIR removed and paths.state_dir overridden to an unexpandable
#: placeholder, so the state law resolves None everywhere.
_NO_STATE_ENV = {k: v for k, v in os.environ.items() if k != "UXR_STATE_DIR"}
_NO_STATE_ENV["UXR_CONFIG__PATHS__STATE_DIR"] = "${UXR_NO_STATE_DIR}/state"


def _cli(*args, env=None):
    """Run the shipped CLI; hermetic via --state-dir on a temp dir."""
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "walkthrough.py"), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), timeout=8,
        env=_NO_STATE_ENV if env is None else env,
    )


def _selftest() -> int:
    """Cover the walkthrough completion-record gate (issue 114 section 3).

    The gate blocks finish until all four features carry a record, each
    feature's record write lands in gate order with its key, unknown
    features and arguments are usage errors, an unresolvable state dir
    fails closed, and a corrupt record is treated as empty. No network,
    no machine state: every probe runs on a temp state dir.
    """
    print("scripts/walkthrough.py test module")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(f"{name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        state = str(Path(td) / "state")
        path = Path(state) / "walkthrough.json"

        # 1. The gate blocks before anything is used.
        probe = _cli("check", "--state-dir", state)
        check("empty record: check blocks (exit 1)", probe.returncode == 1
              and "create" in probe.stdout and "sync" in probe.stdout, probe.stdout[:100])
        probe = _cli("check", "--json", "--state-dir", state)
        try:
            payload = _json.loads(probe.stdout)
            check("empty record: check --json is incomplete with all four missing",
                  probe.returncode == 1 and payload["complete"] is False
                  and payload["missing"] == ["create", "move", "calculator", "sync"],
                  probe.stdout[:120])
        except Exception as exc:
            check("empty record: check --json parses", False, repr(exc))

        # 2. Each feature's record write lands; the file stays deterministic.
        for name, key in (("create", "UX-42"), ("move", "UX-42"),
                          ("calculator", "UX-42"), ("sync", "UX-42")):
            probe = _cli("record", "--feature", name, "--key", key, "--state-dir", state)
            check(f"record {name} exits 0", probe.returncode == 0, probe.stderr[:80])
        try:
            content = _json.loads(path.read_text(encoding="utf-8"))
            check(
                "the completion record is the exact four-feature document",
                content == {"format": 1, "features": {
                    "create": {"key": "UX-42"}, "move": {"key": "UX-42"},
                    "calculator": {"key": "UX-42"}, "sync": {"key": "UX-42"}}},
                path.read_text(encoding="utf-8")[:200],
            )
        except Exception as exc:
            check("the completion record parses", False, repr(exc))

        # 3. The gate passes when all four are recorded.
        probe = _cli("check", "--state-dir", state)
        check("complete record: check passes (exit 0)", probe.returncode == 0
              and "all four features" in probe.stdout, probe.stdout[:100])
        probe = _cli("check", "--json", "--state-dir", state)
        try:
            payload = _json.loads(probe.stdout)
            check("complete record: check --json is complete with no missing",
                  probe.returncode == 0 and payload["complete"] is True
                  and payload["missing"] == [], probe.stdout[:120])
        except Exception as exc:
            check("complete record: check --json parses", False, repr(exc))

        # 4. One missing feature keeps the gate shut (the forced law).
        partial = str(Path(td) / "partial")
        for name in ("create", "move", "sync"):
            _cli("record", "--feature", name, "--state-dir", partial)
        probe = _cli("check", "--state-dir", partial)
        check("three of four: check still blocks", probe.returncode == 1
              and "calculator" in probe.stdout, probe.stdout[:100])

        # 5. Re-record upserts the key; the feature set stays complete.
        _cli("record", "--feature", "move", "--key", "UX-99", "--state-dir", state)
        content = _json.loads(path.read_text(encoding="utf-8"))
        check("re-record upserts the key",
              content["features"]["move"] == {"key": "UX-99"}
              and len(content["features"]) == 4, repr(content))

        # 6. Usage errors: unknown feature, missing --feature, unknown args.
        probe = _cli("record", "--feature", "deploy", "--state-dir", state)
        check("unknown feature exits 2", probe.returncode == 2, probe.stderr[:80])
        probe = _cli("record", "--state-dir", state)
        check("record without --feature exits 2", probe.returncode == 2, probe.stderr[:80])
        probe = _cli("record", "--feature")
        check("--feature without a value exits 2", probe.returncode == 2, probe.stderr[:80])
        probe = _cli("frobnicate")
        check("unknown command exits 2", probe.returncode == 2, probe.stderr[:80])
        probe = _cli("check", "--wat", "--state-dir", state)
        check("unknown argument exits 2", probe.returncode == 2, probe.stderr[:80])

        # 7. Clear resets; clearing an absent record still exits 0.
        probe = _cli("clear", "--state-dir", state)
        check("clear exits 0", probe.returncode == 0, probe.stderr[:80])
        check("clear removed the file", not path.exists(), None)
        probe = _cli("check", "--state-dir", state)
        check("cleared record blocks again", probe.returncode == 1, probe.stdout[:80])
        probe = _cli("clear", "--state-dir", state)
        check("clear on an absent record exits 0", probe.returncode == 0, probe.stderr[:80])

        # 8. Fail closed: corrupt record is empty; record write repairs it.
        corrupt = str(Path(td) / "corrupt")
        Path(corrupt).mkdir(parents=True)
        (Path(corrupt) / "walkthrough.json").write_text("{not json", encoding="utf-8")
        probe = _cli("check", "--state-dir", corrupt)
        check("corrupt record fails closed (all four missing)", probe.returncode == 1
              and probe.stdout.count(",") == 3, probe.stdout[:100])
        _cli("record", "--feature", "create", "--state-dir", corrupt)
        content = _json.loads((Path(corrupt) / "walkthrough.json").read_text(encoding="utf-8"))
        check("record write repairs a corrupt file",
              content == {"format": 1, "features": {"create": {"key": ""}}}, repr(content))
        probe = _cli("check", "--state-dir", corrupt)
        check("repaired record checks the remaining three", probe.returncode == 1
              and "create" not in probe.stdout.split("missing:")[1], probe.stdout[:100])

        # 9. An unresolvable state dir never passes the gate.
        probe = _cli("record", "--feature", "create", env=_NO_STATE_ENV)
        check("record without a state dir exits 3", probe.returncode == 3, probe.stderr[:90])
        probe = _cli("check", env=_NO_STATE_ENV)
        check("check without a state dir fails closed (exit 1)",
              probe.returncode == 1 and "no state dir" in probe.stdout, probe.stdout[:90])

        # 10. The direct helpers agree with the CLI.
        with tempfile.TemporaryDirectory() as td2:
            config = {"paths": {"state_dir": td2}}
            direct = record_path(None, config)
            check("record_path follows paths.state_dir",
                  direct is not None and direct.parent == Path(td2), repr(direct))
            check("record_path --state-dir wins",
                  record_path(str(Path(td2) / "other")).parent == Path(td2) / "other", None)
            check("record_path with an unexpanded placeholder is None",
                  record_path(None, {"paths": {"state_dir": "${CLAUDE_PLUGIN_DATA}/state"}}) is None,
                  None)
            check("missing_features on an empty record lists all four in order",
                  missing_features(None) == ["create", "move", "calculator", "sync"], None)
            save_path = Path(td2) / "direct.json"
            _save(save_path, {"features": {"sync": {"key": "K"}, "create": {"key": ""}}})
            content = _json.loads(save_path.read_text(encoding="utf-8"))
            check("_save writes gate order",
                  list(content["features"]) == ["create", "sync"], repr(content))
            check("_load drops unknown feature names",
                  _load(save_path)["features"].keys() == {"create", "sync"}, None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
