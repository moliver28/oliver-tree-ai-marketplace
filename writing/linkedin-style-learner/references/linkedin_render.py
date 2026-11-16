#!/usr/bin/env python3
"""Deterministic slot filler + post-type selector for LinkedIn voicebook posts.

No LLM calls anywhere. Two modes:

Render mode (legacy contract, unchanged CLI):
  linkedin_render.py --variant V# --brief brief.json --out /tmp/v#.md
  --variant V1..V5 plus any V*.md skeleton found in the effective templates
  dir. V4 (no skeleton) refuses from data (post_types.yaml, refuse_reason)
  until the brief carries a non-empty FAILURE_ROW; render still exits 1.

Slot semantics now live in linkedin_templates/slots.yaml (name, brief_keys,
kind, constraints, list join default mode). render's validate_slot / slot
brief-key map READ the registry; there is no per-slot if-chain left in
python. Adding a slot = add it to slots.yaml + use it in a skeleton. V4
refusal text lives in linkedin_templates/post_types.yaml.

List join modes (generic): any list slot may carry an inline modifier in its
skeleton token: {{SLOT|clauses}} / {{SLOT|para}} / {{SLOT|pair}}. With no
modifier the slot's default_mode from slots.yaml applies:
  clauses  lower-cased items semicolon-bridged into one sentence
  para     item 1 lowercased + later items sentence-cased, joined by '. '
  pair     exactly two items semicolon-bridged (lower-cased)
  commas   comma-joined clause list (DESIGN_MOVES legacy)
  count    STORY_EXAMPLES legacy default: 3 items -> para, 2 items -> pair
STORY_EXAMPLES keeps its exact legacy behavior: a modifier present (any of
the three) selects clauses; no modifier selects para/pair by item count.
The |pair modifier on a 2-item slot; on any other item count the render
fails loudly with the slot name.

Slot values carry no terminal punctuation; the skeleton owns sentence ends.

Configuration (optional; absent file = byte-identical factory behavior):
  $LINKEDIN_TEMPLATES_DIR/<dir>/config.json or
  ~/.hermes/scripts/linkedin_config.json with keys: template_dir,
  url_allowlist (regex list; the LINK gate validates against it),
  ollama_url, voice_corpus. The env var LINKEDIN_TEMPLATES_DIR wins over
  template_dir; with no env var and no config the templates dir is
  ../linkedin_templates relative to this script. app.notion.com links are
  always rejected in code (hard privacy rule, not config).

Select mode (engagement-weighted post-type ranking; gates never bypassed):
  linkedin_render.py --select --brief brief.json
      [--situations has_link=true,news_hook=false] [--used-kinds V1,V3]
      [--explain] [--out selection.json]
  Prints one JSON object with a ranked list of viable post kinds
  (linkedin_templates/post_types.yaml). Viable = every required slot (plus
  one of requires_alt when declared) is fillable from the brief (+ the
  configured link allowlist for LINK); missing recommended slots are
  reported as fill-gaps, missing required slots move the kind to not_viable.
  Score = sum over levers (weights.yaml) of base * product of situation
  multipliers that hold; ordering is deterministic: score desc, then kind
  name asc; top pick is ranked[0]. --explain adds per-kind score breakdown
  lines. --used-kinds demotes those kinds (name or variant) one effective
  rank step downstream in a single stable pass, deterministically. Selection
  lists kinds; the chosen kind is then rendered and gated exactly like today
  (render -> voicebook checker -> lever check -> voice guard). If that gate
  run fails for post-type ranking reasons (e.g. a slot that passed presence
  fails shape), fall back manually to the next ranked kind; there is no
  auto-fallback loop. Rotation (checker's open-sha256 + variant ladder rules)
  stays upstream of selection: the pipeline re-ranks past the used set with
  --used-kinds.

Exit codes: render mode 0 = post written, 1 = fail (no file written).
Select mode: 0 = selection printed; 1 = unusable input.
"""
import argparse, json, os, re, sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_TPL = SCRIPTS / "linkedin_templates"
CONFIG_NAME = "linkedin_config.json"
LINKEDIN_CONFIG = SCRIPTS / CONFIG_NAME

VARIANTS = ["V1", "V2", "V3", "V4", "V5"]  # voicebook rotation ladder (base)
CONTRACT_KEYS = ["title", "primary_keyword", "tags", "link"]
BAD_PUNCT = ("\u2014", " \u2014 ", " -- ", "!")
LIST_MODES = ("clauses", "para", "pair")

