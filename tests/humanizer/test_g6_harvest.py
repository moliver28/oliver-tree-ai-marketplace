#!/usr/bin/env python3
"""Contract tests for the passive harvest loop (wave G6): consent-gated
accepted-draft pool growth with a mechanical, zero-model rebuild.

Run: python3 tests/humanizer/test_g6_harvest.py
Exit 0 = every contract gate green.

Sections:
A. Consent gate (default OFF): flag absent / false / half-configured ->
   silent no-op with zero writes; a short accepted draft skips with one
   line; a --file outside the consented accepted_dir is bad usage (2).
B. Append (Unit 2): the existing pool layout (sha256-keyed text beside
   the vector), the provenance row (source harvest, timestamp, words,
   situation tag), the silent idempotent duplicate skip.
C. Mechanical rebuild (Unit 3): the shared regenerate body runs with
   zero model calls and is deterministic: the same pool state produces
   byte-identical derived artifacts, across runs and across processes.
D. Advisory-first band refresh (Unit 4a): candidates that match the
   active budget write no pending rows and never touch the runtime
   state file; the advisory bands refresh silently.
E. Re-approval gate (Unit 4b): a budget candidate that would change a
   fail line lands ONLY as a pending row (candidate + active numbers,
   plain-words note); the gate keeps the old fail line until the
   explicit --approve-bands; approval writes the band under the
   harvest-bands source, clears the pending row, and the gate then uses
   the new budget.
F. Privacy: harvested text never enters the repository (a unique marker
   in the harvested fixture appears in no tracked file; no pool or
   band-approvals payload is tracked anywhere).
G. resolve_budget unit rules, stdlib-only module imports, and the gate
   pass-line byte-pin without bands.

Every fixture is synthetic text generated in this file (about 560 words
per accepted draft) written to temp directories only: nothing harvested
ever lands in the repo, the payload, or CI.
"""
import ast
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent      # tests/humanizer/
REPO_ROOT = HERE.parent.parent                     # the repository root
PLUGIN_DIR = REPO_ROOT / "humanizer"               # humanizer/
HARVEST = PLUGIN_DIR / "hooks" / "harvest.py"
GATE = PLUGIN_DIR / "hooks" / "gate.py"

fails = []


def ck(cond, name, detail=""):
    if cond:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}" + (f" ({detail})" if detail else ""))
        fails.append(name)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_FILLER = ("The scanner reads the stored rules before the run starts. The report shows "
           "three things: counts, ranges, and notes. We keep the numbers in one file so "
           "the second pass reads the same values. The writer keeps sentences short and "
           "each paragraph carries three sentences at most. The review board reads every "
           "entry from the first page to the last one.")


def draft(kickers=0, marker=None):
    """Deterministic accepted draft of about 560 words; kickers = the
    kicker shapes in the opening section; marker = one unique token that
    privacy section F must not find in any tracked repo file."""
    parts = []
    if kickers >= 2:
        parts.append("Ship it.\n\nNo pain, no gain.")
    elif kickers == 1:
        parts.append("Ship it.")
    body = []
    n = 0
    while n < 560:
        chunk = _FILLER + (("%s sits in one sentence of the stored draft." % marker)
                           if marker and n == 0 else "")
        body.append(chunk)
        n += len(chunk.split())
    parts.append("\n\n".join(body))
    return "\n\n".join(parts)


MARKER = "zxqharvest" + "marker2026"   # runtime join: the literal never sits in this file

core = load_module("g6_battery_core", PLUGIN_DIR / "learn" / "voice_battery_core.py")

# A+E helper: run the hook in one isolated learned-state world -------------------


