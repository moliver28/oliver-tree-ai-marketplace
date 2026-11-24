"""Template-builder .gs selftest (copy-and-go template sheet).

Checks, at the text level (the Apps Script file cannot run outside Google),
that ``uxr-plugin/google/template-builder.gs`` exists and declares
``buildTemplate``, ``onOpen``, and ``installSyncTrigger``; that it builds all
four engine data tabs from the engine's own header constants, seeds every
``CONFIG_DEFAULTS`` key through ``_setCfg`` with a sample ``booking_url``,
and guards the sample Wave rows and the SETUP rows behind empty-tab checks so
a re-run never duplicates; that ``SETUP_STEPS`` carries the copy-owner order
(web app deploy with "Execute as: me" / "Anyone" and the ``webapp_url`` cell
before the first mergeSend, then the trigger, then the screener, then the
test row); that the ``onOpen`` menu is named "uxr mail merge" and binds the
three items to ``mergeSend``, ``setupScreener``, and ``installSyncTrigger``;
and that ``installSyncTrigger`` creates the 15-minute recurring trigger once
behind an installed check. Pure stdlib; rides the smoke check-3 glob.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "uxr-plugin" / "google" / "template-builder.gs"
ENGINE = ROOT / "uxr-plugin" / "google" / "mail-merge.gs"

CONSTANTS = ("WAVE_TAB", "WAVE_HEADERS", "TRACKING_TAB", "TRACKING_HEADERS",
             "FOLLOWUPS_TAB", "FOLLOWUP_HEADERS", "PREP_TAB", "PREP_HEADERS",
             "CONFIG_DEFAULTS")
MENU_ITEMS = (
    ('"Run mergeSend", "mergeSend"'),
    ('"Run setupScreener", "setupScreener"'),
    ('"Install syncEvents trigger", "installSyncTrigger"'),
)


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("tests/uxr_selftests/template_builder_gs.py selftest")
    check("uxr-plugin/google/template-builder.gs exists", BUILDER.is_file(), str(BUILDER))
    builder = BUILDER.read_text(encoding="utf-8") if BUILDER.is_file() else ""
    engine = ENGINE.read_text(encoding="utf-8") if ENGINE.is_file() else ""

    for name in ("buildTemplate", "onOpen", "installSyncTrigger"):
        check(f"the builder declares function {name}(", f"function {name}(" in builder,
              "declaration not found")
    for const in CONSTANTS:
        declared = (f'{const} = "' in engine or f'{const} = [' in engine
                    or f'{const} = {{' in engine)
        check(f"the engine declares {const}", declared, "engine constant missing")
        check(f"the builder builds {const} by name, not a copy of the literal",
              const in builder, "constant not referenced")
    check("the builder seeds Config through _setCfg for every CONFIG_DEFAULTS key",
          "for (var key in CONFIG_DEFAULTS)" in builder and "_setCfg(key," in builder,
          "config seeding missing")
    check("the builder plants a sample booking_url",
          '"https://example.com/book"' in builder, "sample booking link missing")
    check("sample Wave rows and SETUP rows are guarded behind empty-tab checks",
          builder.count("getLastRow() < 2") >= 2, "no re-run guard")
    check("the builder creates the SETUP checklist tab",
          '_ensureTab("SETUP", ["step", "do this"])' in builder, "SETUP tab missing")

    for phrase in ("New deployment", "Execute as: me", "Who has access: Anyone",
                   "webapp_url", "Install syncEvents trigger", "Run setupScreener",
                   "Run mergeSend", "prep_on"):
        check(f"SETUP_STEPS carries the copy step {phrase!r}", phrase in builder,
              "step text not found")
    check("SETUP orders the web app deploy before the first mergeSend step",
          builder.index("New deployment") < builder.rindex("Run mergeSend"),
          "deploy step not first")

    check("the onOpen menu is named 'uxr mail merge'",
          'createMenu("uxr mail merge")' in builder, "menu name drifted")
    check("onOpen auto-builds the tabs on first open",
          'if (!ss().getSheetByName(WAVE_TAB)) buildTemplate();' in builder,
          "no first-open build")
    for item in MENU_ITEMS:
        check(f"the menu binds {item}", f'.addItem({item})' in builder, "menu item missing")
    check("installSyncTrigger creates the 15-minute recurring trigger",
          '.everyMinutes(15).create()' in builder, "trigger cadence drifted")
    check("installSyncTrigger guards against a second trigger",
          'getHandlerFunction() === "syncEvents"' in builder and "if (!installed)" in builder,
          "no installed check")

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