# module state, filled by main(): the registry lives in the templates dir,
# so nothing here is import-time constants anymore
SLOTS = {}          # slot name -> constraint map (slots.yaml)
P_TYPES = {}        # post type name -> entry (post_types.yaml)
WEIGHTS = {}        # lever -> {slots, match, types: kind -> {base, situations}}


def fail(errors, code, detail):
    errors.append(f"{code}: {detail}")


# ---------------- minimal YAML subset parser (stdlib, fail loud) ----------
def _yaml_strip_comment(line):
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _yaml_scalar(s):
    s = s.strip()
    if s == "":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    if s in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _yaml_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _yaml_flow_key(s, i):
    i = _yaml_ws(s, i)
    if i < len(s) and s[i] in "\"'":
        q = s[i]
        j = s.find(q, i + 1)
        if j < 0:
            raise ValueError("yaml flow: unterminated quote in %r" % s)
        return s[i + 1:j], j + 1
    j = i
    while j < len(s) and s[j] != ":":
        j += 1
    while j > i and s[j - 1] in " \t":
        j -= 1
    if j == i:
        raise ValueError("yaml flow: empty key in %r" % s)
    return _yaml_scalar(s[i:j]), j


def _yaml_flow_node(s, i):
    """Flow node: scalar, inline [list] or inline {map} (recursive)."""
    i = _yaml_ws(s, i)
    if i >= len(s):
        raise ValueError("yaml flow: unexpected end in %r" % s)
    ch = s[i]
    if ch == "[":
        i += 1
        arr = []
        i = _yaml_ws(s, i)
        if i < len(s) and s[i] == "]":
            return arr, i + 1
        while True:
            v, i = _yaml_flow_node(s, i)
            arr.append(v)
            i = _yaml_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                return arr, i + 1
            else:
                raise ValueError("yaml flow list: expected ',' or ']' in %r" % s)
    if ch == "{":
        i += 1
        mp = {}
        i = _yaml_ws(s, i)
        if i < len(s) and s[i] == "}":
            return mp, i + 1
        while True:
            k, i = _yaml_flow_key(s, i)
            i = _yaml_ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise ValueError("yaml flow map: expected ':' in %r" % s)
            v, i = _yaml_flow_node(s, i + 1)
            mp[k] = v
            i = _yaml_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "}":
                return mp, i + 1
            else:
                raise ValueError("yaml flow map: expected ',' or '}' in %r" % s)
    if ch in "\"'":
        q = ch
        j = i + 1
        while j < len(s) and s[j] != q:
            j += 1
        if j >= len(s):
            raise ValueError("yaml flow: unterminated quote in %r" % s)
        return s[i + 1:j], j + 1
    j = i
    while j < len(s) and s[j] not in ",]}":
        j += 1
    while j > i and s[j - 1] in " \t":
        j -= 1
    if j == i:
        raise ValueError("yaml flow: empty scalar in %r" % s)
    return _yaml_scalar(s[i:j]), j


def _yaml_flow(s):
    v, i = _yaml_flow_node(s, 0)
    i = _yaml_ws(s, i)
    if i != len(s):
        raise ValueError("yaml: trailing data after flow scalar: %r" % s[i:])
    return v


def _yaml_block_seq(lines, i, indent):
    out = []
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or not (content == "-" or content.startswith("- ")):
            break
        if ind != indent:
            break
        rest = content[1:].strip()
        if rest:
            out.append(_yaml_flow(rest))
            i += 1
        else:
            if i + 1 >= len(lines) or lines[i + 1][0] <= indent:
                raise ValueError("yaml seq: dash at %r needs a nested block" % content)
            v, i = _yaml_block(lines, i + 1, lines[i + 1][0])
            out.append(v)
    return out, i


def _yaml_block_map(lines, i, indent):
    out = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError("yaml: unexpected extra indent at %r" % content)
        if content == "-" or content.startswith("- "):
            break
        if ":" not in content:
            raise ValueError("yaml mapping: not a key line: %r" % content)
        key, _, rest = content.partition(":")
        key_s = _yaml_scalar(key.strip())
        if not isinstance(key_s, str):
            raise ValueError("yaml mapping: key must be a string: %r" % content)
        rest = rest.strip()
        if rest:
            if rest == "-" or rest.startswith("- "):
                raise ValueError("yaml: dash values on key lines unsupported: %r" % content)
            out[key_s] = _yaml_flow(rest)
            i += 1
        else:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                out[key_s], i = _yaml_block(lines, i + 1, lines[i + 1][0])
            else:
                out[key_s] = None
                i += 1
    return out, i


