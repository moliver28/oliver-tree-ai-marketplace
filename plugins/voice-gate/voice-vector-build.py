#!/usr/bin/env python3
"""voice-vector-build.py: embed the tell exemplars and calibrate per-class thresholds.

Usage: python3 voice-vector-build.py [--backend ollama|onnx] [--bg FILE ...]
Writes voice-tells-vectors.json (exemplar vectors, keyed by backend) and
voice-tells-calibration.json (per-class thresholds) beside voice-tells.py.
Run once per backend: embedding spaces are backend-specific and must never mix.
Thresholds follow the owner-validated calibration recipe: per class,
background p99 + 0.03 measured on clean repo prose (--bg, default: repo
markdown). Background chunks colliding with a class threshold are logged
warn-mode (vec_collision, log-only) and recorded in the calibration table,
never fatal. Re-run after editing EXEMPLARS in voice-tells.py.
"""
import argparse
import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "voice_tells", HERE / "voice-tells.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

LABELS = {
    0: "negative-parallelism", 1: "paradigm-shift inflation", 2: "testament/commitment copula",
    3: "nestled/vibrant promo", 4: "pivotal-moment landscape", 5: "rapidly-evolving opener",
    6: "at-the-end-of-the-day authority", 7: "dive-in signpost", 8: "real-question authority",
    9: "game-changer empowerment sweep", 10: "antimetabole/aphorism density",
    11: "experts-underscore weasel", 12: "challenges-and-prospects formula",
    13: "funeral/reframe motif hammer", 14: "reassurance kicker", 15: "robust-solutions slop",
    16: "teaser handoff", 17: "performed candor",
}


def _p99(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(0.99 * len(xs)) - 1))]


def _repo_prose():
    root = HERE.parents[1]  # repo root when run from the marketplace checkout
    if not (root / ".claude-plugin").is_dir():
        raise SystemExit("no repo root above voice-tells.py; pass --bg FILE ...")
    return sorted(root.rglob("*.md"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=("ollama", "onnx"), default="ollama")
    ap.add_argument("--bg", nargs="*", default=None,
                    help="clean-prose files for calibration (default: repo markdown)")
    a = ap.parse_args()

    paths = a.bg if a.bg else _repo_prose()
    prose = "\n\n".join(Path(p).read_text(errors="replace") for p in paths)
    chunks = vt._chunks(prose, cap=400)
    print(f"calibrating {a.backend} against {len(chunks)} chunks from {len(paths)} files")

    cache, cal = vt._load_vectors(), vt._load_calibration()
    cache.setdefault("format", 2); cache.setdefault("backends", {})
    cal.setdefault("format", 1); cal.setdefault("formula", "p99+0.03"); cal.setdefault("backends", {})

    vectors = []
    for i, text in enumerate(vt.EXEMPLARS):
        v, _ = vt._embed(text, timeout=30, backend=a.backend)
        label = LABELS.get(i, f"tell-{i}")
        vectors.append({"label": label, "text": text, "vec": v})
        print(f"embedded {i}: {label}")

    sims = {ex["label"]: [] for ex in vectors}
    for j, c in enumerate(chunks):
        v, _ = vt._embed(c, timeout=60, backend=a.backend)
        for ex in vectors:
            sims[ex["label"]].append(vt._cosine(v, ex["vec"]))

    thresholds, collisions = {}, []
    for label, xs in sims.items():
        t = round(_p99(xs) + vt.CAL_MARGIN, 3)
        thresholds[label] = t
        for k, x in enumerate(xs):
            if x >= t:  # warn-mode: log-only, the formula stays
                collisions.append({"class": label, "sim": round(x, 3), "chunk": chunks[k][:80]})
                vt._log_vec("vec_collision", {"backend": a.backend, "class": label,
                                              "sim": round(x, 3), "threshold": t})
    print(f"thresholds: {json.dumps(thresholds)}")
    print(f"background collisions: {len(collisions)} (warn-mode, logged)")

    cache["backends"][a.backend] = {
        "model": vt.MODEL if a.backend == "ollama" else vt.ONNX_MODEL,
        "built": datetime.now(timezone.utc).isoformat(),
        "dim": len(vectors[0]["vec"]), "vectors": vectors}
    cal["backends"][a.backend] = {
        "built": datetime.now(timezone.utc).isoformat(),
        "background": {"files": len(paths), "chunks": len(chunks)},
        "thresholds": thresholds, "collisions": collisions}
    vt.CACHE_PATH.write_text(json.dumps(cache))
    vt.CAL_PATH.write_text(json.dumps(cal))
    print(f"wrote {vt.CACHE_PATH} and {vt.CAL_PATH} ({a.backend}, {len(vectors)} exemplars)")


if __name__ == "__main__":
    main()
