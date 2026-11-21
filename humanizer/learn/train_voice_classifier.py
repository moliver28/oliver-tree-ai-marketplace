#!/usr/bin/env python3
"""train_voice_classifier.py: trained char n-gram authorship classifier (Tier 2, zero-LLM).

Features: character 3-5-gram hashing trick. Each n-gram is mapped to one of
2^16 buckets by md5(n-gram) modulo buckets; counts become log-scaled tf
(1 + ln count) and the sparse vector is L2-normalized. Text is lowercased,
whitespace-collapsed and capped at 20000 chars before feature extraction.

Model: logistic regression, pure-Python offline SGD. No numpy, no third-party
imports. Fixed seed, deterministic document order (sorted by label then content
hash) and per-epoch LCG permutations; lr 0.1 with decay (0.1 / (1 + 0.3*epoch)),
8 epochs, early stop when the epoch loss improves by less than 1e-4 (plateau).

Training data (all deterministic, zero model tokens):
- positives, weight 1.0: the user's clean corpus (--corpus, same input contract
  as build_voice_profile.py: files or directories of .md/.txt).
- positives, weight 0.5 (provenance edit-confirmed): learned/edit-delta/after/
  texts and learned/clean-corpus-index.txt entries (written by learn/edit_learning.py
  when the user taught the plugin a hand edit of a delivered copy).
- negatives, weight 1.0: learned/edit-delta/before/ texts (substantial pre-edit
  deliveries; only substantial edits ever write that directory) and a
  deterministic synthetic AI-prose seeder (~200 docs) built from the embedded
  tell pattern labels + exemplars + generic AI phrasing templates. The seeder
  contains ZERO personal content.

Artifact learned/voice-classifier.json: {format, buckets, hash_algo,
ngram_range, weights (sparse), bias, voice_baseline, thresholds
{ai_flag, voice_delta}, corpus_hash, trained_at, seeder_version, train_stats}.
Hash guard (ruling 1, issue #127): the corpus hash covers every contributing
document plus the seeder/bucket configuration; with an unchanged hash the tool
prints "current (hash <12 chars>), nothing retrained" and does not train.

Inference (imported by hooks/gate.py, advisory only in 1.1.0):
    score(text) -> {"p_ai": float, "voice_delta": float} | None
p_ai = P(AI-authored) = 1 - sigmoid(w.x + b) with label 1 = user voice;
voice_delta = max(0, p_ai - voice_baseline), where voice_baseline is the
training-time mean p_ai over positive documents (the user's own score floor).
A missing or invalid artifact returns None; the gate treats None as skip.
The classifier NEVER blocks delivery by itself in 1.1.0.

Exit codes: 0 = trained (or the defined empty-input case: a clear message, no
file written, or the hash-guard case: nothing retrained); 2 = bad arguments.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/

BUCKETS = 1 << 16
NGRAM_RANGE = (3, 5)
HASH_ALGO = "md5-mod-65536"
FEATURE_CHARS_CAP = 20000
SEED = 20261121
EPOCHS = 8
LR0 = 0.1
LR_DECAY = 0.3
REG = 1e-5
PLATEAU = 1e-4
SEEDER_VERSION = 1
SEEDER_DOCS = 200
THRESHOLDS = {"ai_flag": 0.9, "voice_delta": 0.5}
WEIGHT_USER = 1.0
WEIGHT_EDIT_CONFIRMED = 0.5


def _learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides, same
    contract as hooks/voice_tells.py learned_dir())."""
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------- features: hashed char n-grams ----------------

