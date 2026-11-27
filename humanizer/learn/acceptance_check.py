#!/usr/bin/env python3
"""acceptance_check.py: offline acceptance check for finished prose (Tier 3,
issue #127; never in the delivery gate).

Two signals, plain numbers only:

A. Burrows' Delta (default backend "delta"; stdlib-only, zero setup):
   the candidate's per-1000-words frequency profile over the 60 hardcoded
   English function words (FUNCTION_WORDS in build_voice_profile.py) is
   z-scored against learned/profile.json's "function_words" section (written
   by build_voice_profile.py: per-document mean + sample stddev, divide by
   k - 1) and the score is the mean absolute z-score over the words with a
   nonzero stddev, each denominator carrying the count floor
   s_eff = sqrt(s^2 + mean * 1000 / n). Lower = closer to the user's
   profile. Delta needs >= 2 profile documents AND at least one word with
   cross-document spread to be meaningful; with fewer, the score is None
   and the row prints n/a (never 0.0: zero is the best score and must not
   stand for "no spread").

B. Local small-LM perplexity + burstiness (--backend onnx; OPTIONAL, offline
   batch): onnxruntime over a GPT-2 small ONNX model placed in
   <learned>/models/gpt2-onnx/ (model.onnx + vocab.json + merges.txt, ~250 MB).
   Per sentence: mean next-token log-prob (stdlib softmax-free scoring over
   the ONNX logits). Per document: perplexity = exp(-mean over sentence mean
   log-probs); burstiness = variance of the per-sentence mean log-probs
   divided by the absolute mean (the classic variance/mean ratio adapted to
   log-prob units, which are negative). onnxruntime, numpy (its own install
   dependency), or the model files absent -> the defined line
   "onnx backend unavailable: pip install onnxruntime + place <model> (see docs)"
   + usage + exit 2 (defined behavior, not an unfinished placeholder).

Setup-time breakdown (estimate, pending owner confirmation on M2 16GB-class):
   Delta backend: none (seconds to run).
   ONNX backend: model download ~250 MB (1-3 min broadband)
                 + pip install onnxruntime (30-60 s, numpy included)
                 + corpus scoring (seconds on M2-class CPU)
                 ~= 3-6 minutes total, under the owner's 10-minute bar.

This tool NEVER runs in the delivery gate: scoring a batch of texts is an
offline acceptance step before publication. The delivery gate stays in its
latency class; passing costs zero model tokens.

Exit codes: 0 = scored (advisory); 2 = bad arguments / missing profile /
onnx backend unavailable.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/

# FUNCTION_WORDS source of truth + WORD_RE + default profile path live in
# build_voice_profile.py (same directory, stdlib-only module).
_bvp_spec = importlib.util.spec_from_file_location(
    "voice_profile_acceptance", HERE / "build_voice_profile.py")
bvp = importlib.util.module_from_spec(_bvp_spec)
_bvp_spec.loader.exec_module(bvp)
WORD_RE = bvp.WORD_RE

ONNX_BACKEND_LINE = "onnx backend unavailable: pip install onnxruntime + place <model> (see docs)"
MODEL_DIR_PARTS = ("models", "gpt2-onnx")
USAGE = "usage: acceptance_check.py FILE... [--profile PATH] [--backend delta|onnx] [--json]"


def learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides, same
    contract as hooks/voice_tells.py learned_dir())."""
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def load_profile(path):
    """Parse profile.json and return its function_words section; a defined
    message + exit 2 when the profile is missing, unreadable or stale."""
    p = Path(path).expanduser()
    if not p.is_file():
        print(f"no voice profile at {p}; run build_voice_profile.py first (see learn/LEARN-VOICE.md)")
        raise SystemExit(2)
    try:
        prof = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"profile at {p} unreadable: {e!r}")
        raise SystemExit(2)
    fw = prof.get("function_words") if isinstance(prof, dict) else None
    if (not isinstance(fw, dict) or not isinstance(fw.get("words"), list) or not fw["words"]
            or not isinstance(fw.get("mean"), dict) or not isinstance(fw.get("stddev"), dict)):
        print(f"profile at {p} has no function_words section; rebuild it with "
              "build_voice_profile.py (see learn/LEARN-VOICE.md)")
        raise SystemExit(2)
    return fw


