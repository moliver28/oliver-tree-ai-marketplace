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
    state_path() -> Path
    effective_rules() -> dict (patterns/exemplars/thresholds + provenance)
"""
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
# Per-user vector artifacts: built by learn/voice_vector_build.py, never
# shipped. Absent files -> vector layer skips itself (fail-open), regex stands.
CACHE_PATH = PLUGIN_DIR / "learned" / "voice-tells-vectors.json"    # exemplar vectors, backend-keyed
CAL_PATH = PLUGIN_DIR / "learned" / "voice-tells-calibration.json"  # per-class thresholds, backend-keyed
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
]

_FLAGS = re.IGNORECASE

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
]

# ---------------- STATE-FILE LAYER (learn/apply decoupling, issue #5) ----------------
# The style learner and any rule register write rule DATA (never .py) to
# <HERMES_HOME>/state/voice-rules.json; this module is the ONE loading contract
# shared by the runtime gate and the published plugin. Schema:
#   {"format": 1, "sources": {"<source>": {"patterns": [{"pattern", "label"}],
#                                           "exemplars": ["..."],
#                                           "thresholds": {"<label>": float}}}}
# with <source> naming provenance (register, learn, owner, ...). Precedence:
# embedded defaults first, then state entries in file order — an identical
# regex replaces the earlier label in place (later source wins), exemplars
# dedupe on exact text, thresholds override the embedded calibration per
# class. Absent file: embedded defaults, silent (pre-loader behavior).
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
          "patterns": [], "exemplars": [], "thresholds": {}}
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
        if th is None:
            continue
        if not isinstance(th, dict):
            warns.append(f"source '{src}': thresholds is not an object")
            continue
        for label, v in th.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                st["thresholds"][label] = float(v)  # later sources override earlier
            else:
                warns.append(f"source '{src}': threshold '{label}' is not a number; skipped")
    if warns:
        st["err"] = "; ".join(warns)  # partial apply: valid entries stand, problems visible
        _log_vec("state_skip", {"path": str(p), "err": st["err"]})
    else:
        _log_vec("state_load", {"path": str(p), "sources": len(st["sources"]),
                                "patterns": len(st["patterns"]), "exemplars": len(st["exemplars"]),
                                "thresholds": len(st["thresholds"])})
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
    try:
        compiled = [(re.compile(p, _FLAGS), l) for p, l in pats]
    except Exception as e:  # belt and braces: a bad regex must never silence the gate
        _log_vec("error", {"path": st["path"], "err": f"compile: {e!r}; embedded-only fallback"})
        pats, psrc = list(PATTERNS), ["embedded"] * len(PATTERNS)
        exs, esrc = list(EXEMPLARS), ["embedded"] * len(EXEMPLARS)
        ths = {}
        compiled = [(re.compile(p, _FLAGS), l) for p, l in pats]
    eff = {"patterns": pats, "pattern_sources": psrc, "exemplars": exs,
           "exemplar_sources": esrc, "thresholds": dict(ths),
           "state": st, "compiled": compiled}
    _eff_cache["key"], _eff_cache["value"] = st["key"], eff
    return eff


def effective_rules():
    """Merged rule set (embedded + state overrides) with per-entry provenance:
    {"patterns": [(rx, label)], "pattern_sources": [...], "exemplars": [...],
     "exemplar_sources": [...], "thresholds": {label: float}, "state": {...}}.
    Consumed by voice-vector-build.py (rebuild reads the effective exemplars)."""
    e = _effective()
    return {k: e[k] for k in ("patterns", "pattern_sources", "exemplars",
                              "exemplar_sources", "thresholds", "state")}

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


def find_vector_hits(text):
    """Return hits from the embedding layer; empty on any infrastructure miss.
    Similarity is compared per class against the calibrated threshold for the
    backend that produced the chunk embedding; state-file thresholds (issue #5)
    override the embedded calibration per class."""
    if os.environ.get("VOICE_GATE_VECTOR", "").lower() == "off":
        return []
    cache, cal = _load_vectors(), _load_calibration()
    if not cache.get("backends"):
        return []
    eff = _effective()
    if eff["state"]["ok"] and _uncal_key[0] != eff["state"]["key"]:
        _uncal_key[0] = eff["state"]["key"]
        cached = {v.get("text") for b in cache["backends"].values() for v in b.get("vectors", [])}
        missing = [t for t, s in zip(eff["exemplars"], eff["exemplar_sources"])
                   if s != "embedded" and t not in cached]
        if missing:  # learned exemplars not yet vectorized: visible gap, fail-open
            _log_vec("state_uncalibrated", {"missing": len(missing), "sample": missing[0][:60]})
    hits = []
    for chunk in _chunks(text):
        try:
            v, backend = _embed(chunk)
        except Exception as e:
            _log_vec("vec_skip", {"err": repr(e)})
            return hits  # fail open: no embedder never blocks on its own
        entry = cache["backends"].get(backend) or {}
        th = (cal.get("backends") or {}).get(backend, {}).get("thresholds", {})
        if not entry.get("vectors") or not th:
            _log_vec("vec_skip", {"err": f"backend '{backend}' uncalibrated"})
            return hits
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