def features(text):
    """Sparse hashed feature vector {bucket_index: l2-normalized log-tf}."""
    t = re.sub(r"\s+", " ", text.lower())[:FEATURE_CHARS_CAP]
    counts = {}
    lo, hi = NGRAM_RANGE
    for n in range(lo, hi + 1):
        for i in range(len(t) - n + 1):
            gram = t[i:i + n]
            idx = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16) % BUCKETS
            counts[idx] = counts.get(idx, 0) + 1
    vec = {i: 1.0 + math.log(c) for i, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {i: v / norm for i, v in vec.items()}


def _sigmoid(z):
    if z > 30.0:
        return 1.0
    if z < -30.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


# ---------------- deterministic synthetic AI-prose seeder ----------------

_SEED_TEMPLATES = [
    "In today's rapidly evolving {n1} landscape, {n2} is more important than ever.",
    "It is not just about {n1}; it is about {n2}.",
    "This marks a pivotal moment in the journey toward {n1}.",
    "At its core, {n1} is about unlocking {n2} at scale.",
    "Let's dive into {n1} and unpack what really matters.",
    "The real question is whether {n1} can navigate the complexities of {n2}.",
    "Organizations that leverage {n1} can supercharge their {n2}.",
    "From {n1} to {n2}, this game-changer empowers every team to thrive.",
    "Seamless integration unlocks the full potential of {n1}.",
    "Navigating the complexities of {n1} requires a robust {n2}.",
    "It is important to note that {n1} drives meaningful change.",
    "In conclusion, {n1} stands as a testament to {n2}.",
    "The ability to harness {n1} separates leaders from laggards.",
    "When it comes to {n1}, best-in-class teams consistently move the needle.",
    "Ultimately, this paradigm shift will revolutionize {n1}.",
    "Experts underscore the critical importance of {n1} in {n2}.",
    "And that's okay: every {n1} journey starts somewhere.",
    "With {n1} at the helm, the company continues to thrive, setting the stage for {n2}.",
]

_SEED_SLOTS = [
    "innovation", "scalability", "digital transformation", "synergy",
    "collaboration", "productivity", "growth", "resilience", "efficiency",
    "engagement", "data-driven insights", "customer success",
    "operational excellence", "market disruption", "thought leadership",
    "the ecosystem", "the roadmap", "the workflow",
]

_SEED_FRAG_WRAPPERS = [
    "When it comes to {frag}, the landscape shifts for everyone involved.",
    "It is not just about {frag}; it is about the paradigm it unlocks.",
    "This {frag} stands as a testament to seamless, world-class execution.",
    "Let's dive deep into {frag} and its game-changing potential.",
    "At the end of the day, {frag} is what really matters.",
    "Moving forward, {frag} will revolutionize how teams operate.",
    "The real question is {frag}, not the tools themselves.",
    "In today's rapidly evolving world, {frag} drives meaningful change.",
]


def _lcg(seed):
    """Deterministic 64-bit LCG stream (no random module)."""
    state = seed & ((1 << 64) - 1)
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        yield state


def _pick(rng, seq):
    return seq[next(rng) % len(seq)]


def _load_voice_tells():
    """Embedded pattern register (labels + exemplars) for the seeder; None when
    the module cannot be loaded (seeder falls back to templates only)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "voice_tells_seed", PLUGIN_DIR / "hooks" / "voice_tells.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _pattern_fragments(vt_mod):
    """Quoted fragments from the embedded pattern labels + the exemplar
    sentences: the raw material of the synthetic negatives."""
    frags = []
    if vt_mod is not None:
        for _rx, label in vt_mod.PATTERNS:
            frags.extend(re.findall(r"'([^']{6,80})'", label))
        frags.extend(vt_mod.EXEMPLARS)
    return sorted({f.strip() for f in frags if len(f.strip()) >= 6})


def _seed_docs(count=SEEDER_DOCS):
    """Deterministic synthetic AI-prose documents (zero personal content)."""
    rng = _lcg(SEED)
    frags = _pattern_fragments(_load_voice_tells())
    docs = []
    for _ in range(count):
        sents = []
        for _s in range(3 + next(rng) % 4):
            roll = next(rng) % 10
            if roll < 4 and frags:
                sents.append(_pick(rng, _SEED_FRAG_WRAPPERS).replace("{frag}", _pick(rng, frags)))
            else:
                sents.append(_pick(rng, _SEED_TEMPLATES)
                             .replace("{n1}", _pick(rng, _SEED_SLOTS))
                             .replace("{n2}", _pick(rng, _SEED_SLOTS)))
        docs.append(" ".join(sents))
    return sorted(set(docs))


# ---------------- training-data collection ----------------

def _collect_corpus(a):
    """--corpus via build_voice_profile.collect_files (files/dirs of .md/.txt);
    missing paths raise SystemExit(2) with a clear message."""
    spec = importlib.util.spec_from_file_location(
        "voice_profile_collect_classifier", HERE / "build_voice_profile.py")
    bvp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bvp)
    return bvp.collect_files(a.corpus) if a.corpus else []


def _delta_texts(learned, side):
    """learned/edit-delta/<side>/*.txt sorted (side: 'before' | 'after')."""
    d = Path(learned) / "edit-delta" / side
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".txt")


def _index_texts(learned):
    """clean-corpus-index.txt entries (path column); missing paths skipped and
    counted (defined behavior, never fatal)."""
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


def _corpus_hash(contrib, extra):
    """Content hash over every contributing document (sorted, tag + path +
    bytes) plus the seeder/bucket configuration."""
    digest = hashlib.sha256()
    for tag, path in sorted(contrib):
        digest.update(f"{tag}\x00{path}\x00".encode("utf-8"))
        digest.update(Path(path).read_bytes())
        digest.update(b"\x00")
    digest.update(json.dumps(extra, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _text_key(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# ---------------- model ----------------

def _lcg_perm(n, seed):
    """Deterministic permutation of range(n) via LCG (fixed-seed Fisher-Yates)."""
    idx = list(range(n))
    state = seed & ((1 << 64) - 1)
    for i in range(n - 1, 0, -1):
        state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        j = state % (i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return idx


def train(docs):
    """Offline SGD logistic regression. docs: [{"x": features, "y": 0|1,
    "weight": float}] in deterministic order. Returns (weights, bias,
    epochs_run, final_mean_loss)."""
    w, b = {}, 0.0
    prev_loss, epochs_run, final_loss = None, EPOCHS, 0.0
    for epoch in range(EPOCHS):
        lr = LR0 / (1.0 + LR_DECAY * epoch)
        total = 0.0
        eps = 1e-12
        for i in _lcg_perm(len(docs), SEED + 7919 * epoch):
            d = docs[i]
            z = b
            for k, v in d["x"].items():
                wk = w.get(k)
                if wk:
                    z += wk * v
            p = _sigmoid(z)
            y, wt = d["y"], d["weight"]
            total += -wt * (y * math.log(p + eps) + (1 - y) * math.log(1 - p + eps))
            g = (p - y) * wt
            if g:
                for k, v in d["x"].items():
                    wk = w.get(k, 0.0)
                    wk -= lr * (REG * wk + g * v)
                    if abs(wk) < 1e-12:
                        w.pop(k, None)
                    else:
                        w[k] = wk
                b -= lr * g
        final_loss = total / max(1, len(docs))
        epochs_run = epoch + 1
        if prev_loss is not None and prev_loss - final_loss < PLATEAU:
            break  # loss plateau: stop early, deterministically
        prev_loss = final_loss
    return w, b, epochs_run, final_loss


def evaluate(w, b, docs):
    """Plain-number training evaluation: correct counts per class and the mean
    p_ai over positives (the voice_baseline)."""
    pos_correct = neg_correct = pos_n = 0
    baseline_sum = 0.0
    for d in docs:
        z = b
        for k, v in d["x"].items():
            wk = w.get(k)
            if wk:
                z += wk * v
        p_ai = 1.0 - _sigmoid(z)
        if d["y"] == 1:
            pos_n += 1
            baseline_sum += p_ai
            if p_ai < 0.5:
                pos_correct += 1
        elif p_ai >= 0.5:
            neg_correct += 1
    baseline = baseline_sum / pos_n if pos_n else 0.0
    return pos_correct, neg_correct, baseline


# ---------------- inference API (imported by hooks/gate.py) ----------------

_clf = None  # loaded artifact cache ({} = absent/invalid, sticky per process)


def _load():
    global _clf
    if _clf is None:
        d = _read_json(_learned_dir() / "voice-classifier.json")
        if (isinstance(d, dict) and d.get("buckets") == BUCKETS
                and d.get("hash_algo") == HASH_ALGO
                and isinstance(d.get("weights"), dict)
                and isinstance(d.get("bias"), (int, float))):
            _clf = d
        else:
            _clf = {}
    return _clf


def score(text):
    """{"p_ai": float, "voice_delta": float} (rounded 3) or None when no valid
    artifact exists. Hash lookups + dot product; no embedder, no network."""
    d = _load()
    if not d:
        return None
    z = float(d["bias"])
    weights = d["weights"]
    for k, v in features(text).items():
        wv = weights.get(str(k))
        if wv:
            z += wv * v
    p_ai = 1.0 - _sigmoid(z)
    baseline = float(d.get("voice_baseline", 0.0))
    return {"p_ai": round(p_ai, 3), "voice_delta": round(max(0.0, p_ai - baseline), 3)}


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", nargs="*", default=None,
                    help="user clean-corpus files/dirs (.md/.txt); positives, weight 1.0")
    ap.add_argument("--learned-dir", default=None,
                    help="learned-artifact directory (default: the plugin's learned/, VOICE_LEARNED_DIR overrides)")
    ap.add_argument("--out", default=None,
                    help="classifier JSON path (default: <learned-dir>/voice-classifier.json)")
    a = ap.parse_args()
    learned = Path(a.learned_dir).expanduser() if a.learned_dir else _learned_dir()
    out = Path(a.out).expanduser() if a.out else Path(learned) / "voice-classifier.json"

    corpus_files = _collect_corpus(a)
    index_files, index_skipped = _index_texts(learned)
    after_files = _delta_texts(learned, "after")
    before_files = _delta_texts(learned, "before")
    if index_skipped:
        print(f"index entries skipped (missing or not .md/.txt): {index_skipped}")

    contrib = ([("user-corpus", f) for f in corpus_files]
               + [("edit-confirmed-index", f) for f in index_files]
               + [("edit-confirmed-after", f) for f in after_files]
               + [("pre-edit-delivery", f) for f in before_files])
    corpus_hash = _corpus_hash(contrib, {"buckets": BUCKETS, "ngram_range": list(NGRAM_RANGE),
                                         "seeder_version": SEEDER_VERSION, "hash_algo": HASH_ALGO})
    existing = _read_json(out)
    if (existing.get("corpus_hash") == corpus_hash
            and existing.get("seeder_version") == SEEDER_VERSION
            and existing.get("buckets") == BUCKETS
            and existing.get("hash_algo") == HASH_ALGO
            and existing.get("weights")):
        print(f"current (hash {corpus_hash[:12]}), nothing retrained")
        return 0

    positive_texts = ([(Path(f).read_text(encoding="utf-8", errors="replace"), WEIGHT_USER, "user")
                       for f in corpus_files]
                      + [(Path(f).read_text(encoding="utf-8", errors="replace"),
                          WEIGHT_EDIT_CONFIRMED, "edit-confirmed")
                         for f in index_files + after_files])
    if not positive_texts:
        print("no positive documents (corpus, edit-delta/after and clean-corpus-index all empty); "
              "classifier not trained")
        return 0
    negative_texts = ([(Path(f).read_text(encoding="utf-8", errors="replace"), 1.0, "pre-edit-delivery")
                       for f in before_files]
                      + [(doc, 1.0, "synthetic") for doc in _seed_docs()])

    docs = []
    for text, weight, provenance in positive_texts:
        docs.append({"x": features(text), "y": 1, "weight": weight,
                     "key": _text_key(text), "provenance": provenance})
    for text, weight, provenance in negative_texts:
        docs.append({"x": features(text), "y": 0, "weight": weight,
                     "key": _text_key(text), "provenance": provenance})
    docs.sort(key=lambda d: (d["y"], d["key"]))  # deterministic document order

    # Class-balance scaling on top of the provenance weights: each class's
    # total weight mass is equalized (standard n/(2*n_class) factor), so a
    # small clean corpus is not swamped by the 200 synthetic negatives. The
    # provenance ratios (user 1.0 vs edit-confirmed 0.5) are preserved within
    # the positive class. Deterministic: pure arithmetic over doc counts.
    n_pos = sum(1 for d in docs if d["y"] == 1)
    n_neg = len(docs) - n_pos
    pos_factor = len(docs) / (2 * n_pos) if n_pos else 0.0
    neg_factor = len(docs) / (2 * n_neg) if n_neg else 0.0
    for d in docs:
        d["weight"] *= pos_factor if d["y"] == 1 else neg_factor

    w, b, epochs_run, final_loss = train(docs)
    pos_correct, neg_correct, baseline = evaluate(w, b, docs)
    artifact = {
        "format": 1,
        "buckets": BUCKETS,
        "hash_algo": HASH_ALGO,
        "ngram_range": list(NGRAM_RANGE),
        "weights": {str(k): round(v, 6) for k, v in sorted(w.items())},
        "bias": round(b, 6),
        "voice_baseline": round(baseline, 4),
        "thresholds": dict(THRESHOLDS),
        "corpus_hash": corpus_hash,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "seeder_version": SEEDER_VERSION,
        "train_stats": {
            "positives": n_pos, "negatives": n_neg,
            "pos_correct": pos_correct, "neg_correct": neg_correct,
            "epochs": epochs_run, "train_loss": round(final_loss, 6),
            "class_balance": {"pos_factor": round(pos_factor, 4), "neg_factor": round(neg_factor, 4)},
        },
    }
    _atomic_write(out, json.dumps(artifact))

    print(f"classifier trained: {n_pos} positives (weight 1.0 user corpus / "
          f"{WEIGHT_EDIT_CONFIRMED} edit-confirmed), {n_neg} negatives "
          f"(pre-edit deliveries + synthetic seeder v{SEEDER_VERSION}, {SEEDER_DOCS} docs); "
          f"class-balance factors pos {pos_factor:.4f} / neg {neg_factor:.4f}")
    print(f"epochs: {epochs_run} (loss {final_loss:.6f}; "
          + ("early stop on loss plateau" if epochs_run < EPOCHS else f"no plateau within {EPOCHS} epochs") + ")")
    print(f"train accuracy (plain counts): positives {pos_correct}/{n_pos}, negatives {neg_correct}/{n_neg}")
    print(f"voice_baseline (mean p_ai over positives): {baseline:.4f}")
    print("sample scores (plain numbers):")
    samples = [d for d in docs if d["y"] == 1][:3] + [d for d in docs if d["y"] == 0][:3]
    for d in samples:
        z = b
        for k, v in d["x"].items():
            wv = w.get(k)
            if wv:
                z += wv * v
        p_ai = 1.0 - _sigmoid(z)
        print(f"  {d['provenance']} sha={d['key'][:12]} p_ai={p_ai:.3f} "
              f"voice_delta={max(0.0, p_ai - baseline):.3f}")
    print(f"thresholds (advisory, never blocks in 1.1.0): {json.dumps(THRESHOLDS)}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
