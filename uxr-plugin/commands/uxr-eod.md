---
description: "Draft end-of-day ticket comments from the session journal: shows every draft, posts only on approval"
argument-hint: "[--dry-run] [--days=<YYYY-MM-DD | A..B>] [--ticket=<KEY>] [--auto]"
---

Draft end-of-day comments for the study tickets touched today (or over a
day range), from the session journal the SessionEnd hook writes. The
comment drafts are yours to write; the posting decision is always the
user's -- except `--auto`, which posts facts only and skips anything
already commented today. Read-only activity is listed, never posted,
unless the user pulls it in.

It uses `get_item` and `add_comment` from `references/tracker.md` (never
`update_item`, `create_item`, or `set_state`), reads the journal under
`paths.state_dir`, and never sends anything else.

## Inputs

`$ARGUMENTS` may hold any of:

1. `--dry-run`: show the drafts, post nothing, leave `processed`
   untouched. This flag always wins.
2. `--days=<YYYY-MM-DD>` or `--days=<A>..<B>` (inclusive; default today).
3. `--ticket=<KEY>`: draft for that ticket only.
4. `--auto`: non-interactive for a scheduled run (the user sets up
   launchd or cron themselves; this command never configures a
   scheduler).

## Steps

1. Read configuration once: run
   `python "${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print` and note
   `paths.state_dir`, `tracker.kind`, `tracker.ticket_regex`,
   `tracker.bare_number_prefix`, and `comments.footer`. Fill every
   `<placeholder>` below from that output; hardcode nothing.
2. Build the day list from `--days` (one date, or `A..B` expanded
   inclusive; default: today only). The journal lives at
   `<state_dir>/work-log-<YYYY-MM-DD>.jsonl`, one file per local day.
3. Filter and group deterministically -- run this and use its output
   verbatim, never a re-computation:

   ```bash
   python - <<'PY'
   import json
   from pathlib import Path
   state = Path(r"<state_dir>")
   days = ["<day 1>", "<day 2>"]   # the resolved day list
   key = "<KEY>"                    # empty unless --ticket was passed
   rows = []
   for day in days:
       path = state / ("work-log-%s.jsonl" % day)
       if not path.is_file():
           continue
       for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
           line = line.strip()
           if not line:
               continue
           try:
               row = json.loads(line)
           except ValueError:
               continue  # malformed lines stay as they are
           if not isinstance(row, dict) or row.get("processed"):
               continue
           if key and key not in (row.get("ticket_keys") or []):
               continue
           rows.append(row)
   active, readonly, unlinked = {}, [], []
   for row in rows:
       keys = row.get("ticket_keys") or []
       if not keys and row.get("in_research_dir"):
           unlinked.append(row)
           continue
       for k in keys:
           bucket = active.setdefault(k, [])
           bucket.append(row)
   for k, bucket in active.items():
       if all(not row.get("files_edited_count") and not row.get("tracker_tool_calls")
              for row in bucket):
           readonly.extend(bucket)
           continue
       active[k] = bucket
   for k in [k for k, v in active.items() if not v]:
       del active[k]
   print(json.dumps({"active": {k: len(v) for k, v in active.items()},
                     "readonly_sessions": [r.get("session_id") for r in readonly],
                     "unlinked_sessions": [r.get("session_id") for r in unlinked]},
                    indent=2))
   PY
   ```

4. No rows at all: print exactly one line and stop --
   `No unposted UX research work for <date>.` (a single date) or
   `No unposted UX research work for <A>..<B>.` (a range). Nothing else.
5. Groups with no ticket key but `in_research_dir: true` go under a
   `No ticket linked` heading (session ids and cwd only). Post nothing
   for them; offer `new` as the follow-up in one line.
6. Read-only groups (no file edits, no tracker calls) print under
   `Skipped (read-only activity)`. The user can pull one in later with
   `include <KEY>`.
