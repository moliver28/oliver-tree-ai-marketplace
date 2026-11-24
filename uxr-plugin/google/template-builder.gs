/**
 * Template builder for the merge Sheet. One master Sheet is built once and
 * shared view-only; File > Make a copy ships the tabs, the sample rows, the
 * SETUP checklist, and this script to every new researcher. Triggers and
 * authorizations do not copy, so the copy re-creates them from the
 * "uxr mail merge" menu, which onOpen installs (a simple trigger needs no
 * authorization and survives the copy). Setup law lives in google/README.md.
 * Optional: delete this file from the master once the tabs exist, so copies
 * carry only the engine.
 */

// --- one-time build of the master ---
function buildTemplate() {
  _ensureTab(WAVE_TAB, WAVE_HEADERS);
  _ensureTab(TRACKING_TAB, TRACKING_HEADERS);
  _ensureTab(FOLLOWUPS_TAB, FOLLOWUP_HEADERS);
  _ensureTab(PREP_TAB, PREP_HEADERS);
  for (var key in CONFIG_DEFAULTS) {
    _setCfg(key, key === "booking_url" ? "https://example.com/book" : CONFIG_DEFAULTS[key]);
  }
  var wave = _ensureTab(WAVE_TAB, WAVE_HEADERS);
  if (wave.getLastRow() < 2) {
    wave.appendRow(["", "you@example.com", "Sample One", "Sample study",
      "Your session next week",
      "Hi {{name}},\n\nConfirm your slot: [confirm your slot](https://example.com/confirm).\n\nSee you soon,\nThe research team", ""]);
    wave.appendRow(["", "second@example.com", "Sample Two", "Sample study",
      "Interview invitation",
      "Hello {{name}},\n\nYour booking link: {{booking_url}}\n\nThanks!", ""]);
  }
  var setup = _ensureTab("SETUP", ["step", "do this"]);
  if (setup.getLastRow() < 2) {
    SETUP_STEPS.forEach(function (row) { setup.appendRow(row); });
  }
}
var SETUP_STEPS = [
  [1, "This sheet is your copy; the script came with it. Menu items below ask Google for access the first time - approve once."],
  [2, "Extensions > Apps Script > Deploy > New deployment > Web app. Execute as: me. Who has access: Anyone. Copy the URL into the Config webapp_url cell."],
  [3, "Fill Config: booking_url, calendar_name, event_regex, followup_hours."],
  [4, "Menu 'uxr mail merge' > Install syncEvents trigger."],
  [5, "Menu > Run setupScreener. The screener form's confirmation page carries booking_url."],
  [6, "Delete the two sample Wave rows. Add one test row with your own address. Menu > Run mergeSend. Open your inbox, then check the Tracking tab."],
  [7, "Optional prep briefs: set the Config prep_on cell to true."],
];

// --- the copy's menu (simple trigger: survives Make a copy, no authorization) ---
function onOpen() {
  SpreadsheetApp.getUi().createMenu("uxr mail merge")
    .addItem("Run mergeSend", "mergeSend")
    .addItem("Run setupScreener", "setupScreener")
    .addItem("Install syncEvents trigger", "installSyncTrigger")
    .addToUi();
}
function installSyncTrigger() {
  var installed = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === "syncEvents";
  });
  if (!installed) ScriptApp.newTrigger("syncEvents").timeBased().everyMinutes(15).create();
}

