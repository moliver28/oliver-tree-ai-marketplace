#!/usr/bin/env python3
"""calibrate.py: run the gate's regex layer over a clean-writing corpus (zero LLM).

Input: a directory of the user's real CLEAN writing (.md/.txt), optionally a
second directory of edited deliveries (posts/docs that already shipped). The
tool runs the hooks/voice_tells.py regex layer (including any runtime state
overrides) over every sentence and writes learned/calibration.json:

- per_class: one entry per pattern label with hits, files affected, and hits
  per 1000 sentences. A class with zero hits is a defined, expected state:
  rate 0.0, no flag (most of the register never fires on clean prose).
- deviations: patterns that fire on the user's clean prose at or above
  --floor hits per 1000 sentences. Each deviation is a decision for the USER
  (ban it, allow it, or add a state-file override), never an automatic rule
  change; the tool prints "decide by hand" for every flagged class.
- index entries (when learned/clean-corpus-index.txt exists): light-edit
  confirmations recorded by learn/edit_learning.py are scanned in addition to
  --corpus (same counts, merged; missing files are skipped and counted).
- deliveries (when given): the same counts over the deliveries corpus, so the
  user can compare clean writing against shipped work.

Deterministic: file order is sorted, every ordering is count-descending then
lexicographic, identical inputs produce identical bytes. No network, no model.

Exit codes: 0 = calibration written (including the empty-corpus case: zeros,
a clear message); 2 = bad arguments (missing path, corpus path is a file).
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/
DEFAULT_OUT = PLUGIN_DIR / "learned" / "calibration.json"

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides, same
    contract as hooks/voice_tells.py learned_dir())."""
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def load_voice_tells():
    spec = importlib.util.spec_from_file_location(
        "voice_tells_calibrate", HERE.parent / "hooks" / "voice_tells.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collect_files(root):
    """Sorted .md/.txt files under root; a missing path or a file where a
    directory is required raises SystemExit(2) with a clear message."""
    p = Path(root).expanduser()
    if not p.exists():
        print(f"missing path: {p}", file=sys.stderr)
        raise SystemExit(2)
    if p.is_file():
        print(f"corpus must be a directory of .md/.txt files, got a file: {p}", file=sys.stderr)
        raise SystemExit(2)
    return sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in (".md", ".txt"))


def scan_corpus(files, compiled):
    """One deterministic pass: per-label hit counts, files affected, sentence
    count. File order is sorted; every counter is plain arithmetic."""
    per_class = {label: {"hits": 0, "files": 0} for _rx, label in compiled}
    sentences = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        file_sents = []
        for para in paras:
            file_sents += [s for s in SENT_SPLIT.split(para.strip()) if s.strip()]
        sentences += len(file_sents)
        fired_here = set()
        for s in file_sents:
            for rx, label in compiled:
                if rx.search(s):
                    per_class[label]["hits"] += 1
                    fired_here.add(label)
        for label in fired_here:
            per_class[label]["files"] += 1
    n = sentences
    out = {}
    for _rx, label in compiled:
        hits = per_class[label]["hits"]
        out[label] = {
            "hits": hits,
            "files": per_class[label]["files"],
            "per_1k_sentences": round(hits * 1000.0 / n, 2) if n else 0.0,
        }
    return out, sentences


def index_entries(path):
    """clean-corpus-index.txt entries: "<path>\\t<provenance>" lines; the path
    column is used. Missing or non-.md/.txt paths are skipped and counted
    (defined behavior, never fatal). Returns (sorted unique files, skipped)."""
    p = Path(path).expanduser()
    files, skipped = [], 0
    if not p.is_file():
        return files, skipped
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        cand = Path(line.split("\t")[0].strip()).expanduser()
        if cand.is_file() and cand.suffix.lower() in (".md", ".txt"):
            files.append(cand)
        else:
            skipped += 1
    return sorted(set(files)), skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", required=True, help="directory of the user's real clean writing (.md/.txt)")
    ap.add_argument("--deliveries", default=None, help="optional directory of edited deliveries for comparison")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="calibration JSON path (default: the plugin's learned/calibration.json)")
    ap.add_argument("--index", default=None, help="clean-corpus-index.txt path (default: learned/clean-corpus-index.txt; its entries are scanned in addition to --corpus)")
    ap.add_argument("--floor", type=float, default=1.0, help="deviation floor: hits per 1000 sentences that flag a class for review (default 1.0)")
    a = ap.parse_args()
    vt = load_voice_tells()
    eff = vt.effective_rules()
    compiled = [(re.compile(rx, re.IGNORECASE), label) for rx, label in eff["patterns"]]

    files = collect_files(a.corpus)
    index_path = Path(a.index).expanduser() if a.index else learned_dir() / "clean-corpus-index.txt"
    idx_files, idx_skipped = index_entries(index_path)
    merged = []
    seen = set()
    for f in sorted(files + idx_files):
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            merged.append(f)
    per_class, sentences = scan_corpus(merged, compiled)
    deviations = [
        {"label": label, "per_1k_sentences": d["per_1k_sentences"], "hits": d["hits"],
         "action": "decide by hand"}
        for label, d in sorted(per_class.items(), key=lambda kv: (-kv[1]["per_1k_sentences"], kv[0]))
        if d["per_1k_sentences"] >= a.floor
    ]
    deliveries = None
    delivery_sentences = 0
    delivery_files = []
    if a.deliveries:
        delivery_files = collect_files(a.deliveries)
        deliveries, delivery_sentences = scan_corpus(delivery_files, compiled)

    out_path = Path(a.out).expanduser()
    if out_path.parent and str(out_path.parent):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "corpus": str(Path(a.corpus).expanduser()),
        "files": len(files),
        "index": {"path": str(index_path), "entries": len(idx_files), "skipped": idx_skipped},
        "sentences": sentences,
        "patterns_checked": len(compiled),
        "deviation_floor_per_1k": a.floor,
        "per_class": per_class,
        "deviations": deviations,
    }
    if deliveries is not None:
        payload["deliveries"] = {"files": len(delivery_files),
                                 "sentences": delivery_sentences, "per_class": deliveries}
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if idx_skipped:
        print(f"index entries skipped (missing or not .md/.txt): {idx_skipped}")
    if not merged:
        print(f"no .md/.txt files under {a.corpus} and no readable index entries; "
              "calibration written with zero counts")
    else:
        print(f"calibrated {len(merged)} files ({len(files)} corpus + {len(idx_files)} index entries), "
              f"{sentences} sentences against "
              f"{len(compiled)} patterns: {sum(1 for d in per_class.values() if d['hits'])} classes fired, "
              f"{len(deviations)} deviations (floor {a.floor} per 1000 sentences) -> {out_path}")
    if deviations:
        print("decide by hand: flagged patterns fire on your clean prose. Ban them, allow them, "
              "or add an override in the runtime state file (voice-rules.json); nothing changes automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
