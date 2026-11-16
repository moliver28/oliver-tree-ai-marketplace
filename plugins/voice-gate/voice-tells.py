#!/usr/bin/env python3
"""voice-tells.py: shared detection core for Michael's zero-AI-tells bar.

Two layers, both importable by voice-gate.py (hook) and voice-check.py:
1. REGEX layer: inflection- and variant-aware patterns (case-insensitive,
   word-boundary anchored, hyphen/spacing tolerant). Pure CPU, sub-millisecond.
2. VECTOR layer: cosine similarity against embedded tell exemplars via local
   Ollama (nomic-embed-text, warm ~100ms). Exemplar vectors are precomputed by
   voice-vector-build.py into ~/.hermes/state/voice-tells-vectors.json and are
   version-tagged with the pattern set. If the service is down, the vector
   layer is skipped (logged), the regex layer still stands.

Public API:
    find_regex_hits(text) -> list[str]
    find_vector_hits(text, chunks=None) -> list[str]
"""
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
VEC_PATH = HOME / "state" / "voice-tells-vectors.json"
LOG = HOME / "logs" / "voice-gate.log"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
COSINE_THRESHOLD = 0.66          # tuned: paraphrases hit 0.75-0.83, clean prose <=0.62
EMBED_TIMEOUT_S = 2.0
MAX_EMBED_CHARS = 4000           # truncate embedded prose; long docs scan per chunk below

