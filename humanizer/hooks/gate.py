#!/usr/bin/env python3
"""Delivery gate adapter for the /voice plugin.

Contract (token economy):
- Deterministic scan only (regex tell scan from hooks/voice_tells.py + an ASD-STE100 layer). Zero LLM tokens to evaluate.
- Surfaces: --surface public (default: tell scan + STE) or --surface chat (STE always enforced; the onboarding STE row decides whether public mode also carries STE).
- PASS: emit {"status": "pass", "tokens_to_model": 0} and stop. The model is never re-engaged.
- FAIL: emit the violated pattern labels (one line each, max 5) with nearby context, plus one instruction
  block: patch in place, do not regenerate, do not re-emit the full text. One fix line per distinct pattern.
- ERROR (scan unavailable): fail-open, {"status": "error", "deliver": true}.

Advisory signals (v1.1.0, issue #127 Tiers 1+2; zero model tokens; both
surfaces; every step fails open, so absent artifacts simply mean absent fields):
- "voice_fit": mean cosine of the rewrite chunks to the user's clean-corpus
  centroid, computed inside the vector layer's single embedding pass when the
  per-user artifacts are present. Never changes pass/fail.
- "source_fidelity" (--source FILE): cosine of the source text embedding to
  the rewrite document embedding (source-context-only rule, mechanical). The
  source embedding is disk-cached, hash-keyed and bounded
  (learned/embed-cache.json, max 64 entries): a repeated /voice run on the
  same draft does not re-embed the source (ruling 1, issue #127).
- "p_ai" / "voice_delta": trained char n-gram authorship classifier
  (learn/train_voice_classifier.py) when learned/voice-classifier.json exists.
  Advisory only in 1.1.0: the classifier NEVER blocks delivery by itself;
  threshold action comes after the owner reviews score distributions.

ASD-STE100 layer (simplified-technical-English checks, keep rules minimal and mechanical):
S1 sentence length: no sentence over 20 words.
S2 paragraph length: no paragraph over 3 sentences.
S3 passive voice: forms of be followed by a past participle (heuristic on -ed/-en) get flagged; rewrite active.
S4 inflated verb chains: "is used to/it should be noted/in order to" style filler flagged with a plain-verb fix.
S5 -ing chains: two or more present participles in one sentence; convert to main verbs.
S6 approved-word discipline: flag the classic banned adverbs/vague intensifiers (e.g. "very", "really", "basically") and undefined pronoun-style references ("this/these" with no noun within 3 words).

Usage: python3 gate.py [--surface chat|public] [--source FILE] < <text-file>; or point a pre-delivery hook at it.
Exit codes: 0 pass/error, 4 fail (instruction block on stdout), 2 usage.
"""
import json, os, re, importlib.util, sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "voice_tells", os.path.join(_HERE, "voice_tells.py"))
tells = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(tells)  # loaded once per process; main() fails open if this failed
    _TELLS_OK = True
except Exception:
    _TELLS_OK = False

MAX_PATTERNS = 5

FIX_HINT = (
    ("em dash", "Replace with comma, period, colon, or parentheses in place."),
    ("spaced double hyphen", "Same rewrite as an em dash."),
    ("negative parallelism", 'Delete the "not just X" frame; state the second half only.'),
    ("less about", "State the 'more about' half only."),
    ("copula", 'serves as/stands as/functions as -> "is" in place.'),
    ("testament", "Cut the inflation; state the concrete fact."),
    ("pivotal|landscape", "Cut the significance inflation; state the concrete fact."),
    ("not just", "See negative parallelism."),
)

S1_MAX_WORDS = 20
S2_MAX_SENT = 3
S6_ADVERBS = r"\b(very|really|basically|actually|literally|definitely|certainly)\b"
S4_FILLER = r"\b(in order to|it should be noted that|it is important to note that|is used to)\b"
S3_PASSIVE = r"\b(is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b"

def ste_hits(text):
    hits = []
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    for pi, para in enumerate(paras):
        sents = re.split(r"(?<=[.!?])\s+", para.strip())
        sents = [s for s in sents if s.strip()]
        if len(sents) > S2_MAX_SENT:
            hits.append(f"S2 paragraph has {len(sents)} sentences (max {S2_MAX_SENT}) (para {pi+1} near: '"
                        + para.strip()[:60].replace(chr(10), ' ') + "...')")
        for si, s in enumerate(sents):
            wc = len(re.findall(r"[A-Za-z0-9']+", s))
            if wc > S1_MAX_WORDS:
                hits.append(f"S1 sentence over {S1_MAX_WORDS} words ({wc}) (para {pi+1}, sent {si+1} near: '"
                            + s[:60] + "...')")
            if len(re.findall(r"\b\w+ing\b", s)) >= 2:
                hits.append(f"S5 two or more -ing forms in one sentence (para {pi+1}, sent {si+1} near: '"
                            + s[:60] + "...')")
            for rx, tag, fixnote in (
                (S3_PASSIVE, "S3 passive voice", "S3 passive voice detected: rewrite the clause active at that spot."),
                (S4_FILLER, "S4 filler verb chain", "S4 filler: use the plain verb directly."),
                (S6_ADVERBS, "S6 vague intensifier", "S6 delete the vague intensifier or state the degree concretely."),
            ):
                for m in re.finditer(rx, s, re.IGNORECASE):
                    hits.append(f"{tag} (para {pi+1}, sent {si+1} near: '..." + s[max(0,m.start()-15):m.end()+15] + "...') [fix: " + fixnote + "]")
                    break
            if re.search(r"\b(this|these)\s+(?![a-z])", s):
                hits.append(f"S6 dangling 'this/these' with no noun after it (para {pi+1}, sent {si+1} near: '"
                            + s[:50] + "...')")
    return hits