def _yaml_block(lines, i, indent):
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        return _yaml_block_seq(lines, i, indent)
    return _yaml_block_map(lines, i, indent)


def parse_yaml_subset(text):
    """Parse the registry YAML subset: nested block maps, block sequences of
    plain scalars, inline lists/maps (recursively), quoted or plain scalars,
    ints/floats/bools, '#' comments. Anything else fails loudly (a malformed
    registry may never be silently misread). No PyYAML dependency."""
    lines = []
    for raw in text.splitlines():
        line = _yaml_strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if not lines:
        return {}
    val, i = _yaml_block(lines, 0, 0)
    if i != len(lines):
        raise ValueError("yaml: unparsed line %d: %r" % (i + 1, lines[i][1]))
    return val


# ---------------- shared config loader (one local copy per script) --------
_CFG = None
CFG_LOADED = False


def load_config():
    """Config discovery (same contract in every linkedin*.py script):
    $LINKEDIN_TEMPLATES_DIR/config.json first, then
    ~/.hermes/scripts/linkedin_config.json. Neither present -> None, which
    keeps factory default behavior byte-identical. A present-but-corrupt
    file raises (fail loud, never silently ignored)."""
    global _CFG, CFG_LOADED
    if CFG_LOADED:
        return _CFG
    CFG_LOADED = True
    candidates = []
    env = os.environ.get("LINKEDIN_TEMPLATES_DIR")
    if env:
        candidates.append(Path(env).expanduser() / "config.json")
    candidates.append(LINKEDIN_CONFIG)
    for cand in candidates:
        if cand.is_file():
            try:
                _CFG = json.loads(cand.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"config unreadable: {cand} ({e})")
            if not isinstance(_CFG, dict):
                raise ValueError(f"config must be a JSON object: {cand}")
            break
    return _CFG


def templates_dir(cfg):
    env = os.environ.get("LINKEDIN_TEMPLATES_DIR")
    if env:
        return Path(env).expanduser()
    if cfg and cfg.get("template_dir"):
        return Path(str(cfg["template_dir"])).expanduser()
    return DEFAULT_TPL


def url_allowlisted(url, cfg):
    """LINK public check: config url_allowlist regexes when a config carries
    them; the legacy substring rule (notion.site / synology-nas) otherwise."""
    pats = (cfg or {}).get("url_allowlist")
    if not pats:
        return "notion.site" in url or "synology-nas" in url
    return any(re.search(p, url) for p in pats)


# ---------------- slot registry -------------------------------------------
def load_registry(tdir, strict=True):
    """slots.yaml -> {name: spec}. strict=False reads best-effort (used by
    scripts that can fall back to built-ins)."""
    p = tdir / "slots.yaml"
    if not p.is_file():
        if strict:
            raise ValueError(f"slot registry missing: {p}")
        return {}
    data = parse_yaml_subset(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"slot registry malformed: {p}")
    for name, spec in data.items():
        if not isinstance(spec, dict):
            raise ValueError(f"slot registry: '{name}' entry must be a mapping")
        if spec.get("kind", "text") not in ("text", "list", "object"):
            raise ValueError(f"slot registry: '{name}' unknown kind")
        if not spec.get("brief_keys"):
            raise ValueError(f"slot registry: '{name}' needs brief_keys")
    return data


def load_post_types(tdir):
    p = tdir / "post_types.yaml"
    if not p.is_file():
        return {}
    data = parse_yaml_subset(p.read_text(encoding="utf-8"))
    post_types = (data or {}).get("post_types")
    if not isinstance(post_types, dict):
        raise ValueError(f"post types malformed: {p}")
    return post_types


def load_weights(tdir):
    p = tdir / "weights.yaml"
    if not p.is_file():
        return {}
    data = parse_yaml_subset(p.read_text(encoding="utf-8"))
    weights = (data or {}).get("weights")
    if not isinstance(weights, dict):
        raise ValueError(f"weights malformed: {p}")
    return weights


def post_type_for_variant(ptypes, variant):
    for kind, pt in (ptypes or {}).items():
        if str(pt.get("variant", "")).strip().upper() == variant:
            return kind, pt
    return None, None


# ---------------- string helpers (unchanged legacy behavior) --------------
def strip_end(s):
    return re.sub(r"[.!?,;:\s]+$", "", s).strip()


def lower_first(s):
    # lower the opening cap only when it looks like a normal word, so
    # acronyms (LLMs, UX) survive untouched
    return (s[:1].lower() + s[1:]) if re.match(r"[A-Z][a-z]", s) else s