# ---------------- REGEX LAYER ----------------
# (pattern, label). All case-insensitive except nothing here requires case.
PATTERNS = [
    (r"\u2014", "em dash (U+2014): use comma, period, colon or parentheses"),
    (r"\s--\s", "spaced double hyphen used as a dash"),
    # negative parallelism: "It's not just X (that)... it's Y", "not merely A but B"
    (r"\b(?:it'?s|it is|this is|they'?re|these are|that'?s)\s+not\s+(?:just|merely|only|simply)\b",
     "negative parallelism 'not just/merely/only' construction (humanizer pattern 9)"),
    (r"\bnot\s+(?:just|merely|only|simply)\s+(?:about|the|a|an)\b",
     "negative parallelism 'not just about/the/a' construction"),
    (r"\bless\s+about\s+.{1,60}\bmore\s+about\b",
     "the 'less about X, more about Y' contrast cliché"),
    # copula/verb avoidance family (high precision forms only)
    (r"\bstands?\s+as\s+(?:a|an|the)\b[^.!?]{0,40}\?\!",
     "copula avoidance 'stands as' (use 'is')"),
    (r"(?i)\bnot\s+(?:a|an)\s+\b[\w-]+\s*,?\s+(?:but|rather)\s+(?:a|an)\b",
     "'not a X, but a Y' contrast construction"),
    # persuasive authority / signposts
    (r"\bthe\s+real\s+question\s+(?:is|here)\b", "persuasive authority 'the real question is'"),
    (r"\bat\s+its\s+core\b", "persuasive authority 'at its core'"),
    (r"\bwhat\s+really\s+matters\b", "persuasive authority 'what really matters'"),
    (r"\bthe\s+heart\s+of\s+the\s+(?:matter|issue)\b", "persuasive authority 'the heart of the matter'"),
    (r"\bwhen\s+it\s+comes\s+to\b", "blog cliché 'when it comes to'"),
    (r"\bin\s+a\s+world\s+where\b", "blog cliché 'in a world where'"),
    (r"\bmoving\s+forward\b", "blog cliché 'moving forward'"),
    (r"\bat\s+the\s+end\s+of\s+the\s+day\b", "blog cliché 'at the end of the day'"),
    (r"\bmake\s+no\s+mistake\b", "blog cliché 'make no mistake'"),
    (r"\bit\s+(?:turns?\s+out|turned\s+out)\s+that\b", "blog cliché 'it turns out that'"),
    (r"\blet'?s\s+dive\s+in(?:to)?\b", "signpost 'let's dive in(to)'"),
    (r"\bdive\s+deep(?:er)?\s+into\b", "signpost 'dive deep(er) into'"),
    (r"\bdeep[-\s]?dive\s+(?:into|on)\b", "signpost 'deep dive into'"),
    (r"\bcircle\s+back\b", "filler 'circle back'"),
    (r"\btake\s+a?\s?step\s+back\b", "filler 'take a step back'"),
    (r"\bin\s+order\s+to\b", "filler 'in order to' (use 'to')"),
    (r"\bdue\s+to\s+the\s+fact\s+that\b", "filler 'due to the fact that' (use 'because')"),
    (r"\bit\s+is\s+(?:important|worth)\s+(?:to\s+note|noting)\b",
     "filler 'it is important/worth noting'"),
    (r"\bthe\s+ability\s+to\b", "filler 'the ability to X' (say 'can X')"),
    # reassurance kickers
    (r"\band\s+that'?s\s+(?:okay|ok|fine)\b", "reassurance kicker 'and that's okay/fine'"),
    (r"\bthere'?s\s+no\s+shame\s+in\b", "reassurance kicker 'no shame in'"),
    (r"\byou'?re\s+not\s+alone\b", "reassurance kicker 'you're not alone'"),
    (r"\bit'?s\s+completely\s+normal\b", "reassurance kicker 'it's completely normal'"),
    # banned vocabulary, inflection and variant tolerant
    (r"\bspearhead(?:ed|ing|s)?\b", "banned word 'spearhead(ed/ing/s)' (own the verb: led, built, ran)"),
    (r"\bresults?[-\s]?driven\b", "banned phrase 'results-driven'"),
    (r"\bpassionate\s+about\b", "banned phrase 'passionate about'"),
    (r"\bproven\s+track\s+record\b", "banned phrase 'proven track record'"),
    (r"\bgame[-\s]?changers?\b", "banned phrase 'game-changer'"),
    (r"\bbest[-\s]?in[-\s]?class\b", "banned phrase 'best-in-class'"),
    (r"\bseamless(?:ly)?\b", "banned word 'seamless(ly)'"),
    (r"\bdelv(?:e|es|ed|ing)\s+(?:deep(?:er|ly)?\s+)?(?:in)?to?\b", "banned word 'delve (into)' (say 'examine')"),
    (r"\btapestr(?:y|ies)\b", "banned word 'tapestry'"),
    (r"\bsupercharg(?:e|es|ed|ing)\b", "banned word 'supercharge'"),
    (r"\bunlocks?(?:ed|ing)?\b", "banned word 'unlock' (state the concrete outcome)"),
    (r"\bleverag(?:e|es|ed|ing)\b", "banned word 'leverage' (say 'use')"),
    (r"\bsynerg(?:y|ies|istic)\b", "banned word 'synergy'"),
    (r"\bin\s+today'?s\s+(?:rapidly\s+)?(?:evolving|changing|shifting)\s+(?:landscape|world|environment|market)\b",
     "banned opener 'in today's (rapidly evolving) landscape'"),
    (r"\bnavigat(?:e|es|ed|ing)\s+(?:the\s+)?(?:challenges|complexities|complex\s+landscape)\b",
     "banned use 'navigate challenges' (plain verb)"),
    (r"\bthe\s+journey\s+(?:toward|to)\s+\w", "banned word 'journey' in 'the journey toward'"),
    (r"\bdynamic\s+(?:team|professional|leader|individual)\b", "resume-slop 'dynamic professional/team/leader'"),
    (r"\bcutting[-\s]?edge\b", "resume-slop 'cutting-edge'"),
    (r"\bworld[-\s]?class\b", "resume-slop 'world-class'"),
    (r"\brevolutionar(?:y|ize)\b", "resume-slop 'revolutionary/revolutionize'"),
    (r"\bharness(?:ed|ing)?\s+the\s+power\b", "slop 'harness the power of'"),
    (r"\bin\s+conclusion,?\s+", "signpost 'In conclusion,'"),
    (r"\bwould\s+you\s+like\s+me\s+to\b", "chatbot artifact 'Would you like me to...'"),
    (r"\bi\s+hope\s+this\s+helps?\b", "chatbot artifact 'I hope this helps'"),
    (r"\bfeel\s+free\s+to\s+(?:reach\s+out|let\s+me\s+know)\b", "chatbot artifact 'feel free to...'"),
    # Zero-AI-Tells Register adds (owner order 2026-11-11/12): patterns 36, 37
    (r"\b(?:it\s+deserves|that\s+deserves)\s+a\s+(?:real|proper)\s+answer\b", "teaser handoff 'deserves a real answer' (register 36: carry the transition in the next section's first line of evidence)"),
    (r"\b(?:shows?|tells?|will\s+show)\s+(?:you\s+)?what\s+that\s+costs?,?\s+with\s+(?:dates|numbers)\s+attached\b", "teaser handoff 'X shows what that costs, with dates attached' (register 36)"),
    (r"\b(?:and\s+)?(?:someone|somebody)\s+is\s+filling\s+it\b", "teaser handoff 'someone is filling it' (register 36)"),
    (r"\b(?:to\s+be\s+precise|want\s+to\s+be\s+precise)\s+(?:here\s+)?[,:;.]\b", "performed candor 'to be precise (here)' (register 37: state the caveat as a fact)"),
    (r"\b(?:a\s+|the\s+)?cost\s+worth\s+stating\b", "performed candor 'a cost worth stating' (register 37)"),
    (r"\blet\s+me\s+be\s+(?:honest|clear|precise)\b", "performed candor 'let me be honest/clear/precise' (register 37)"),
]

