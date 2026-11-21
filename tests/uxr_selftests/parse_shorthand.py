from _harness import bind

bind("scripts.parse_shorthand", globals())
def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/parse_shorthand.py --selftest")

    # the acceptance example, byte for byte
    code, stdout, stderr = run(_ACCEPTANCE_REQUEST)
    check(
        "roster+= acceptance request prints the exact delta",
        code == 0 and stdout.strip() == _ACCEPTANCE_OUTPUT and stderr == "",
        f"code={code} stdout={stdout!r} stderr={stderr!r}",
    )
    if code == 0:
        parsed = json.loads(stdout)
        check(
            "roster+= delta round-trips as the expected object",
            parsed == {
                "name": "Ada",
                "email": "ada@x.io",
                "slack": "",
                "reason": "",
                "status": "Scheduled",
                "channel": "internal",
            },
            repr(parsed),
        )
        check(
            "delta keys keep the roster field order",
            list(parsed.keys()) == ["name", "email", "slack", "reason", "status", "channel"],
            repr(list(parsed.keys())),
        )

    # resources url remap (acceptance)
    code, stdout, _ = run('{"kind":"resources","op":"+=","arg":"Plan|https://x|shared|"}')
    delta = json.loads(stdout) if code == 0 else {}
    check(
        "resources+= writes url, never url_or_text",
        code == 0
        and delta.get("url") == "https://x"
        and "url_or_text" not in delta
        and delta.get("share_status") == "shared",
        f"code={code} delta={delta}",
    )

    # list and patch shapes
    cases = (
        (
            "resources+= non-http value lands in text",
            '{"kind":"resources","op":"+=","arg":"Notes|plain context|"}',
            0,
            {"label": "Notes", "text": "plain context", "share_status": "", "share_note": ""},
        ),
        (
            "hypotheses+= yields label and text",
            '{"kind":"hypotheses","op":"+=","arg":"H3|Export is findable."}',
            0,
            {"label": "H3", "text": "Export is findable."},
        ),
        (
            "assumptions+= yields label and text",
            '{"kind":"assumptions","op":"+=","arg":"A2|Surveys skew to power users"}',
            0,
            {"label": "A2", "text": "Surveys skew to power users"},
        ),
        (
            "roster~= returns match and one-field patch",
            '{"kind":"roster","op":"~=","arg":"ada|status=Data Collected"}',
            0,
            {"match": "ada", "set": {"status": "Data Collected"}},
        ),
        (
            "roster-= returns the match name",
            '{"kind":"roster","op":"-=","arg":"Ada Example"}',
            0,
            {"match": "Ada Example"},
        ),
        (
            "resources~= maps url_or_text in the patch",
            '{"kind":"resources","op":"~=","arg":"Plan|url_or_text=https://y"}',
            0,
            {"match": "Plan", "set": {"url": "https://y"}},
        ),
        (
            "hypotheses-= returns the match label",
            '{"kind":"hypotheses","op":"-=","arg":"H3"}',
            0,
            {"match": "H3"},
        ),
    )
    for name, request, want_code, want_delta in cases:
        code, stdout, stderr = run(request)
        try:
            got = json.loads(stdout) if stdout.strip() else None
        except ValueError:
            got = None
        check(name, code == want_code and got == want_delta, f"code={code} stdout={stdout!r} stderr={stderr!r}")

    # rejections
    rejections = (
        (
            "malformed request JSON exits 2",
            "{oops",
            2,
        ),
        (
            "unknown kind exits 2",
            '{"kind":"milestones","op":"+=","arg":"x"}',
            2,
        ),
        (
            "non-string arg exits 2",
            '{"kind":"roster","op":"+=","arg":42}',
            2,
        ),
        (
            "non-object request exits 2",
            '["roster"]',
            2,
        ),
        (
            "unknown op exits 3",
            '{"kind":"roster","op":"=","arg":"Ada"}',
            3,
        ),
        (
            "roster+= without a name exits 3",
            '{"kind":"roster","op":"+=","arg":"|a@b"}',
            3,
        ),
        (
            "roster~= with an unknown field exits 3",
            '{"kind":"roster","op":"~=","arg":"Ada|bogus=1"}',
            3,
        ),
        (
            "resources+= with too many parts exits 3",
            '{"kind":"resources","op":"+=","arg":"a|b|c|d|e"}',
            3,
        ),
    )
    for name, request, want_code in rejections:
        code, stdout, _ = run(request)
        check(name, code == want_code and stdout == "", f"code={code} stdout={stdout!r}")

    # the acceptance command through the real CLI
    try:
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "parse_shorthand.py")],
            input=_ACCEPTANCE_REQUEST,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
        )
        check(
            "CLI prints the exact acceptance delta and exits 0",
            proc.returncode == 0 and proc.stdout.strip() == _ACCEPTANCE_OUTPUT,
            f"code={proc.returncode} stdout={proc.stdout!r}",
        )
    except OSError as exc:
        check("CLI subprocess check ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
