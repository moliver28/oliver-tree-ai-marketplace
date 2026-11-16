#!/usr/bin/env python3
"""voice-gate.py: pre_tool_call shell hook. Mechanical enforcement of Michael's
zero-AI-tells bar (owner order 2026-11-11) across any session that registers it.

stdin JSON: {tool_name, args, session_id, ...} per agent/shell_hooks.py.
stdout JSON: {} (allow) | {"decision": "block", "reason": ...} | {"decision": "modify", "text": ...}
Every fire logs JSONL to <HERMES_HOME>/logs/voice-gate.log.

Routing by tool_name:
- discord / slack (chat sends): scan the outgoing text. One banned hit blocks.
  Status-token lines ([SILENT], NO-POST, POSTED, DELIVERY-FAILED, CRON_FAILURE,
  DRAFT-READY, DRAFT-BLOCKED, [CRON_FAILURE]) and code-fence bodies pass.
- write_file: scan content only when the path is a public-facing surface
  (career materials, uxr-blog pipeline/posts/marketing, personal sites, resumes).
- terminal: when the command renders a PDF (pandoc or headless Chrome
  --print-to-pdf), demand a `<source-stem>.voice-pass` marker written by
  voice-check.py next to the source; refuse the render without it.
- delegate_task: if any task goal touches resume / cover letter / career /
  portfolio prose, append the enforcement contract to the goal (modify).

Fail-soft on internal errors: return {} and log; blocks only come from the
decisions below, never from a crash.
"""
import json, os, re, sys
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "logs" / "voice-gate.log"

_spec = importlib.util.spec_from_file_location(
    "voice_tells", str(Path(__file__).resolve().parent / "voice-tells.py"))
_tells = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tells)


def _find_banned(text, use_vector=True):
    """Shared detection core (voice-tells.py): regex layer always; vector layer
    (cosine vs tell exemplars via local Ollama) when prose is long enough and
    the service is up. Fail-open on any vector-infrastructure miss."""
    return _tells.scan(text, use_vector=use_vector)

STATUS_MARKERS = ("[SILENT]", "[CRON_FAILURE]", "NO-POST", "POSTED", "DELIVERY-FAILED",
                  "DRAFT-READY", "DRAFT-BLOCKED", "VOICE-GATE", "N8N-HERMES", "BRIDGE-OK")

PUBLIC_PATH_RE = re.compile(
    r"(/Documents/career/|/career/|resume|cover[- _]?letter|uxr-blog|karahokes|"
    r"investigation|github\.io|/posts/|/marketing/)", re.I)

VOICE_CHECK_HELP = (
    "Zero-AI-tells gate: no <source>.voice-pass marker next to the source file. "
    "Run `python3 ~/.hermes/agent-hooks/voice-check.py <source>` first; it exits "
    "nonzero with the offending lines until the text is clean, then writes the "
    "marker and the render may proceed.")

def _texts_from_args(args):
    out = []
    if isinstance(args, dict):
        for v in args.values():
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict):
                        out.extend(s for s in item.values() if isinstance(s, str))
    return out