def upper_first(s):
    return (s[:1].upper() + s[1:]) if re.match(r"[a-z]", s) else s


def split_sentences(text):
    text = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)  # protect decimals
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.replace("<DOT>", ".").strip() for s in parts if s.strip()]


def scan_bad_punct(errors, name, v):
    for bad in BAD_PUNCT:
        if bad in v:
            label = "em dash" if bad.strip() in ("\u2014",) else "spaced double hyphen" if bad.strip() == "--" else "exclamation mark"
            fail(errors, "slot-format", f"{name} contains banned punctuation ({label})")
            return False
    return True


def validate_component(errors, name, raw, spec):
    """One key of an object slot (slots.yaml keys: gap_stat_a, what_broke...).
    Spec may carry strip_end, lower_first, digit, single_fragment, no_punct,
    max_chars, string_only; ordering matches the legacy component validator."""
    if spec.get("string_only") and (not isinstance(raw, str) or not raw.strip()):
        fail(errors, "slot-format", f"{name} must be a non-empty string clause containing a digit")
        return None
    v = raw if isinstance(raw, str) else str(raw)
    if spec.get("strip_end"):
        v = strip_end(v)
    if "{{" in v or "}}" in v:
        fail(errors, "slot-format", f"{name} contains placeholder braces")
        return None
    if spec.get("no_punct") and not scan_bad_punct(errors, name, v):
        return None
    if spec.get("single_fragment") and re.search(r"(?<=[.!?])\s+\S", v):
        fail(errors, "slot-format", f"{name} must be a single clause (internal sentence break)")
        return None
    if spec.get("digit") and not re.search(r"\d", v):
        fail(errors, "slot-format", f"{name} must contain a digit")
        return None
    if spec.get("max_chars") and len(v) > spec["max_chars"]:
        fail(errors, "slot-format", f"{name} too long ({len(v)} chars, max {spec['max_chars']})")
        return None
    if spec.get("lower_first"):
        v = lower_first(v)
    return v


def check_single_fragment(errors, name, v):
    if not scan_bad_punct(errors, name, v):
        return False
    if re.search(r"(?<=[.!?])\s+\S", v):
        fail(errors, "slot-format", f"{name} must be a single sentence (internal sentence break found)")
        return False
    return True


def check_sentences(errors, name, v, max_n):
    s = split_sentences(v)
    if "?" in v or "!" in v:
        fail(errors, "slot-format", f"{name} must not contain ? or !")
        return False
    if not (1 <= len(s) <= max_n):
        fail(errors, "slot-format", f"{name} must be 1-{max_n} sentences, got {len(s)}")
        return False
    return scan_bad_punct(errors, name, v)


def check_list_slot(errors, name, v, spec):
    lo, hi = spec.get("min_items", 2), spec.get("max_items", 3)
    imin, imax = spec.get("item_min_chars", 1), spec.get("item_max_chars", 100000)
    if not isinstance(v, list):
        fail(errors, "slot-type", f"{name} must be a JSON array")
        return []
    if not (lo <= len(v) <= hi):
        fail(errors, "slot-format", f"{name} needs {lo}-{hi} items, got {len(v)}")
        return []
    out = []
    for i, item in enumerate(v, 1):
        if not isinstance(item, str) or not item.strip():
            fail(errors, "slot-type", f"{name} item {i} must be a non-empty string")
            continue
        item = item.strip()
        if "\n" in item:
            fail(errors, "slot-format", f"{name} item {i} must be single-line")
            continue
        if item.rstrip().endswith((".", "?")):
            item = re.sub(r"[.!?,;:\s]+$", "", item)
        if not (imin <= len(item) <= imax):
            fail(errors, "slot-format", f"{name} item {i} must be {imin}-{imax} characters, got {len(item)}")
            continue
        if item.rstrip() != item or re.search(r"(?<=[.!?])\s+\S", item):
            fail(errors, "slot-format", f"{name} item {i} must be one sentence (internal sentence break)")
            continue
        if not scan_bad_punct(errors, name, item):
            continue
        out.append(strip_end(item))
    return out


