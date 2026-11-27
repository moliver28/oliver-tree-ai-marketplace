#!/usr/bin/env python3
"""voice-tells.py: shared detection core for the zero-AI-tells bar.

Two layers, both importable by gate.py (hook) and voice_check.py:
1. REGEX layer: inflection- and variant-aware patterns (case-insensitive,
   word-boundary anchored, hyphen/spacing tolerant). Pure CPU, sub-millisecond.
2. VECTOR layer: cosine similarity against tell exemplars. Exemplar vectors
   are precomputed per user by learn/voice_vector_build.py into
   voice-tells-vectors.json inside the plugin's learned/ directory, keyed by
   backend ("ollama" | "onnx"): embedding spaces are backend-specific and
   never mixed. Per-class thresholds live in voice-tells-calibration.json
   (background p99 + 0.03 measured on clean prose by the same build). The
   vectors and the calibration are per-user artifacts, never shipped with the
   plugin: with neither file present the vector layer is skipped (logged
   vec_skip) and the regex layer still stands. Embedder: local Ollama
   nomic-embed-text as the fast path (warm ~13-64 ms); lazy in-process ONNX
   fallback (bge-small-en-v1.5 int8, ~35 MB, downloaded + cached on first
   use) when the daemon is absent.
3. VOICE-FIT layer (v1.1.0, issue #127 Tier 1, attraction side): the same
   chunk embeddings are also compared to the user's clean-corpus centroid
   (learned/voice-centroid.json, built by voice_vector_build.py, backend-keyed
   like the vectors). voice_fit(text) = mean over chunks of
   cosine(chunk_embedding, centroid); absent artifact -> silently skipped
   (fail-open, logged like the vectors). One embedding per unique text per
   process: a chunk embedded for tell scoring is never embedded again for
   voice-fit or source fidelity (_embed_memo + embed_cached). The gate's
   --source fidelity check reuses the source embedding from the bounded,
   hash-keyed disk cache learned/embed-cache.json so a repeated /voice run on
   the same draft does not re-embed the source (ruling 1, issue #127).

Learn/apply decoupling (issue #5): both layers load rule DATA from the runtime
state file <HERMES_HOME>/state/voice-rules.json (path override: VOICE_RULES_STATE)
at scan time, keyed per-source provenance (register, learn pass, manual
entries). Embedded PATTERNS/EXEMPLARS below are the fail-open defaults; valid
state entries merge/override them, per-source provenance is preserved, and an
absent/invalid state file falls back to the embedded lists exactly as before.
Runtime gate and published plugin share this ONE loading contract.

Public API:
    find_regex_hits(text) -> list[str]
    find_vector_hits(text) -> list[str]
    voice_fit(text) -> float | None
    vector_scores(text) -> {"tell_hits": [...], "voice_fit": float | None}
    vector_pass(text) -> full single-pass dict (tell hits + voice_fit + doc vector + chunk vectors)
    cycling_signals(vp, sets) -> chunk-pair paraphrase divergence (family 11, advisory)
    embed_cached(text, backend=None) -> (vector, backend)  # per-process memo
    embed_source_cached(text, backend) -> vector | None    # disk-cached source embed
    learned_dir() -> Path
    state_path() -> Path
    effective_rules() -> dict (patterns/exemplars/thresholds/bands + provenance)
"""
import hashlib
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
HERE = Path(__file__).resolve().parent          # <plugin>/hooks/
PLUGIN_DIR = HERE.parent                        # <plugin>/ (learned/ lives here)
# Per-user learned artifacts: built by the learn tools + /voice, never shipped.
# VOICE_LEARNED_DIR relocates the whole directory (tests, side-by-side installs)
# exactly like VOICE_RULES_STATE / VOICE_GATE_LOG override their sinks.
LEARNED_DIR = Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides)."""
    return LEARNED_DIR


CACHE_PATH = LEARNED_DIR / "voice-tells-vectors.json"    # exemplar vectors, backend-keyed
CAL_PATH = LEARNED_DIR / "voice-tells-calibration.json"  # per-class thresholds, backend-keyed
CENTROID_PATH = LEARNED_DIR / "voice-centroid.json"      # clean-corpus centroid, backend-keyed
EMBED_CACHE_PATH = LEARNED_DIR / "embed-cache.json"      # --source embed cache, hash-keyed, bounded
LEGACY_VEC_PATH = HOME / "state" / "voice-tells-vectors.json"
STATE_ENV = "VOICE_RULES_STATE"   # runtime rule state override (tests, side-by-side installs)
# Log sink resolves per call (VOICE_GATE_LOG override, tests + side-by-side installs)
LOG = HOME / "logs" / "voice-gate.log"
OLLAMA_URL = os.environ.get("VOICE_GATE_OLLAMA_URL", "http://localhost:11434/api/embeddings")
MODEL = "nomic-embed-text"        # Ollama tag: fast path
ONNX_MODEL = "bge-small-en-v1.5"  # availability path: int8 quantized, CLS pooling
ONNX_BASE = f"https://huggingface.co/Xenova/{ONNX_MODEL}/resolve/main"
ONNX_DIR = HOME / "state" / "models" / ONNX_MODEL
CAL_MARGIN = 0.03                 # per-class threshold = background p99 + margin
EMBED_TIMEOUT_S = 2.0
MAX_EMBED_CHARS = 4000            # truncate embedded prose; long docs scan per chunk below

# ---------------- REGEX LAYER ----------------
# (pattern, label). All case-insensitive except nothing here requires case.
PATTERNS = [
    (r"\u2014", "em dash (U+2014): use comma, period, colon or parentheses"),
    (r"\s--\s", "spaced double hyphen used as a dash"),
    # negative parallelism: "It's not just X (that)... it's Y", "not merely A but B"
    (r"\b(?:it'?s|it is|this is|they'?re|these are|that'?s)\s+not\s+(?:just|merely|only|simply)\b",
     "negative parallelism 'not just/merely/only' construction"),
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
    # humanizer gap patterns (2026-11-22 scan extension): plug the humanizer 35-pattern
    # families the gate missed; each maps to a numbered humanizer SKILL.md pattern.
    # 22 sycophantic/servile tone
    (r"\byou'?re\s+absolutely\s+right\b", "humanizer 22 sycophancy 'you're absolutely right' (state the substance instead)"),
    (r"\bgreat\s+(?:question|point)!\b", "humanizer 22 sycophancy 'great question/point!' (state the substance instead)"),
    (r"\bexcellent\s+point\b", "humanizer 22 sycophancy 'excellent point' (state the substance instead)"),
    (r"^\s*(?:absolutely!|certainly!|of course!)\s*$", "humanizer 22 sycophancy bare 'Absolutely!/Certainly!/Of course!' (state the substance instead)"),
    (r"\bthat'?s\s+an\s+excellent\b", "humanizer 22 sycophancy 'that's an excellent ...'"),
    # 25 generic positive conclusions
    (r"\bthe\s+future\s+looks?\s+bright\b", "humanizer 25 generic positive conclusion (state the concrete next fact)"),
    (r"\bexciting\s+times\s+(?:lie|are)\s+ahead\b", "humanizer 25 generic positive conclusion"),
    (r"\ba\s+(?:major\s+)?step\s+in\s+the\s+right\s+direction\b", "humanizer 25 generic positive conclusion"),
    (r"\bcontinue\s+(?:their|its)\s+journey\b", "humanizer 25 generic positive conclusion 'continue their journey'"),
    # 27 leftovers
    (r"\bfundamentally,?\s", "humanizer 27 persuasive authority 'fundamentally,'"),
    (r"\bthe\s+deeper\s+(?:issue|question|point)\b", "humanizer 27 persuasive authority 'the deeper issue'"),
    (r"\bin\s+reality,?\s", "humanizer 27 persuasive authority 'in reality,'"),
    # 28 signposting leftovers
    (r"\bhere'?s\s+what\s+(?:you\s+)?need\s+to\s+know\b", "humanizer 28 signpost 'here's what you need to know'"),
    (r"\bwithout\s+further\s+ado\b", "humanizer 28 signpost 'without further ado'"),
    (r"\blet'?s\s+break\s+(?:this|it|that)\s+down\b", "humanizer 28 signpost 'let's break this down'"),
    (r"\blet'?s\s+explore\b", "humanizer 28 signpost 'let's explore'"),
    (r"\bnow\s+let'?s\s+(?:look|turn)\s+(?:at|to)\b", "humanizer 28 signpost 'now let's look at'"),
    # 32 rhetorical questions answered immediately
    (r"\bever\s+wonder(?:ed)?\b", "humanizer 32 rhetorical question 'ever wondered' (state the point directly)"),
    (r"\bthink\s+about\s+it:?\b", "humanizer 32 rhetorical question 'think about it'"),
    (r"\bwhat\s+if\s+(?:i|we|you)\s+told\s+you\b", "humanizer 32 rhetorical question 'what if I told you'"),
    # 33 sentence-opener tics
    (r"^\s*(?:Interestingly|Importantly|Notably|Crucially|Essentially|Ultimately),\s", "humanizer 33 adverb opener (start with the substance; the sentence must earn the adverb)"),
    (r"^\s*So,\s", "humanizer 33 sentence opener 'So,'"),
    (r"^\s*Look,?\s", "humanizer 33 sentence opener 'Look,'"),
    # 34 leftover
    (r"\bthere'?s\s+nothing\s+wrong\s+with\s+(?:that|this)\b", "humanizer 34 reassurance kicker 'there's nothing wrong with that' (trust the reader)"),
    # 19 curly quotes
    (r"[\u201c\u201d\u2018\u2019]", "humanizer 19 curly quotation marks (use straight quotes)"),
    # 15/16/17/18 style and formatting
    (r"^\s*[-*]\s\*\*[^*\n]+:\*\*\s", "humanizer 16 inline-header list item '- **Header:** text' (write flowing prose)"),
    (r"^#{1,6}\s+(?-i:[A-Z][a-z]+\s+[A-Z][a-z]+)", "humanizer 17 Title Case heading (use sentence case)"),
    (r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "humanizer 18 emoji decoration (delete the emoji)"),
    # 12 false ranges
    (r"\bfrom\s+\w[\w\s]{0,20}\b\s+to\s+\b[\w\s]{0,20},?\s+from\b", "humanizer 12 false range 'from X to Y, from A to B' (list the real items)"),
    # personal-voice hard bans (em dash, corporate speak, throat-clearing family) the list missed
    (r"\bnorth[-\s]?star\b", "voice ban 'north star' (state the concrete goal)"),
    (r"\bdelight(?:ed|ing)?\b", "voice ban 'delight' (state what happens, not how it feels)"),
    (r"\bimpactful\b", "voice ban 'impactful' (name the actual effect)"),
    (r"\bdrive\s+(?:meaningful\s+)?(?:impact|change|results)\b", "voice ban 'drive impact/change/results' (name the concrete outcome)"),
    (r"\bstakeholder\s+value\b", "voice ban 'stakeholder value' (name whose value and what changes)"),
    # humanizer 1/4/7 vocabulary: significance inflation and promo language that was
    # previously vector-layer-only; these are regexable, so scan them deterministically.
    (r"\btestament\s+to\b", "humanizer 1 significance inflation 'testament to' (state the concrete fact)"),
    (r"\bpivotal\b", "humanizer 1 significance inflation 'pivotal' (state what changed)"),
    (r"\bcrucial\s+(?:role|moment|step|factor)\b", "humanizer 1 significance inflation 'crucial role/moment'"),
    (r"\b(?:underscore|highlight|highlights)s?\s+(?:its|the)\s+(?:importance|significance)\b", "humanizer 1 significance inflation 'underscores/highlights the importance'"),
    (r"\bstand(?:s|ing)\s+the\s+test\s+of\s+time\b", "humanizer 1 significance cliché 'stands the test of time'"),
    (r"\burges?\s+(?:visitors|readers)\b", "humanizer 4 promo-tourism 'urges visitors/readers'"),
    (r"\bnested\b|\bmust-visit\b|\bbreathtaking\b|\bstunning\b", "humanizer 4 promotional language (state the feature plainly)"),
    (r"\bvibrant\b", "humanizer 4 promotional language 'vibrant'"),
    (r"\bboast(?:s|ing)?\b", "humanizer 8 copula avoidance 'boasts' (use 'has')"),
]

_FLAGS = re.IGNORECASE | re.MULTILINE  # MULTILINE: opener/heading anchors match per line

# Register-gap note (issue #145, wave H-C 2026-11-27): humanizer families
# 11 (synonym cycling) and 35 (aphorism density) are not single-regex
# families. Family 11 rides the chunk-pair divergence signal below
# (cycling_signals; advisory until the owner calibrates its bands in the
# state file). Family 35 is a budget check, not a pattern match: the
# mechanical counter lives in learn/voice_battery_core.py (aphorism_shapes)
# and hooks/gate.py enforces the skill's own budget (max one kicker per
# section, two to three per piece). Both stay listed here so the gap stays
# visible next to the register.

# ---------------- VOICE RULES LAYER (named-regex YAML adapter) ----------------
# 2026-11-22: the tell scan adapts to a host's local voice rules and
# anti-patterns by consuming its named-regex YAML (DANEEL_RULES_YAML), so the
# two systems share one source of truth. When the env var is unset
# (portable/de-personalized installs), the layer skips: fail-open.
_RULES_YAML = os.environ.get("DANEEL_RULES_YAML")  # env-configured voice-rules layer; unset -> layer off

def _load_voice_rules():
    if not _RULES_YAML:
        return []
    try:
        import yaml
        rules = yaml.safe_load(open(_RULES_YAML)).get("rules") or {}
        return [(rid, rule["pattern"], str(rule.get("message") or rid),
                 [str(a) for a in (rule.get("allowlist") or [])]) for rid, rule in rules.items()]
    except Exception:
        return []

def voice_rules_hits(text):
    hits = []
    for rid, pattern, message, allowlist in _load_voice_rules():
        # Compile semantics mirror daneel_style_lint.make_flexible exactly, so the
        # gate and the style plugin see the same rules.
        flags = re.VERBOSE if "\n" in pattern else 0
        if "(?-i)" not in pattern:
            flags |= re.IGNORECASE
        p = pattern.replace("(?-i)", "")
        try:
            rx = re.compile(p, flags)
        except re.error:
            continue
        for m in rx.finditer(text):
            token = m.group(0)
            if allowlist and any(token.strip() == a for a in allowlist):
                continue
            near = text[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
            hits.append(f"daneel {rid}: {message} (near: {near!r})")
            break  # one report per rule per scan; density is the scanner's job
    return hits

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
    "Great teams do not build products; they build movements that carry their name for them.",
    "Experts and industry observers alike underscore the critical importance of this trend.",
    "Despite these challenges, with its strategic vision, the company continues to thrive, setting the stage for a bright future.",
    "The deadline did not slip; the scope quietly grew while nobody was measuring it.",
    "And that's okay. Every team starts somewhere, and there's nothing wrong with growing from there.",
    "They deliver robust, best-in-class, world-class solutions that supercharge productivity and enhance collaboration.",
    # 2026-11-22 gap-register exemplars (one per family; de-personalized). The
    # vector layer calibrates per-class thresholds against a clean corpus, so
    # each exemplar enables paraphrase catch for its whole family, regexed or not.
    "Awesome! You're absolutely right, that's an excellent point and I'm happy to jump on a call whenever it works best.",
    "The future looks bright and exciting times lie ahead as we continue our journey toward this major step in the right direction.",
    "Ever wondered what makes this tick? Think about it: the answer is simpler than the question implies.",
    "So, let me break this down. Interestingly, the rollout went fine. Essentially, you will love it.",
    "Curly quotes look extra polished. Here is a \U0001F680 emoji, plus a **Quick wins:** bullet list for you.",
    "Our north star is unlocking customer delight; this impactful platform boasts a stunning suite of solutions.",
]

# ---------------- STATE-FILE LAYER (learn/apply decoupling, issue #5) ----------------
# The style learner and any rule register write rule DATA (never .py) to
# <HERMES_HOME>/state/voice-rules.json; this module is the ONE loading contract
# shared by the runtime gate and the published plugin. Schema:
#   {"format": 1, "sources": {"<source>": {"patterns": [{"pattern", "label"}],
#                                           "exemplars": ["..."],
#                                           "thresholds": {"<label>": float},
#                                           "bands": {"<name>": {"<key>": float}}}}}
# with <source> naming provenance (register, learn, owner, ...). Precedence:
# embedded defaults first, then state entries in file order: an identical
# regex replaces the earlier label in place (later source wins), exemplars
# dedupe on exact text, thresholds override the embedded calibration per
# class, and band numbers override per <name>/<key> in file order (wave H-C,
# 2026-11-27: the detector threshold bands of the new signal methods, for
# example cycling t_sem/t_lex, load from here at scan time; absent bands
# mean the signal stays advisory with no fail line, never a code constant).
# Absent file: embedded defaults, silent (pre-loader behavior).
# Corrupt/invalid file: embedded defaults + one `state_skip` log line per
# state change (fail-open unchanged); entry-level problems skip just that
# entry and log, valid entries still apply.

_rules_cache = {"key": None, "value": None}  # (path, mtime_ns, size) -> parsed state
_eff_cache = {"key": None, "value": None}    # same key -> merged view + compiled regexes
_uncal_key = [None]                          # state key already checked for uncalibrated exemplars


def state_path():
    """Runtime rule state file: $VOICE_RULES_STATE or <HERMES_HOME>/state/voice-rules.json."""
    override = os.environ.get(STATE_ENV)
    return Path(override) if override else HOME / "state" / "voice-rules.json"


def _read_state():
    p = state_path()
    try:
        info = p.stat()
        key = (str(p), info.st_mtime_ns, info.st_size)
    except OSError:
        key = (str(p), None, None)
    if _rules_cache["key"] == key:
        return _rules_cache["value"]
    value = _parse_state(p, key)
    _rules_cache["key"], _rules_cache["value"] = key, value
    return value


def _dead_state(st, err):
    """Top-level unusable state: full fallback to embedded defaults, logged."""
    st["ok"], st["err"] = False, err
    _log_vec("state_skip", {"path": st["path"], "err": err})
    return st


def _parse_state(p, key):
    st = {"key": key, "ok": False, "err": None, "path": str(p), "sources": {},
          "patterns": [], "exemplars": [], "thresholds": {}, "bands": {}}
    if key[1] is None:
        st["err"] = "absent"  # embedded-only, silent like today: no log line
        return st
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return _dead_state(st, f"parse: {e!r}")
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        return _dead_state(st, "schema: expected a top-level object with a 'sources' object")
    st["ok"], st["sources"] = True, raw["sources"]
    warns = []
    for src, body in raw["sources"].items():
        if not isinstance(body, dict):
            warns.append(f"source '{src}' is not an object")
            continue
        pats = body.get("patterns")
        if pats is not None and not isinstance(pats, list):
            warns.append(f"source '{src}': patterns is not a list")
        elif isinstance(pats, list):
            for i, entry in enumerate(pats):
                if (isinstance(entry, dict) and isinstance(entry.get("pattern"), str)
                        and isinstance(entry.get("label"), str)):
                    try:
                        re.compile(entry["pattern"], _FLAGS)
                    except Exception as e:
                        warns.append(f"source '{src}': pattern[{i}] {entry['pattern'][:40]!r} "
                                     f"does not compile ({e!r}); skipped")
                        continue
                    st["patterns"].append((entry["pattern"], entry["label"], src))
                else:
                    warns.append(f"source '{src}': pattern entry needs pattern/label strings; skipped")
        exs = body.get("exemplars")
        if exs is not None and not isinstance(exs, list):
            warns.append(f"source '{src}': exemplars is not a list")
        elif isinstance(exs, list):
            for text in exs:
                if isinstance(text, str) and text.strip():
                    st["exemplars"].append((text, src))
                else:
                    warns.append(f"source '{src}': non-string exemplar skipped")
        th = body.get("thresholds")
        if th is not None:
            if not isinstance(th, dict):
                warns.append(f"source '{src}': thresholds is not an object")
            else:
                for label, v in th.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        st["thresholds"][label] = float(v)  # later sources override earlier
                    else:
                        warns.append(f"source '{src}': threshold '{label}' is not a number; skipped")
        bd = body.get("bands")
        if bd is None:
            continue
        if not isinstance(bd, dict):
            warns.append(f"source '{src}': bands is not an object")
            continue
        for name, entries in bd.items():
            if not isinstance(entries, dict):
                warns.append(f"source '{src}': band '{name}' is not an object; skipped")
                continue
            slot = st["bands"].setdefault(name, {})  # later sources override per key
            for k, v in entries.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    slot[k] = float(v)
                else:
                    warns.append(f"source '{src}': band '{name}.{k}' is not a number; skipped")
    if warns:
        st["err"] = "; ".join(warns)  # partial apply: valid entries stand, problems visible
        _log_vec("state_skip", {"path": str(p), "err": st["err"]})
    else:
        _log_vec("state_load", {"path": str(p), "sources": len(st["sources"]),
                                "patterns": len(st["patterns"]), "exemplars": len(st["exemplars"]),
                                "thresholds": len(st["thresholds"]),
                                "bands": len(st["bands"])})
    return st


def _effective():
    """Embedded defaults merged with state-file overrides; regexes compiled."""
    st = _read_state()
    if _eff_cache["key"] == st["key"]:
        return _eff_cache["value"]
    pats = list(PATTERNS)
    psrc = ["embedded"] * len(pats)
    idx = {p: i for i, (p, _) in enumerate(pats)}
    for pat, label, src in st["patterns"]:
        if pat in idx:
            pats[idx[pat]], psrc[idx[pat]] = (pat, label), src
        else:
            idx[pat] = len(pats)
            pats.append((pat, label))
            psrc.append(src)
    exs = list(EXEMPLARS)
    esrc = ["embedded"] * len(exs)
    seen = set(exs)
    for text, src in st["exemplars"]:
        if text not in seen:
            seen.add(text)
            exs.append(text)
            esrc.append(src)
    ths = st["thresholds"]
    bands = st["bands"]
    try:
        compiled = [(re.compile(p, _FLAGS), l) for p, l in pats]
    except Exception as e:  # belt and braces: a bad regex must never silence the gate
        _log_vec("error", {"path": st["path"], "err": f"compile: {e!r}; embedded-only fallback"})
        pats, psrc = list(PATTERNS), ["embedded"] * len(PATTERNS)
        exs, esrc = list(EXEMPLARS), ["embedded"] * len(EXEMPLARS)
        ths, bands = {}, {}
        compiled = [(re.compile(p, _FLAGS), l) for p, l in pats]
    eff = {"patterns": pats, "pattern_sources": psrc, "exemplars": exs,
           "exemplar_sources": esrc, "thresholds": dict(ths), "bands": dict(bands),
           "state": st, "compiled": compiled}
    _eff_cache["key"], _eff_cache["value"] = st["key"], eff
    return eff


def effective_rules():
    """Merged rule set (embedded + state overrides) with per-entry provenance:
    {"patterns": [(rx, label)], "pattern_sources": [...], "exemplars": [...],
     "exemplar_sources": [...], "thresholds": {label: float},
     "bands": {name: {key: float}}, "state": {...}}.
    Consumed by voice-vector-build.py (rebuild reads the effective exemplars)."""
    e = _effective()
    return {k: e[k] for k in ("patterns", "pattern_sources", "exemplars",
                              "exemplar_sources", "thresholds", "bands", "state")}

_cache = None       # loaded exemplar vectors (backend-keyed)
_cal = None         # loaded calibration table (backend-keyed)
_ollama_down = False  # sticky per process: one daemon miss switches to ONNX for good
_onnx = None        # lazy (session, tokenizer vocab) bundle


def _load_vectors():
    """Backend-keyed exemplar cache: beside this file first, then the legacy
    HERMES_HOME state path (flat pre-0.2.0 caches count as ollama-built)."""
    global _cache
    if _cache is None:
        cache = {}
        for p in (CACHE_PATH, LEGACY_VEC_PATH):
            try:
                cache = json.loads(p.read_text())
                break
            except Exception:
                continue
        if cache and "backends" not in cache:
            cache = {"format": 2, "backends": {"ollama": {
                "model": cache.get("model", MODEL), "vectors": cache.get("vectors", [])}}}
        _cache = cache if cache else {"format": 2, "backends": {}}
    return _cache


def _load_calibration():
    global _cal
    if _cal is None:
        try:
            _cal = json.loads(CAL_PATH.read_text())
        except Exception:
            _cal = {}
    return _cal


_centroid = None  # loaded voice-centroid.json (backend-keyed), fail-open


def _load_centroid():
    global _centroid
    if _centroid is None:
        try:
            loaded = json.loads(CENTROID_PATH.read_text(encoding="utf-8"))
            _centroid = loaded if isinstance(loaded, dict) else {}
        except Exception:
            _centroid = {}
    return _centroid


def _atomic_write(path, text):
    """Atomic artifact write: temp file in the same dir, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# Per-process embed memo: one embedding per unique (backend, text); a sentence
