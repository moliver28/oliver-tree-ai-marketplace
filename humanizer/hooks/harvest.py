#!/usr/bin/env python3
"""harvest.py: the passive harvest hook (wave G6, consent-gated, default OFF).

Accepted final drafts flow into the user's reference pool automatically,
and every derived measurement rebuilds mechanically afterwards: ZERO model
calls, no distill pass, no network. The hook never talks to any model and
never transmits anything: accepted drafts are stored ONLY in the user's own
local learned-state chain (the reference pool under the VOICE_REFERENCE_DIR
chain), and nothing harvested ever lands in the repository, the shipped
payload, a test, or CI.

Consent gate (both halves are required; the flag never ships enabled):
the hook runs only when the settings file carries BOTH

1. the flag: "harvest": {"enabled": true, ...} in
   <learned>/state/setup.json (the same settings file /voice-setup writes),
2. the accepted input: "accepted_dir": "<directory of accepted drafts>"
   plus the optional "accepted_glob" (default "*.md") and the optional
   "situation" tag stored with the harvested vectors.

With the flag off, absent, or without the accepted-input config the hook
does nothing, costs nothing, and logs nothing: it reads one settings file
with the standard library and exits 0. Turning the flag on means: accepted
drafts get stored in the user's own local reference pool. They are never
transmitted anywhere.

Wiring (the platform points its hooks at this script; it never
re-implements the pool append):
- Session end: run the script with no arguments; it reads the configured
  accepted_dir through accepted_glob and harvests every new draft.
- Document acceptance: run the script with --file <path> right after the
  user accepts a draft; the flag and the accepted_dir config still apply
  (the file must live under the configured directory, so acceptance stays
  inside what the user consented to harvest).

Append (Unit 2): one pool record per accepted draft, exactly the existing
pool layout: <sha256(text)[:16]>.txt beside <same-id>.json (the vector).
An exact sha256 duplicate is skipped silently (idempotent append). An
accepted draft under the battery's 500-word document floor is skipped
with one line: the band math owns that floor. Every appended vector
gains the provenance row: source "harvest", the UTC timestamp, the word
count, and the situation tag (from the settings config when set). The
script itself contains no document text and never touches repository
files.

Mechanical rebuild (Unit 3): after pool growth the hook calls the shared
rebuild_pool() body of learn/regenerate.py (the data-contract machinery):
stale pool vectors recompute from the stored text and the bands rebuild
from the refreshed vectors into <learned>/state/voice-bands.json. Pure
compute over the stored pool: no model tokens, no distill pass, no network
model calls, deterministic for identical pool state (stable iteration
order, pinned sort keys). If the regenerate pass or the derived rows are
absent (older install), the hook prints one notice line and skips the
rebuild: fail-open, never an error.

Band refresh (Unit 4, advisory-first): the refreshed bands in
voice-bands.json are advisory rows and update silently (the
calibration-before-fail law). The ONLY band kind that can change a fail
line is a budget-override band ('aphorism', see
learn/voice_battery_core.py resolve_budget). The candidate follows the
athena methodology ruling (binding Q1, 2026-11-28): the observed pool
maximum shrunk toward the active budget with the codebase's own k/(k+5)
shape (SHRINK_K = 5, the voice_setup N0=5 law), rounded UP, never below
1, per grain derived independently; the bare maximum is disapproved, and
the raw maximum rides the pending row beside the shrunk number. A
refreshed budget candidate never lands silently: the candidate and the
active numbers are written as pending rows into
<learned>/state/band-approvals.json with a plain-words note (pool-size
tier, provenance line, what changed and by how much), and the old budget
stays active. The explicit command below promotes them:

    python3 humanizer/hooks/harvest.py --approve-bands

--approve-bands writes the approved numbers into the runtime state file
(<HERMES_HOME>/state/voice-rules.json, path override VOICE_RULES_STATE)
under the source name "harvest-bands": a DATA write per the issue #5 data
contract (learning commands write only data, never gate code). Until that
explicit approval the old budget stays active. Approval state lives in
the learned-state data files; nothing pending ever reaches the gate.

Exit codes: 0 = the run ended fine (flag off, nothing new, duplicate skip,
fail-open skip lines: all defined, none failures); 2 = bad usage (a
missing --file path, or a --file outside the consented accepted_dir).
Standard library only; the learn machinery loads lazily, after the
consent gate.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/hooks/
PLUGIN_DIR = HERE.parent                        # humanizer/

SETTINGS_FLAG = "harvest"        # the settings key in <learned>/state/setup.json
PENDING_FILE = "band-approvals.json"   # pending band rows in the learned state
BAND_SOURCE = "harvest-bands"    # the runtime-state source approved bands land in
DEFAULT_GLOB = "*.md"
# The battery's own document floor (voice_setup: a document enters the band
# math at 500 or more words). A shorter accepted draft would fall under the
# battery row floors, so the hook skips it with one line instead of storing
# rows the band derivation cannot use.
BATTERY_FLOOR_WORDS = 500
# The codebase's own shrinkage constant (voice_setup.py N0=5, the k/(k+5)
# situation-factor law, owner-approved 2026-11-27). The budget candidate
# borrows the same pinned shape per the athena methodology ruling (Q1,
# 2026-11-28): shrink the pool maximum toward the active budget, round up,
# floor 1, and report the raw maximum beside it.
SHRINK_K = 5


def learned_dir():
    """Per-user learned-artifact directory (VOICE_LEARNED_DIR overrides),
    the same contract as hooks/voice_tells.py learned_dir()."""
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def settings_path():
    return learned_dir() / "state" / "setup.json"


def read_settings():
    """The setup settings the /voice-setup command owns. Read-only; a
    missing or unreadable file reads {} and stays silent."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def harvest_config():
    """The harvest settings block, or None when absent/misshaped."""
    cfg = read_settings().get(SETTINGS_FLAG)
    return cfg if isinstance(cfg, dict) else None