def _log(event_label, detail):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "event": event_label, **detail}) + "\n")
    except Exception as e:
        sys.stderr.write("voice-gate _log error: %r\n" % (repr(e),))

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    tool = str(payload.get("tool_name", ""))
    args = payload.get("args") or {}

    try:
        # --- chat sends (discord / slack) ---
        if tool in ("discord", "slack", "send_message"):
            texts = _texts_from_args(args)
            joined = "\n".join(texts)
            if joined.strip() and not any(mk in joined for mk in STATUS_MARKERS):
                # skip pure code bodies
                prose = "\n".join(l for l in joined.splitlines() if not l.strip().startswith("```"))
                hits = _find_banned(prose)
                if hits:
                    _log("chat_block", {"tool": tool, "hits": hits})
                    print(json.dumps({"decision": "block",
                        "reason": "Zero-AI-tells gate (owner order 2026-11-11): " + "; ".join(hits[:4]) +
                        ". Rewrite in Michael's voice (humanizer skill) and resend."}))
                    return
            _log("chat_pass", {"tool": tool})
            print(json.dumps({}))
            return

        # --- file writes on public-facing surfaces ---
        if tool in ("write_file", "Write", "write"):
            path = ""
            if isinstance(args, dict):
                path = str(args.get("path") or args.get("file_path") or "")
            content = str(args.get("content", "")) if isinstance(args, dict) else ""
            if PUBLIC_PATH_RE.search(path):
                hits = _find_banned(content)
                if hits:
                    _log("write_block", {"path": path, "hits": hits})
                    print(json.dumps({"decision": "block",
                        "reason": f"Zero-AI-tells gate on public-facing path {path}: " + "; ".join(hits[:4]) +
                        ". Fix the content (humanizer skill) and rewrite."}))
                    return
            _log("write_ok", {"path": path})
            print(json.dumps({}))
            return

        # --- PDF render gate ---
        if tool in ("terminal", "Terminal", "Bash"):
            cmd = str(args.get("command", "")) if isinstance(args, dict) else str(args)
            if "pandoc" in cmd and ("print-to-pdf" in cmd or "-o" in cmd and ".pdf" in cmd):
                src = None
                for tok in cmd.replace("(", " ").replace(")", " ").split():
                    if tok.endswith(".md") or tok.endswith(".txt") or tok.endswith(".html") or tok.endswith(".tex"):
                        src = Path(tok)
                        break
                if src and src.exists():
                    marker = src.with_suffix("." + src.suffix.lstrip(".") + "-voice-pass") if False else src.with_name(src.stem + ".voice-pass")
                    if not marker.exists():
                        _log("render_block", {"cmd": cmd[:200], "missing_marker": str(marker)})
                        print(json.dumps({"decision": "block", "reason": VOICE_CHECK_HELP}))
                        return
                elif src:
                    _log("render_block", {"cmd": cmd[:200], "src_not_found": str(src)})
                    print(json.dumps({"decision": "block", "reason": VOICE_CHECK_HELP}))
                    return
                else:
                    _log("render_block", {"cmd": cmd[:200], "no_source_found": True})
                    print(json.dumps({"decision": "block", "reason": VOICE_CHECK_HELP}))
                    return
            print(json.dumps({}))
            return

        # --- delegation brief injection for career-family tasks ---
        if tool in ("delegate_task", "delegation"):
            goals = ""
            if isinstance(args, dict):
                for t in (args.get("tasks") or []):
                    if isinstance(t, dict):
                        goals += "\n" + str(t.get("goal", ""))
            if re.search(r"resume|cover letter|job application|portfolio|career", goals, re.I):
                contract = ("\n\n[voice-gate contract] Owner order 2026-11-11: every resume bullet, cover letter "
                            "paragraph, summary and case-study line must pass the zero-AI-tells scan "
                            "(python3 ~/.hermes/agent-hooks/voice-check.py <file>) before any file is written "
                            "or PDF rendered; the render gate rejects PDFs without the .voice-pass marker. "
                            "Register: committed first-person ownership verbs, plain declarative evidence, "
                            "no banned vocabulary. Report the scan verdict with the deliverable.")
                _log("delegate_inject", {"chars": len(contract)})
                print(json.dumps({"decision": "modify",
                    "args_patch": {"tasks": _append_goal_contract(args.get("tasks"), contract)}}))
                return
            print(json.dumps({}))
            return
    except Exception as e:
        _log("error", {"tool": tool, "err": repr(e)})
        print(json.dumps({}))
        return


def _append_goal_contract(tasks, contract):
    if not isinstance(tasks, list):
        return tasks
    out = []
    for t in tasks:
        if isinstance(t, dict):
            t = dict(t)
            t["goal"] = str(t.get("goal", "")) + contract
        out.append(t)
    return out

if __name__ == "__main__":
    main()