_FLAGS = re.IGNORECASE
_COMPILED = [(re.compile(p, _FLAGS), label) for p, label in PATTERNS]

# ---------------- VECTOR LAYER ----------------
# One or more exemplar strings per tell family; paraphrases of these should hit.
EXEMPLARS = [
    "It's not just about the features; it's about the peace of mind they bring.",
    "This isn't merely a tool upgrade. It's a paradigm shift that promises to revolutionize how teams operate.",
    "The product stands as a testament to the company's enduring commitment to excellence.",
    "Nestled in the heart of the vibrant tech ecosystem, the platform boasts a rich array of cutting-edge features.",
    "This marks a pivotal moment in the ever-evolving landscape of AI-assisted writing.",
    "In today's rapidly evolving digital world, businesses must leverage seamless solutions to unlock their full potential.",
    "At the end of the day, what really matters is fostering innovation and driving meaningful change.",
    "Let's dive in and unpack the intricate interplay between automation and human judgment.",
    "The real question is whether organizations can navigate the complexities of this transformative journey.",
    "From startups to enterprises, this game-changer empowers everyone to harness the power of data.",
    "The arithmetic is accurate; the obituary is the misreading. The numbers don't lie, but the narrative does.",
    "Experts and industry observers alike underscore the critical importance of this trend.",
    "Despite these challenges, with its strategic vision, the company continues to thrive, setting the stage for a bright future.",
    "A posting increasingly displays a decision made elsewhere, and the funeral everyone keeps describing is a reorganization.",
    "And that's okay. Every team starts somewhere, and there's nothing wrong with growing from there.",
    "They deliver robust, best-in-class, world-class solutions that supercharge productivity and enhance collaboration.",
    "Someone is filling it. X shows what that costs, with dates attached. It deserves a real answer.",
    "To be precise here, that is a cost worth stating, and let me be honest about the arithmetic.",
]

_cache = None  # loaded vectors


def _load_vectors():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(VEC_PATH.read_text())
        except Exception:
            _cache = {"model": MODEL, "built": None, "vectors": []}
    return _cache


def _log_vec(event, detail):
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "event": event, **detail}) + "\n")
    except Exception:
        pass


def _embed(text, timeout=EMBED_TIMEOUT_S):
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({"model": MODEL, "prompt": text[:MAX_EMBED_CHARS]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["embedding"]


def _cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)); db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def _chunks(text, size=1200):
    """Split long prose on paragraph boundaries so long docs don't blur the vector."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    paras = [p for p in text.split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = ""
        cur += ("\n\n" if cur else "") + p
    if cur:
        out.append(cur)
    return out[:12]  # bounded: 12 chunk embeds worst case


def find_regex_hits(text):
    hits = []
    for rx, label in _COMPILED:
        m = rx.search(text)
        if m:
            near = text[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
            hits.append(f"{label} (near: {near!r})")
    return hits


def find_vector_hits(text):
    """Return hits from the embedding layer; empty on any infrastructure miss."""
    cache = _load_vectors()
    if not cache.get("vectors"):
        return []
    hits = []
    for chunk in _chunks(text):
        try:
            v = _embed(chunk)
        except Exception as e:
            _log_vec("vec_skip", {"err": repr(e)})
            return hits  # fail open: service down never blocks on its own
        for ex in cache["vectors"]:
            sim = _cosine(v, ex["vec"])
            if sim >= COSINE_THRESHOLD:
                hits.append(f"vector tell '{ex['label']}' sim={sim:.2f} (near exemplar: "
                            f"{ex['text'][:70]}...)")
    # dedupe labels
    seen, uniq = set(), []
    for h in hits:
        label = h.split(" sim=")[0]
        if label not in seen:
            seen.add(label)
            uniq.append(h)
    return uniq


def scan(text, use_vector=True):
    hits = find_regex_hits(text)
    if use_vector and len(text) > 40:
        hits.extend(find_vector_hits(text))
    return hits