def consented(cfg):
    """The consent gate: the flag is exactly true AND the accepted input is
    configured. Anything else reads as OFF (no run, no cost, no log)."""
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return False
    return bool(cfg.get("accepted_dir"))


def _load_plugin(relpath, name):
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def doc_id(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def resolve_files(cfg, file_arg):
    """The accepted documents of one run: the explicit --file (it must sit
    under the consented accepted_dir, so the hook never widens its own
    consent), or the configured directory scanned through accepted_glob in
    sorted order. Returns (files, error_line)."""
    root = Path(str(cfg.get("accepted_dir"))).expanduser()
    pattern = str(cfg.get("accepted_glob") or DEFAULT_GLOB)
    if file_arg:
        p = Path(file_arg).expanduser().resolve()
        try:
            inside = p.is_relative_to(root.expanduser().resolve())
        except AttributeError:
            inside = str(p).startswith(str(root.expanduser().resolve()))
        if not root.is_dir():
            return None, "harvest: the configured accepted_dir is missing (%s); nothing harvested" % root
        if not inside:
            return None, "usage: --file must stay inside the consented accepted_dir (%s)" % root
        if not p.is_file():
            return None, "usage: --file is not a readable file: %s" % p
        return [p], None
    if not root.is_dir():
        return None, "harvest: the configured accepted_dir is missing (%s); nothing harvested" % root
    return sorted(f for f in root.glob(pattern) if f.is_file()), None


def append_pool(vs, cfg, files):
    """Unit 2: append every not-yet-stored draft to the pool with its
    provenance row; exact sha256 duplicates skip silently. Drafts under
    the battery's 500-word document floor are skipped with one line (the
    band math owns that floor). Returns the number of appended documents;
    the context step fails open (a pool holding under-floor documents from
    an older install skips the append with a notice, never an error)."""
    new = []
    short = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        if not text:
            continue
        if len(vs.WORD_RE.findall(text)) < BATTERY_FLOOR_WORDS:
            short += 1
            continue
        if (vs.pool_dir() / (doc_id(text) + ".txt")).is_file():
            continue
        new.append(text)
    if short:
        print("harvest: %d draft(s) under the %d-word battery floor were not harvested"
              % (short, BATTERY_FLOOR_WORDS))
    if not new:
        return 0
    situation = cfg.get("situation") or None
    grown = [t for t, _v in vs.pool_read()] + new   # stable order: pool id order, then sorted files
    try:
        ref, window = vs.pool_context(grown)
    except Exception as e:
        print("harvest: append skipped (the pool context did not compute: %s); "
              "nothing was stored" % (repr(e)[:80],))
        return 0
    now = datetime.now(timezone.utc).isoformat()
    for text in new:
        acc = vs.vb.scan(text, phrases=True, tri=False)
        row = vs.vb.values(acc, ref=ref, window=window)
        provenance = {"source": "harvest", "harvested_at": now,
                      "words": acc["n"], "situation": situation}
        vs.pool_store(text, situation, row, provenance=provenance)
    return len(new)


def shrink_statistic(observed, default, n):
    """The approved pool-derived budget candidate (athena methodology
    ruling, binding Q1, 2026-11-28): the pool maximum shrunk toward the
    active budget with the codebase's own k/(k+5) shape, then rounded UP
    to the whole number the resolver needs, never below 1:
    candidate = max(1, ceil((n/(n+5))*observed + (5/(n+5))*default)).
    The bare maximum is disapproved as the derivation statistic (an order
    statistic that one unusual document moves); the shrink keeps the
    "your own practice, at your scale" semantics with the plugin's own
    pinned constant. Pure; deterministic; zero model calls."""
    w = n / (n + SHRINK_K)
    return max(1, math.ceil(w * float(observed) + (1.0 - w) * float(default)))


def budget_candidates(core, pool_texts, default_section, default_piece):
    """Unit 4 candidate derivation, mechanical over the stored pool, per
    grain derived independently: the observed per-section and per-piece
    kicker-shape maxima across the accepted drafts, then the ruling's
    shrink of each toward its active default. Returns (observed_section,
    observed_piece, candidate_section, candidate_piece, sections_seen).
    Deterministic: pool id order in, plain maxima out, pure shrink math."""
    per_section = 0
    per_piece = 0
    sections = 0
    for text in pool_texts:
        counts = core.aphorism_section_counts(text)
        per_section = max([per_section] + [cnt for _name, cnt in counts])
        per_piece = max(per_piece, sum(cnt for _name, cnt in counts))
        sections += len(counts)
    n = len(pool_texts)
    return (per_section, per_piece,
            shrink_statistic(per_section, default_section, n),
            shrink_statistic(per_piece, default_piece, n),
            sections)


def budget_note_tier(n):
    """The plain-words uncertainty line for the pending note, selected by
    the pool size (athena ruling Q3, 2026-11-28). Three tiers, no
    confidence percentages: at a small pool the honest wording is a start
    value; at a large one, nearly all. ASD-STE100: short sentences."""
    if n < 10:
        return ("Only %d accepted drafts are in the pool. This budget is a start value. "
                "It will move as you accept more drafts." % n)
    if n < 30:
        return ("The pool has %d accepted drafts. This budget tracks most of your "
                "accepted drafts." % n)
    return ("The pool has %d accepted drafts. This budget tracks nearly all of your "
            "accepted drafts." % n)


def read_pending():
    p = learned_dir() / "state" / PENDING_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return p, []
    rows = data.get("pending") if isinstance(data, dict) else None
    return p, (rows if isinstance(rows, list) else [])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="harvest.py",
        description="Passive harvest hook (default OFF): append accepted drafts to the "
                    "local reference pool, rebuild the derived measurements mechanically, "
                    "and hold fail-affecting band changes for explicit approval.")
    parser.add_argument("--file", default=None, metavar="PATH",
                        help="harvest one accepted document (document-acceptance wiring; "
                             "the consent settings still apply)")
    parser.add_argument("--approve-bands", action="store_true",
                        help="promote the pending budget-band rows to active (explicit "
                             "user command; a DATA write into the runtime state file)")
    args = parser.parse_args(argv)
    if args.approve_bands:
        return approve_bands()

    cfg = harvest_config()
    if not consented(cfg):
        return 0                      # flag off or no config: no-op, silent, zero cost
    files, error_line = resolve_files(cfg, args.file)
    if error_line:
        print(error_line, file=sys.stderr)
        return 2 if args.file else 0  # a consent/config miss fails open; bad usage exits 2
    if not files:
        return 0                      # nothing accepted in this window: silent

    vs = _load_plugin(os.path.join("learn", "voice_setup.py"), "harvest_voice_setup")
    appended = append_pool(vs, cfg, files)
    if not appended:
        return 0                      # exact duplicates: idempotent skip, silent
    print("harvest: %d accepted document(s) appended to the reference pool" % appended)

    # Unit 3: the mechanical rebuild (shared regenerate body; zero model calls)
    try:
        reg = _load_plugin(os.path.join("learn", "regenerate.py"), "harvest_regenerate")
        print("harvest rebuild: %s" % reg.rebuild_pool())
    except Exception as e:
        print("harvest: rebuild skipped (%s); the stored bands stay at the last rebuild"
              % (repr(e)[:100],))

    # Unit 4: advisory-first band refresh with the re-approval gate
    try:
        notice = refresh_bands(vs)
    except Exception as e:
        notice = None
        print("harvest: band refresh skipped (%s)" % (repr(e)[:100],))
    if notice:
        print(notice)
    return 0


