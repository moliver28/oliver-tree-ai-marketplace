"""Mail-merge .gs selftest: the Task 1 contract pins (wave 2, #91/#92).

Checks, at the text level (the Apps Script file cannot run outside
Google), that ``uxr-plugin/google/mail-merge.gs`` exists within the LOC
budget, declares the five contract functions (``mergeSend``, ``scheduleSend``,
``doGet``, ``syncEvents``, ``setupScreener``), carries the three web-app
route markers (``?o=`` open pixel, ``?c=`` + ``go`` click, ``?u=``
unsubscribe), runs the send pass under ``LockService`` inside ``mergeSend``,
names all ten Config-tab cells, and writes the screener confirmation text
``Book your session:``; that the sync section carries the pending-only
cancellation guard (a vanished match cancels a ``pending`` row, a ``sent``
row gets a note, never a resend); that the task 9b fix pass holds (the
``_plainCell`` formula-injection guard on every appended value, the
``e.source.getTitle()`` form API, the per-row try/catch and quota gate in
the due-send loop, the send-first ``sendScheduled`` ordering, cancelled
rows never blocking re-created events, the one-click click interstitial,
the unsub id-row match guard, and the ``TRACK_DAILY_CAP`` counter); and
that ``uxr-plugin/google/README.md`` carries the SETUP law (paste into
Extensions > Apps Script, Deploy > New deployment > Web app, "Execute as:
me", "Who has access: Anyone") and the ``syncEvents`` trigger step. Pure
stdlib; rides the smoke check-3 glob; parity enrollment is out of scope
(W2 adapters precedent).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GS = ROOT / "uxr-plugin" / "google" / "mail-merge.gs"
README = ROOT / "uxr-plugin" / "google" / "README.md"

EXIT_OK = 0        # all checks passed
EXIT_SELFTEST = 3  # selftest failure exit (runner convention)
LOC_BUDGET = 420   # plan Task 1 set 400; the 9b fix pass raised it to 420

FUNCTIONS = ("mergeSend", "scheduleSend", "doGet", "syncEvents", "setupScreener")
ROUTES = ("?o=", "?c=", "?u=")
CONFIG_CELLS = (
    "webapp_url", "tracking_on", "unsub_on", "calendar_name", "event_regex",
    "followup_hours", "prep_on", "prep_lead_hours", "booking_url", "form_id",
)
SETUP_PHRASES = (
    "Extensions > Apps Script",
    "Deploy > New deployment",
    "Web app",
    "Execute as: me",
    "Who has access: Anyone",
    "syncEvents",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start_marker: str, end_marker: str) -> str:
    """The source slice between two section banners (the sync law spans the
    syncEvents function plus its _syncFollowups/_syncPrep helpers)."""
    start = text.index(start_marker)
    end = text.find(end_marker, start)
    return text[start:end if end != -1 else len(text)]


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/mailmerge_gs.py selftest")

    check("uxr-plugin/google/mail-merge.gs exists", GS.is_file(), str(GS))
    gs = _text(GS) if GS.is_file() else ""
    readme = _text(README) if README.is_file() else ""

    lines = gs.count("\n") + (1 if gs and not gs.endswith("\n") else 0)
    check(f"the .gs fits the LOC budget (<= {LOC_BUDGET} incl. comments)",
          0 < lines <= LOC_BUDGET, f"{lines} lines")

    for name in FUNCTIONS:
        check(f"the .gs declares function {name}(",
              f"function {name}(" in gs, "declaration not found")

    for route in ROUTES:
        check(f"the .gs carries the web-app route marker {route}",
              route in gs, "route marker not found")

    send_body = _section(gs, "function mergeSend(", "\nfunction _tokenOf(")
    check("the send pass runs under LockService inside mergeSend",
          "LockService" in send_body and "tryLock(" in send_body,
          "no script lock in the send function")
    check("mergeSend stamps the Email Sent cell",
          '"Email Sent"' in send_body, "stamp column not named")
    check("mergeSend skips stamped rows (never double-send)",
          "continue" in send_body and "stamp" in send_body, "no skip path")

    # Task 9b fix 1: the formula-injection guard on every appended value.
    check("the .gs declares _plainCell(", "function _plainCell(" in gs,
          "guard helper missing")
    check("_plainCell covers the six formula prefixes (= + - @ tab CR LF)",
          "/^[=+\\-@\\t\\r\\n]/" in gs and """? "'" + t : t""" in gs,
          "prefix set or quote branch drifted")
    track_body = _section(gs, "function _track(", "\nfunction _findById(")
    check("_track passes every appended value through _plainCell",
          track_body.count("_plainCell(") >= 4, str(track_body.count("_plainCell(")))
    check("_track runs the daily cap counter over Script Properties",
          "TRACK_DAILY_CAP" in track_body and "getScriptProperties" in track_body
          and '"track_count"' in track_body, "cap counter missing")
    form_body = _section(gs, "function onFormSubmit(", "\n// --- end of file marker")
    check("the form append passes the respondent values through _plainCell",
          "_plainCell(email)" in form_body and "_plainCell(name)" in form_body
          and "_plainCell(study)" in form_body, "unwrapped append values")

    # Task 9b fix 2: the submit event carries the Form on e.source.
    check("the study name reads e.source.getTitle()",
          "e.source.getTitle()" in form_body, "form API call missing")
    check("the nonexistent getFormTitle API is gone",
          "getFormTitle" not in gs, "bad API still present")

    sync_law = _section(gs, "function syncEvents(",
                        "// --- screener Form")
    check("syncEvents reads calendar_name and event_regex from Config",
          '"calendar_name"' in sync_law and '"event_regex"' in sync_law,
          "config cells not read")
    check("syncEvents scans the matched calendar through CalendarApp",
          "CalendarApp.getCalendarsByName(" in sync_law
          and ".getEvents(" in sync_law, "no calendar scan")
    check("the sync path runs under LockService",
          "LockService" in sync_law and 'tryLock(' in sync_law, "no script lock")
    check("syncEvents gates Prep rows on prep_on",
          '"prep_on"' in sync_law and '"prep_lead_hours"' in sync_law,
          "prep gate not read")
    check("due pending Followups rows send and stamp sent",
          '"followup_hours"' in sync_law
          and '_stampFollowup(sheet, i + 2, "sent"' in sync_law,
          "no due-row send path")
    check("every sync send gates on the remaining daily quota",
          "MailApp.getRemainingDailyQuota() > 0" in sync_law,
          "no quota gate")
    # Task 9b fix 5: one bad row never wedges the pass.
    check("the due-send wraps the send in a per-row try/catch",
          "catch (err)" in sync_law and '"failed"' in sync_law,
          "no per-row failure isolation")
    check("an exhausted quota skips with a note and stays pending",
          '"skipped: daily quota exhausted"' in sync_law
          and '_stampFollowup(sheet, i + 2, "pending"' in sync_law,
          "quota skip not recorded")
    # Pending-only cancellation guard: a vanished match cancels a pending row;
    # a sent row gets a Tracking note only - never a resend, never a rewrite.
    check("a vanished match cancels only pending rows",
          'status === "pending"' in sync_law and 'setValue("cancelled")' in sync_law,
          "no pending-only cancellation guard")
    check("a sent row with a vanished match gets a note, never a resend",
          '"event removed after send"' in sync_law
          and '_stampFollowup(sheet, i + 2, "sent"'
          not in sync_law.split('"event removed after send"')[0],
          "resend risk on vanished events")
    # Task 9b fix 7: cancelled rows never block a re-created event.
    check("a cancelled Followups row never seeds the seen set",
          'if (status === "cancelled") continue;' in sync_law
          and sync_law.index('if (status === "cancelled") continue;')
          < sync_law.index("seen[key] = true;"),
          "cancelled rows still block re-appends")
    prep_body = _section(gs, "function _syncPrep(", "// --- screener Form")
    check("a cancelled prep row never seeds the seen set",
          'indexOf("[cancelled] ") === 0) continue;' in prep_body
          and prep_body.index('indexOf("[cancelled] ") === 0) continue;')
          < prep_body.index("seen[key] = true;"),
          "cancelled prep rows still block re-appends")

    # Task 9b fix 6: the scheduled handler sends first, cleans up on success.
    sched_body = _section(gs, "function sendScheduled(",
                          "\n// --- web app routes")
    check("sendScheduled runs mergeSend before the trigger cleanup",
          "mergeSend(" in sched_body and "deleteProperty" in sched_body
          and sched_body.index("mergeSend(") < sched_body.index("deleteProperty"),
          "cleanup runs before the send")

    # Task 9b fix 10: the web-app abuse surfaces.
    doget_body = _section(gs, "function doGet(",
                          "\n// --- calendar-timed")
    check("the click route returns a one-click interstitial",
          '"<p>Continue to " + _esc(host)' in doget_body, "no interstitial page")
    check("the instant meta-refresh redirector is gone",
          "http-equiv" not in doget_body, "meta-refresh still present")
    check("the unsub honors u only against a Wave-tab row (m-only is unverified)",
          "!!who.email" in doget_body and '"unverified"' in doget_body,
          "no id-row match guard")

    for cell in CONFIG_CELLS:
        check(f"the .gs names the Config cell {cell}",
              cell in gs, "config cell not found")

    check("the screener confirmation text is Book your session: <booking_url>",
          'setConfirmationMessage("Book your session: " + booking)' in gs,
          "confirmation text drifted")

    check("uxr-plugin/google/README.md exists", README.is_file(), str(README))
    for phrase in SETUP_PHRASES:
        check(f"the SETUP doc names {phrase!r}", phrase in readme,
              "SETUP phrase not found")
    check("the SETUP doc carries the tracking-limits paragraph",
          "image proxy" in readme and "not trackable" in readme,
          "limits paragraph missing")
    check("the SETUP doc states the write-side bounds (interstitial, "
          "unverified unsub, 500/day cap)",
          "continuation page" in readme and "`unverified`" in readme
          and "500 rows a day" in readme, "write-side limits missing")
    check("the SETUP doc carries the Followups note column law",
          "`failed`" in readme and "`note`" in readme,
          "failed/note schema missing")

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