def fix_line(hit):
    line = f"- {hit} -> "
    low = hit.lower()
    for needle, hint in FIX_HINT:
        if needle in low:
            return line + hint
    for prefix, hint in (
        ("s1", "Split the sentence at the natural clause; keep both halves under 20 words."),
        ("s2", "Split the paragraph into one sentence per idea."),
        ("s3", "Rewrite the clause active: name the actor as subject."),
        ("s4", "Use the plain verb directly; delete the filler frame."),
        ("s5", "Convert -ing constructions to main verbs in separate clauses."),
        ("s6", "Delete the intensifier, or attach a noun to this/these."),
    ):
        if low.startswith(prefix):
            return line + hint
    return line + "Rewrite that phrase plainly, in the profile's voice, same length intent."

def _log_gate(event, detail):
    """Gate-side JSONL event via the shared sink (no-op when the scanner
    module itself failed to load)."""
    if _TELLS_OK:
        try:
            tells._log_vec(event, detail)
        except Exception:
            pass

def _classifier_score(text):
    """Advisory authorship score from learn/train_voice_classifier.py when its
    artifact exists; None otherwise (fail-open, logged like the vector layer).
    The module is loaded per call (cheap, stdlib defs only) so an artifact that
    appears mid-process is picked up; load errors are sticky per call, never
    fatal. Advisory only: the classifier never changes pass/fail in 1.1.0."""
    if not _TELLS_OK:
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "voice_classifier_gate", os.path.join(_HERE, "..", "learn", "train_voice_classifier.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "score"):
            return None
        return mod.score(text)
    except Exception as e:
        _log_gate("classifier_skip", {"err": repr(e)})
        return None

def _advisory_signals(raw, source_path):
    """Zero-token advisory fields for the gate JSON (both surfaces). Every
    step fails open: absent artifacts or no embedder -> absent fields."""
    if not _TELLS_OK:
        return {}
    advisory = {}
    try:
        vp = tells.vector_pass(raw)
    except Exception as e:
        vp = None
        _log_gate("vec_skip", {"err": repr(e)})
    if vp and vp.get("active"):
        fit = vp.get("voice_fit")
        if fit is not None:
            advisory["voice_fit"] = round(fit, 3)
        if source_path and vp.get("doc_vec") and vp.get("backend"):
            try:
                source_text = Path(source_path).expanduser().read_text(encoding="utf-8", errors="replace")
                svec = tells.embed_source_cached(source_text, vp["backend"])
            except Exception as e:
                svec = None
                _log_gate("vec_skip", {"err": f"source read: {e!r}"})
            if svec:
                advisory["source_fidelity"] = round(tells._cosine(svec, vp["doc_vec"]), 3)
    cs = _classifier_score(raw)
    if cs:
        advisory["p_ai"] = cs["p_ai"]
        advisory["voice_delta"] = cs["voice_delta"]
    return advisory

def main():
    argv = sys.argv[1:]
    surface = "public"
    source_path = None
    if "--surface" in argv:
        i = argv.index("--surface"); surface = argv[i+1] if i+1 < len(argv) and argv[i+1] in ("chat", "public") else "public"
        argv = [a for j, a in enumerate(argv) if j not in (i, i+1)]
    if "--source" in argv:
        i = argv.index("--source")
        source_path = argv[i+1] if i+1 < len(argv) else None
        argv = [a for j, a in enumerate(argv) if j not in (i, i+1)]
        if not source_path or not Path(source_path).expanduser().is_file():
            print("usage: --source FILE must point to a readable source text file", file=sys.stderr)
            return 2
    raw = sys.stdin.read()
    if not raw.strip():
        print("usage: pipe text to stdin", file=sys.stderr); return 2
    try:
        hits = [] if surface == "chat" else tells.find_regex_hits(raw)
    except Exception:
        hits = []
    # STE always enforced, both surfaces.
    try:
        hits = list(hits) + ste_hits(raw)
    except Exception:
        pass
    advisory = _advisory_signals(raw, source_path)
    if not hits:
        print(json.dumps({"status": "pass", "surface": surface, "tokens_to_model": 0, **advisory})); return 0
    family = {}
    for h in hits:
        key = " ".join(h.split("(")[0].split()[:2])
        family.setdefault(key, h)
    reported = list(family.values())[:MAX_PATTERNS]
    lines = [fix_line(h) for h in reported]
    instruction = (
        "REPAIR, DO NOT REWRITE. Each line below names one rule break with its nearby context. "
        "Patch that phrase in place; keep voice, length, and all other text identical. "
        "Do not paste the full text back unless the surface forces one final copy.\n"
        + "\n".join(lines))
    print(json.dumps({
        "status": "fail", "surface": surface, "hit_count": len(hits), "reported": len(reported),
        "instruction_char_budget": 900, "instruction": instruction, **advisory}))
    return 4

if __name__ == "__main__":
    sys.exit(main())