def refresh_bands(vs):
    """Compare the grown pool's budget candidates with the active budget.
    Advisory rows need no approval (the rebuild already refreshed them
    silently); a changed budget-override band lands as a pending row only.
    The candidate follows the athena methodology ruling (binding Q1,
    2026-11-28): the observed maximum shrunk toward the active budget, the
    raw maximum reported beside it, the note carrying the pool-size tier."""
    core = _load_plugin(os.path.join("learn", "voice_battery_core.py"), "harvest_battery_core")
    vt = _load_plugin(os.path.join("hooks", "voice_tells.py"), "harvest_voice_tells")
    pool_texts = [t for t, _v in vs.pool_read()]
    band = (vt.effective_rules().get("bands") or {}).get("aphorism") or {}
    act_s, act_p = core.resolve_budget(band)
    obs_s, obs_p, cand_s, cand_p, sections = budget_candidates(
        core, pool_texts, act_s, act_p)
    n = len(pool_texts)
    changes = {}
    if cand_s != act_s:
        changes["max_per_section"] = {"active": act_s, "candidate": cand_s}
    if cand_p != act_p:
        changes["max_per_piece"] = {"active": act_p, "candidate": cand_p}

    pending_path, rows = read_pending()
    row = next((r for r in rows if isinstance(r, dict) and r.get("band") == "aphorism"), None)
    kept = [r for r in rows if not (isinstance(r, dict) and r.get("band") == "aphorism")]
    if not changes:
        if len(kept) != len(rows):    # a stale pending row resolves itself
            _write_pending(pending_path, kept)
            return ("harvest: the pending band change matches the pool now; "
                    "the pending row was dropped")
        return None
    changed_bits = sorted(changes)
    signature = (tuple(sorted((k, changes[k]["active"], changes[k]["candidate"])
                              for k in changed_bits)))
    if row and isinstance(row.get("changes"), dict):
        old_sig = tuple(sorted((k, (row["changes"].get(k) or {}).get("active"),
                                (row["changes"].get(k) or {}).get("candidate"))
                               for k in changed_bits
                               if k in row["changes"]))
        if old_sig == signature and len(row["changes"]) == len(changes):
            kept.append(row)          # identical pending row: keep the first timestamp
            return pending_notice(kept)
    parts = []
    if "max_per_section" in changes:
        parts.append("the shrunk candidate is %d kicker shapes per section against the "
                     "active budget of %d (the raw pool maximum is %d)"
                     % (changes["max_per_section"]["candidate"],
                        changes["max_per_section"]["active"], obs_s))
    if "max_per_piece" in changes:
        parts.append("the shrunk candidate is %d kicker shapes per piece against the "
                     "active budget of %d (the raw pool maximum is %d)"
                     % (changes["max_per_piece"]["candidate"],
                        changes["max_per_piece"]["active"], obs_p))
    new_row = {
        "band": "aphorism",
        "changes": changes,
        "note": ("%s Your budget comes from your accepted drafts only. The pool suggests "
                 "a budget change: %s. Approve to make the gate use these numbers, or "
                 "leave it to keep the active budget."
                 % (budget_note_tier(n), "; ".join(parts))),
        "derived_from": {
            "pool_docs": n,
            "pool_sections": sections,
            "observed_max_per_section": obs_s,
            "observed_max_per_piece": obs_p,
            "method": "shrunken largest kicker-shape count toward the active budget "
                      "(k/(k+5), k=5)",
        },
        "created": datetime.now(timezone.utc).isoformat(),
    }
    kept.append(new_row)
    _write_pending(pending_path, kept)
    return pending_notice(kept)