# embedded for tell scoring is NOT embedded again for voice-fit or fidelity
# (ruling 1, issue #127). Bounded; oldest entries dropped in insertion order.
_embed_memo = {}
EMBED_MEMO_MAX = 512


def embed_cached(text, timeout=EMBED_TIMEOUT_S, backend=None):
    """Memoized embed: returns (vector, resolved_backend). backend=None tries
    the Ollama fast path then ONNX (same order as _embed) and consults the memo
    for either; an explicit backend only hits its own memo entries."""
    h = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    if backend is not None:
        hit = _embed_memo.get((backend, h))
        if hit is not None:
            return hit, backend
    else:
        for cand in ((["ollama"] if not _ollama_down else []) + ["onnx"]):
            hit = _embed_memo.get((cand, h))
            if hit is not None:
                return hit, cand
    vec, used = _embed(text, timeout, backend)
    if len(_embed_memo) >= EMBED_MEMO_MAX:
        for key in list(_embed_memo)[:len(_embed_memo) - EMBED_MEMO_MAX + 1]:
            _embed_memo.pop(key, None)
    _embed_memo[(used, h)] = vec
    return vec, used


# Source-embedding disk cache (gate --source fidelity, ruling 1): hash-keyed,
# max 64 entries, oldest dropped in insertion order, atomic write. Key is
# "<backend>:<sha256(text)[:16]>"; embedding spaces are backend-specific.
_embed_cache = None
EMBED_CACHE_MAX = 64