def harvest_world():
    """One temp world: the learned dir, the accepted dir, the env."""
    td = tempfile.TemporaryDirectory()
    tdp = pathlib.Path(td.name)
    learned = tdp / "learned"
    (learned / "state").mkdir(parents=True)
    accepted = tdp / "accepted"
    accepted.mkdir()
    env = {**os.environ, "VOICE_LEARNED_DIR": str(learned),
           "HERMES_HOME": str(tdp / "hermes"),
           "VOICE_GATE_LOG": str(tdp / "gate.log")}

    def run(*extra, gate_env=False):
        e = env
        script = HARVEST
        stdin = None
        if gate_env:
            e = {k: v for k, v in env.items() if k != "VOICE_RULES_STATE"}
            script = GATE
            stdin = "Ship it.\n\nNo pain, no gain."
        return subprocess.run([sys.executable, "-I", str(script)] + list(extra),
                              input=stdin, capture_output=True, text=True, env=e)

    return td, tdp, learned, accepted, env, run


# A. consent gate: silent no-op with zero writes ---------------------------------
td_a, tdp_a, learned_a, acc_a, env_a, run_a = harvest_world()
try:
    r = run_a()
    files = sorted(str(p.relative_to(learned_a)) for p in learned_a.rglob("*"))
    ck(r.returncode == 0 and r.stdout == "" and r.stderr == "" and files == ["state"],
       "consent: flag absent -> exit 0, silent, zero writes", "%r %r %s" % (r.stdout, r.stderr, files))
    (learned_a / "state" / "setup.json").write_text(json.dumps(
        {"harvest": {"enabled": False, "accepted_dir": str(acc_a)}}))
    r = run_a()
    ck(r.returncode == 0 and r.stdout == "" and r.stderr == "",
       "consent: enabled false -> silent no-op")
    (learned_a / "state" / "setup.json").write_text(json.dumps({"harvest": {"enabled": True}}))
    r = run_a()
    ck(r.returncode == 0 and r.stdout == "" and r.stderr == "" and not (learned_a / "pool").exists(),
       "consent: enabled without accepted input -> silent no-op, no pool dir created")
    (learned_a / "state" / "setup.json").write_text(json.dumps({
        "harvest": {"enabled": True, "accepted_dir": str(acc_a),
                    "accepted_glob": "*.md", "situation": "blog"}}))
    (acc_a / "short.md").write_text("Ship it.\n\nToo short to harvest.")
    r = run_a("--file", str(acc_a / "short.md"))
    ck(r.returncode == 0 and "battery floor" in r.stdout and not (learned_a / "pool").exists(),
       "consent: a short draft skips with the floor line, nothing stored", r.stdout)
    outside = tdp_a / "outside.md"
    outside.write_text(draft())
    r = run_a("--file", str(outside))
    ck(r.returncode == 2 and "accepted_dir" in r.stderr,
       "consent: --file outside the consented dir is bad usage (exit 2)", r.stderr)
finally:
    td_a.cleanup()