def burrows_delta(text, fw):
    """Signal A: mean absolute z-score of the candidate's function-word
    frequencies against the profile. Mirrors learn/voice_fit.py
    burrows_delta line for line (one math source, two entry points): sample
    stddev profile (AM-04), count floor s_eff = sqrt(s^2 + mean * 1000 / n)
    (AM-06), and None when no word has spread (AM-03). Returns
    (delta_or_None, word_count, words_counted)."""
    words = [w.lower() for w in WORD_RE.findall(text)]
    n = len(words)
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    mean, sd = fw["mean"], fw["stddev"]
    zs = []
    used = 0
    for w in fw["words"]:
        s = sd.get(w, 0.0)
        if s and s > 0:
            f = counts.get(w, 0) * 1000.0 / n if n else 0.0
            mu = mean.get(w, 0.0)
            se = math.sqrt(s * s + mu * 1000.0 / n) if n else s
            zs.append(abs((f - mu) / se))
            used += 1
    delta = sum(zs) / len(zs) if zs else None
    return delta, n, used


# ---------------- Signal B: GPT-2 small ONNX (optional) ----------------

_PRETOKEN_RE = re.compile(
    r"'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?[^\s\w]+| ?_+|\s+(?!\S)|\s+", re.UNICODE)

# documented approximation of the GPT-2 reference regex: \p{L} -> [^\W\d_],
# \p{N} -> \d; byte-level BPE and merges stay exact per pre-token.


