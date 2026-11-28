#!/usr/bin/env python3
"""Contract tests for the opt-in PDF text-layer extra (formats issue #167,
owner amendment 2026-11-27: the end user installs only what they need).

Run: python3 tests/humanizer/test_pdf_text.py
Exit 0 = every contract gate green (SKIP lines, never failures, cover the
paths that need the optional reader on this machine).

Pins:
1. Absent reader: read_pdf_text returns ("", hint); the hint names the
   optional install (pip install pypdf) and the native-reading note; the
   module never raises out of read_pdf_text.
2. Present reader (SKIP when pypdf is not installed on this machine): a
   minimal text-layer PDF extracts its text; a scanned-image style PDF
   (no text objects) reads as "" with no hint (text layer only, no OCR
   claim).
3. Report surface: a .pdf candidate runs the report on the extracted
   text (SKIP without the reader); the usage message names the .pdf
   input; the samples loader skips an unreadable PDF with the defined
   note and keeps the .md files.
4. Default payload: the lazy import sits inside the one PDF branch; the
   battery report module's import set stays in its pinned stdlib set
   (checked in test_voice_battery.py; this file re-checks pdf_text.py).
"""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import os

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PLUGIN_DIR = REPO_ROOT / "humanizer"

fails = []


def ck(cond, name, detail=""):
    if cond:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}" + (f" ({detail})" if detail else ""))
        fails.append(name)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pdf_mod = load_module("hc_pdf_text", PLUGIN_DIR / "learn" / "pdf_text.py")

HAS_PYPDF = True
try:
    import pypdf  # noqa: F401  (presence probe for the present-reader paths)
except Exception:
    HAS_PYPDF = False


def _mk_pdf(path, text):
    """A minimal one-page PDF with one Helvetica text object; xref offsets
    computed so the file parses without repair."""
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                   b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    stream = ("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % text).encode("ascii")
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >> stream\n"
                   + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_pos)).encode()
    path.write_bytes(out)
    return path


# 1. absent-reader path (deterministic: block the module via sys.modules) ------
saved = sys.modules.pop("pypdf", None)
try:
    sys.modules["pypdf"] = None  # import raises ImportError; find_spec guards first
    text, hint = pdf_mod.read_pdf_text("whatever.pdf")
    ck(text == "" and hint is not None and "pip install pypdf" in hint,
       "pdf extra: absent reader -> empty text plus the one-line install hint",
       str(hint))
    ck("natively" in (hint or ""),
       "pdf extra: the hint names the native-reading option")
    try:
        pdf_mod.read_pdf_text(None)
        raised = False
    except Exception:
        raised = True
    ck(not raised, "pdf extra: read_pdf_text never raises (fail-open contract)")
finally:
    if saved is None:
        sys.modules.pop("pypdf", None)
    else:
        sys.modules["pypdf"] = saved

# 2. present-reader paths ------------------------------------------------------
if HAS_PYPDF:
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        good = _mk_pdf(tdp / "good.pdf", "Hello voice gate text layer")
        text, hint = pdf_mod.read_pdf_text(good)
        ck(hint is None and "Hello voice gate" in text,
           "pdf extra: a text-layer PDF extracts its text", repr(text[:60]) + str(hint))
        blank = _mk_pdf(tdp / "blank.pdf", "")
        text_b, hint_b = pdf_mod.read_pdf_text(blank)
        ck(hint_b is None and text_b.strip() == "",
           "pdf extra: a textless (scanned-image style) PDF reads empty with no hint")
        text_c, hint_c = pdf_mod.read_pdf_text(tdp / "missing.pdf")
        ck(text_c == "" and hint_c is not None and "pypdf failed" in hint_c,
           "pdf extra: an unreadable file yields the defined failure line, no exception")
    # 3. report surface with the reader present
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
               "VOICE_GATE_LOG": str(tdp / "gate.log"), "VOICE_GATE_VECTOR": "off"}
        (tdp / "learned").mkdir()
        cand = _mk_pdf(tdp / "cand.pdf", "The scanner reads the rules first. Save the file after the edit.")
        r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                            str(cand)], capture_output=True, text=True, env=env)
        ck(r.returncode == 0 and "voice fit" in r.stdout and "L10-19" in r.stdout,
           "report: a .pdf candidate runs the full report on the extracted text")
        samples = tdp / "samples"
        samples.mkdir()
        _mk_pdf(samples / "with-text.pdf", "The reader parses this page for the pool.")
        (samples / "plain.md").write_text("The scanner reads the rules first.", encoding="utf-8")
        cand_md = tdp / "cand.md"
        cand_md.write_text("The scanner reads the rules first. Save the file after the edit.",
                           encoding="utf-8")
        rs = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                             str(cand_md), "--samples", str(samples)],
                            capture_output=True, text=True, env=env)
        ck(rs.returncode == 0,
           "report: --samples accepts a mixed .md/.pdf directory with the reader present")