7. For each active ticket: call `get_item` (fields + Markdown body +
   comments, per `references/tracker.md`) and `item_url(key)`. Look for
   an existing comment whose first line is `[ux-eod <date>]` for the
   target date.
8. Draft ONE comment per active ticket (this is your writing work):

   - First line exactly `[ux-eod <YYYY-MM-DD>]`.
   - Lead with the work done today (sessions, what they settled); name
     one or two concrete files or decisions; close with next steps.
   - Never restate the study background; never invent work the journal
     does not show; never include session ids or snippets.
   - End with one blank line and the footer from `comments.footer`
     with `{display_name}` replaced by the current user's display name
     (`current_user()`; cache it for the session).
   - At most 300 words total. Verify each draft mechanically before
     showing it:

   ```bash
   python - <<'PY'
   from pathlib import Path
   text = Path(r"<draft file>").read_text(encoding="utf-8")
   footer = """<comments.footer with {display_name} already replaced>"""
   print(len(text.split()), text.rstrip().endswith(footer.strip()))
   PY
   ```

   A draft over 300 words gets shortened before it is shown, not after.

9. **The gate.** Show every draft together, then stop and wait for one
   reply: `go` (post all), `skip <KEY>` (leave that one unprocessed),
   `edit <KEY>` (apply the user's wording, re-verify the cap, show it
   again), `include <KEY>` (draft for a skipped read-only group after
   pulling its rows), or `cancel`. When today's `[ux-eod <date>]`
   comment already exists, ask for that ticket: append or replace.
   Under `--dry-run`: show the drafts under a `DRY RUN - nothing posted`
   heading, then stop -- no posting, no journal rewrite.
10. On `go`: call `add_comment(key, <draft>)` once per approved ticket.
    A failed post is reported and leaves that ticket unprocessed. Then
    rewrite the journal so `processed: true` for every posted ticket's
    rows AND every skipped read-only row (read-only work is done; it
    must not resurface tomorrow). Run the rewrite once, verbatim:

    ```bash
    python - <<'PY'
    import json, os, sys, tempfile
    from pathlib import Path
    sys.path.insert(0, r"<plugin root>/hooks")
    from provenance import file_lock
    state = Path(r"<state_dir>")
    days = ["<day 1>", "<day 2>"]
    posted = {"<KEY 1>", "<KEY 2>"}          # approved tickets
    readonly = {"<session_id>", "<session_id>"}  # read-only session ids
    for day in days:
        path = state / ("work-log-%s.jsonl" % day)
        if not path.is_file():
            continue
        with file_lock(path.with_name(path.name + ".lock")):
            out = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except ValueError:
                    out.append(stripped)  # malformed lines stay as they are
                    continue
                if (isinstance(row, dict)
                        and not row.get("processed")
                        and (set(row.get("ticket_keys") or []) & posted
                             or row.get("session_id") in readonly)):
                    row["processed"] = True
                out.append(json.dumps(row, ensure_ascii=False)
                           if isinstance(row, dict) else stripped)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name,
                                       suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(out) + "\n")
            os.replace(tmp, path)
    PY
    ```

    Print one line per posted ticket:
    `Posted [ux-eod <date>] to [KEY](url).` using `item_url(key)`.
11. `--auto` (no user present): draft facts only from the journal rows
    (files edited, tracker calls, commands run -- one short sentence
    each, no narrative), skip any ticket that already has today's
    `[ux-eod <date>]` comment, post, rewrite `processed`, and print the
    same `Posted ...` lines. Under `--auto` the gate is skipped by
    design; without `--auto` the gate in step 9 is never skipped.

## Safety

- Every draft is shown before anything posts; only `go` (or `--auto`)
  posts. `cancel` and `skip <KEY>` are always honored first.
- `--dry-run` posts nothing and leaves `processed` untouched: a second
  `--dry-run` on the same day shows the same unprocessed rows.
- Read-only work is listed under `Skipped (read-only activity)`, never
  drafted into a ticket comment unless `include <KEY>` says so.