# B+C+D+E. the full loop in one world --------------------------------------------
td_b, tdp_b, learned_b, acc_b, env_b, run_b = harvest_world()
try:
    (learned_b / "state" / "setup.json").write_text(json.dumps({
        "harvest": {"enabled": True, "accepted_dir": str(acc_b),
                    "accepted_glob": "*.md", "situation": "blog"}}))
    d1 = acc_b / "draft1.md"
    d1.write_text(draft(kickers=2, marker=MARKER))

    # B. append: pool layout + provenance row
    r = run_b("--file", str(d1))
    pool = learned_b / "pool"
    txts = sorted(pool.glob("*.txt"))
    vecs = sorted(pool.glob("*.json"))
    ck(r.returncode == 0 and "1 accepted document(s) appended" in r.stdout
       and len(txts) == 1 and len(vecs) == 1 and txts[0].stem == vecs[0].stem
       and len(txts[0].stem) == 16,
       "append: one sha256-keyed pool record (txt beside json)", r.stdout + r.stderr)
    vec = json.loads(vecs[0].read_text(encoding="utf-8")) if vecs else {}
    prov = vec.get("provenance") or {}
    ck(prov.get("source") == "harvest" and isinstance(prov.get("harvested_at"), str)
       and prov.get("words") == vec.get("words") and prov.get("situation") == "blog",
       "append: the provenance row carries source, timestamp, words, situation tag",
       json.dumps(prov))
    ck(MARKER in txts[0].read_text(encoding="utf-8"),
       "append: the text is stored in the user's pool, not transformed")

    # B. idempotent duplicate skip: silent, no rewrite
    raw_before = vecs[0].read_bytes()
    r = run_b("--file", str(d1))
    ck(r.returncode == 0 and r.stdout == "" and vecs[0].read_bytes() == raw_before,
       "append: an exact sha256 duplicate skips silently and rewrites nothing", r.stdout)

    # C. mechanical rebuild: the shared body wrote the bands deterministically
    bands_path = learned_b / "state" / "voice-bands.json"
    ck(bands_path.is_file(), "rebuild: voice-bands.json exists after pool growth")
    reg = load_module("g6_regenerate", PLUGIN_DIR / "learn" / "regenerate.py")
    os.environ["VOICE_LEARNED_DIR"] = str(learned_b)
    saved_hh = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(tdp_b / "hermes")
    try:
        b1 = bands_path.read_bytes()
        reg.rebuild_pool()
        b2 = bands_path.read_bytes()
        reg.rebuild_pool()
        b3 = bands_path.read_bytes()
        ck(b1 == b2 == b3,
           "rebuild: deterministic - the same pool state gives byte-identical derived artifacts")
    finally:
        if saved_hh is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = saved_hh
        os.environ.pop("VOICE_LEARNED_DIR", None)

    # E. pending rows: candidate 2 vs active 1, plain words, gate unchanged
    pend = learned_b / "state" / "band-approvals.json"
    ck(pend.is_file(), "approval: pending rows written for the budget candidate")
    pdata = json.loads(pend.read_text(encoding="utf-8")) if pend.is_file() else {}
    rows = pdata.get("pending") or []
    ck(len(rows) == 1 and rows[0].get("band") == "aphorism",
       "approval: exactly one pending band row (aphorism)", json.dumps(rows))
    ch = (rows[0].get("changes") or {}).get("max_per_section") or {}
    ck(ch.get("candidate") == 2 and ch.get("active") == 1,
       "approval: the pending row carries the candidate AND the active numbers",
       json.dumps(ch))
    ck("kicker shapes" in (rows[0].get("note") or ""),
       "approval: the plain-words note says what changed and by how much",
       rows[0].get("note"))
    g = run_b(gate_env=True)
    ck(g.returncode == 4,
       "approval: the gate keeps the old fail line while the row is pending (exit 4)",
       g.stdout[:160])

    # E. --approve-bands promotes into the runtime state; the gate then passes
    r = run_b("--approve-bands")
    ck(r.returncode == 0 and "approved aphorism.max_per_section = 2" in r.stdout,
       "approval: --approve-bands promotes the row and prints the promotion",
       r.stdout + r.stderr)
    st = tdp_b / "hermes" / "state" / "voice-rules.json"
    sdata = json.loads(st.read_text(encoding="utf-8")) if st.is_file() else {}
    got = (((sdata.get("sources") or {}).get("harvest-bands") or {}).get("bands")
           or {}).get("aphorism") or {}
    ck(got.get("max_per_section") == 2,
       "approval: the approved band lands in the runtime state under harvest-bands (data only)",
       json.dumps(got))
    pdata2 = json.loads(pend.read_text(encoding="utf-8"))
    ck((pdata2.get("pending") or []) == [], "approval: the pending row clears", json.dumps(pdata2))
    g2 = run_b(gate_env=True)
    ck(g2.returncode == 0,
       "approval: the gate now uses the new budget for the same text (exit 0)", g2.stdout[:160])
    r = run_b("--approve-bands")
    ck(r.returncode == 0 and "no pending band changes" in r.stdout,
       "approval: nothing pending -> the defined line, exit 0", r.stdout)

    # D. advisory refresh silent: candidates equal to the active budget
    (acc_b / "draft2.md").write_text(draft(kickers=0))
    r = run_b()
    ck(r.returncode == 0 and "1 accepted document(s) appended" in r.stdout,
       "session end: the configured accepted_dir is scanned", r.stdout + r.stderr)
    pdata3 = json.loads(pend.read_text(encoding="utf-8"))
    ck((pdata3.get("pending") or []) == [] and "approval" not in r.stdout,
       "advisory: candidates inside the active budget write no pending rows and no notice",
       json.dumps(pdata3))
    ck(not st.exists() or json.loads(st.read_text(encoding="utf-8")) == sdata,
       "advisory: the runtime state file is untouched by a plain harvest run")
    ck(bands_path.is_file() and json.loads(bands_path.read_text(encoding="utf-8")).get("docs") == 2,
       "advisory: the refreshed advisory bands rebuild silently (2 documents)")
