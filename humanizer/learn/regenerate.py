#!/usr/bin/env python3
"""regenerate.py: one scripted regenerate pass over the derived artifacts
(issue #5 ruling, clause 3: "one scripted regenerate pass moves data to
everything that mirrors it").

Every deterministic builder in learn/ rebuilds its artifact from source
data and is hash-guarded, so re-running the whole chain rebuilds exactly
what the grown data changed and nothing else. This script runs the chain
in one pass, in a fixed order, one line per step, zero model tokens:

1. calibrate.py            regex hit rates over the clean corpus
                           (needs --corpus; skipped with a note otherwise)
2. distill_phrases.py      phrases.log -> rules.json (defined empty-log
                           behavior; safe to run any time)
3. voice_vector_build.py   effective exemplars -> vectors, per-class
                           thresholds, clean-corpus centroid (hash-guarded;
                           skipped with a note when no embedder answers)
4. train_voice_classifier.py  char n-gram classifier (needs --corpus;
                           hash-guarded; skipped with a note otherwise)
5. build_voice_profile.py  battery profile from the sample documents
                           (needs --samples; skipped with a note otherwise)
6. reference pool refresh  the stored pool vectors recompute any stale or
                           missing battery rows from the stored text, then
                           the bands and factors rebuild from the refreshed
                           vectors (learn/voice_setup.py pool_refresh +
                           bands_from_pool; the pool is the stored record)

Laws: learners write DATA files only, never gate code (clause 2 of the
ruling); each step fails open (a missing input or an unavailable embedder
is one skip line, never an error); the order is fixed and the output is
deterministic for identical inputs. Nothing here runs a model.

Exit codes: 0 = the pass ran (skip lines are expected, not failures);
2 = bad usage (a named --corpus/--samples path does not exist).

Usage:
    python3 humanizer/learn/regenerate.py
    python3 humanizer/learn/regenerate.py --corpus <clean writing dir> --samples <sample dir>
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/


def _load(name):
    spec = importlib.util.spec_from_file_location("regenerate_" + name, HERE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_step(label, fn):
    """One builder step: one result line, one skip line on any failure."""
    try:
        line = fn()
    except SystemExit as e:
        line = "skipped (exit %s)" % (e.code,)
    except Exception as e:
        line = "skipped (%s)" % (repr(e)[:120],)
    print("regenerate %s: %s" % (label, line))
    return line


def _call_main(mod, tool, *args):
    """Run a tool main() with an injected argv; returns its exit code."""
    saved = sys.argv
    try:
        sys.argv = [tool] + list(args)
        return mod.main()
    finally:
        sys.argv = saved


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="regenerate.py",
        description="One scripted regenerate pass: rebuild every derived artifact "
                    "from source data (hash-guarded builders, fail-open steps, zero model tokens).")
    parser.add_argument("--corpus", default=None,
                        help="clean writing directory (.md/.txt); enables the calibrate and "
                             "classifier steps (both hash-guarded)")
    parser.add_argument("--samples", default=None,
                        help="sample documents directory; enables the battery profile step")
    args = parser.parse_args(argv)
    for name, value in (("corpus", args.corpus), ("samples", args.samples)):
        if value and not Path(value).expanduser().is_dir():
            print("usage: --%s must be a directory: %s" % (name, value), file=sys.stderr)
            return 2

    # 1. calibrate (regex hit rates over the clean corpus)
    if args.corpus:
        cal = _load("calibrate")
        _run_step("calibrate", lambda: _call_main(
            cal, "calibrate.py", "--corpus", args.corpus) == 0 and "calibration.json written")
    else:
        print("regenerate calibrate: skipped (--corpus not given)")

    # 2. distill_phrases (defined empty-log behavior); the output goes to the
    # configured learned dir explicitly, because distill_phrases.py's own
    # default predates the VOICE_LEARNED_DIR override contract
    dist = _load("distill_phrases")
    learned = Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))
    _run_step("distill", lambda: _call_main(dist, "distill_phrases.py",
                                            "--out", str(learned / "rules.json")) == 0
              and "rules.json written")

    # 3. voice_vector_build (hash-guarded; embedder or not)
    vb = _load("voice_vector_build")
    _run_step("vectors", lambda: _call_main(vb, "voice_vector_build.py") in (0, None)
              and "vector artifacts current or rebuilt")

    # 4. train_voice_classifier (hash-guarded)
    if args.corpus:
        tc = _load("train_voice_classifier")
        _run_step("classifier", lambda: _call_main(
            tc, "train_voice_classifier.py", "--corpus", args.corpus) == 0
            and "classifier current or retrained")
    else:
        print("regenerate classifier: skipped (--corpus not given)")

    # 5. build_voice_profile (battery profile from the samples)
    if args.samples:
        bp = _load("build_voice_profile")
        _run_step("profile", lambda: _call_main(
            bp, "build_voice_profile.py", args.samples) in (0, None)
            and "profile.json rebuilt from the samples")
    else:
        print("regenerate profile: skipped (--samples not given)")

    # 6. reference pool refresh + bands rebuild from the stored vectors
    def _pool():
        vs = _load("voice_setup")
        records, updated = vs.pool_refresh()
        if not records:
            return "pool empty (ingest samples with /voice-setup); nothing refreshed"
        bands, notes = vs.bands_from_pool()
        if bands is None:
            return "pool refresh: %d vectors held, %d recomputed; bands not rebuilt (%s)" % (
                records, updated, "; ".join(notes) or "no bands derivable")
        (vs.state_dir() / "voice-bands.json").write_text(
            json.dumps(bands, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return "pool refresh: %d vectors held, %d recomputed; bands rebuilt from the vectors" % (
            records, updated)
    _run_step("pool", _pool)

    return 0


if __name__ == "__main__":
    sys.exit(main())
