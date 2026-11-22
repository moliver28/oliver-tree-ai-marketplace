#!/usr/bin/env python3
"""edit_learning.py: post-hoc edit learning for the humanizer (Tier 2, ruling 2, zero-LLM).

When the user edited a delivered copy by hand, teach the plugin from the pair:

    python3 edit_learning.py <edited-file> <delivered-original-file> [--learned-dir DIR]

Two-argument contract (both required):
1. The delivered original's sha256 is matched against learned/deliveries.log
   column 2. /voice appends one line there after every successful non-dry
   delivery: "<date>\\t<sha256(delivered)>\\t<target id/path>" (a shell append,
   zero model tokens, in addition to the phrases.log line that stays
   verbatim-input). No matching hash -> one line, nothing learned:
   "no matching delivery recorded; nothing learned".
2. Edit magnitude = changed-token share from difflib.SequenceMatcher opcodes
   over word tokens: matched = tokens inside equal blocks; share = (1 -
   matched / max(1, max(before_tokens, after_tokens))) * 100, rounded to one
   decimal — the share of the larger token stream that changed, bounded to
   0-100%. (difflib unified-diff machinery, magnitude only; the pair is stored
   whole, never the diff.)
3. share > 15% -> substantial: BEFORE is written to
   learned/edit-delta/before/<sha256(AFTER)>.txt and AFTER to
   learned/edit-delta/after/<sha256(AFTER)>.txt (classifier negative /
   positive; retrain pending). share <= 15% -> light: AFTER is copied to
   learned/edit-delta/light/<sha256(AFTER)>.txt and THAT durable path joins
   learned/clean-corpus-index.txt as "<path>\\tedit-confirmed" (durable copy, so
   index entries survive moves of the user's original file); BEFORE discarded.
4. One line out, e.g. "learned: substantial edit (34% changed) -> classifier
   retrain pending" / "learned: light edit (6% changed) -> corpus updated".
   Never mentions model tokens.

learn_run(before_text, after_text, learned_dir) is the importable core
(scripts/verify.py exercises it without the CLI); append_delivery() writes the
deliveries.log line for tools and tests. Every step is deterministic; identical
inputs produce identical files (re-runs overwrite the same content, and an
already-indexed light edit is not duplicated).

Exit codes: 0 = processed (or the defined no-match case); 2 = bad arguments.
"""
import argparse
import difflib
import hashlib
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/

WORD_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)
SUBSTANTIAL_ABOVE_PCT = 15.0
DELIVERIES_LOG = "deliveries.log"
CLEAN_CORPUS_INDEX = "clean-corpus-index.txt"
PROVENANCE_TAG = "edit-confirmed"


def _learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides, same
    contract as hooks/voice_tells.py learned_dir())."""
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def delivery_hash(text):
    """sha256 hexdigest of a delivered text (deliveries.log column 2)."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def append_delivery(learned, date, dhash, target):
    """Append one deliveries.log line (tools + tests; the /voice command
    appends the same format with a plain shell redirect)."""
    log = Path(learned) / DELIVERIES_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{date}\t{dhash}\t{target}\n")


def find_delivery(learned, dhash):
    """ deliveries.log row for a delivered-text hash, or None. Tolerates
    trailing columns; a malformed line (fewer than 2 columns) is skipped."""
    log = Path(learned) / DELIVERIES_LOG
    if not log.is_file():
        return None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[1].strip() == dhash:
            return cols
    return None


def changed_share(before_text, after_text):
    """Changed-token share in percent (see module docstring for the exact
    definition; difflib.SequenceMatcher opcodes over word tokens, bounded to
    0-100)."""
    before = WORD_RE.findall(before_text)
    after = WORD_RE.findall(after_text)
    sm = difflib.SequenceMatcher(None, before, after, autojunk=False)
    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
    return round((1.0 - matched / max(1, max(len(before), len(after)))) * 100.0, 1)


def classify_edit(before_text, after_text):
    """{"changed_pct": float, "substantial": bool} — share > 15% is substantial."""
    share = changed_share(before_text, after_text)
    return {"changed_pct": share, "substantial": share > SUBSTANTIAL_ABOVE_PCT}


def learn_run(before_text, after_text, learned):
    """Core edit-learning step (importable, deterministic). Returns
    {"status": "no_match" | "substantial" | "light", "changed_pct": float|None,
     "message": one line, "paths": [written files]}."""
    learned = Path(learned)
    dhash = delivery_hash(before_text)
    hit = find_delivery(learned, dhash)
    if hit is None:
        return {"status": "no_match", "changed_pct": None,
                "message": "no matching delivery recorded; nothing learned", "paths": []}
    share = changed_share(before_text, after_text)
    after_hash = delivery_hash(after_text)
    if share > SUBSTANTIAL_ABOVE_PCT:
        before_path = learned / "edit-delta" / "before" / f"{after_hash}.txt"
        after_path = learned / "edit-delta" / "after" / f"{after_hash}.txt"
        for p, content in ((before_path, before_text), (after_path, after_text)):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return {"status": "substantial", "changed_pct": share,
                "message": f"learned: substantial edit ({share:g}% changed) -> classifier retrain pending",
                "paths": [str(before_path), str(after_path)]}
    light_dir = learned / "edit-delta" / "light"
    light_dir.mkdir(parents=True, exist_ok=True)
    light_path = light_dir / f"{after_hash}.txt"
    light_path.write_text(after_text, encoding="utf-8")
    index = learned / CLEAN_CORPUS_INDEX
    index.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if index.is_file():
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            cols = line.split("\t")
            if cols:
                existing.add(cols[0].strip())
    line = f"{light_path}\t{PROVENANCE_TAG}"
    if str(light_path) not in existing:  # already indexed: no duplicate line
        with open(index, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return {"status": "light", "changed_pct": share,
            "message": f"learned: light edit ({share:g}% changed) -> corpus updated",
            "paths": [str(light_path), str(index)]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edited", help="the file the user edited by hand (AFTER)")
    ap.add_argument("delivered", help="the original delivered copy (BEFORE; a file or saved paste)")
    ap.add_argument("--learned-dir", default=None,
                    help="learned-artifact directory (default: the plugin's learned/, VOICE_LEARNED_DIR overrides)")
    a = ap.parse_args()
    learned = Path(a.learned_dir).expanduser() if a.learned_dir else _learned_dir()
    edited = Path(a.edited).expanduser()
    delivered = Path(a.delivered).expanduser()
    for p in (edited, delivered):
        if not p.is_file():
            print(f"missing file: {p}", file=sys.stderr)
            return 2
    result = learn_run(delivered.read_text(encoding="utf-8", errors="replace"),
                       edited.read_text(encoding="utf-8", errors="replace"),
                       learned)
    print(result["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
