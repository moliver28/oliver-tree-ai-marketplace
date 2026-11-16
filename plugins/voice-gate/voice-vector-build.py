#!/usr/bin/env python3
"""voice-vector-build.py: embed the tell exemplars once and cache them.

Usage: python3 voice-vector-build.py
Writes ~/.hermes/state/voice-tells-vectors.json, tagged with model + build time.
Re-run after editing EXEMPLARS in voice-tells.py. Needs Ollama with
nomic-embed-text running locally.
"""
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location(
    "voice_tells", "/Users/moliver/.hermes/agent-hooks/voice-tells.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)


def main():
    out = {"model": vt.MODEL, "built": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), "vectors": []}
    labels = {
        0: "negative-parallelism", 1: "paradigm-shift inflation", 2: "testament/commitment copula",
        3: "nestled/vibrant promo", 4: "pivotal-moment landscape", 5: "rapidly-evolving opener",
        6: "at-the-end-of-the-day authority", 7: "dive-in signpost", 8: "real-question authority",
        9: "game-changer empowerment sweep", 10: "antimetabole/aphorism density",
        11: "experts-underscore weasel", 12: "challenges-and-prospects formula",
        13: "funeral/reframe motif hammer", 14: "reassurance kicker", 15: "robust-solutions slop",
    }
    for i, text in enumerate(vt.EXEMPLARS):
        v = vt._embed(text, timeout=30)
        out["vectors"].append({"label": labels.get(i, f"tell-{i}"), "text": text, "vec": v})
        print(f"embedded {i}: {labels.get(i,'?')}")
    vt.VEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    vt.VEC_PATH.write_text(vt.json.dumps(out))
    print(f"wrote {vt.VEC_PATH} with {len(out['vectors'])} vectors")


if __name__ == "__main__":
    main()