def validate_slot(name, raw, errors):
    """slots.yaml-driven validator. Same pass/fail boundary and messages as
    the legacy per-slot if-chain; the constraints now come from data."""
    spec = SLOTS.get(name)
    if spec is None:
        fail(errors, "slot-format", f"{name}: slot not declared in slots.yaml")
        return None
    kind = spec.get("kind", "text")
    if kind == "list":
        return check_list_slot(errors, name, raw, spec)
    if kind == "object":
        keyspec = spec.get("keys") or {}
        if not isinstance(raw, dict):
            fail(errors, "slot-format", f"{name} must be an object ({', '.join(keyspec)})")
            return None
        missing = [k for k in keyspec if not str(raw.get(k, "")).strip()]
        if missing:
            fail(errors, "slot-format", f"{name} missing keys: " + ", ".join(missing))
            return None
        parts = {}
        for k, cspec in keyspec.items():
            v = validate_component(errors, k, raw.get(k), cspec or {})
            if v is None:
                return None
            parts[k] = v
        return str(spec.get("join", "")).format(**parts)
    v = raw
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        return None  # caller reports as missing
    v = v.strip()
    if "\n" in v:
        fail(errors, "slot-format", f"{name} must be single-line")
        return None
    if "{{" in v or "}}" in v:
        fail(errors, "slot-format", f"{name} contains placeholder braces")
        return None
    if spec.get("digit") and not re.search(r"\d", v):
        fail(errors, "slot-format", f"{name} must contain a digit")
        return None
    if spec.get("single_fragment") and not check_single_fragment(errors, name, v):
        return None
    if "max_sentences" in spec and not check_sentences(errors, name, v, spec["max_sentences"]):
        return None
    if spec.get("is_token") and not re.search(r"(?<![A-Za-z])is(?![A-Za-z])", v):
        fail(errors, "slot-format", f"{name} must read 'Term is plain-words definition' (is-token)")
        return None
    if spec.get("question"):
        if not scan_bad_punct(errors, name, v):
            return None
        if v.count("?") != 1:
            fail(errors, "slot-format", f"{name} must contain exactly one '?'")
            return None
        if spec.get("you_your") and not re.search(r"\b(you|your)\b", v, re.I):
            fail(errors, "slot-format", f"{name} must address the reader's experience (you/your)")
            return None
    # standalone banned-punct scan for text slots whose other checks do not
    # already scan (PERSON_CONTEXT / CONSENSUS_HOLDER legacy branch)
    if spec.get("no_punct") and not (spec.get("single_fragment") or "max_sentences" in spec or spec.get("question")):
        if not scan_bad_punct(errors, name, v):
            return None
    if spec.get("must_be_url"):
        if not re.fullmatch(r"https://\S+", v):
            fail(errors, "slot-format", f"{name} must be a bare https:// URL")
            return None
        if "app.notion.com" in v:
            fail(errors, "slot-format", f"{name} is a private app.notion.com URL")
            return None
        if spec.get("must_be_public") and not url_allowlisted(v, load_config()):
            if (load_config() or {}).get("url_allowlist"):
                fail(errors, "slot-format", f"{name} is not on the configured public allowlist")
            else:
                fail(errors, "slot-format", f"{name} must be a public notion.site URL or the KB mirror")
            return None
    if spec.get("max_chars") and len(v) > spec["max_chars"]:
        detail = spec.get("length_msg") or f"too long ({len(v)} chars, max {spec['max_chars']})"
        fail(errors, "slot-format", f"{name} {detail}")
        return None
    mn, mx = spec.get("min_chars"), spec.get("max_chars")
    if mn and len(v) < mn:
        if mx:
            fail(errors, "slot-format", f"{name} must be {mn}-{mx} chars, got {len(v)}")
        else:
            fail(errors, "slot-format", f"{name} must be at least {mn} chars, got {len(v)}")
        return None
    return strip_end(v) if spec.get("trim", "end") == "end" else v


def apply_list_join(items, mode):
    if mode == "clauses":
        return "; ".join([lower_first(items[0])] + [lower_first(i) for i in items[1:]])
    if mode == "pair":
        return "; ".join(lower_first(i) for i in items[:2])
    if mode == "para":
        return ". ".join([lower_first(items[0])] + [upper_first(i) for i in items[1:]])
    return ", ".join(lower_first(i) for i in items)  # commas


def parse_template_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    def as_list(s):
        return [x.strip() for x in re.findall(r"[A-Za-z0-9_\-]+", s)]
    fm["required_slots"] = as_list(fm.get("required_slots", ""))
    fm["stanzas"] = as_list(fm.get("stanzas", ""))
    floors = {}
    for k, v in re.findall(r"(\d+)\s*:\s*(\d+)", fm.get("word_floors", "")):
        floors[int(k)] = int(v)
    fm["word_floors"] = floors
    return fm, text[m.end():]