def embed_source_cached(text, backend):
    """Source embedding for the gate's --source fidelity check. Disk-cached in
    learned/embed-cache.json: a repeated /voice run on the same draft must not
    re-embed the source. Returns the vector, or None when no backend/embedder
    is available (fail-open)."""
    global _embed_cache
    if not backend:
        return None
    short = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
    key = f"{backend}:{short}"
    if _embed_cache is None:
        try:
            loaded = json.loads(EMBED_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        _embed_cache = loaded if (isinstance(loaded, dict)
                                  and isinstance(loaded.get("entries"), dict)) else {"entries": {}}
    entries = _embed_cache["entries"]
    hit = entries.get(key)
    if isinstance(hit, dict) and isinstance(hit.get("vec"), list):
        _log_vec("embed_cache_hit", {"backend": backend, "key": short})
        return hit["vec"]
    try:
        vec, used = embed_cached(text, backend=backend)
    except Exception as e:
        _log_vec("vec_skip", {"err": f"source embed: {e!r}"})
        return None
    if used != backend:
        return vec  # backend switched mid-flight: usable, but not cacheable under this key
    entries.pop(key, None)
    entries[key] = {"vec": vec, "at": datetime.now(timezone.utc).isoformat()}
    while len(entries) > EMBED_CACHE_MAX:
        entries.pop(next(iter(entries)))
    _atomic_write(EMBED_CACHE_PATH, json.dumps(_embed_cache))
    _log_vec("embed_cache_store", {"backend": backend, "key": short})
    return vec


def _log_vec(event, detail):
    try:
        log = Path(os.environ.get("VOICE_GATE_LOG", str(LOG)))
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "event": event, **detail}) + "\n")
    except Exception:
        pass


