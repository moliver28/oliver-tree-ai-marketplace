#!/usr/bin/env python3
"""Marketplace verifier. Run before any publish claim.

Checks:
1. marketplace.json parses and every listed plugin source dir exists with a plugin.json manifest.
2. Every SKILL.md in the repo has name + description frontmatter.
3. The /voice gate actually runs: one sloppy text must fail, one clean text must pass (exit codes 4/0),
   and the fail JSON carries the patch-in-place repair contract (max 5 patterns).
4. Every README-indexed path exists.
5. humanizer loads learned rules from the runtime state file (issue #5): a state
   pattern/exemplar/threshold override is applied at scan time with per-source
   provenance; an absent state file falls back to the embedded lists silently; a
   corrupt state file falls back and logs `state_skip` (fail-open unchanged).
6. learn/apply drift: the runtime gate's embedded rule data must hash-match the
   published mirror (humanizer/hooks/voice_tells.py), and a state file present on
   the machine must parse under the shared loader. No runtime on the machine (CI)
   -> explicit SKIP line.
7. Organization law (issue #8, flatten): top-level dirs and level-2 entries inside
   group dirs are whitelisted; a new group or entry requires a verify.py edit
   (explicit owner approval); grouping depth max 2 (entry-internal anatomy exempt).
   A `plugins/` grouping dir must not reappear.
8. Zero-stub law (deterministic, no LLM inference): no 0-byte files, no tracked
   `__pycache__`/`*.pyc`, no stub markers in plugin/skill text files (inline
   `verify-allow` whitelists honored), no `pass`/`...`-only function bodies in
   plugin `.py` files, no dangling catalog/PROVENANCE path rows.
9. Efficiency gate (W1, MO ruling 2026-11-21; runs only with `--efficiency` or
   env `VERIFY_EFFICIENCY=1`, i.e. the develop -> main release lane): shipped
   uxr-plugin payload lines vs the recorded floor in tests/efficiency-baseline.json
   (tolerance 0; any growth FAILs and lists the growing dirs, and a justification
   must be recorded in the baseline file in the same PR), and the declared
   golden-path model-call budget vs the recorded floor (growth FAILs without a
   recorded justification). Golden immobility and the hash pins are enforced
   above by tests/test_parity.py; the efficiency gate references them, never
   duplicates them.
10. Learn-tool determinism (canonical v1.0.0): the learn tools are importable with
    a main(); calibrate.py emits parseable per-class JSON on a fixture corpus
    (clean corpus = zero hits, tell fixture = deterministic hits); distill_phrases.py
    has a defined empty-log behavior.
11. De-personalization gate (owner ruling 2026-11-21): the owner's personal voice
    artifacts left the public mirror (canonical copies live in the private archive
    outside this repo). A fixed token list must not appear in any published
    plugin/skill content file outside the named exceptions.
12. Voice-NLP v1.1.0 (issue #127 Tiers 1+2+3): hash-guard no-recompute (the
    second build run prints the no-rebuild line and runs WITHOUT any embedder);
    gate advisory fields (voice_fit/source_fidelity/p_ai/voice_delta) appear
    deterministically with fixture artifacts and stay absent without them;
    classifier trains on a fixture corpus, parses, scores deterministically,
    and reports a defined empty-input message; learn-edit classifies
    substantial/light edits and reports the defined no-match line;
    acceptance_check scores the Delta path and prints the defined onnx-absent
    line with exit 2.
13. Researcher instruction gate (W4, issue #120): when the current
    EOL-normalized sha256 of any researcher instruction asset
    (agents/hcd-researcher.md, prompts/hcd-gate/prompt.md and its fragments,
    references/script-rigor.md) differs from the hash recorded in
    tests/evals/hcd-researcher/baseline.json, verify FAILS unless baseline.json
    also records a run whose verdict is PASS carrying that new hash. The tuning
    harness itself (tests/evals/hcd-researcher/run_evals.py) never runs here
    and is never imported.
14. Voice-fit advisory v1.2.0: learn/voice_fit.py (the count-based stylometry
    advisory: M15 Burrows' Delta + M18 surface stats, promoted with the
    sitefactory P18 refinements) imports with a main(); its CLI fails open
    with no profile (exit 0, n/a reference columns, defined note); profile
    mode reads a delta against a built profile.json; a sample corpus too
    small for leave-one-out reads n/a sample-self; the contract suite
    humanizer/tests/test_voice_fit.py exits 0 (sitefactory parity fixture,
    gate no-op byte-pin, fail-open, spread rule, stdlib-only); version
    parity at 1.2.0.

Exit 0 = marketplace verified working; nonzero = broken, do not publish.
"""
import hashlib
import importlib.util
import io, json, math, os, shutil, sys, subprocess, pathlib, re, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []

def ck(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        fails.append(msg)


def _rules_hash(mod):
    """Stable content hash of a voice-tells module's embedded rule data."""
    payload = {"patterns": [[a, b] for a, b in mod.PATTERNS], "exemplars": list(mod.EXEMPLARS)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def voice_gate_drift(published, hermes_home):
    """Learn/apply drift check (issue #5). Returns (status, msg), status in
    ok|skip|fail. The runtime gate's embedded rule data must hash-match the
    published mirror, and a state file present on this machine must parse
    under the shared loader contract. No runtime gate and no state file on
    the machine (CI) -> explicit skip."""
    home = pathlib.Path(hermes_home)
    gate = home / "agent-hooks" / "voice-tells.py"
    state = home / "state" / "voice-rules.json"
    gate_present, state_present = gate.is_file(), state.is_file()
    if not gate_present and not state_present:
        return ("skip", f"no Hermes runtime on this machine: {gate} and {state} both absent")
    msgs, status = [], "ok"
    if state_present:
        saved = os.environ.get("VOICE_RULES_STATE")
        try:
            os.environ["VOICE_RULES_STATE"] = str(state)
            eff = published.effective_rules()
            st = eff["state"]
            n_pat = sum(1 for s in eff["pattern_sources"] if s != "embedded")
            n_ex = sum(1 for s in eff["exemplar_sources"] if s != "embedded")
            if st["ok"]:
                msgs.append(f"state file parses under the shared loader ({n_pat} state patterns, "
                            f"{n_ex} state exemplars)" + (f"; warnings: {st['err']}" if st["err"] else ""))
            else:
                status = "fail"
                msgs.append(f"state file invalid -> gate silently embedded-only: {st['err']}")
        except Exception as e:
            status = "fail"
            msgs.append(f"state file unusable under the shared loader: {e!r}")
        finally:
            if saved is None:
                os.environ.pop("VOICE_RULES_STATE", None)
            else:
                os.environ["VOICE_RULES_STATE"] = saved
    if gate_present:
        try:
            spec = importlib.util.spec_from_file_location("runtime_voice_tells", gate)
            rt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rt)
            h_rt, h_pub = _rules_hash(rt), _rules_hash(published)
            if h_rt != h_pub:
                status = "fail"
                msgs.append(f"pattern-list hash drift: runtime gate {h_rt[:12]} != published mirror {h_pub[:12]}")
            else:
                msgs.append(f"runtime gate matches published mirror ({h_rt[:12]})")
        except Exception as e:
            status = "fail"
            msgs.append(f"runtime gate unusable for hash compare: {e!r}")
    elif state_present:
        msgs.append("state-only machine: embedded-hash compare skipped (no runtime gate to hash)")
        if status != "fail":
            status = "skip"
    return (status, "; ".join(msgs))

mp = ROOT / ".claude-plugin" / "marketplace.json"
data = json.loads(mp.read_text())
ck(data.get("name") == "oliver-tree-ai-marketplace", "marketplace name")
for p in data["plugins"]:
    src = ROOT / p["source"].lstrip("./")
    ck(src.is_dir(), f"plugin dir {p['name']}")
    ck((src / ".claude-plugin" / "plugin.json").is_file(), f"manifest {p['name']}")
    mj = json.loads((src / ".claude-plugin" / "plugin.json").read_text())
    ck(mj.get("name") == p["name"], f"manifest name matches for {p['name']}")
    ck(mj.get("version") == p.get("version"), f"version parity {p['name']} (manifest vs marketplace)")
    if p["name"] == "humanizer-voice":
        ck(mj.get("version") == "1.2.0", f"humanizer-voice is at 1.2.0 (stylometry advisory shipped): got {mj.get('version')}")
    d = mj.get("description", "")
    ck(len(d) <= 256, f"description <=256 chars for {p['name']} ({len(d)})")
    ck("'" in d and "use when the user says" in d.lower(), f"description carries human trigger phrases for {p['name']}")
    chlog = src / "CHANGELOG.md"
    ck(chlog.is_file(), f"changelog exists for {p['name']}")
    ck(f"[{p.get('version')}]" in chlog.read_text(), f"changelog entry for {p.get('version')} in {p['name']}")
    if p["name"] == "humanizer-voice":
        ck((src / "learned" / "phrases.log").exists(), "learned sidecar exists")
        cmd = (src / "commands" / "voice.md").read_text()
        ck("phrases.log" in cmd, "/voice logs learned phrases deterministically")
        # --- canonical v1.0.0: the plugin is self-contained; the engine lives in hooks/, the
        # zero-LLM learn tools in learn/. Vectors/calibration are per-user artifacts, never shipped.
        hooks_dir = src / "hooks"
        learn_dir = src / "learn"
        ck(not (src / "voice-tells-vectors.json").is_file()
           and not (src / "voice-tells-calibration.json").is_file(),
           "humanizer ships no packaged vector payload (vectors/calibration are per-user learned/ artifacts)")
        vt_src = (hooks_dir / "voice_tells.py").read_text()
        ck("COSINE_THRESHOLD" not in vt_src, "voice_tells global cosine threshold removed (per-class table)")
        ck(all(l[:1] in " \t" for l in vt_src.splitlines() if "import onnxruntime" in l),
           "onnxruntime import confined to lazy fallback path (not module scope)")
        vt = None
        try:
            _spec = importlib.util.spec_from_file_location("voice_tells_verify", hooks_dir / "voice_tells.py")
            vt = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(vt)
        except Exception as e:
            ck(False, f"voice_tells.py importable in verifier: {e!r}")
        if vt is not None:
            # De-personalized register: 55 patterns (the six owner-order register-36/37
            # adds are gone), 16 synthetic exemplars, and no register/owner wording in labels.
            ck(len(vt.PATTERNS) == 55,
               f"voice_tells embedded pattern count == 55 (de-personalized register; edit this check together with the register): got {len(vt.PATTERNS)}")
            ck(len(vt.EXEMPLARS) == 16,
               f"voice_tells embedded exemplar count == 16 (synthetic exemplar set): got {len(vt.EXEMPLARS)}")
            ck(not any(("register" in label.lower() or "owner" in label.lower()) for _p, label in vt.PATTERNS),
               "voice_tells labels carry no register/owner references (de-personalization ruling)")
            ck(vt.PLUGIN_DIR == ROOT / "humanizer",
               "voice_tells resolves per-user vector/calibration paths into the plugin's learned/ dir")
            ck(not vt.CACHE_PATH.exists() and not vt.CAL_PATH.exists(),
               "no per-user vector payload committed into humanizer/learned/")
            ck(all(not (vt.learned_dir() / n).exists()
                   for n in ("voice-centroid.json", "embed-cache.json", "voice-classifier.json",
                             "deliveries.log", "clean-corpus-index.txt"))
               and not (vt.learned_dir() / "edit-delta").exists(),
               "no per-user v1.1.0 runtime artifacts committed into humanizer/learned/ "
               "(centroid, embed cache, classifier, deliveries.log, corpus index, edit-delta)")
            ck(all(hasattr(vt, name) for name in
                   ("voice_fit", "vector_scores", "vector_pass", "embed_cached",
                    "embed_source_cached", "learned_dir")),
               "voice_tells exposes the v1.1.0 API (voice_fit/vector_scores/vector_pass/"
               "embed_cached/embed_source_cached/learned_dir)")
            # learn tools importable (same importlib pattern as the voice-tells check above)
            for tool_name in ("build_voice_profile", "distill_phrases", "calibrate", "voice_vector_build",
                              "train_voice_classifier", "edit_learning", "acceptance_check", "voice_fit"):
                try:
                    tspec = importlib.util.spec_from_file_location(
                        f"humanizer_learn_{tool_name}", learn_dir / f"{tool_name}.py")
                    tmod = importlib.util.module_from_spec(tspec)
                    tspec.loader.exec_module(tmod)
                    ck(hasattr(tmod, "main"), f"learn tool {tool_name}.py importable with main()")
                except Exception as e:
                    ck(False, f"learn tool {tool_name}.py importable: {e!r}")
            # default corpus root must resolve to the plugin root from the new location
            try:
                _vbs = importlib.util.spec_from_file_location(
                    "voice_vector_build_verify", learn_dir / "voice_vector_build.py")
                vb = importlib.util.module_from_spec(_vbs)
                _vbs.loader.exec_module(vb)
                ck(vb.plugin_root() == ROOT / "humanizer",
                   "voice_vector_build resolves the default corpus root to the plugin root")
            except (SystemExit, Exception) as e:
                ck(False, f"voice_vector_build resolves the default corpus root to the plugin root: {e!r}")

        # --- learn/apply decoupling (issue #5): shared state-file loader contract ---
        has_loader = vt is not None and hasattr(vt, "effective_rules") and hasattr(vt, "state_path")
        ck(has_loader, "voice_tells exposes the shared state-file loader API (state_path/effective_rules)")
        if has_loader:
            with tempfile.TemporaryDirectory() as td:
                tdp = pathlib.Path(td)
                logf, stf = tdp / "gate.log", tdp / "voice-rules.json"
                saved = {k: os.environ.pop(k) for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG") if k in os.environ}
                try:
                    os.environ["VOICE_GATE_LOG"] = str(logf)
                    # case: absent state file -> embedded defaults, silent (identical to today)
                    try:
                        os.environ["VOICE_RULES_STATE"] = str(tdp / "absent.json")
                        eff = vt.effective_rules()
                        ck(eff["patterns"] == list(vt.PATTERNS) and eff["exemplars"] == list(vt.EXEMPLARS),
                           "absent state file -> embedded defaults")
                        ck(eff["state"]["ok"] is False and eff["state"]["err"] == "absent",
                           "absent state file reported via loader status")
                        ck(not logf.exists(), "absent state file -> silent fallback (no log side effects)")
                        ck(str(vt.state_path()) == str(tdp / "absent.json"),
                           "VOICE_RULES_STATE overrides the state path")
                        os.environ.pop("VOICE_RULES_STATE")
                        ck(vt.state_path().parent.name == "state" and vt.state_path().name == "voice-rules.json",
                           "default state path is <HERMES_HOME>/state/voice-rules.json")
                    except Exception as e:
                        ck(False, f"loader case absent-state: {e!r}")
                    # case: valid state file -> overrides applied at scan time, provenance preserved
                    try:
                        stf.write_text(json.dumps({
                            "format": 1,
                            "sources": {
                                "register": {"patterns": [
                                    {"pattern": "\\bfrobnicate\\b", "label": "state pattern 'frobnicate' (register)"}]},
                                "learn": {"exemplars": ["Frobnicate the paradigm to seamlessly unlock synergy."],
                                          "thresholds": {"performed candor": 0.9}}}}, indent=2))
                        os.environ["VOICE_RULES_STATE"] = str(stf)
                        eff = vt.effective_rules()
                        ck(eff["patterns"][-1] == ("\\bfrobnicate\\b", "state pattern 'frobnicate' (register)"),
                           "state pattern appended to effective patterns")
                        ck(eff["pattern_sources"][-1] == "register" and eff["pattern_sources"].count("embedded") == len(vt.PATTERNS),
                           "per-source provenance preserved (register vs embedded)")
                        state_exemplar = "Frobnicate the paradigm to seamlessly unlock synergy."
                        ck(state_exemplar in eff["exemplars"]
                           and eff["exemplar_sources"][eff["exemplars"].index(state_exemplar)] == "learn",
                           "state exemplar merged with provenance (learn)")
                        ck(eff["thresholds"].get("performed candor") == 0.9,
                           "state threshold overrides calibration per class")
                        hits = vt.find_regex_hits("Please frobnicate the stack at the end of the day.")
                        ck(len(hits) == 2 and any("frobnicate" in h for h in hits)
                           and any("at the end of the day" in h for h in hits),
                           "scan-time load: gate fires state pattern alongside embedded patterns")
                        stf.write_text(json.dumps({"format": 1, "sources": {"learn": {"patterns": [
                            {"pattern": "\\bfrobnicate\\b", "label": "updated label"}]}}}))
                        hits2 = vt.find_regex_hits("Please frobnicate the stack.")
                        ck(len(hits2) == 1 and "updated label" in hits2[0],
                           "state edit picked up at scan time without restart")
                    except Exception as e:
                        ck(False, f"loader case override-applied: {e!r}")
                    # case: corrupt state file -> embedded fallback + state_skip logged
                    try:
                        if logf.exists():
                            logf.unlink()
                        stf.write_text("{corrupt json here")
                        eff = vt.effective_rules()
                        ck(eff["patterns"] == list(vt.PATTERNS) and eff["exemplars"] == list(vt.EXEMPLARS),
                           "corrupt state file -> embedded defaults (fail-open unchanged)")
                        ck(eff["state"]["ok"] is False and "parse" in (eff["state"]["err"] or ""),
                           "corrupt state file reported as parse failure")
                        ck(logf.exists() and any('"state_skip"' in line for line in logf.read_text(errors="replace").splitlines()),
                           "corrupt state file -> state_skip logged via _log_vec")
                    except Exception as e:
                        ck(False, f"loader case corrupt-state: {e!r}")
                    # case: invalid regex in one state entry -> that entry dropped + logged,
                    # valid entries still enforced at scan (entry-level failure isolation)
                    try:
                        if logf.exists():
                            logf.unlink()
                        stf.write_text(json.dumps({"format": 1, "sources": {"register": {"patterns": [
                            {"pattern": "[unclosed", "label": "bad regex entry"},
                            {"pattern": "\\bquuxophone\\b",
                             "label": "state pattern 'quuxophone' (register)"}]}}}))
                        os.environ["VOICE_RULES_STATE"] = str(stf)
                        eff = vt.effective_rules()
                        ck(("\\bquuxophone\\b", "state pattern 'quuxophone' (register)") in eff["patterns"]
                           and all(p != "[unclosed" for p, _ in eff["patterns"]),
                           "invalid state regex entry dropped, valid entries kept in the merged set")
                        hits = vt.find_regex_hits("Please quuxophone the stack.")
                        ck(any("quuxophone" in h for h in hits),
                           "invalid state regex dropped: valid state pattern still enforced at scan")
                        ck(logf.exists() and "does not compile" in logf.read_text(errors="replace"),
                           "invalid state regex entry logged with source + entry id (state_skip)")
                    except Exception as e:
                        ck(False, f"loader case invalid-regex entry: {e!r}")
                    # drift-check unit cases against fabricated runtime homes
                    try:
                        fake = tdp / "hermes-fake"
                        (fake / "agent-hooks").mkdir(parents=True)
                        shutil.copyfile(hooks_dir / "voice_tells.py", fake / "agent-hooks" / "voice-tells.py")
                        st, msg = voice_gate_drift(vt, fake)
                        ck(st == "ok", f"drift: identical runtime gate -> ok ({msg})")
                        gate_py = fake / "agent-hooks" / "voice-tells.py"
                        gate_py.write_text(gate_py.read_text(errors="replace")
                                           + "\nPATTERNS.append((r'\\bdrifted\\b', 'drifted pattern'))\n")
                        st, msg = voice_gate_drift(vt, fake)
                        ck(st == "fail" and "drift" in msg, f"drift: modified runtime gate -> fail ({msg})")
                        st, msg = voice_gate_drift(vt, tdp / "hermes-none")
                        ck(st == "skip", f"drift: no runtime on machine -> skip ({msg})")
                        fake2 = tdp / "hermes-stateonly"
                        (fake2 / "state").mkdir(parents=True)
                        (fake2 / "state" / "voice-rules.json").write_text(json.dumps(
                            {"format": 1, "sources": {"manual": {"patterns": [
                                {"pattern": "\\bwidget\\b", "label": "manual note 'widget'"}]}}}))
                        st, msg = voice_gate_drift(vt, fake2)
                        ck(st == "skip" and "state-only" in msg,
                           f"drift: valid state file without runtime gate -> skip with note ({msg})")
                        (fake2 / "state" / "voice-rules.json").write_text("{nope")
                        st, msg = voice_gate_drift(vt, fake2)
                        ck(st == "fail" and "state file invalid" in msg,
                           f"drift: corrupt state file -> fail even without gate ({msg})")
                    except Exception as e:
                        ck(False, f"drift unit cases: {e!r}")
                finally:
                    for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG"):
                        os.environ.pop(k, None)
                    for k, v in saved.items():
                        os.environ[k] = v
        # drift of the real machine's runtime gate vs this published mirror
        if vt is not None:
            try:
                hermes_home = os.environ.get("HERMES_HOME") or str(pathlib.Path.home() / ".hermes")
                drift_status, drift_msg = voice_gate_drift(vt, hermes_home)
                if drift_status == "skip":
                    print("SKIP humanizer drift check: " + drift_msg)
                else:
                    ck(drift_status == "ok", f"humanizer drift check (issue #5): {drift_msg}")
            except Exception as e:
                ck(False, f"humanizer drift check crashed: {e!r}")

        # --- regex-layer standalone scanner: tell-laden text fails, clean text passes + marker
        with tempfile.TemporaryDirectory() as td:
            vf = pathlib.Path(td) / "probe.md"
            vf.write_text("The tool serves as a foundation for innovation, and that is okay. "
                          "It is not just about speed, it is about unlocking value at the end of the day.")
            env = {**os.environ, "VOICE_GATE_VECTOR": "off"}
            r = subprocess.run(["python3", str(hooks_dir / "voice_check.py"), str(vf)], capture_output=True, text=True, env=env)
            ck(r.returncode == 1, "voice_check regex layer fails tell-laden text (exit 1)")
            ck(not (pathlib.Path(td) / "probe.voice-pass").exists(), "voice_check writes no marker on failure")
            vf.write_text("The scanner loads the rules from the shared module, so the hook and the checker cannot drift.")
            r2 = subprocess.run(["python3", str(hooks_dir / "voice_check.py"), str(vf)], capture_output=True, text=True, env=env)
            ck(r2.returncode == 0 and "PASS" in r2.stdout, "voice_check passes clean text and writes marker")

skills = list(ROOT.glob("**/SKILL.md"))
for s in skills:
    text = s.read_text()
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    head = fm.group(1) if fm else text[:400]  # full frontmatter block, not first 400 chars
    ck("name:" in head and "description:" in head, f"frontmatter {s.relative_to(ROOT)}")
    m = re.search(r"description:(.*)", head)
    if m:
        lines = [m.group(1)]  # multi-line YAML descriptions: join indented continuation lines
        for line in head[m.end():].splitlines():
            if line[:1] not in (" ", "\t"):
                break
            lines.append(line.strip())
        d = " ".join(l for l in lines if l and l not in (">-", "|-", "|", ">")).strip()
        ck(len(d) <= 300, f"skill description <=300 chars {s.relative_to(ROOT)} ({len(d)})")
        ck("use when the user says" in d.lower(), f"skill description carries invocation trigger {s.relative_to(ROOT)}")
        ck(d.count("'") >= 4 or len(re.findall(r'\\"', d)) >= 4, f"skill description carries quoted human phrases {s.relative_to(ROOT)}")
ck(len(skills) >= 6, f"skill count {len(skills)} >= 6")

hooks = ROOT / "humanizer" / "hooks" / "gate.py"
sloppy = "The tool serves as a foundation for innovation, and that is okay. It is not just about speed, it is about unlocking value at the end of the day."
clean = "The scanner loads the rules from the shared module, so the hook and the checker cannot drift."
r_chat = subprocess.run(["python3", str(hooks), "--surface", "chat"], input="The configuration was completed in order to provide a really robust system that everybody in the building uses daily without any problems.", capture_output=True, text=True)
ck(r_chat.returncode == 4, "gate chat surface fails STE-breaking text (exit 4)")
r_chat2 = subprocess.run(["python3", str(hooks), "--surface", "chat"], input="Set the timeout. The scanner reads the config first. Save the file.", capture_output=True, text=True)
ck(r_chat2.returncode == 0, "gate chat surface passes clean STE text (exit 0)")
ck("Ste" not in r_chat2.stdout, "chat pass carries no nudge")
r = subprocess.run(["python3", str(hooks)], input=sloppy, capture_output=True, text=True)
ck(r.returncode == 4 and json.loads(r.stdout)["status"] == "fail", "gate fails sloppy text (exit 4)")
r2 = subprocess.run(["python3", str(hooks)], input=clean, capture_output=True, text=True)
ck(r2.returncode == 0 and json.loads(r2.stdout)["status"] == "pass", "gate passes clean text (exit 0)")
# gate self-containment on the explicit public surface: fail JSON = one repair
# contract, max 5 patterns, patch-in-place instruction; pass JSON = zero tokens.
r_pub = subprocess.run(["python3", str(hooks), "--surface", "public"], input=sloppy, capture_output=True, text=True)
try:
    pj = json.loads(r_pub.stdout)
    ck(r_pub.returncode == 4 and pj["status"] == "fail" and 1 <= pj["reported"] <= 5
       and pj["instruction_char_budget"] == 900 and "REPAIR, DO NOT REWRITE" in pj["instruction"],
       "gate public surface self-containment: fail JSON carries the patch-in-place repair contract (max 5 patterns)")
except Exception as e:
    ck(False, f"gate public-surface fail JSON parse: {e!r}")
r_pub2 = subprocess.run(["python3", str(hooks), "--surface", "public"], input=clean, capture_output=True, text=True)
try:
    pj2 = json.loads(r_pub2.stdout)
    ck(r_pub2.returncode == 0 and pj2["status"] == "pass" and pj2["tokens_to_model"] == 0,
       "gate public surface self-containment: clean text pass JSON, zero tokens to the model")
except Exception as e:
    ck(False, f"gate public-surface pass JSON parse: {e!r}")

# --- learn-tool determinism (zero-LLM loop): fixture corpus + defined empty behavior ---
voice_fix = ROOT / "tests" / "fixtures" / "voice"
if voice_fix.is_dir():
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        cal_script = ROOT / "humanizer" / "learn" / "calibrate.py"
        out_clean = tdp / "calibration_clean.json"
        rc = subprocess.run(["python3", str(cal_script), "--corpus", str(voice_fix / "clean"),
                             "--out", str(out_clean)], capture_output=True, text=True)
        ck(rc.returncode == 0, "calibrate.py runs on the clean fixture corpus (exit 0)")
        try:
            cal = json.loads(out_clean.read_text())
            total_hits = sum(v["hits"] for v in cal.get("per_class", {}).values())
            ck(cal.get("format") == 1 and isinstance(cal.get("per_class"), dict)
               and cal.get("sentences", 0) > 0 and "deviations" in cal and total_hits == 0,
               "calibrate.py emits parseable calibration JSON; clean fixture corpus passes the full regex layer")
        except Exception as e:
            ck(False, f"calibrate.py clean-corpus JSON parse: {e!r}")
        out_tell = tdp / "calibration_tells.json"
        rc2 = subprocess.run(["python3", str(cal_script), "--corpus", str(voice_fix / "tells"),
                              "--out", str(out_tell)], capture_output=True, text=True)
        try:
            cal2 = json.loads(out_tell.read_text())
            total_hits2 = sum(v["hits"] for v in cal2.get("per_class", {}).values())
            dev = [d["label"] for d in cal2.get("deviations", [])]
            ck(rc2.returncode == 0 and total_hits2 >= 3 and len(dev) >= 3,
               f"calibrate.py deterministically flags the tell fixture (>= 3 hits, deviations listed: {len(dev)})")
        except Exception as e:
            ck(False, f"calibrate.py tell-fixture JSON parse: {e!r}")
        dist_script = ROOT / "humanizer" / "learn" / "distill_phrases.py"
        out_rules = tdp / "rules.json"
        rd = subprocess.run(["python3", str(dist_script), "--log", str(tdp / "absent.log"),
                             "--out", str(out_rules)], capture_output=True, text=True)
        try:
            rules = json.loads(out_rules.read_text())
            ck(rd.returncode == 0 and rules.get("request_lines") == 0
               and rules.get("recurring_ngrams") == [],
               "distill_phrases.py empty/missing log: defined behavior, parseable rules.json, exit 0")
        except Exception as e:
            ck(False, f"distill_phrases.py empty-log behavior: {e!r}")

# --- v1.1.0 (issue #127 T1/T2/T3): attraction-side scores, trained classifier,
# post-hoc edit learning, offline acceptance check. All fixture artifacts live
# in a temp learned dir via VOICE_LEARNED_DIR (same override contract as
# VOICE_RULES_STATE/VOICE_GATE_LOG), so no per-user payload can land in the
# repo. The embedder is patched ONLY for the first in-process build/run; the
# no-rebuild and no-retrain runs are unpatched subprocesses with no embedder on
# the machine — if the hash guard ever tried to embed they would crash, which
# is the ruling-1 proof. Deterministic fake embedder: pure function of the text
# sha256, so every advisory value is reproducible.
if voice_fix.is_dir():
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        learned = tdp / "learned"
        learned.mkdir()
        saved_env = {k: os.environ.get(k) for k in ("VOICE_LEARNED_DIR", "HERMES_HOME", "VOICE_GATE_LOG")}
        os.environ["VOICE_LEARNED_DIR"] = str(learned)
        os.environ["HERMES_HOME"] = str(tdp / "hermes")
        os.environ["VOICE_GATE_LOG"] = str(tdp / "gate.log")
        os.environ.pop("VOICE_GATE_VECTOR", None)
        env_base = {**os.environ}  # VOICE_LEARNED_DIR set; no patched embedder travels with subprocesses
        try:

            # absent artifacts: the gate JSON is unchanged, advisory fields silently absent
            r_absent = subprocess.run([sys.executable, "-I", str(ROOT / "humanizer" / "hooks" / "gate.py"),
                                       "--surface", "public"],
                                      input="The scanner reads the rules first.",
                                      capture_output=True, text=True, env=env_base)
            try:
                jabs = json.loads(r_absent.stdout)
                ck(r_absent.returncode == 0 and jabs["status"] == "pass" and jabs["tokens_to_model"] == 0
                   and not any(k in jabs for k in ("voice_fit", "source_fidelity", "p_ai", "voice_delta")),
                   "gate with absent learned artifacts: pass JSON unchanged, advisory fields silently absent")
            except Exception as e:
                ck(False, f"gate absent-artifact JSON: {e!r}")

            def _fake_embed(text, timeout=2.0, backend=None):
                h = hashlib.sha256(text.encode("utf-8", "replace")).digest()
                vec = [(b / 127.5) - 1.0 for b in h[:64]]
                norm = math.sqrt(sum(x * x for x in vec)) or 1.0
                return [x / norm for x in vec], backend or "ollama"

            # check 1: hash-guard double build (ruling 1: no recompute)
            _vb_spec = importlib.util.spec_from_file_location(
                "voice_vector_build_v110", ROOT / "humanizer" / "learn" / "voice_vector_build.py")
            vb = importlib.util.module_from_spec(_vb_spec)
            _vb_spec.loader.exec_module(vb)
            vb.vt._embed = _fake_embed
            build_args = ["--backend", "ollama", "--corpus", str(voice_fix / "clean"),
                          "--bg", str(voice_fix / "clean" / "clean-notes.md")]
            saved_argv = sys.argv
            try:
                sys.argv = ["voice_vector_build.py"] + build_args
                rc_build = vb.main()
            finally:
                sys.argv = saved_argv
            ck(rc_build == 0 and all((learned / n).is_file() for n in
               ("voice-tells-vectors.json", "voice-tells-calibration.json", "voice-centroid.json")),
               "voice_vector_build first run writes vectors + calibration + centroid (patched embedder)")
            try:
                cen = json.loads((learned / "voice-centroid.json").read_text())["backends"]["ollama"]
                ck(isinstance(cen.get("centroid"), list) and cen.get("corpus_hash")
                   and cen.get("unit") == "document-chunks",
                   "voice-centroid.json carries backend-keyed centroid + corpus_hash + unit")
            except Exception as e:
                ck(False, f"voice-centroid.json schema: {e!r}")
            r_guard = subprocess.run([sys.executable, "-I", str(ROOT / "humanizer" / "learn" / "voice_vector_build.py")]
                                     + build_args, capture_output=True, text=True, env=env_base)
            ck(r_guard.returncode == 0 and "nothing rebuilt" in r_guard.stdout,
               f"hash guard: second build run prints the no-rebuild line with no embedder available "
               f"({r_guard.stdout.strip()[:60] or r_guard.stderr.strip()[:60]})")

            # check 2: gate advisory fields (voice_fit + source_fidelity), deterministic
            _gm_spec = importlib.util.spec_from_file_location(
                "gate_v110", ROOT / "humanizer" / "hooks" / "gate.py")
            gm = importlib.util.module_from_spec(_gm_spec)
            _gm_spec.loader.exec_module(gm)
            gm.tells._embed = _fake_embed
            src_file = tdp / "source.txt"
            src_file.write_text("The original fixture source text carries the facts for the rewrite.")
            rewrite = "The scanner reads the config before the tool starts. Save the file after the edit."

            def _run_gate():
                old = (sys.argv, sys.stdin, sys.stdout)
                buf = io.StringIO()
                try:
                    sys.argv = ["gate.py", "--surface", "public", "--source", str(src_file)]
                    sys.stdin = io.StringIO(rewrite)
                    sys.stdout = buf
                    code = gm.main()
                finally:
                    (sys.argv, sys.stdin, sys.stdout) = old
                return code, buf.getvalue()

            rc_g1, out_g1 = _run_gate()
            rc_g2, out_g2 = _run_gate()
            try:
                j1, j2 = json.loads(out_g1), json.loads(out_g2)
                ck(j1["status"] in ("pass", "fail") and "voice_fit" in j1 and "source_fidelity" in j1
                   and isinstance(j1["voice_fit"], float) and isinstance(j1["source_fidelity"], float),
                   f"gate JSON carries voice_fit + source_fidelity with fixture artifacts (status {j1['status']})")
                ck(j1["voice_fit"] == j2["voice_fit"] and j1["source_fidelity"] == j2["source_fidelity"]
                   and round(j1["voice_fit"], 3) == j1["voice_fit"],
                   "gate advisory values deterministic across runs at 3 decimals")
                ck((learned / "embed-cache.json").is_file()
                   and len(json.loads((learned / "embed-cache.json").read_text()).get("entries", {})) == 1,
                   "gate --source stored exactly one hash-keyed embed-cache entry (bounded disk cache)")
            except Exception as e:
                ck(False, f"gate advisory JSON parse: {e!r}")

            # check 3: classifier trains, parses, scores deterministically, defined empty input
            train_cmd = [sys.executable, "-I", str(ROOT / "humanizer" / "learn" / "train_voice_classifier.py"),
                         "--corpus", str(voice_fix / "clean")]
            r_tr = subprocess.run(train_cmd, capture_output=True, text=True, env=env_base)
            ck(r_tr.returncode == 0 and (learned / "voice-classifier.json").is_file(),
               f"train_voice_classifier trains on the fixture corpus and writes the artifact "
               f"({r_tr.stderr.strip()[:60]})")
            try:
                clf = json.loads((learned / "voice-classifier.json").read_text())
                ck(clf.get("buckets") == 65536 and clf.get("hash_algo") == "md5-mod-65536"
                   and isinstance(clf.get("weights"), dict) and clf.get("weights")
                   and isinstance(clf.get("bias"), (int, float)) and bool(clf.get("corpus_hash"))
                   and clf.get("seeder_version") == 1 and isinstance(clf.get("thresholds"), dict),
                   "voice-classifier.json parses with the documented schema")
            except Exception as e:
                ck(False, f"voice-classifier.json schema: {e!r}")
            _tc_spec = importlib.util.spec_from_file_location(
                "voice_classifier_v110", ROOT / "humanizer" / "learn" / "train_voice_classifier.py")
            tc = importlib.util.module_from_spec(_tc_spec)
            _tc_spec.loader.exec_module(tc)
            user_text = "The scanner reads the config before the tool starts. Save the file after the edit."
            s1, s2 = tc.score(user_text), tc.score(user_text)
            s3 = tc.score("In today's rapidly evolving innovation landscape, synergy unlocks seamless "
                          "productivity at scale. Let's dive into the ecosystem.")
            ck(s1 is not None and s1 == s2 and 0.0 <= s1["p_ai"] <= 1.0,
               f"classifier score() deterministic across calls ({s1})")
            ck(s3 is not None and s3["p_ai"] > s1["p_ai"],
               f"classifier scores AI-shaped prose above the user fixture (p_ai {s1['p_ai']} -> {s3['p_ai']})")
            r_tr_guard = subprocess.run(train_cmd, capture_output=True, text=True, env=env_base)
            ck(r_tr_guard.returncode == 0 and "nothing retrained" in r_tr_guard.stdout,
               "classifier hash guard: unchanged inputs -> nothing retrained")
            empty_dir = tdp / "empty-corpus"
            empty_dir.mkdir()
            r_empty = subprocess.run([sys.executable, "-I",
                                      str(ROOT / "humanizer" / "learn" / "train_voice_classifier.py"),
                                      "--corpus", str(empty_dir)], capture_output=True, text=True, env=env_base)
            ck(r_empty.returncode == 0 and "no positive documents" in r_empty.stdout,
               "classifier empty-input corpus exits 0 with the defined message")

            # check 4: learn-edit substantial/light/no-match
            _el_spec = importlib.util.spec_from_file_location(
                "edit_learning_v110", ROOT / "humanizer" / "learn" / "edit_learning.py")
            el = importlib.util.module_from_spec(_el_spec)
            _el_spec.loader.exec_module(el)
            delivered = ("The team ships the release pipeline every week and the audit reads the "
                         "chain from change to evidence.")
            el.append_delivery(learned, "2026-11-21", el.delivery_hash(delivered), "fixture-target.md")
            big_edit = ("Our crew ships the release train each week while the review board reads "
                        "every entry from commit to proof and beyond all quarters.")
            res_s = el.learn_run(delivered, big_edit, learned)
            ck(res_s["status"] == "substantial" and res_s["changed_pct"] > 15
               and (learned / "edit-delta" / "before").is_dir() and (learned / "edit-delta" / "after").is_dir(),
               f"learn-edit substantial: >15% classified, before/after pair written "
               f"({res_s['changed_pct']}% changed)")
            light_edit = delivered.replace("every week", "each week")
            res_l = el.learn_run(delivered, light_edit, learned)
            ck(res_l["status"] == "light" and res_l["changed_pct"] <= 15
               and (learned / "clean-corpus-index.txt").is_file(),
               f"learn-edit light: <=15% classified, corpus index updated ({res_l['changed_pct']}% changed)")
            idx_lines = (learned / "clean-corpus-index.txt").read_text().splitlines()
            ck(len(idx_lines) == 1 and idx_lines[0].endswith("edit-confirmed"),
               "clean-corpus-index line carries the edit-confirmed provenance tag")
            res_n = el.learn_run("text never delivered to any surface.",
                                 "text never delivered to any surface at all.", learned)
            ck(res_n["status"] == "no_match"
               and res_n["message"] == "no matching delivery recorded; nothing learned",
               "learn-edit unknown delivery hash -> defined no-match message")
            r_tr2 = subprocess.run(train_cmd, capture_output=True, text=True, env=env_base)
            ck(r_tr2.returncode == 0 and "nothing retrained" not in r_tr2.stdout,
               "classifier corpus hash covers edit-delta/index: the edit pair triggers retrain")

            # check 2b: gate advisory fields with the classifier artifact present
            rc_g3, out_g3 = _run_gate()
            try:
                j3 = json.loads(out_g3)
                ck("p_ai" in j3 and "voice_delta" in j3 and j3.get("voice_fit") == j1["voice_fit"],
                   f"gate JSON with the classifier artifact carries p_ai + voice_delta "
                   f"(advisory; status {j3['status']})")
            except Exception as e:
                ck(False, f"gate classifier JSON parse: {e!r}")

            # check 5: acceptance_check Delta + onnx-absent defined behavior
            r_bp = subprocess.run([sys.executable, "-I",
                                   str(ROOT / "humanizer" / "learn" / "build_voice_profile.py"),
                                   str(voice_fix / "clean"), "--out", str(learned / "profile.json")],
                                  capture_output=True, text=True, env=env_base)
            try:
                prof = json.loads((learned / "profile.json").read_text())
                fw = prof.get("function_words") or {}
                ck(r_bp.returncode == 0 and fw.get("docs") and len(fw.get("words", [])) == 60
                   and bool(fw.get("mean")) and bool(fw.get("stddev")),
                   "build_voice_profile writes the function_words Burrows' Delta profile (60 words)")
            except Exception as e:
                ck(False, f"profile function_words schema: {e!r}")
            ac_script = str(ROOT / "humanizer" / "learn" / "acceptance_check.py")
            r_ac = subprocess.run([sys.executable, "-I", ac_script,
                                   str(voice_fix / "clean" / "clean-notes.md"),
                                   "--profile", str(learned / "profile.json")],
                                  capture_output=True, text=True, env=env_base)
            ck(r_ac.returncode == 0 and "burrows_delta=" in r_ac.stdout,
               f"acceptance_check Delta path prints plain-number output ({r_ac.stdout.strip()[:60]})")
            r_acj = subprocess.run([sys.executable, "-I", ac_script,
                                    str(voice_fix / "clean" / "clean-notes.md"),
                                    "--profile", str(learned / "profile.json"), "--json"],
                                   capture_output=True, text=True, env=env_base)
            try:
                rows = json.loads(r_acj.stdout)
                ck(r_acj.returncode == 0 and isinstance(rows, list) and rows
                   and isinstance(rows[0].get("burrows_delta"), (int, float)),
                   "acceptance_check --json emits a parseable row array")
            except Exception as e:
                ck(False, f"acceptance_check --json parse: {e!r}")
            r_onnx = subprocess.run([sys.executable, "-I", ac_script,
                                     str(voice_fix / "clean" / "clean-notes.md"),
                                     "--profile", str(learned / "profile.json"), "--backend", "onnx"],
                                    capture_output=True, text=True, env=env_base)
            ck(r_onnx.returncode == 2 and "onnx backend unavailable" in r_onnx.stdout,
               "acceptance_check onnx-absent path prints the defined line and exits 2")

            # check 6: voice_fit advisory table (v1.2.0): fail-open with no
            # profile, profile-mode delta, small-sample n/a spread rule, and
            # the contract suite (sitefactory parity fixture, gate no-op
            # byte-pin, stdlib-only). The tool never gates; the contract suite
            # proves the delivery gate's bytes are unchanged by its presence.
            vf_script = str(ROOT / "humanizer" / "learn" / "voice_fit.py")
            # the fail-open probe points at a fresh empty learned dir: by this
            # point check 5 has already built learned/profile.json
            env_vf = {**env_base, "VOICE_LEARNED_DIR": str(learned / "absent")}
            r_vf = subprocess.run([sys.executable, "-I", vf_script, "-"],
                                  input=clean,
                                  capture_output=True, text=True, env=env_vf)
            ck(r_vf.returncode == 0 and r_vf.stdout.startswith("voice fit:")
               and "n/a" in r_vf.stdout and "no profile at" in r_vf.stdout,
               "voice_fit fail-open: no profile -> advisory table renders, exit 0, n/a delta")
            r_vfp = subprocess.run([sys.executable, "-I", str(ROOT / "humanizer" / "learn" / "build_voice_profile.py"),
                                    str(voice_fix / "clean"), str(voice_fix / "tells"),
                                    "--out", str(learned / "profile-fit.json")],
                                   capture_output=True, text=True, env=env_base)
            try:
                pf = json.loads((learned / "profile-fit.json").read_text())
                pf_docs = pf.get("function_words", {}).get("docs")
            except Exception as e:
                pf, pf_docs = None, None
                ck(False, f"voice_fit profile-mode setup JSON: {e!r}")
            ck(r_vfp.returncode == 0 and pf_docs == 2,
               "voice_fit profile-mode setup: 2-document profile built (spread for delta)")
            if pf_docs == 2:
                vf_json = subprocess.run([sys.executable, "-I", vf_script, "-",
                                          "--profile", str(learned / "profile-fit.json"), "--json"],
                                         input=clean, capture_output=True, text=True, env=env_base)
                try:
                    jvf = json.loads(vf_json.stdout)
                    ck(vf_json.returncode == 0 and jvf["reference"] == "profile"
                       and isinstance(jvf["burrows_delta"]["copy"], float)
                       and jvf["candidate"]["word count"] > 0,
                       "voice_fit profile mode: delta reads a float against the built profile")
                except Exception as e:
                    ck(False, f"voice_fit profile-mode JSON: {e!r}")
            vf_one = subprocess.run([sys.executable, "-I", vf_script, "-",
                                     "--samples", str(voice_fix / "clean"), "--json"],
                                    input=clean, capture_output=True, text=True, env=env_base)
            try:
                jone = json.loads(vf_one.stdout)
            except Exception:
                jone = None
            ck(vf_one.returncode == 0 and isinstance(jone, dict)
               and jone.get("burrows_delta", {}).get("sample_self") is None,
               "voice_fit spread rule: a sample corpus too small for leave-one-out reads n/a sample-self")
            r_ct = subprocess.run([sys.executable, "-I", str(ROOT / "humanizer" / "tests" / "test_voice_fit.py")],
                                  capture_output=True, text=True, env=env_base)
            tail_ct = (r_ct.stdout or r_ct.stderr or "").strip().splitlines()
            ck(r_ct.returncode == 0,
               f"voice_fit contract suite (sitefactory parity / gate no-op / fail-open / stdlib-only): "
               f"{tail_ct[-1] if tail_ct else r_ct.returncode}")
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

readme = (ROOT / "README.md").read_text()
ck("`humanizer/`" in readme, "README indexes humanizer plugin")
ck("PROVENANCE.md" in readme, "README links provenance ledger")

# --- Organization law (issue #8, MO ruling 2026-11-17): flatten + grouping cap ---
# Top-level folders are the highest grouping. Level 1 = top-level groups and
# top-level plugin entries; level 2 = entries inside a group. Entry-internal
# anatomy (a plugin's own hooks/, learn/, commands/, .claude-plugin/, a skill's
# references/) is NOT grouping and is unrestricted in depth. Adding a level-1
# dir or a level-2 entry requires editing these whitelists -> reviewable code
# change = explicit owner approval. Zero stubs / markers enforced below.
TOP_GROUPS = {"business", "engineering", "hobby", "research"}
TOP_PLUGINS = {"decision-advisor", "humanizer", "uxr-plugin"}
TOP_WHITELIST = TOP_GROUPS | TOP_PLUGINS | {"scripts", "tests"}
LEVEL2_WHITELIST = {
    "business": ["side-business-gtm"],
    "engineering": ["codebase-inspection", "deliberation", "iit-hci-integration", "llm-integration",
                    "meta-decision", "node-inspect-debugger", "prompt-engineering", "python-debugpy"],
    "hobby": ["media-taste-algo"],
    "research": ["academic", "document-to-action-items", "grounded-citations", "literature-review",
                 "meeting-action-items", "nlp-analyst"],
}
for name in sorted(p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")):
    ck(name in TOP_WHITELIST, f"top-level dir whitelisted (issue #8): {name}/")
ck(not (ROOT / "plugins").is_dir(), "no plugins/ grouping dir at top level (issue #8)")
for group in sorted(LEVEL2_WHITELIST):
    gp = ROOT / group
    if not gp.is_dir():
        ck(False, f"group dir present (issue #8): {group}/")
        continue
    for entry in sorted(p.name for p in gp.iterdir()):
        ck(entry in LEVEL2_WHITELIST[group], f"level-2 entry whitelisted in {group}/ (issue #8): {entry}")

# --- Zero-stub law (MO ruling 2026-11-18): pure deterministic file/regex checks ---
TEXT_EXTS = {".md", ".py", ".yaml", ".yml", ".json", ".txt"}
MARKER_RE = re.compile(
    r"\b(?:TODO|FIXME|XXX|HACK|stub|NotImplementedError)\b"
    r"|not yet implemented|not implemented|coming soon|to be implemented",
    re.IGNORECASE)
MARKER_EXEMPT = {"catalog.md", "PROVENANCE.md"}  # honest-ledger rows legitimately describe pending states
DEF_STUB_RE = re.compile(
    r"^(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]*)?:[ \t]*\n[ \t]+(?:pass|\.\.\.)[ \t]*(?:#.*)?$",
    re.MULTILINE)

# tracked files are the repo's published content (git ls-files): untracked
# machine caches (.mimosa/, .token-optimizer/, ...) are disk-local only and do
# not fail the law — same scope rule as the tracked-pyc check below.
tracked = [t for t in subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                                     capture_output=True).stdout.split(b"\x00") if t]
tracked = [t.decode("utf-8", "replace") for t in tracked]

# 0-byte tracked files anywhere. Named exception: the learned-phrase sink
# `*/learned/phrases.log` is empty until the first /voice run appends to it;
# the contract is existence (checked above), not content.
for t in tracked:
    p = ROOT / t
    if p.is_file() and p.stat().st_size == 0 and not (p.parent.name == "learned" and p.name == "phrases.log"):
        ck(False, f"0-byte file (zero-stub law): {t}")

# no tracked __pycache__/*.pyc anywhere: runtime bytecode artifacts are
# gitignored, so anything tracked here is committed cruft (the uxr-plugin husk
# pattern).
pyc_cruft = [t for t in tracked
             if t.endswith(".pyc") or "__pycache__" in pathlib.PurePosixPath(t).parts]
ck(not pyc_cruft, f"no tracked __pycache__/*.pyc anywhere (zero-stub law): {pyc_cruft[:5]}")

# stub markers in plugin/skill text files (word-boundary matched: prose like
# "stubborn" is not a marker). Inline `verify-allow: stub-marker` on the same
# or preceding line whitelists a load-bearing construct; rare and explicit.
for base in sorted(TOP_GROUPS | TOP_PLUGINS):
    bp = ROOT / base
    if not bp.is_dir():
        continue
    for p in sorted(bp.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in TEXT_EXTS) or p.name in MARKER_EXEMPT:
            continue
        lines = p.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            m = MARKER_RE.search(line)
            if not m:
                continue
            if "verify-allow" in line or (i > 1 and "verify-allow" in lines[i - 2]):
                continue
            ck(False, f"stub marker {m.group(0)!r} in {p.relative_to(ROOT).as_posix()}:{i} (zero-stub law)")

# pass-only / `...`-only function bodies in plugin .py files (fail-open
# `except: pass` handlers are not def bodies and are not flagged)
for base in sorted(TOP_PLUGINS):
    bp = ROOT / base
    if not bp.is_dir():
        continue
    for p in sorted(bp.rglob("*.py")):
        src = p.read_text(errors="replace")
        for m in DEF_STUB_RE.finditer(src):
            if "verify-allow" in m.group(0):
                continue
            ln = src[:m.start()].count("\n") + 1
            ck(False, f"pass/...-only function body in {p.relative_to(ROOT).as_posix()}:{ln} (zero-stub law)")

# --- De-personalization gate (owner ruling 2026-11-21) ----------------------
# Michael Oliver's personal voice artifacts (voice/, the zero-ai-tells register,
# the runtime hook adapter with his personal surfaces, his vectors/calibration,
# the linkedin voice guard + real article briefs) were REMOVED from the public
# mirror; canonical copies live in the private archive outside this repo. This
# scan makes the ruling mechanical: none of the tokens below may appear in any
# published plugin/skill content file. Allowed exceptions: frontmatter `author:`
# lines, the marketplace.json owner block, the law/ledger files (PROVENANCE.md,
# REVIEW.md, MAINTENANCE.md keep honest history), and CHANGELOG.md author credit
# lines. A hit anywhere else fails verification with file + line.
FORBIDDEN_TOKENS = [
    "/Users/moliver",
    "moliver/Downloads",
    "michaeleoliver.notion.site",
    "uxr-blog",
    "karahokes",
    "pierce county",
    "michael's voice",
    "owner order",
    "owner's canonical register",
    "voice spec (michael oliver)",
    "voice-michael-oliver",
]
DEPERSONALIZED_EXEMPT_FILES = {"PROVENANCE.md", "REVIEW.md", "MAINTENANCE.md"}


def _exempt_lines(path):
    """Line indexes exempt from the token scan in one file: frontmatter
    `author:` lines, marketplace.json's owner object, changelog author credits."""
    lines = path.read_text(errors="replace").splitlines()
    exempt = set()
    # frontmatter author lines (--- delimited block at the very top)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 2):
            if line.strip() == "---":
                break
            if re.match(r"^\s*author\s*:", line):
                exempt.add(i)
    # marketplace.json owner block: the object after the "owner" key
    if path.suffix == ".json":
        depth = None
        for i, line in enumerate(lines, 1):
            if depth is None:
                if '"owner"' in line and "{" in line:
                    depth = line.count("{") - line.count("}")
                    exempt.add(i)
                continue
            exempt.add(i)
            depth += line.count("{") + line.count("[") - line.count("}") - line.count("]")
            if depth <= 0:
                break
    # changelog author-credit lines
    if path.name == "CHANGELOG.md" and "author" in path.read_text(errors="replace").lower():
        for i, line in enumerate(lines, 1):
            if re.search(r"\bauthor\b", line, re.IGNORECASE):
                exempt.add(i)
    return exempt


dep_bases = sorted((TOP_GROUPS | TOP_PLUGINS))
dep_targets = []
for base in dep_bases:
    bp = ROOT / base
    if bp.is_dir():
        dep_targets += [p for p in sorted(bp.rglob("*"))
                        if p.is_file() and p.suffix.lower() in TEXT_EXTS
                        and p.name not in DEPERSONALIZED_EXEMPT_FILES]
dep_targets += [ROOT / f for f in ("README.md", "catalog.md", ".claude-plugin/marketplace.json")
                if (ROOT / f).is_file()]
for p in dep_targets:
    exempt = _exempt_lines(p)
    for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
        if i in exempt:
            continue
        low = line.lower()
        for tok in FORBIDDEN_TOKENS:
            if tok in low:
                ck(False, f"forbidden token {tok!r} in {p.relative_to(ROOT).as_posix()}:{i} "
                          f"(de-personalization ruling 2026-11-21)")

# dangling catalog/PROVENANCE path rows: a path named in a row must exist on
# disk. A token counts as a repo path only if its group segment is a whitelisted
# level-2 entry (prose references to removed dirs and the strikethrough REMOVED
# rows are not repo paths; removed top-level dirs drop out of the regex
# entirely); trailing punctuation is stripped (Windows tolerates a trailing dot
# in paths, Linux CI does not). "Published at X" statements are checked
# unconditionally; gated uxr-plugin carries no "Published at" row.
TOP_ALT = "|".join(sorted(TOP_WHITELIST))
ROW_PATH_RE = re.compile(rf"\b(?:{TOP_ALT})(?:/[\w.-]+)+")
for doc in ("catalog.md", "PROVENANCE.md"):
    dp = ROOT / doc
    if not dp.is_file():
        continue
    for i, line in enumerate(dp.read_text(errors="replace").splitlines(), 1):
        for m in ROW_PATH_RE.finditer(line):
            ref = m.group(0).rstrip(".,;:")
            parts = ref.split("/")
            if parts[0] in LEVEL2_WHITELIST and parts[1] not in LEVEL2_WHITELIST[parts[0]]:
                continue
            ck((ROOT / ref).exists(), f"{doc}:{i} referenced path exists: {ref}")
        pm = re.search(r"Published at ([\w./-]+)", line)
        if pm:
            ck((ROOT / pm.group(1)).is_dir(), f"{doc}:{i} Published-at target exists: {pm.group(1)}")

# --- uxr-plugin golden parity gates (W2 efficiency pass) -------------------
# The plugin's tests/test_parity.py regenerates every deterministic artifact
# from its fixture and compares it against the committed expected output, and
# hash-pins the baseline goldens (tests/goldens/, with DIFFERS markers on the
# four F1-F4 sections). A failure here means a UX-visible output drifted.
uxr = ROOT / "uxr-plugin"
#: parity harness at repo level; not in the installed plugin
uxr_tests = ROOT / "tests"
if uxr.is_dir() and uxr_tests.is_dir():
    parity = subprocess.run([sys.executable, str(uxr_tests / "test_parity.py")],
                            capture_output=True, text=True, cwd=str(uxr))
    tail = ((parity.stdout or "") + (parity.stderr or "")).strip().splitlines()
    ck(parity.returncode == 0, f"uxr-plugin golden parity tests (W2): {tail[-1] if tail else parity.returncode}")

# --- Researcher instruction gate (W4, issue #120): instruction changes are gated
# by the tuning harness's PASS record in tests/evals/hcd-researcher/baseline.json.
# The harness never runs and is never imported here; this reads its record only.
RESEARCHER_ASSET_FILES = (
    "uxr-plugin/agents/hcd-researcher.md",
    "uxr-plugin/prompts/hcd-gate/prompt.md",
    "uxr-plugin/references/script-rigor.md",
)
researcher_baseline_path = ROOT / "tests" / "evals" / "hcd-researcher" / "baseline.json"
if researcher_baseline_path.is_file():
    def _researcher_asset_hash(p):
        return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    current_assets = {
        rel: _researcher_asset_hash(ROOT / rel)
        for rel in RESEARCHER_ASSET_FILES if (ROOT / rel).is_file()
    }
    fragment_dir = ROOT / "uxr-plugin" / "prompts" / "hcd-gate" / "fragments"
    if fragment_dir.is_dir():
        for frag in sorted(fragment_dir.glob("*.md")):
            current_assets[f"uxr-plugin/prompts/hcd-gate/fragments/{frag.name}"] = \
                _researcher_asset_hash(frag)
    try:
        researcher_baseline = json.loads(researcher_baseline_path.read_text(encoding="utf-8"))
    except ValueError:
        researcher_baseline = {}
    recorded_assets = researcher_baseline.get("instruction_assets") or {}
    drift = sorted(
        asset for asset in set(recorded_assets) | set(current_assets)
        if recorded_assets.get(asset) != current_assets.get(asset)
    )
    pass_runs = [
        run_entry for run_entry in (researcher_baseline.get("runs") or [])
        if str(run_entry.get("verdict", "")).upper() == "PASS"
        and all(run_entry.get("instruction_assets", {}).get(asset) == current_assets.get(asset)
                for asset in drift)
    ]
    ck(not drift or bool(pass_runs),
       f"researcher instruction assets drifted without a PASS eval run (rule 13): {drift}")

# --- Efficiency gate (W1, MO ruling 2026-11-21) ------------------------------
# Release-lane only: CI arms VERIFY_EFFICIENCY=1 on develop -> main PRs, so
# ordinary pushes run the base checks unchanged. The recorded floor lives in
# tests/efficiency-baseline.json (recorded with the repo's shipped ex-tests
# counting convention, cited in the file). The gate FAILs any payload growth
# and lists the growing dirs, so the release PR must argue the growth by
# recording a justification in the baseline file in the same PR. Golden
# immobility and the hash pins are already enforced above by tests/test_parity.py;
# the REF line below points at that check, it does not repeat it.
if "--efficiency" in sys.argv or os.environ.get("VERIFY_EFFICIENCY") == "1":
    eff_base = json.loads((ROOT / "tests" / "efficiency-baseline.json").read_text())
    eff_just = eff_base.get("justifications", {})
    cur_total, cur_dirs = 0, {}
    for t in tracked:
        if not t.startswith("uxr-plugin/") or t.startswith("uxr-plugin/tests/"):
            continue
        if not t.endswith((".py", ".md", ".yaml", ".yml")):
            continue
        raw = (ROOT / t).read_bytes()
        n = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
        cur_total += n
        d = t.split("/")[1] if len(t.split("/")) > 2 else "root"
        cur_dirs[d] = cur_dirs.get(d, 0) + n
    floor = eff_base["payload"]["total_lines"]
    grew = sorted(d for d, n in cur_dirs.items() if n > eff_base["payload"]["per_dir"].get(d, 0))
    ck(cur_total <= floor or bool(eff_just.get("payload_growth")),
       f"payload {cur_total} lines vs baseline {floor} (tolerance 0; growing dirs: "
       + (", ".join(grew) if grew else "none") + ")")
    ck(not grew or bool(eff_just.get("payload_growth")),
       "payload growth (if any) justified in tests/efficiency-baseline.json (the release PR must argue it)")
    declared = []
    for t in tracked:
        if not t.startswith("uxr-plugin/") or not t.endswith(".md"):
            continue
        for line in (ROOT / t).read_text(errors="replace").splitlines():
            if "golden path" not in line.lower():
                continue
            for m in re.finditer(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+model\s+calls?\b",
                                 line, re.IGNORECASE):
                declared.append({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                                 "seven": 7, "eight": 8, "nine": 9, "ten": 10}.get(m.group(1).lower())
                                or int(m.group(1)))
    budget = eff_base["golden_path_model_calls"]
    if not declared:
        ck(False, f"declared golden-path model-call budget present in plugin md (baseline records {budget})")
    else:
        ck(max(declared) <= budget or bool(eff_just.get("golden_path_growth")),
           f"declared golden-path model calls {max(declared)} vs baseline {budget} "
           "(growth FAILs without a recorded justification)")
    pins = len(json.loads((ROOT / "tests" / "goldens" / "hashes.json").read_text()))
    print(f"REF efficiency: golden immobility + {pins} hash pins enforced above by "
          "tests/test_parity.py (referenced, not duplicated)")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