def refusal_missing(brief, pt):
    """Slots a post_types entry refuses on (V4: FAILURE_ROW). Sourced from
    data; the message text comes with it."""
    out = []
    for slot in (pt.get("refuse_unless") or []):
        keys = (SLOTS.get(slot) or {}).get("brief_keys") or [slot.lower()]
        if not any(brief.get(k) not in (None, "", [], {}) for k in keys):
            out.append(slot)
    return out


def render(variant, brief, errors, tdir, discovered):
    if variant not in VARIANTS and variant not in discovered:
        fail(errors, "template", f"unknown variant '{variant}'")
        return None
    tp = tdir / f"{variant}.md"
    if not tp.exists():
        _kind, pt = post_type_for_variant(P_TYPES, variant)
        if pt and pt.get("refuse_reason") and refusal_missing(brief, pt):
            fail(errors, "template-unavailable", str(pt["refuse_reason"]))
        else:
            fail(errors, "template", f"template file missing: {tp}")
        return None
    fm, body = parse_template_frontmatter(tp.read_text(encoding="utf-8"))
    required = fm.get("required_slots", [])

    # presence check first: report every missing required slot at once
    values = {}
    ok = True
    for slot in required:
        spec = SLOTS.get(slot)
        if spec is None:
            fail(errors, "slot-format", f"{slot}: slot not declared in slots.yaml")
            ok = False
            continue
        keys = spec.get("brief_keys")
        raws = {k: brief.get(k) for k in keys}
        empty = [k for k in keys if raws[k] in (None, "", [], {})]
        if empty:
            if len(empty) == len(keys):
                fail(errors, "missing-slots", "; ".join(f"{slot} (brief key: {k})" for k in keys))
            else:
                fail(errors, "missing-slots", "; ".join(f"{slot}: brief key '{k}' empty while sibling keys present" for k in empty))
            ok = False
            continue
        kind = spec.get("kind", "text")
        if kind == "object":
            keyspec = spec.get("keys") or {}
            if keyspec and all(k in keyspec for k in keys):
                # component-style object: each brief key is a string component
                # (GAP_STAT_PAIR: gap_stat_a + gap_stat_b joined with a bridge)
                parts = {}
                for k in keys:
                    v = validate_component(errors, k, brief.get(k), keyspec.get(k) or {})
                    if v is None:
                        ok = False
                        parts = None
                        break
                    parts[k] = v
                if parts is not None:
                    values[slot] = str(spec.get("join", "")).format(**parts)
            else:
                # dict-style object (FAILURE_ROW): one brief key carries all keys
                val = validate_slot(slot, brief.get(keys[0]), errors)
                if val is None:
                    ok = False
                else:
                    values[slot] = val
            continue
        raw = raws[keys[0]]
        val = validate_slot(slot, raw, errors)
        if val is None or (isinstance(val, list) and not val):
            ok = False
            continue
        values[slot] = val
    if errors or not ok:
        return None

    # link slot is written as the bare final line; strip it before substitution
    link = values.pop("LINK", None)
    if not link:
        fail(errors, "missing-slots", "LINK (brief key: link)")
        return None

    # generic list-token modes: any list slot may carry |clauses/|para/|pair
    list_slots = [s for s, spec in SLOTS.items() if spec.get("kind") == "list"]
    for slot in list_slots:
        if slot not in values:
            continue
        items = values[slot]
        toks = re.findall(r"\{\{" + slot + r"(?:\|(" + "|".join(LIST_MODES) + r"))?\}\}", body)
        for mod in toks:
            if slot != "STORY_EXAMPLES":
                mode = mod or (SLOTS[slot].get("default_mode") or "commas")
            else:
                mode = "clauses" if mod else ("para" if len(items) == 3 else "pair")
            if mode == "pair" and len(items) != 2:
                fail(errors, "slot-format", f"{slot} modifier |pair needs exactly 2 items, got {len(items)}")
                ok = False
        if not ok:
            return None

        def _repl(m, slot=slot, items=items):
            mod = m.group(1)
            if slot == "STORY_EXAMPLES":
                mode = "clauses" if mod else ("para" if len(items) == 3 else "pair")
            else:
                mode = mod or (SLOTS[slot].get("default_mode") or "commas")
            return apply_list_join(items, mode)
        pattern = r"\{\{" + slot + r"(?:\|(" + "|".join(LIST_MODES) + r"))?\}\}"
        body = re.sub(pattern, _repl, body)

    for slot, val in values.items():
        if slot not in list_slots:
            body = body.replace("{{" + slot + "}}", str(val))

    # residue + final scans: nothing double-braced, nothing banned may survive
    if "{{" in body or "}}" in body:
        hits = re.findall(r"\{\{[^}]*\}\}", body)
        fail(errors, "unrendered-slot", ", ".join(dict.fromkeys(hits)))
    if any(bad in body for bad in BAD_PUNCT):
        fail(errors, "slot-format", "assembled post contains banned punctuation (em dash, spaced double hyphen or !)")
    if errors:
        return None
    return body.rstrip("\n") + "\n\n" + link + "\n"


