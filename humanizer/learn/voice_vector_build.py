#!/usr/bin/env python3
"""voice-vector-build.py: embed the tell exemplars, calibrate per-class thresholds,
and persist the user's clean-corpus voice centroid (zero LLM, one embed pass).

Usage: python3 voice-vector-build.py [--backend ollama|onnx] [--bg FILE ...]
                                     [--corpus PATH ...] [--channel]
Writes into the plugin's learned/ directory (hooks/voice_tells.py reads them
from there at scan time):
- voice-tells-vectors.json     exemplar vectors, keyed by backend
- voice-tells-calibration.json per-class thresholds, keyed by backend
- voice-centroid.json          clean-corpus voice centroid (Tier 1, issue #127),
                               backend-keyed; the centroid is the L2-normalized
                               mean of PER-DOCUMENT chunk embeddings of the
                               user's clean corpus ("unit": "document-chunks")

All three files are per-user artifacts: they are never shipped with the plugin,
and a scan without them simply runs the regex layer (fail-open). The build
consumes a USER-supplied corpus and embeds the user's EFFECTIVE exemplar set;
it never reads or ships any packaged vector payload.
Run once per backend: embedding spaces are backend-specific and must never mix.

Hash guard (ruling 1, issue #127 — nothing re-embeds when inputs are unchanged):
before embedding anything, the build hashes the sorted corpus files (sha256 of
concatenated contents), the background files and the effective exemplar set.
When voice-tells-vectors.json AND voice-tells-calibration.json AND
voice-centroid.json already match backend + hashes (+ channel layout), it
prints "current (hash <12 chars>), nothing rebuilt" and exits WITHOUT loading
the embedder. A stale centroid with current vectors/calibration rebuilds the
centroid only (no exemplar or background re-embedding).

Thresholds follow the validated calibration recipe: per class, background
p99 + 0.03 measured on clean prose (--bg, default: the plugin's own markdown).
Background chunks colliding with a class threshold are logged warn-mode
(vec_collision, log-only) and recorded in the calibration table, never fatal.
Since v1.1.0 the background is chunked per document (sorted file order), the
same chunks the centroid consumes, so one embedding pass serves both.

Corpus: --corpus takes the user's clean writing (files or directories of
.md/.txt, same input contract as build_voice_profile.py); it defaults to the
--bg calibration files. Entries of learned/clean-corpus-index.txt (light-edit
confirmations, see learn/edit_learning.py) join the corpus; their contents are
part of the corpus hash, so a new light edit changes the hash and triggers the
one rebuild that reflects it.

--channel: with --corpus directories that have channel subdirectories
(immediate child dirs), per-channel centroids are stored in the same file
under "channels": {name: centroid}. Files not under a channel subdir
contribute to the global centroid only. Without the flag the entry carries no
channels (and rebuilding without the flag drops previously stored ones).

Re-run after editing EXEMPLARS in hooks/voice_tells.py or the runtime state
file voice-rules.json (issue #5): the build embeds the EFFECTIVE exemplars
(embedded + state-file, provenance-keyed; state exemplars beyond the embedded
list get auto-labels tell-<i>).

All embeddings in one run go through the shared per-process memo
(hooks/voice_tells.py embed_cached): each unique text is embedded exactly once,
even where calibration background and corpus overlap.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "voice_tells", HERE.parent / "hooks" / "voice_tells.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)
_bvp_spec = importlib.util.spec_from_file_location(
    "voice_profile_collect", HERE / "build_voice_profile.py")
bvp = importlib.util.module_from_spec(_bvp_spec)
_bvp_spec.loader.exec_module(bvp)

LABELS = {
    0: "negative-parallelism", 1: "paradigm-shift inflation", 2: "testament/commitment copula",
    3: "nestled/vibrant promo", 4: "pivotal-moment landscape", 5: "rapidly-evolving opener",
    6: "at-the-end-of-the-day authority", 7: "dive-in signpost", 8: "real-question authority",
    9: "game-changer empowerment sweep", 10: "aphorism/antimetabole density",
    11: "experts-underscore weasel", 12: "challenges-and-prospects formula",
    13: "reframe-hammer motif", 14: "reassurance kicker", 15: "robust-solutions slop",
}


def _p99(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, math.ceil(0.99 * len(xs)) - 1))]


def plugin_root():
    """Plugin root: nearest dir above this file whose .claude-plugin carries
    plugin.json (learn/ and hooks/ are the plugin's own anatomy). Works from
    any checkout depth and from an installed plugin copy; None when there is
    no plugin root above this file (caller decides)."""
    root = HERE
    while not (root / ".claude-plugin" / "plugin.json").is_file():
        if root == root.parent:
            return None
        root = root.parent
    return root


def default_corpus_root():
    """Default calibration corpus root: the plugin root (its own markdown is
    the shipped clean-prose sample). None when no plugin root exists."""
    return plugin_root()


def _default_prose():
    root = default_corpus_root()
    if root is None:
        raise SystemExit("no plugin root above voice_vector_build.py; pass --bg FILE ...")
    return sorted(root.rglob("*.md"))


def _file_hash(paths):
    """Content hash over sorted files (ruling 1): sha256 of the concatenated
    contents, path-tagged so a renamed file counts as a change."""
    digest = hashlib.sha256()
    for p in sorted(paths):
        digest.update(str(p).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(Path(p).read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _exemplar_hash(exemplars):
    payload = json.dumps(list(exemplars), ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _index_entries(learned):
    """clean-corpus-index.txt entries (light-edit confirmations): lines of
    "<path>\\t<provenance>". Missing or non-.md/.txt paths are skipped and
    counted (defined behavior, never fatal). Returns (sorted unique files,
    skipped count)."""
    idx = Path(learned) / "clean-corpus-index.txt"
    files, skipped = [], 0
    if not idx.is_file():
        return files, skipped
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line.split("\t")[0].strip()).expanduser()
        if p.is_file() and p.suffix.lower() in (".md", ".txt"):
            files.append(p)
        else:
            skipped += 1
    return sorted(set(files)), skipped


def _channel_of(path, corpus_dir_args):
    """--channel mode: the channel is the immediate subdirectory under a corpus
    directory argument. Returns the channel name, or None (global centroid)."""
    for arg in corpus_dir_args or []:
        try:
            rel = Path(path).resolve().relative_to(Path(arg).expanduser().resolve())
        except Exception:
            continue
        if len(rel.parts) > 1:
            return rel.parts[0]
    return None


def _doc_chunks(files):
    """Per-document chunks in sorted file order (the centroid unit and, since
    v1.1.0, the calibration background unit)."""
    chunks = []
    for f in sorted(files):
        text = Path(f).read_text(encoding="utf-8", errors="replace")
        chunks.extend(vt._chunks(text))
    return chunks


def _normalized_mean(vectors):
    """L2-normalized mean of same-dimension vectors (the centroid)."""
    mean = [sum(col) / len(col) for col in zip(*vectors)]
    norm = math.sqrt(sum(x * x for x in mean))
    return [x / norm for x in mean] if norm else mean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=("ollama", "onnx"), default="ollama")
    ap.add_argument("--bg", nargs="*", default=None,
                    help="clean-prose files for calibration (default: the plugin's own markdown)")
    ap.add_argument("--corpus", nargs="*", default=None,
                    help="user clean corpus files/dirs (.md/.txt) for the voice centroid (default: the --bg files)")
    ap.add_argument("--channel", action="store_true",
                    help="with --corpus directories: store per-channel centroids (immediate subdirs)")
    a = ap.parse_args()

    learned = vt.learned_dir()
    bg_files = bvp.collect_files(a.bg if a.bg else [str(p) for p in _default_prose()])
    corpus_files = bvp.collect_files(a.corpus) if a.corpus else list(bg_files)
    index_files, index_skipped = _index_entries(learned)
    corpus_all = sorted({Path(f).resolve() for f in list(corpus_files) + list(index_files)})
    corpus_hash = _file_hash(corpus_all)
    bg_hash = _file_hash(bg_files)
    exemplar_hash = _exemplar_hash(vt.effective_rules()["exemplars"])
    if index_skipped:
        print(f"index entries skipped (missing or not .md/.txt): {index_skipped}")

    cache = _read_json(vt.CACHE_PATH) or {}
    cal = _read_json(vt.CAL_PATH) or {}
    cen = _read_json(vt.CENTROID_PATH) or {}
    vec_b = (cache.get("backends") or {}).get(a.backend) or {}
    cal_b = (cal.get("backends") or {}).get(a.backend) or {}
    cen_b = (cen.get("backends") or {}).get(a.backend) or {}
    channels_expected = sorted({name for f in corpus_files
                                if a.corpus and a.channel
                                and (name := _channel_of(f, a.corpus))})
    vec_ok = bool(vec_b.get("vectors")) and vec_b.get("exemplar_hash") == exemplar_hash
    cal_ok = bool(cal_b.get("thresholds")) and cal_b.get("corpus_hash") == bg_hash
    cen_ok = (isinstance(cen_b.get("centroid"), list) and bool(cen_b["centroid"])
              and cen_b.get("corpus_hash") == corpus_hash
              and sorted((cen_b.get("channels") or {}).keys()) == channels_expected)
    if vec_ok and cal_ok and cen_ok:
        # Ruling 1 (issue #127): identical inputs -> zero embedding work.
        print(f"current (hash {corpus_hash[:12]}), nothing rebuilt")
        return 0

    rebuilt = []
    if not (vec_ok and cal_ok):
        vectors = []
        exemplars = vt.effective_rules()["exemplars"]  # embedded + state-file exemplars (issue #5)
        for i, text in enumerate(exemplars):
            v, _ = vt.embed_cached(text, timeout=30, backend=a.backend)
            label = LABELS.get(i, f"tell-{i}")
            vectors.append({"label": label, "text": text, "vec": v})
            print(f"embedded {i}: {label}")
        bg_chunks = _doc_chunks(bg_files)
        print(f"calibrating {a.backend} against {len(bg_chunks)} chunks from {len(bg_files)} files")
        sims = {ex["label"]: [] for ex in vectors}
        for c in bg_chunks:
            v, _ = vt.embed_cached(c, timeout=60, backend=a.backend)
            for ex in vectors:
                sims[ex["label"]].append(vt._cosine(v, ex["vec"]))
        thresholds, collisions = {}, []
        for label, xs in sims.items():
            t = round(_p99(xs) + vt.CAL_MARGIN, 3)
            thresholds[label] = t
            for k, x in enumerate(xs):
                if x >= t:  # warn-mode: log-only, the formula stays
                    collisions.append({"class": label, "sim": round(x, 3), "chunk": bg_chunks[k][:80]})
                    vt._log_vec("vec_collision", {"backend": a.backend, "class": label,
                                                  "sim": round(x, 3), "threshold": t})
        print(f"thresholds: {json.dumps(thresholds)}")
        print(f"background collisions: {len(collisions)} (warn-mode, logged)")
        cache = _read_json(vt.CACHE_PATH) or {}  # re-read: another backend build may have run meanwhile
        cal = _read_json(vt.CAL_PATH) or {}
        cache.setdefault("format", 2); cache.setdefault("backends", {})
        cal.setdefault("format", 1); cal.setdefault("formula", "p99+0.03"); cal.setdefault("backends", {})
        cache["backends"][a.backend] = {
            "model": vt.MODEL if a.backend == "ollama" else vt.ONNX_MODEL,
            "built": datetime.now(timezone.utc).isoformat(),
            "dim": len(vectors[0]["vec"]), "vectors": vectors,
            "exemplar_hash": exemplar_hash}
        cal["backends"][a.backend] = {
            "built": datetime.now(timezone.utc).isoformat(),
            "background": {"files": len(bg_files), "chunks": len(bg_chunks)},
            "thresholds": thresholds, "collisions": collisions,
            "corpus_hash": bg_hash}
        vt._atomic_write(vt.CACHE_PATH, json.dumps(cache))
        vt._atomic_write(vt.CAL_PATH, json.dumps(cal))
        print(f"wrote {vt.CACHE_PATH} and {vt.CAL_PATH} ({a.backend}, {len(vectors)} exemplars)")
        rebuilt.append("vectors+calibration")

    if not cen_ok:
        doc_vecs, channel_vecs = [], {}
        n_chunks = 0
        for f in corpus_all:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
            for c in vt._chunks(text):
                v, _ = vt.embed_cached(c, timeout=60, backend=a.backend)
                doc_vecs.append(v)
                if a.corpus and a.channel:
                    name = _channel_of(f, a.corpus)
                    if name:
                        channel_vecs.setdefault(name, []).append(v)
                n_chunks += 1
        if not doc_vecs:
            print("no corpus chunks; voice-centroid.json not written (pass --corpus with .md/.txt files)")
            return 0
        entry = {
            "backend": a.backend,
            "model": vt.MODEL if a.backend == "ollama" else vt.ONNX_MODEL,
            "corpus_hash": corpus_hash,
            "unit": "document-chunks",
            "files": len(corpus_all), "chunks": n_chunks,
            "centroid": _normalized_mean(doc_vecs),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        if a.corpus and a.channel:
            entry["channels"] = {name: _normalized_mean(vs) for name, vs in sorted(channel_vecs.items())}
            print(f"channels: {', '.join(sorted(channel_vecs)) or '(none found)'}")
        cen = _read_json(vt.CENTROID_PATH) or {}
        cen.setdefault("format", 1); cen.setdefault("unit", "document-chunks"); cen.setdefault("backends", {})
        cen["backends"][a.backend] = entry
        vt._atomic_write(vt.CENTROID_PATH, json.dumps(cen))
        print(f"voice centroid: {n_chunks} document chunks from {len(corpus_all)} files "
              f"(unit: document-chunks) -> {vt.CENTROID_PATH}")
        rebuilt.append("centroid")

    if rebuilt:
        print(f"rebuilt: {', '.join(rebuilt)}; "
              f"{len(vt._embed_memo)} unique texts embedded this run (per-process memo, one pass)")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit or 0)