def _post_json(url: str, body: dict, timeout: float) -> dict:
    """POST JSON to the configured model server. http is allowed only for
    loopback/link-local hosts (the local model server); https elsewhere.
    No userinfo; redirects are never followed."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or not host:
        raise ValueError("endpoint must have a plain hostname")
    if parts.scheme == "https":
        conn_cls = http.client.HTTPSConnection
    elif parts.scheme == "http":
        _require_local(host)
        conn_cls = http.client.HTTPConnection
    else:
        raise ValueError("only https, or http to a local model server, is supported")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    conn = conn_cls(host, port, timeout=timeout)
    try:
        conn.request("POST", path, body=json.dumps(body).encode(),
                     headers={"Content-Type": "application/json"})
        payload = conn.getresponse().read()
    finally:
        conn.close()
    return json.loads(payload)


def _is_local_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return ip.is_loopback or ip.is_link_local


def _require_local(host: str) -> None:
    """Every resolved address must be loopback/link-local."""
    for _family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
        if not _is_local_ip(sockaddr[0]):
            raise ValueError(f"{host} resolves outside loopback/link-local")


def _embed_ollama(text, timeout=EMBED_TIMEOUT_S):
    return _post_json(OLLAMA_URL, {"model": MODEL, "prompt": text[:MAX_EMBED_CHARS]},
                      timeout)["embedding"]


def _download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    for _hop in range(4):
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password or not host:
            raise ValueError("endpoint must have a plain hostname")
        if parts.scheme == "https":
            conn_cls = http.client.HTTPSConnection
        elif parts.scheme == "http":
            _require_local(host)
            conn_cls = http.client.HTTPConnection
        else:
            raise ValueError("downloads are https (or http to a local server) only")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn = conn_cls(host, port, timeout=120)
        try:
            conn.request("GET", path, headers={"User-Agent": "voice-gate"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, resp.getheader("Location") or "")
                continue
            body = resp.read()
        finally:
            conn.close()
        break
    else:
        raise ValueError("too many redirects")
    with tmp.open("wb") as f:
        f.write(body)
    tmp.replace(dest)


def _onnx_session():
    global _onnx
    if _onnx is None:
        import onnxruntime  # optional runtime dep: fallback path only, never module scope
        model, tokf = ONNX_DIR / "model_quantized.onnx", ONNX_DIR / "tokenizer.json"
        if not (model.is_file() and tokf.is_file()):
            ONNX_DIR.mkdir(parents=True, exist_ok=True)
            _download(f"{ONNX_BASE}/onnx/model_quantized.onnx", model)
            _download(f"{ONNX_BASE}/tokenizer.json", tokf)
        vocab = json.loads(tokf.read_text(encoding="utf-8"))["model"]["vocab"]
        sess = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        _onnx = (sess, vocab)
    return _onnx


def _wordpiece(text, vocab):
    """BERT-style basic tokenize + greedy WordPiece, vocab from tokenizer.json."""
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(c)).lower()[:MAX_EMBED_CHARS]
    ids, unk, prefix = [], vocab["[UNK]"], "##"
    for word in re.findall(r"\w+|[^\w\s]", text):
        if len(word) > 100:
            word = word[:100]
        i, toks = 0, []
        while i < len(word):
            for j in range(len(word), i, -1):
                cand = word[i:j] if i == 0 else prefix + word[i:j]
                if cand in vocab:
                    toks.append(vocab[cand])
                    break
            else:
                toks = [unk]
                break
            i = j
        ids.extend(toks)
    return ids


def _embed_onnx(text):
    sess, vocab = _onnx_session()
    ids = [vocab["[CLS]"]] + _wordpiece(text, vocab)[:510] + [vocab["[SEP]"]]
    feed = {}
    for inp in sess.get_inputs():
        if inp.name == "input_ids":
            feed[inp.name] = [ids]
        elif inp.name == "attention_mask":
            feed[inp.name] = [[1] * len(ids)]
        elif inp.name == "token_type_ids":
            feed[inp.name] = [[0] * len(ids)]
    out = sess.run(None, feed)[0]  # last_hidden_state [1, T, H]
    v = [float(x) for x in out[0][0]]  # CLS pooling (bge v1.5)
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _embed(text, timeout=EMBED_TIMEOUT_S, backend=None):
    """Return (embedding, backend). backend=None tries the Ollama fast path
    then the ONNX fallback; an explicit backend never silently switches."""
    global _ollama_down
    order = [backend] if backend else ([] if _ollama_down else ["ollama"]) + ["onnx"]
    errs = {}
    for b in order:
        if b == "ollama":
            try:
                return _embed_ollama(text, timeout), "ollama"
            except Exception as e:
                _ollama_down = True  # sticky: no daemon re-probed this process
                errs[b] = repr(e)
                _log_vec("vec_fallback", {"to": "onnx", "err": errs[b]})
        elif b == "onnx":
            try:
                return _embed_onnx(text), "onnx"
            except Exception as e:
                errs[b] = repr(e)
    raise RuntimeError(f"no embedder available: {errs}")


def _cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)); db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def _chunks(text, size=1200, cap=12):
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
    return out[:cap]


def find_regex_hits(text):
    hits = []
    for rx, label in _effective()["compiled"]:
        m = rx.search(text)
        if m:
            near = text[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
            hits.append(f"{label} (near: {near!r})")
    return hits


def vector_pass(text):
    """Single embedding pass over the chunks of text (v1.1.0, issue #127 T1).

    Returns {"active": bool, "backend": str | None, "tell_hits": [str],
             "voice_fit": float | None, "doc_vec": [float] | None,
             "chunk_vecs": [[float]] | None}.
    active False = the vector layer is off or unavailable (no artifacts, no
    embedder): every consumer fails open. One chunk embed serves the tell
    similarities, the voice-fit cosines, the document vector and the
    per-chunk vectors (wave H-C 2026-11-27: chunk_vecs carries the same
    normalized chunk vectors the pass already computed, so the chunk-pair
    divergence signal adds zero embed calls; None when inactive). Embed or
    calibration miss on a chunk aborts the scan exactly like v1.0.0
    find_vector_hits (fail-open, logged)."""
    inactive = {"active": False, "backend": None, "tell_hits": [],
                "voice_fit": None, "doc_vec": None, "chunk_vecs": None}
    if os.environ.get("VOICE_GATE_VECTOR", "").lower() == "off":
        return inactive
    cache, cal = _load_vectors(), _load_calibration()
    if not cache.get("backends"):
        return inactive
    eff = _effective()
    if eff["state"]["ok"] and _uncal_key[0] != eff["state"]["key"]:
        _uncal_key[0] = eff["state"]["key"]
        cached = {v.get("text") for b in cache["backends"].values() for v in b.get("vectors", [])}
        missing = [t for t, s in zip(eff["exemplars"], eff["exemplar_sources"])
                   if s != "embedded" and t not in cached]
        if missing:  # learned exemplars not yet vectorized: visible gap, fail-open
            _log_vec("state_uncalibrated", {"missing": len(missing), "sample": missing[0][:60]})
    centroids = _load_centroid().get("backends") or {}
    hits, fits, vecs = [], [], []
    backend = None
    for chunk in _chunks(text):
        try:
            v, backend = embed_cached(chunk, backend=backend)
        except Exception as e:
            _log_vec("vec_skip", {"err": repr(e)})
            break  # fail open: no embedder never blocks on its own
        entry = cache["backends"].get(backend) or {}
        th = (cal.get("backends") or {}).get(backend, {}).get("thresholds", {})
        if not entry.get("vectors") or not th:
            _log_vec("vec_skip", {"err": f"backend '{backend}' uncalibrated"})
            break
        chunk_hits = []
        for ex in entry["vectors"]:
            t = eff["thresholds"].get(ex["label"])
            if t is None:
                t = th.get(ex["label"])
            sim = _cosine(v, ex["vec"])
            if t is not None and sim >= t:
                chunk_hits.append(f"vector tell '{ex['label']}' sim={sim:.2f} (near exemplar: "
                                  f"{ex['text'][:70]}...)")
                _log_vec("vec_hit", {"backend": backend, "class": ex["label"], "sim": round(sim, 3),
                                     "threshold": t})
        if len(chunk_hits) > 1:  # class collision: warn-mode, block decision unchanged
            _log_vec("vec_collision", {"backend": backend, "classes": len(chunk_hits),
                                       "chunk": chunk[:80]})
        hits.extend(chunk_hits)
        cent = centroids.get(backend) or {}
        if isinstance(cent.get("centroid"), list) and cent["centroid"]:
            fits.append(_cosine(v, cent["centroid"]))
        vecs.append(v)
    # dedupe labels
    seen, uniq = set(), []
    for h in hits:
        label = h.split(" sim=")[0]
        if label not in seen:
            seen.add(label)
            uniq.append(h)
    doc_vec = None
    if vecs:
        mean = [sum(col) / len(col) for col in zip(*vecs)]
        norm = math.sqrt(sum(x * x for x in mean))
        doc_vec = [x / norm for x in mean] if norm else mean
    voice_fit = sum(fits) / len(fits) if fits else None
    return {"active": backend is not None, "backend": backend, "tell_hits": uniq,
            "voice_fit": voice_fit, "doc_vec": doc_vec, "chunk_vecs": vecs or None}


def cycling_signals(vp, sets):
    """Chunk-pair paraphrase divergence (family 11, wave H-C 2026-11-27,
    method-menu A1): for each adjacent chunk pair (i, i+1), the pair is a
    cycling pair when the semantic cosine of the EXISTING chunk vectors is
    high and the lexical Jaccard overlap of the content-word sets from the
    EXISTING fast-core token loop is low: same meaning, different words.
    Thresholds are never code constants: they load from the learned-state
    chain at scan time (source 'bands', name 'cycling', keys 't_sem' and
    't_lex'). Absent or invalid bands -> [] (the signal stays advisory, no
    fail line ships from this method). vp is a vector_pass result; sets the
    aligned chunk content sets (learn/voice_battery_core.py
    chunk_content_sets). Pure; fails open on any shape mismatch."""
    try:
        band = (_effective().get("bands") or {}).get("cycling") or {}
        t_sem, t_lex = band.get("t_sem"), band.get("t_lex")
        if not (isinstance(t_sem, (int, float)) and isinstance(t_lex, (int, float))
                and not isinstance(t_sem, bool) and not isinstance(t_lex, bool)):
            return []
        vecs = (vp or {}).get("chunk_vecs") or []
        if len(vecs) < 2 or len(sets) != len(vecs):
            return []
        out = []
        for i in range(len(vecs) - 1):
            sem = _cosine(vecs[i], vecs[i + 1])
            a, b = sets[i] or set(), sets[i + 1] or set()
            union = a | b
            lex = (len(a & b) / float(len(union))) if union else 0.0
            if sem >= t_sem and lex <= t_lex:
                out.append({"pair": i, "cosine": round(sem, 3), "jaccard": round(lex, 3)})
        return out
    except Exception:
        return []


def find_vector_hits(text):
    """Return hits from the embedding layer; empty on any infrastructure miss.
    Similarity is compared per class against the calibrated threshold for the
    backend that produced the chunk embedding; state-file thresholds (issue #5)
    override the embedded calibration per class. Signature and semantics
    unchanged from v1.0.0 (the tell part of the single vector_pass)."""
    return vector_pass(text)["tell_hits"]


def voice_fit(text):
    """Attraction-side score (issue #127 Tier 1): mean over the chunks of
    cosine(chunk_embedding, clean-corpus centroid) under the resolved backend.
    None when the centroid artifact is absent or the embedder is unavailable
    (fail-open, logged like the vector layer)."""
    return vector_pass(text)["voice_fit"]


def vector_scores(text):
    """Convenience view over the single pass: {"tell_hits": [...],
    "voice_fit": float | None}."""
    vp = vector_pass(text)
    return {"tell_hits": vp["tell_hits"], "voice_fit": vp["voice_fit"]}


def scan(text, use_vector=True):
    """Full deterministic scan: embedded regex register + optional vector layer
    + host voice-rules YAML layer (DANEEL_RULES_YAML; skip when unset,
    fail-open). All rules ride every caller that uses scan(): the plugin gate,
    the Hermes pre-delivery hook, and voice_check.py."""
    hits = find_regex_hits(text)
    if use_vector and len(text) > 40:
        hits.extend(find_vector_hits(text))
    try:
        hits.extend(voice_rules_hits(text))
    except Exception:
        pass
    return hits

# ---------------- SITUATIONAL RULE SELECTION (2026-11-22) ----------------
# Not every tell family is a tell in every situation: formatting conventions
# (bolded list items, sentence-case headings) are correct in email and docs but
# wrong in a blog post; assistant-conduct families (sycophancy, reassurance,
# announcement openers) matter everywhere a human reads it but the marketing
# vocabulary rarely applies. The table lists which families stay ON per
# situation; None = full register (the default for long-form surfaces).
# Family ids are the label prefixes the register already carries:
#   humanizer N (n-specific), daneel (voice-rules YAML layer), plus the legacy
#   category words: banned, resume-slop, chatbot artifact, signpost, filler,
#   blog cliché, persuasive authority, negative parallelism, copula avoidance,
#   reassurance kicker, slop, humanizer gap/vocabulary labels.
def _family(hit):
    head = hit.split(" (")[0]
    if head.startswith("humanizer"):
        return " ".join(head.split()[:2])  # e.g. 'humanizer 22'
    for kw in ("banned", "resume-slop", "chatbot", "signpost", "filler",
               "blog cliché", "persuasive", "negative parallelism", "copula",
               "reassurance", "slop", "voice ban", "daneel"):
        if head.startswith(kw):
            return kw
    return head

SITUATIONS = {
    # name -> "all" (full register) or {"on": [...family ids...]}
    "public": "all",
    "blog": "all",
    "linkedin": "all",
    "report": "all",
    # Chat/conversational surfaces apply the assistant-conduct register and the
    # voice-rules YAML layer; formatting and marketing families stay off (an
    # emoji or a bolded item in Slack/Discord is not a tell).
    "chat": {"on": ["daneel", "humanizer 12", "humanizer 22", "humanizer 25",
                    "humanizer 27", "humanizer 28", "humanizer 32", "humanizer 33",
                    "humanizer 34", "chatbot", "filler", "signpost",
                    "persuasive", "negative parallelism", "reassurance",
                    "sycophancy", "voice ban"]},
    # Email: conduct + artifact families on; markdown-formatting families off.
    "email": {"on": ["daneel", "humanizer 12", "humanizer 22", "humanizer 25",
                     "humanizer 27", "humanizer 28", "humanizer 32", "humanizer 33",
                     "humanizer 34", "chatbot", "filler", "signpost", "persuasive",
                     "negative parallelism", "reassurance", "voice ban"]},
}

def situation_filter(hits, situation="public"):
    """Filter scan hits down to the families the situation keeps on. Unknown
    situation names raise KeyError so typos surface instead of silently
    scanning with the wrong rules."""
    spec = SITUATIONS.get(situation)
    if spec is None:
        raise KeyError(f"unknown situation {situation!r}; known: {sorted(SITUATIONS)}")
    if spec == "all":
        return list(hits)
    on = set(spec["on"])
    return [h for h in hits if _family(h) in on]