else:
    print("SKIP pdf present-reader paths: pypdf is not installed on this machine "
          "(the opt-in extra is the point; the absent-reader pins above still ran)")

# 3b. report surface WITHOUT the reader (the CI shape) --------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
           "VOICE_GATE_LOG": str(tdp / "gate.log"), "VOICE_GATE_VECTOR": "off"}
    (tdp / "learned").mkdir()
    saved = sys.modules.pop("pypdf", None)
    try:
        sys.modules["pypdf"] = None
        env_np = {**env, "PYTHONPATH": ""}
        code = ("import sys; sys.modules['pypdf'] = None; sys.argv = "
                "['r', %r]; import importlib.util as iu; spec = iu.spec_from_file_location"
                "('r', %r); m = iu.module_from_spec(spec); spec.loader.exec_module(m); "
                "sys.exit(m.main())") % (str(tdp / "cand.pdf"), str(PLUGIN_DIR / "learn" / "voice_battery_report.py"))
        (tdp / "cand.pdf").write_bytes(b"%PDF-1.4\n")
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                           text=True, env=env_np)
        ck(r.returncode == 2 and "pip install pypdf" in r.stderr,
           "report: a .pdf candidate without the reader prints the one-line hint and "
           "exits 2 (graceful skip, no error)")
        samples = tdp / "samples"
        samples.mkdir()
        (samples / "a.pdf").write_bytes(b"%PDF-1.4\n")
        (samples / "b.md").write_text("The scanner reads the rules first.", encoding="utf-8")
        code_s = ("import sys; sys.modules['pypdf'] = None; sys.argv = "
                  "['r', '-', '--samples', %r]; import importlib.util as iu; "
                  "spec = iu.spec_from_file_location('r', %r); m = iu.module_from_spec(spec); "
                  "spec.loader.exec_module(m); "
                  "sys.stdout.write('CAND'); sys.exit(m.main())") % (str(samples), str(PLUGIN_DIR / "learn" / "voice_battery_report.py"))
        rs = subprocess.run([sys.executable, "-I", "-c", code_s], capture_output=True,
                            text=True, env=env_np, input="The scanner reads the rules first.")
        ck(rs.returncode == 0 and "pip install pypdf" in rs.stderr,
           "report: --samples skips a PDF without the reader after the one-line hint "
           "and keeps the .md files (exit 0)")
    finally:
        if saved is None:
            sys.modules.pop("pypdf", None)
        else:
            sys.modules["pypdf"] = saved

# 4. lazy-import shape ----------------------------------------------------------
src = (PLUGIN_DIR / "learn" / "pdf_text.py").read_text(encoding="utf-8")
ck("from pypdf import" in src and src.count("pypdf import") >= 1
   and src.index("def _load_reader") < src.index("from pypdf import"),
   "pdf extra: the pypdf import sits lazily inside the loader (module scope stays clean)")

print(f"\npdf text extra: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
