from _harness import bind

bind("scripts.build_body", globals())

import spec_blocks  # tests/uxr_selftests/spec_blocks.py: the moved GOLDEN_SPEC/selftest_config home (selftest body stays verbatim)

def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/build_body.py --selftest")

    spec_text = json.dumps(spec_blocks.GOLDEN_SPEC, ensure_ascii=False)

    # golden body: exit 0 and byte-identical across two runs
    first = run(spec_text, config=spec_blocks.selftest_config("markdown"))
    second = run(spec_text, config=spec_blocks.selftest_config("markdown"))
    check(
        "golden spec renders exit 0 twice with byte-identical stdout",
        first[0] == 0 and first == second and bool(first[1].strip()),
        f"codes {first[0]}/{second[0]}",
    )

    # the acceptance command: empty hypotheses exits 3 with empty stdout
    code, stdout, stderr = run('{"hypotheses": []}', config=spec_blocks.selftest_config())
    check(
        "empty hypotheses exits 3 with empty stdout and '  - ' stderr lines",
        code == 3 and stdout == "" and stderr.startswith("  - "),
        f"code={code} stdout={stdout!r} stderr={stderr!r}",
    )

    # bad JSON exits 2
    code, stdout, _ = run("{not json", config=spec_blocks.selftest_config())
    check("malformed spec JSON exits 2 with empty stdout", code == 2 and stdout == "", f"code={code}")

    # adf output is a JSON document
    code, stdout, _ = run(spec_text, config=spec_blocks.selftest_config("adf"))
    adf_ok = False
    if code == 0:
        try:
            adf_ok = json.loads(stdout).get("type") == "doc"
        except ValueError:
            adf_ok = False
    check("adf body leaves stdout as a JSON ADF document", adf_ok, f"code={code}")

    # incomplete document exits 4
    from lib import spec_blocks as _shipped  # patch the module object build_body binds; the local spec_blocks is a bind-copy dict, not that object
    patched = spec_blocks.selftest_config()
    original = _shipped.assert_full_document
    try:
        _shipped.assert_full_document = lambda body: (False, ["injected: missing checklist"])
        code, stdout, stderr = run(spec_text, config=patched)
    finally:
        _shipped.assert_full_document = original
    check(
        "failed document check exits 4 with empty stdout",
        code == 4 and stdout == "" and "injected" in stderr,
        f"code={code}",
    )

    # the real CLI: the acceptance command verbatim, in a subprocess
    try:
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
            input='{"hypotheses": []}',
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
        )
        check(
            "CLI echo of the acceptance command exits 3 with empty stdout",
            proc.returncode == 3 and proc.stdout == "" and proc.stderr.lstrip().startswith("-"),
            f"code={proc.returncode} stdout={proc.stdout!r}",
        )

        golden_twins = [
            subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
                input=spec_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            for _ in range(2)
        ]
        check(
            "CLI golden spec renders byte-identical stdout on two runs",
            golden_twins[0].returncode == 0
            and golden_twins[0].stdout == golden_twins[1].stdout
            and bool(golden_twins[0].stdout.strip()),
            f"codes {golden_twins[0].returncode}/{golden_twins[1].returncode}",
        )

        adf_env = {**os.environ, "UXR_CONFIG__TRACKER__BODY_FORMAT": "adf"}
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
            input=spec_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
            env=adf_env,
        )
        adf_ok = False
        if proc.returncode == 0:
            try:
                adf_ok = json.loads(proc.stdout).get("type") == "doc"
            except ValueError:
                adf_ok = False
        check("CLI honors the tracker.body_format config override", adf_ok, f"code={proc.returncode}")
    except OSError as exc:
        check("CLI subprocess checks ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
