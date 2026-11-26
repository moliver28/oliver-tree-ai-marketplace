from _harness import bind

bind("scripts.render_script_docx", globals())
def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        suffix = f" ({detail})" if detail and not condition else ""
        print(f"  [{'ok' if condition else 'FAIL'}] {name}{suffix}")
        if not condition:
            failures.append(name)

    # 1. Parser classification.
    elements = parse_script(FIXTURE)
    kinds = [element.kind for element in elements]
    for expected in ("heading", "read_aloud", "note", "question", "conditional",
                     "probe", "survey", "moderator", "plain"):
        check(f"parser finds a {expected} element", expected in kinds,
              f"kinds: {sorted(set(kinds))}")
    read_aloud = next(e for e in elements if e.kind == "read_aloud")
    check("read_aloud body strips the italic markers",
          read_aloud.text == "Thanks for making time today.", read_aloud.text)
    conditional = next(e for e in elements if e.kind == "conditional")
    check("conditional keeps criteria and number",
          conditional.criteria == "if they mention exports" and conditional.label == "2",
          f"{conditional.criteria!r} {conditional.label!r}")
    survey = next(e for e in elements if e.kind == "survey")
    check("survey keeps label verbatim",
          survey.label == "umux_lite_usability_7_point", survey.label)

    # 2. A script with no notes, read-aloud extras, or conditionals parses to
    #    an element set that asks for no such checks (reference defect fix:
    #    verify checks only contained element types).
    minimal = parse_script(MINIMAL_FIXTURE)
    minimal_kinds = {element.kind for element in minimal}
    check("minimal script parses without note/conditional/survey elements",
          "note" not in minimal_kinds and "conditional" not in minimal_kinds
          and "survey" not in minimal_kinds, f"kinds: {sorted(minimal_kinds)}")
    absent = [kind for kind in ("note", "conditional", "survey", "probe", "moderator")
              if kind not in minimal_kinds]
    check("absent element types are simply not verified", len(absent) == 5,
          f"absent: {absent}")

    # 3. CLI surface without python-docx: render and verify exit 2 with the
    #    install hint; usage errors exit 2. (With python-docx these become a
    #    full round trip instead.)
    script = str(Path(__file__).resolve())
    import subprocess
    import tempfile

    _load_docx()
    if not HAVE_DOCX:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "script.md"
            src.write_text(FIXTURE, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, script, "render", str(src), str(Path(tmp) / "out.docx")],
                capture_output=True, text=True, timeout=30,
            )
            check("render without python-docx exits 2",
                  proc.returncode == EXIT_USAGE and "pip install python-docx" in proc.stderr,
                  f"exit {proc.returncode}")
            proc = subprocess.run(
                [sys.executable, script, "verify", str(src)],
                capture_output=True, text=True, timeout=30,
            )
            check("verify without python-docx exits 2",
                  proc.returncode == EXIT_USAGE and "pip install python-docx" in proc.stderr,
                  f"exit {proc.returncode}")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "script.md"
            src.write_text(FIXTURE, encoding="utf-8")
            out = Path(tmp) / "script.docx"
            proc = subprocess.run(
                [sys.executable, script, "render", str(src), str(out)],
                capture_output=True, text=True, timeout=60,
            )
            check("render exits 0", proc.returncode == EXIT_OK, proc.stdout + proc.stderr)
            proc = subprocess.run(
                [sys.executable, script, "verify", str(out)],
                capture_output=True, text=True, timeout=60,
            )
            check("verify of the rendered file exits 0",
                  proc.returncode == EXIT_OK, proc.stdout + proc.stderr)
            # Break one note run (not bold): verify must flag it.
            doc = Document(str(out))
            broken = 0
            for paragraph in doc.paragraphs:
                if _classify_paragraph(paragraph) == "note":
                    for run in paragraph.runs:
                        run.bold = False
                        broken += 1
                        break
                    break
            check("fixture contains a note to break", broken == 1, f"notes broken: {broken}")
            tampered = Path(tmp) / "tampered.docx"
            doc.save(str(tampered))
            proc = subprocess.run(
                [sys.executable, script, "verify", str(tampered)],
                capture_output=True, text=True, timeout=60,
            )
            check("verify catches a non-bold note run", proc.returncode == EXIT_MISMATCH,
                  proc.stdout + proc.stderr)
    proc = subprocess.run(
        [sys.executable, script, "render"], capture_output=True, text=True, timeout=30
    )
    check("render without arguments exits 2", proc.returncode == EXIT_USAGE,
          f"exit {proc.returncode}")
    proc = subprocess.run(
        [sys.executable, script, "render", "no-such-file.md", "out.docx"],
        capture_output=True, text=True, timeout=30,
    )
    if HAVE_DOCX:
        expected = EXIT_USAGE
        hint = ""
    else:
        expected = EXIT_USAGE
        hint = " (python-docx hint path)"
    check(f"render on a missing input exits 2{hint}",
          proc.returncode == expected, f"exit {proc.returncode}")

    print("render_script_docx.py selftest")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