# ---------------- post-type selection engine -------------------------------
def filled_keys(brief, keys):
    return all(brief.get(k) not in (None, "", [], {}) for k in keys)


def filled_slots(brief):
    out = set()
    for name, spec in SLOTS.items():
        if filled_keys(brief, spec.get("brief_keys") or []):
            out.add(name)
    return out


def parse_situations(situations_arg, brief):
    flags = {
        "has_link": filled_keys(brief, ["link"]),
        "has_failure_row": filled_keys(brief, (SLOTS.get("FAILURE_ROW") or {}).get("brief_keys") or ["failure_row"]),
        "has_definition": filled_keys(brief, (SLOTS.get("DEFINITION") or {}).get("brief_keys") or ["definition"]),
        "has_gap_pair": filled_keys(brief, ["gap_stat_a"]) and filled_keys(brief, ["gap_stat_b"]),
        "news_hook": False,
        "debate_active": False,
    }
    for part in re.split(r"[,\s]+", (situations_arg or "").strip()):
        if not part:
            continue
        k, _, v = part.partition("=")
        if k not in flags:
            raise ValueError("unknown situation '%s' (known: %s)" % (k, ", ".join(flags)))
        lv = v.strip().lower()
        if lv not in ("true", "false", "1", "0"):
            raise ValueError("situation '%s' needs true/false" % k)
        flags[k] = lv in ("true", "1")
    return flags


def lever_triggered(lever, lw, filled, flags, pt):
    if lever == "link_penalty":
        return bool(flags.get("has_link")) and bool(pt.get("commentary_type"))
    slots = lw.get("slots") or []
    match = lw.get("match", "any")
    if match == "all":
        return bool(slots) and all(s in filled for s in slots)
    return any(s in filled for s in slots)


def rank_post_types(brief, flags, used):
    filled = filled_slots(brief)
    ranked, not_viable, fill_gaps = [], {}, {}
    for kind, pt in P_TYPES.items():
        requires = pt.get("requires") or []
        requires_alt = pt.get("requires_alt") or None
        link_required = pt.get("link_required", True) is not False
        missing = [s for s in requires if s not in filled]
        if requires_alt and not any(s in filled for s in requires_alt):
            missing.append("one of: " + ", ".join(requires_alt))
        if link_required and "LINK" in SLOTS:
            if not filled_keys(brief, SLOTS["LINK"].get("brief_keys") or ["link"]):
                missing.append("LINK (brief key: link)")
            elif not url_allowlisted(str(brief.get("link") or ""), load_config()):
                missing.append("LINK (brief key: link, off the configured public allowlist)")
        gaps = [s for s in (pt.get("recommended") or requires) if s not in filled]
        total, lines = 0.0, []
        for lever, lw in WEIGHTS.items():
            tw = (lw.get("types") or {}).get(kind)
            if not tw or "base" not in tw:
                continue
            if not lever_triggered(lever, lw, filled, flags, pt):
                continue
            base = float(tw["base"])
            contrib = base
            applied = []
            for flag, mult in (tw.get("situations") or {}).items():
                if flags.get(flag):
                    contrib *= float(mult)
                    applied.append(f"{flag}x{mult:g}")
            total += contrib
            lines.append("%s %+.3f%s (slots: %s)" % (
                lever, contrib, (" [" + ", ".join(applied) + "]") if applied else "",
                "+".join(lw.get("slots") or ["condition"])))
        fill_gaps[kind] = gaps
        if missing:
            not_viable[kind] = {"missing_required": missing, "fill_gaps": gaps,
                                "score": round(total, 4)}
        else:
            ranked.append({
                "kind": kind, "variant": pt.get("variant"), "score": round(total, 4),
                "explain": "%s: %.4f = %s" % (kind, round(total, 4),
                                              " + ".join(ln.split(" (")[0] for ln in lines) if lines else "no filled-weighted lever"),
                "explain_lines": lines,
            })
    ranked.sort(key=lambda r: (-r["score"], r["kind"]))
    if used:
        used_kinds = set()
        for token in re.split(r"[,\s]+", str(used).strip()):
            if not token:
                continue
            kind_used, _pt = post_type_for_variant(P_TYPES, token.upper())
            used_kinds.add(kind_used or token)
        # one stable pass: each used kind demotes one effective rank step
        for i in range(len(ranked) - 1):
            if ranked[i]["kind"] in used_kinds:
                ranked[i], ranked[i + 1] = ranked[i + 1], ranked[i]
        for r in ranked:
            if r["kind"] in used_kinds:
                r["demoted"] = True
    return ranked, not_viable, fill_gaps


