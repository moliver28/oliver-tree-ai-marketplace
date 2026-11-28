#!/usr/bin/env python3
"""pdf_text.py: the text-layer PDF reader of the humanizer plugin (opt-in
extra; formats issue #167, owner amendment 2026-11-27: the end user
installs only what they need).

The reader imports pypdf lazily inside the one PDF branch: the default
payload never grows, and a PDF that arrives without the reader installed
skips gracefully with a one-line hint (naming the optional install and
the fact that most LLM harnesses read PDFs natively). Text layer only:
no OCR claim; a scanned-image PDF reads as no text and the caller states
so in its own note.

read_pdf_text(path) -> (text, hint):
  text  the extracted text ("" when the PDF carries no text layer or the
        reader is absent)
  hint  None, or the one line the caller prints before skipping (the
        install hint when pypdf is absent, a defined failure line when
        the file itself does not open). Fail-open: this module never
        raises out of read_pdf_text.

Floor pin (documented in learn/LEARN-VOICE.md and learned/README.md):
pypdf >= 7.2.0, the newest stable release at build time (published
2026-11-26; floor pin only, no ceiling pin). The manifest schema carries
no optional-dependencies key, so the extra is documented instead of
declared and the import stays lazy: absence = graceful skip.
"""
import importlib.util
from pathlib import Path

PYPDF_HINT = ("PDF text layer needs the optional reader: pip install pypdf "
              "(most LLM harnesses read PDFs natively); the plugin skips the file.")


def _load_reader():
    """The PdfReader class, or None when the extra is absent or broken
    (fail-open; the ValueError case covers a deliberately blocked entry
    in sys.modules, which the contract tests use)."""
    try:
        if importlib.util.find_spec("pypdf") is None:
            return None
    except (ValueError, ModuleNotFoundError):
        return None
    try:
        from pypdf import PdfReader  # lazy: the one optional-dependency branch
        return PdfReader
    except Exception:
        return None


def read_pdf_text(path):
    """The text layer of one PDF. Returns (text, hint); hint None on
    success (text may be "" for a textless PDF), the one-line skip
    message otherwise."""
    load = _load_reader()
    if load is None:
        return "", PYPDF_HINT
    try:
        reader = load(str(Path(path).expanduser()))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n".join(pages), None
    except Exception as e:
        return "", ("pypdf failed on %s (%r); the plugin skips the file."
                    % (Path(path).name, e))