finally:
    td_b.cleanup()

# F. privacy: harvested text never enters the repo --------------------------------
tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
                         capture_output=True).stdout.split(b"\x00")
tracked = [t.decode("utf-8", "replace") for t in tracked if t]
hits = []
for t in tracked:
    p = REPO_ROOT / t
    if p.is_file() and p.suffix.lower() in (".py", ".md", ".json", ".yaml", ".yml", ".txt"):
        try:
            if MARKER in p.read_text(errors="replace"):
                hits.append(t)
        except Exception:
            pass
ck(not hits, "privacy: the harvested marker text appears in no tracked repo file", str(hits[:5]))
pool_tracked = [t for t in tracked if "/pool/" in t or t.endswith("band-approvals.json")]
ck(not pool_tracked, "privacy: no pool text or approval payload is tracked anywhere",
   str(pool_tracked[:5]))

# G. resolve_budget unit rules -----------------------------------------------------
ck(core.resolve_budget(None) == (1, 3) and core.resolve_budget({}) == (1, 3),
   "resolve budget: absent band -> the embedded constants (1, 3)")
ck(core.resolve_budget({"max_per_section": 2}) == (2, 3),
   "resolve budget: a whole-number key applies, the other stays")
ck(core.resolve_budget({"max_per_section": 2.0, "max_per_piece": 6}) == (2, 6),
   "resolve budget: integral floats and ints both apply")
ck(core.resolve_budget({"max_per_section": True, "max_per_piece": 0}) == (1, 3),
   "resolve budget: booleans and numbers below 1 never apply")
ck(core.resolve_budget({"max_per_section": 1.5}) == (1, 3),
   "resolve budget: non-whole numbers never apply")
ck(core.aphorism_budget_hits("Ship it.\n\nNo pain, no gain.",
                             budgets={"max_per_section": 2}) == [],
   "budget hits: the override raises the budget and the lines vanish")
ck("at most 1 per section" in core.aphorism_budget_hits("Ship it.\n\nNo pain, no gain.")[0],
   "budget hits: absent band keeps the byte-identical embedded line")

# G. stdlib-only module scope ------------------------------------------------------
_STDLIB = {"argparse", "hashlib", "importlib.util", "json", "os", "sys",
           "datetime", "pathlib"}
tree = ast.parse(HARVEST.read_text(encoding="utf-8"))
top_imports = set()
for node in tree.body:
    if isinstance(node, ast.Import):
        top_imports |= {a.name for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        top_imports.add(node.module)
ck(top_imports <= _STDLIB,
   "harvest module: stdlib-only imports at module scope (lazy plugin loads)",
   str(sorted(top_imports)))
harvest_mod = load_module("g6_harvest", HARVEST)
ck(hasattr(harvest_mod, "main"), "harvest module: importable with main()")

# G. gate pass-line byte-pin without bands -----------------------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
           "HERMES_HOME": str(tdp / "hermes"), "VOICE_GATE_VECTOR": "off",
           "VOICE_GATE_LOG": str(tdp / "gate.log")}
    (tdp / "learned").mkdir()
    r = subprocess.run([sys.executable, "-I", str(GATE), "--surface", "public"],
                       input="Set the timeout.\n\nShip it.",
                       capture_output=True, text=True, env=env)
    ck(r.returncode == 0
       and r.stdout.strip() == '{"status": "pass", "surface": "public", "tokens_to_model": 0}',
       "gate: a one-kicker text passes with the byte-identical pass line (no bands)",
       r.stdout.strip())

print(f"\ng6 passive harvest: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