def cmd_select(args, brief):
    cfg = load_config()
    tdir = templates_dir(cfg)
    flags = parse_situations(args.situations, brief)
    ranked, not_viable, fill_gaps = rank_post_types(brief, flags, args.used_kinds)
    out = {
        "ok": True, "mode": "select", "brief": brief.get("title"),
        "situations": flags, "situations_source": "derived-from-brief + overrides",
        "top_pick": (ranked[0]["kind"] if ranked else None),
        "top_variant": (ranked[0].get("variant") if ranked else None),
    }
    ranked_out = []
    for i, r in enumerate(ranked, 1):
        entry = {"rank": i, "kind": r["kind"], "variant": r["variant"], "score": r["score"]}
        if r.get("demoted"):
            entry["used_demoted"] = True
        if args.explain:
            entry["explain"] = r["explain"]
            entry["explain_lines"] = r["explain_lines"]
        entry["fill_gaps"] = fill_gaps.get(r["kind"]) or []
        ranked_out.append(entry)
    out["ranked"] = ranked_out
    out["not_viable"] = {k: v["missing_required"] for k, v in not_viable.items()}
    if args.explain:
        out["not_viable_reasons"] = not_viable
    out["fill_gaps"] = {k: v for k, v in fill_gaps.items() if v}
    out["note"] = ("selection lists kinds and never bypasses gates: render the chosen "
                   "kind's variant through the normal pipeline; on a gate failure fall back "
                   "manually to the next ranked kind")
    text = json.dumps(out, sort_keys=True)
    if args.out:
        p = Path(args.out)
        if p.parent and str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    print(text)
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", help="render variant: V1..V5 or a registered V*.md skeleton")
    ap.add_argument("--select", action="store_true", help="post-type selection mode (ignores --variant)")
    ap.add_argument("--situations", help="select mode: comma list of situation overrides k=true|false")
    ap.add_argument("--explain", action="store_true", help="select mode: include per-kind score breakdown lines")
    ap.add_argument("--used-kinds", dest="used_kinds", help="select mode: comma list of used kinds/variants demoted one rank")
    ap.add_argument("--brief", required=True, help="brief JSON")
    ap.add_argument("--out", help="render mode: rendered post path (required, written only on success); select mode: optional JSON path")
    a = ap.parse_args()

    global SLOTS, P_TYPES, WEIGHTS
    cfg = load_config()
    tdir = templates_dir(cfg)
    SLOTS = load_registry(tdir)
    P_TYPES = load_post_types(tdir)
    WEIGHTS = load_weights(tdir)
    discovered = sorted(p.stem for p in tdir.glob("V*.md")) if tdir.is_dir() else []

    try:
        brief = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"ok": False, "out": None, "errors": [f"brief-unreadable: {e}"]}))
        sys.exit(1)
    if not isinstance(brief, dict):
        print(json.dumps({"ok": False, "out": None, "errors": ["brief-unreadable: top level must be a JSON object"]}))
        sys.exit(1)

    if a.select:
        if a.variant:
            print(json.dumps({"ok": False, "out": None, "errors": ["usage: --select ignores --variant"]}))
            sys.exit(1)
        cmd_select(a, brief)  # exits

    if not a.variant or not a.out:
        ap.error("render mode requires --variant and --out (or use --select)")

    errors = []
    out_text = render(a.variant.strip().upper(), brief, errors, tdir, discovered)
    contract_warn = [k for k in CONTRACT_KEYS if brief.get(k) in (None, "",)]
    if errors or out_text is None:
        print(json.dumps({"ok": False, "out": None, "errors": errors}))
        sys.exit(1)
    p = Path(a.out)
    if p.parent and str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out_text, encoding="utf-8")
    body = out_text.rsplit("\n\n", 1)[0]
    words = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", body))
    print(json.dumps({"ok": True, "out": str(p), "variant": a.variant.upper(),
                      "words": words, "contract_warnings": contract_warn}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "out": None, "errors": [f"internal: {e}"]}))
        sys.exit(1)