def pending_notice(rows):
    n = sum(1 for r in rows if isinstance(r, dict) and r.get("band") == "aphorism")
    if not n:
        return None
    return ("harvest: %d band change(s) wait for approval; a fail-line budget never "
            "moves without you (run hooks/harvest.py --approve-bands)" % n)


def _write_pending(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps({"format": 1, "pending": rows},
                              indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def approve_bands():
    """The explicit promotion: pending budget rows become active band data
    in the runtime state file (source "harvest-bands"). Learning commands
    write only data; until this call the old budget stays active."""
    vt = _load_plugin(os.path.join("hooks", "voice_tells.py"), "harvest_voice_tells")
    pending_path, rows = read_pending()
    promote = [r for r in rows if isinstance(r, dict) and r.get("band") == "aphorism"]
    if not promote:
        print("harvest: no pending band changes")
        return 0
    st_path = vt.state_path()
    try:
        data = json.loads(st_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not (isinstance(data, dict) and isinstance(data.get("sources"), dict)):
        data = {"format": 1, "sources": {}}
    sources = data["sources"]
    body = sources.get(BAND_SOURCE)
    body = body if isinstance(body, dict) else {}
    bands = body.get("bands")
    bands = bands if isinstance(bands, dict) else {}
    aph = bands.get("aphorism")
    aph = aph if isinstance(aph, dict) else {}
    for r in promote:
        for key, ch in sorted((r.get("changes") or {}).items()):
            if not isinstance(ch, dict) or "candidate" not in ch:
                continue
            aph[key] = ch["candidate"]
            print("harvest: approved aphorism.%s = %s (was %s); the gate uses the new "
                  "budget at the next scan"
                  % (key, ch["candidate"], ch.get("active")))
    bands["aphorism"] = aph
    body["bands"] = bands
    sources[BAND_SOURCE] = body
    vt._atomic_write(st_path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    _write_pending(pending_path, [r for r in rows if r not in promote])
    return 0


if __name__ == "__main__":
    sys.exit(main())