def _bytes_to_unicode():
    """GPT-2 byte-to-unicode table (the reversible bytes->chars mapping)."""
    bs = (list(range(ord("!"), ord("~") + 1))
          + list(range(ord("\xa1"), ord("\xac") + 1))
          + list(range(ord("\xae"), ord("\xff") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def _gpt2_dir():
    return learned_dir().joinpath(*MODEL_DIR_PARTS)


def onnx_available():
    """onnxruntime importable AND the three model files present. Anything
    missing -> the caller prints ONNX_BACKEND_LINE and exits 2."""
    try:
        import onnxruntime  # optional Tier-3 dep: lazy, never at module scope
    except Exception:
        return False
    d = _gpt2_dir()
    return ((d / "model.onnx").is_file() and (d / "vocab.json").is_file()
            and (d / "merges.txt").is_file())


class _GPT2:
    """Minimal stdlib byte-level BPE + ONNX session for GPT-2 small."""

    def __init__(self):
        import onnxruntime  # lazy, optional (availability checked by the caller)
        d = _gpt2_dir()
        self.vocab = json.loads((d / "vocab.json").read_text(encoding="utf-8"))
        self.ranks = {}
        for line in (d / "merges.txt").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                self.ranks[(parts[0], parts[1])] = len(self.ranks)
        self.byte_enc = _bytes_to_unicode()
        self.sess = onnxruntime.InferenceSession(str(d / "model.onnx"),
                                                 providers=["CPUExecutionProvider"])
        self.eot = self.vocab.get("<|endoftext|>", 50256)
        self._cache = {}

    def _bpe(self, token):
        hit = self._cache.get(token)
        if hit is not None:
            return hit
        word = list(token)
        while len(word) > 1:
            pairs = {(word[i], word[i + 1]) for i in range(len(word) - 1)}
            best = min(pairs, key=lambda p: self.ranks.get(p, 1 << 30))
            if best not in self.ranks:
                break
            first, second = best
            merged, i = [], 0
            while i < len(word):
                if i < len(word) - 1 and word[i] == first and word[i + 1] == second:
                    merged.append(first + second)
                    i += 2
                else:
                    merged.append(word[i])
                    i += 1
            word = merged
        out = " ".join(word)
        if len(self._cache) < 4096:
            self._cache[token] = out
        return out

    def encode(self, text, cap=511):
        """ids = [endoftext] + BPE ids of the text, capped at cap+1 tokens."""
        ids = [self.eot]
        for pre in _PRETOKEN_RE.findall(text):
            mapped = "".join(self.byte_enc.get(b, "") for b in pre.encode("utf-8"))
            for piece in self._bpe(mapped).split(" "):
                tid = self.vocab.get(piece)
                if tid is not None:
                    ids.append(tid)
        return ids[:cap + 1]

    def next_token_log_probs(self, ids):
        """log p(ids[i+1] | ids[0..i]) for every position (stdlib log-sum-exp
        over the ONNX logits; only the actual next token's log-prob is kept)."""
        import numpy as np  # onnxruntime's own install dependency; optional path only
        feed = {}
        for inp in self.sess.get_inputs():
            if inp.name == "input_ids":
                feed["input_ids"] = np.array([ids], dtype=np.int64)
            elif inp.name == "attention_mask":
                feed["attention_mask"] = np.ones((1, len(ids)), dtype=np.int64)
        outputs = self.sess.run(None, feed)
        logits = outputs[0]  # [1, T, V]
        out = []
        for pos in range(len(ids) - 1):
            row = logits[0][pos]
            m = float(row.max())
            lse = m + math.log(float(np.exp(row - m).sum()))
            out.append(float(row[ids[pos + 1]]) - lse)
        return out


def onnx_scores(model, text):
    """Per-document (perplexity, burstiness, sentence_count) for Signal B.
    Empty text -> (0.0, 0.0, 0) (defined)."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sent_means = []
    for s in sentences:
        ids = model.encode(s)
        if len(ids) < 2:
            ids = ids + [model.eot]  # at least one predicted position
        lps = model.next_token_log_probs(ids)
        sent_means.append(sum(lps) / len(lps))
    if not sent_means:
        return 0.0, 0.0, 0
    mean_lp = sum(sent_means) / len(sent_means)
    ppl = math.exp(min(-mean_lp, 700.0))
    variance = sum((m - mean_lp) ** 2 for m in sent_means) / len(sent_means)
    burstiness = variance / abs(mean_lp) if mean_lp else 0.0
    return ppl, burstiness, len(sent_means)


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description="Offline acceptance check: Burrows' Delta "
                                             "(default) or optional local GPT-2 perplexity/burstiness. "
                                             "Never in the delivery gate.")
    ap.add_argument("files", nargs="+", help="candidate text files (.md/.txt) to score")
    ap.add_argument("--profile", default=None,
                    help="profile.json path (default: the plugin's learned/profile.json)")
    ap.add_argument("--backend", choices=("delta", "onnx"), default="delta",
                    help="delta = stdlib Burrows' Delta (zero setup); onnx = local GPT-2 small "
                         "perplexity/burstiness (optional setup, see docs)")
    ap.add_argument("--json", action="store_true", help="emit a JSON array instead of the plain table")
    a = ap.parse_args()
    if a.backend == "onnx" and not onnx_available():
        print(ONNX_BACKEND_LINE)
        d = _gpt2_dir()
        print(f"expected: onnxruntime installed and GPT-2 small ONNX files in {d} "
              "(model.onnx, vocab.json, merges.txt); setup estimate 3-6 min, see learn/LEARN-VOICE.md")
        print(USAGE)
        return 2
    for f in a.files:
        if not Path(f).expanduser().is_file():
            print(f"missing path: {f}", file=sys.stderr)
            return 2
    rows = []
    if a.backend == "delta":
        profile_path = Path(a.profile).expanduser() if a.profile else bvp.DEFAULT_OUT
        fw = load_profile(profile_path)
        for f in a.files:
            text = Path(f).expanduser().read_text(encoding="utf-8", errors="replace")
            delta, n, used = burrows_delta(text, fw)
            rows.append({"file": f, "backend": "delta",
                         "burrows_delta": round(delta, 3) if delta is not None else None,
                         "words_counted": used, "words": n})
    else:
        model = _GPT2()
        for f in a.files:
            text = Path(f).expanduser().read_text(encoding="utf-8", errors="replace")
            ppl, burst, ns = onnx_scores(model, text)
            rows.append({"file": f, "backend": "onnx", "perplexity": round(ppl, 3),
                         "burstiness": round(burst, 3), "sentences": ns})
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            if r["backend"] == "delta":
                d = "n/a" if r["burrows_delta"] is None else r["burrows_delta"]
                print(f"{r['file']}  burrows_delta={d}  words={r['words']}")
            else:
                print(f"{r['file']}  perplexity={r['perplexity']}  burstiness={r['burstiness']}  "
                      f"sentences={r['sentences']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
