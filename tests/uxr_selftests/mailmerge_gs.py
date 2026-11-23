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
row gets a note, never a resend); and that ``uxr-plugin/google/README.md``
carries the SETUP law (paste into Extensions > Apps Script, Deploy > New
deployment > Web app, "Execute as: me", "Who has access: Anyone") and the
``syncEvents`` trigger step. Pure stdlib; rides the smoke check-3 glob;
parity enrollment is out of scope (W2 adapters precedent).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GS = ROOT / "uxr-plugin" / "google" / "mail-merge.gs"
README = ROOT / "uxr-plugin" / "google" / "README.md"

EXIT_OK = 0        # all checks passed
EXIT_SELFTEST = 3  # selftest failure exit (runner convention)
LOC_BUDGET = 400   # plan Task 1: .gs lines incl. comments

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
          '"followup_hours"' in sync_law and 'setValue("sent")' in sync_law,
          "no due-row send path")
    # Pending-only cancellation guard: a vanished match cancels a pending row;
    # a sent row gets a Tracking note only - never a resend, never a rewrite.
    check("a vanished match cancels only pending rows",
          'status === "pending"' in sync_law and 'setValue("cancelled")' in sync_law,
          "no pending-only cancellation guard")
    check("a sent row with a vanished match gets a note, never a resend",
          '"event removed after send"' in sync_law
          and 'setValue("sent")' not in sync_law.split('"event removed after send"')[0],
          "resend risk on vanished events")

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

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
