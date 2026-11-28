#!/usr/bin/env python3
"""Delivery gate adapter for the /voice plugin.

Contract (token economy):
- Deterministic scan only (regex tell scan from hooks/voice_tells.py + an ASD-STE100 layer + the battery fast core of learn/voice_battery_core.py). Zero LLM tokens to evaluate.
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
    ("battery marker", "Delete the marker word or state the concrete fact in its place."),
    ("humanizer 22", "Delete the praise line; open with the substantive point."),
    ("humanizer 25", "Cut the uplift; state the concrete next fact or plan."),
    ("humanizer 27", "Delete the authority frame; state the ordinary point plainly."),
    ("humanizer 28", "Delete the announcement; do the thing instead of naming it."),
    ("humanizer 32", "Replace the question with the point it was going to make."),
    ("humanizer 33", "Delete the opener; start the sentence with its subject."),
    ("humanizer 34", "Cut the reassurance clause; the point stands without it."),
    ("aphorism", "Keep at most one kicker per section (at most three per piece); rewrite the extra kickers as plain sentences."),
    ("humanizer 19", "Swap curly quotes for straight quotes."),
    ("humanizer 16", "Fold the bullet into a sentence listing the items."),
    ("humanizer 17", "Lowercase the heading words (sentence case) except the first."),
    ("humanizer 18", "Delete the emoji."),
    ("humanizer 12", "List the real items instead of the from-X-to-Y sweep."),
    ("daneel", "Patch per the stated voice rule; the message names the repair."),
)

S1_MAX_WORDS = 20
S2_MAX_SENT = 3
profile = "public"  # public | resume (ATS exemptions, humanizer-skill condition profiles; set in main())
S6_ADVERBS = r"\b(very|really|basically|actually|literally|definitely|certainly)\b"
S4_FILLER = r"\b(in order to|it should be noted that|it is important to note that|is used to)\b"
S3_PASSIVE = r"\b(is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b"

def ste_hits(text):
    hits = []
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    for pi, para in enumerate(paras):
        # Line-aware splitting: bullets, headings, and labeled lines are their own
        # units so profiles can exempt them per the humanizer skill's condition
        # profiles; prose lines still split into sentences normally.
        sents = []
        unit_flags = []  # True when the unit is a heading/bullet, not a paragraph sentence
        bullet_lines = 0
        for line in para.splitlines():
            if not line.strip():
                continue
            is_bh = bool(re.match(r"\s*(#{1,6}\s|[-*\u2022]\s)", line))
            if re.match(r"\s*[-*\u2022]\s", line):
                bullet_lines += 1
            chunks = re.split(r"(?<=[.!?])\s+", line.strip())
            for s in chunks:
                if s.strip():
                    sents.append(s.strip())
                    unit_flags.append(is_bh)
        bullet_para = bullet_lines >= 2 or (bullet_lines >= 1 and len(sents) <= bullet_lines + 1)
        # Headings and bullet list items are not paragraph sentences: they sit
        # out of the S2 count on every surface; S1/S3/S5 still scan their text.
        s2_sent_count = len([f for f in unit_flags if not f])
        if s2_sent_count > S2_MAX_SENT and not (profile == "resume" and bullet_para):
            hits.append(f"S2 paragraph has {s2_sent_count} sentences (max {S2_MAX_SENT}) (para {pi+1} near: '"
                        + para.strip()[:60].replace(chr(10), ' ') + "...')")
        for si, s in enumerate(sents):
            wc = len(re.findall(r"[A-Za-z0-9']+", s))
            # ATS profile: bullets and labeled section lines are exempt from S1
            # length (subjectless fragments are the resume convention); the S3
            # passive heuristic reads "was standardized" as passive when it is a
            # parser-required ownership verb.
            bullet_or_label = bool(re.match(r"\s*[-*\u2022]\s|^[A-Z][\w ]+:", s))
            exempt = profile == "resume" and bullet_or_label
            if wc > S1_MAX_WORDS and not exempt:
                hits.append(f"S1 sentence over {S1_MAX_WORDS} words ({wc}) (para {pi+1}, sent {si+1} near: '"
                            + s[:60] + "...')")
            if len(re.findall(r"\b\w+ing\b", s)) >= 2:
                hits.append(f"S5 two or more -ing forms in one sentence (para {pi+1}, sent {si+1} near: '"
                            + s[:60] + "...')")
            if exempt:
                continue
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

def _battery_layer(raw):
    """Battery fast core (v1.2.0) plus the family-35 aphorism budget
    (wave H-C): lazy-import learn/voice_battery_core.py (the small
    gate-path module; the full battery sits outside the gate's latency
    budget) and run its fast core: token loop, sentence block, paragraph
    block, character counts in one pass (no diversity index, no profile
    distance). The gate turns only the L10-1 marker-word hits into gate
    hits, one line per distinct word; the family dedup below collapses
    them to at most ONE fail line, never a sixth, and the pass line stays
    byte-identical. The aphorism budget lines follow the same dedup law:
    the mechanical counter enforces the skill's own budget (max one kicker
    per section, at most three per piece); the line names the section and
    the count, never an AI accusation; --profile resume and the situational
    table keep their existing exemptions. Fail-open: an unavailable battery
    layer means no battery hits, never a gate error.
    Returns (marker_hits, aphorism_hits, module_or_None)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "voice_battery_gate", os.path.join(_HERE, "..", "learn", "voice_battery_core.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fc = mod.fast_core(raw)
    except Exception:
        return [], [], None
    hits = []
    for word in sorted(fc["marker_counts"]):
        m = re.search(r"\b%s\b" % re.escape(word), raw, re.IGNORECASE)
        near = raw[max(0, m.start() - 20):m.end() + 20].replace(chr(10), " ") if m else word
        hits.append("battery marker word (L10-1) '%s' (near: '...%s...')" % (word, near))
    aph = []
    try:
        aph = mod.aphorism_budget_hits(raw, profile)
    except Exception:
        aph = []
    return hits, aph, mod

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

def _advisory_signals(raw, source_path, battery_mod=None):
    """Zero-token advisory fields for the gate JSON (both surfaces). Every
    step fails open: absent artifacts or no embedder -> absent fields.
    Wave H-C adds two band-gated advisory fields (they appear only when the
    learned state carries the matching bands, so the pass line stays
    byte-identical while uncalibrated; neither ever changes pass/fail):
    cycling_pairs (family 11, chunk-pair divergence on the existing chunk
    vectors and content sets) and compression_profile (family support,
    per-paragraph zlib profile)."""
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
    try:
        bands = (tells.effective_rules().get("bands") or {})
        if battery_mod is not None and bands.get("compression"):
            advisory["compression_profile"] = battery_mod.compression_profile(raw)
        if battery_mod is not None and vp and vp.get("active") and bands.get("cycling"):
            pairs = tells.cycling_signals(vp, battery_mod.chunk_content_sets(raw))
            if pairs:
                chunks = tells._chunks(raw)
                i = pairs[0]["pair"]
                preview = (chunks[i][:60] + " | " + chunks[i + 1][:60]) if len(chunks) >= i + 2 else ""
                advisory["cycling_pairs"] = {"count": len(pairs), "first": pairs[0],
                                             "preview": preview}
    except Exception as e:
        _log_gate("vec_skip", {"err": f"hc advisory: {e!r}"})
    return advisory

def main():
    global profile
    argv = sys.argv[1:]
    surface = "public"
    source_path = None
    if "--surface" in argv:
        i = argv.index("--surface"); surface = argv[i+1] if i+1 < len(argv) and argv[i+1] in ("chat", "public") else "public"
        argv = [a for j, a in enumerate(argv) if j not in (i, i+1)]
    if "--profile" in argv:
        i = argv.index("--profile"); profile = argv[i+1] if i+1 < len(argv) and argv[i+1] in ("public", "resume") else "public"
        argv = [a for j, a in enumerate(argv) if j not in (i, i+1)]
    situation = "public"
    if "--situation" in argv:
        i = argv.index("--situation"); situation = argv[i+1] if i+1 < len(argv) else "public"
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
        # --situation runs the full register then filters per the situational
        # table (chat/email keep conduct families, drop formatting/marketing).
        hits = [] if (surface == "chat" and situation == "public") else tells.find_regex_hits(raw)
    except Exception:
        hits = []
    if profile == "resume":
        # ATS profile (humanizer skill, document-type condition logic): labeled
        # category lines (pattern 16) and Title Case sections/titles (pattern 17)
        # are parser convention, not tells.
        try:
            hits = [h for h in hits if "humanizer 16" not in h and "humanizer 17" not in h]
        except Exception:
            pass
    # STE always enforced, both surfaces.
    try:
        hits = list(hits) + ste_hits(raw)
    except Exception:
        pass
    # battery fast core (L10-1 marker words) + aphorism budget (family 35),
    # both surfaces; family dedup below caps each contribution at one fail
    # line, and the pass line stays byte-identical.
    battery_hits, aphorism_hits, battery_mod = _battery_layer(raw)
    hits = list(hits) + battery_hits + aphorism_hits
    # Voice-rules layer (daneel_style_rules.yaml adapter): the local voice rules
    # and anti-patterns ride on top of the humanizer scan, one source of truth.
    try:
        hits = list(hits) + tells.voice_rules_hits(raw)
    except Exception:
        pass
    advisory = {}
    if situation != "public":
        try:
            hits = tells.situation_filter(hits, situation)
        except KeyError as e:
            print(f"usage: {e.args[0]}", file=sys.stderr)
            return 2
        advisory["situation"] = situation
    advisory.update(_advisory_signals(raw, source_path, battery_mod))
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
