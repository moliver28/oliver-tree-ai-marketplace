/**
 * uxr mail-merge engine, Google side (#89 ruling: Google runs the sends;
 * the repo owns this source and ships it unchanged).
 *
 * Paste this file into the Apps Script project bound to the merge Sheet;
 * setup lives in google/README.md. The script runs inside the researcher's
 * Google account. The plugin's Python (recruit_send.py) covers the SMTP
 * path; this file covers the Google path: merge send, schedule send,
 * open/click/unsubscribe tracking, calendar-timed follow-ups with optional
 * meeting prep, and the screener Form.
 * Quota reality: MailApp spends one quota unit per recipient per day.
 * Consumer accounts get about 100 units a day, Workspace accounts more.
 * Research waves send tens, not thousands, so the quota holds. One
 * recurring 15-minute trigger scans due work, so the 20-trigger cap never
 * binds. Every send pass runs under one LockService script lock, so an
 * overlapping trigger cannot double-send.
 * Tab law lives in google/README.md: Wave (merge rows), Tracking
 * (date|route|email|study|target|note; routes open|click|unsub|cancelled),
 * Followups (when|email|template_key|study|status: pending|sent|cancelled),
 * Prep (when|event|email|items), Config (name in column A, value in B).
 */
var WAVE_TAB = "Wave", TRACKING_TAB = "Tracking", FOLLOWUPS_TAB = "Followups";
var PREP_TAB = "Prep", CONFIG_TAB = "Config";
var WAVE_HEADERS = ["Tracking ID", "Email", "Name", "Study", "Subject", "Body", "Email Sent"];
var TRACKING_HEADERS = ["date", "route", "email", "study", "target", "note"];
var FOLLOWUP_HEADERS = ["when", "email", "template_key", "study", "status"];
var PREP_HEADERS = ["when", "event", "email", "items"];
var FOLLOWUP_KEY = "followup";  // template_key stamped on rows syncEvents creates
var FOLLOWUP_STATUS_COL = 5;    // 1-based column of status on Followups
var HOUR_MS = 3600 * 1000;
var SCAN_BACK_HOURS = 48;       // events older than this are never re-matched
var SCAN_AHEAD_HOURS = 14 * 24;
// The Config tab carries one row per setting: label in column A (the name
// below), value in column B. The first run creates the tab automatically.
var CONFIG_DEFAULTS = {
  webapp_url: "", tracking_on: true, unsub_on: true, calendar_name: "",
  event_regex: "Session|Interview", followup_hours: 48, prep_on: false,
  prep_lead_hours: 24, booking_url: "", form_id: ""
};

// --- plumbing ---
function ss() { return SpreadsheetApp.getActiveSpreadsheet(); }
function _now() { return new Date(); }
function _fmt(date) { return Utilities.formatDate(date, Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm"); }
function _iso(date) { return Utilities.formatDate(date, Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm"); }
function _asDate(v) { if (v instanceof Date) return v; var d = new Date(v); return isNaN(d.getTime()) ? null : d; }
function _newId() { return Utilities.getUuid().substring(0, 8); }
function _esc(text) { return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function _plain(html) { return html.replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>/gi, "\n\n").replace(/<[^>]+>/g, "").trim(); }
function _ensureTab(name, headers) {
  var sheet = ss().getSheetByName(name) || ss().insertSheet(name);
  if (sheet.getLastRow() === 0) sheet.appendRow(headers);
  return sheet;
}
function _cfg(name) {
  var sheet = _ensureTab(CONFIG_TAB, ["name", "value"]);
  var rows = sheet.getRange(1, 1, Math.max(sheet.getLastRow(), 1), 2).getValues();
  for (var i = 0; i < rows.length; i++) if (String(rows[i][0]).trim() === name) return rows[i][1];
  return CONFIG_DEFAULTS[name];
}
function _cfgText(name) { return String(_cfg(name) == null ? "" : _cfg(name)).trim(); }
function _cfgFlag(name) { var v = _cfg(name); return v === "" || v == null ? CONFIG_DEFAULTS[name] === true : v === true || String(v).toLowerCase() === "true"; }
function _cfgNum(name) { var n = Number(_cfg(name)); return isNaN(n) ? Number(CONFIG_DEFAULTS[name]) : n; }
function _track(route, email, study, target, note) {
  _ensureTab(TRACKING_TAB, TRACKING_HEADERS).appendRow(
    [_fmt(_now()), route, email || "", study || "", target || "", note || ""]);
}
function _findById(id) {
  var sheet = ss().getSheetByName(WAVE_TAB);
  if (!sheet || sheet.getLastRow() < 2) return {email: "", study: ""};
  var head = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var idCol = head.indexOf("Tracking ID"), emailCol = head.indexOf("Email"), studyCol = head.indexOf("Study");
  if (idCol < 0 || emailCol < 0) return {email: "", study: ""};
  var rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, head.length).getValues();
  for (var i = 0; i < rows.length; i++) {
    if (String(rows[i][idCol]).trim() === id) {
      return {email: String(rows[i][emailCol]).trim(), study: String(rows[i][studyCol] || "").trim()};
    }
  }
  return {email: "", study: ""};
}

// --- shared send path ---
function _sendOne(recipient, subject, html) { MailApp.sendEmail(recipient, subject, _plain(html), {htmlBody: html}); }
// The unsubscribe footer (default on). id names the Wave-tab row; m= carries the address for paths with no Wave-tab row.
function _unsubHtml(id, email) {
  var base = _cfgText("webapp_url").replace(/\/+$/, "");
  if (!_cfgFlag("unsub_on") || !base) return "";
  if (!id) id = _newId();
  return '<p style="color:#666;font-size:12px">Do not want these emails? <a href="' +
    base + "?u=" + id + (email ? "&m=" + encodeURIComponent(email) : "") + '">Unsubscribe</a>.</p>';
}
function _isUnsubscribed(email) {
  var sheet = _ensureTab(TRACKING_TAB, TRACKING_HEADERS);
  var last = sheet.getLastRow();
  if (last < 2) return false;
  var rows = sheet.getRange(2, 1, last - 1, TRACKING_HEADERS.length).getValues();
  var want = String(email).toLowerCase();
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][1] === "unsub" && String(rows[i][2]).toLowerCase() === want) return true;
  }
  return false;
}

// --- merge send ---
// One email per sendable row of tabName. Sendable: Email holds an address,
// the Email Sent cell is empty (never double-send), the recipient has not
// unsubscribed, Subject and Body are non-empty. {{token}} merges approved
// columns (lowercase, non-alnum runs read as one underscore) plus booking_url
// from Config; an unknown token stops the pass before any send. The pass runs
// under one LockService script lock. Returns rows sent.
function mergeSend(tabName) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error("mergeSend: another pass holds the lock");
  try {
    var sheet = _ensureTab(tabName || WAVE_TAB, WAVE_HEADERS);
    var last = sheet.getLastRow();
    if (last < 2) return 0;
    var head = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    var col = {};
    WAVE_HEADERS.forEach(function (h) {
      col[h] = head.indexOf(h);
      if (col[h] < 0) throw new Error("mergeSend: tab is missing column " + h);
    });
    var rows = sheet.getRange(2, 1, last - 1, head.length).getValues();
    var extras = {booking_url: _cfgText("booking_url")};
    var i, bad;
    for (i = 0; i < rows.length; i++) {
      bad = _unknownToken(rows[i][col["Subject"]], head, extras) ||
        _unknownToken(rows[i][col["Body"]], head, extras);
      if (bad) throw new Error("mergeSend: row " + (i + 2) + " token {{" + bad + "}} names no approved column");
    }
    var sent = 0;
    for (i = 0; i < rows.length; i++) {
      var email = String(rows[i][col["Email"]] || "").trim();
      var stamp = rows[i][col["Email Sent"]];
      if (!email || email.indexOf("@") < 0 || stamp) continue;
      if (_isUnsubscribed(email)) continue;
      var id = String(rows[i][col["Tracking ID"]] || "").trim();
      if (!id) { id = _newId(); sheet.getRange(i + 2, col["Tracking ID"] + 1).setValue(id); }
      var subject = String(_mergeTokens(rows[i][col["Subject"]], head, rows[i], extras)).trim();
      var body = String(_mergeTokens(rows[i][col["Body"]], head, rows[i], extras)).trim();
      if (!subject || !body) continue;
      _sendOne(email, subject, _compose(id, body));
      sheet.getRange(i + 2, col["Email Sent"] + 1).setValue(_fmt(_now()));
      sent++;
    }
    return sent;
  } finally {
    lock.releaseLock();
  }
}
function _tokenOf(header) { return String(header).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""); }
function _unknownToken(text, head, extras) {
  var found = String(text || "").match(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g) || [];
  for (var i = 0; i < found.length; i++) {
    var token = found[i].replace(/[{}\s]/g, "");
    var known = head.some(function (h) { return _tokenOf(h) === token.toLowerCase(); });
    if (!known && !(extras && token in extras)) return token;
  }
  return null;
}
function _mergeTokens(text, head, rowValues, extras) {
  return String(text || "").replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, function (m, token) {
    var key = token.toLowerCase();
    for (var i = 0; i < head.length; i++) {
      if (_tokenOf(head[i]) === key) return String(rowValues[i]);
    }
    return extras && token in extras ? extras[token] : m;
  });
}
function _compose(id, body) {
  var base = _cfgText("webapp_url").replace(/\/+$/, "");
  var tracking = _cfgFlag("tracking_on") && base;
  var html = String(body).split(/\r?\n/).map(function (line) {
    if (tracking) { // [text](https://url) in the Body cell becomes a tracked link
      line = line.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, function (m, text, url) {
        return '<a href="' + base + "?c=" + id + "&go=" + encodeURIComponent(url) + '">' + _esc(text) + "</a>";
      });
    }
    return "<p>" + line + "</p>";
  }).join("");
  html += _unsubHtml(id, null);
  if (tracking) html += '<img src="' + base + "?o=" + id + '" width="1" height="1" alt="">';
  return html;
}

// --- schedule send (#89: one-off installable time trigger) ---
// Schedules one mergeSend pass of tabName near `when` (a Date or a text a
// Date parses); Google picks the exact minute. The handler deletes its
// trigger and property after firing.
function scheduleSend(tabName, when) {
  var at = when instanceof Date ? when : new Date(when);
  if (isNaN(at.getTime())) throw new Error("scheduleSend: `when` is not a date");
  var trigger = ScriptApp.newTrigger("sendScheduled").timeBased().at(at).create();
  PropertiesService.getScriptProperties().setProperty(trigger.getUniqueId(), tabName || WAVE_TAB);
  return trigger;
}
function sendScheduled(e) {
  var props = PropertiesService.getScriptProperties();
  var uid = e && e.triggerUid, tabName = uid ? props.getProperty(uid) : null;
  if (uid) {
    props.deleteProperty(uid);
    ScriptApp.getProjectTriggers().forEach(function (t) {
      if (t.getUniqueId() === uid) ScriptApp.deleteTrigger(t);
    });
  }
  mergeSend(tabName || WAVE_TAB);
}

// --- web app routes (one deployment, "Who has access: Anyone") ---
function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.o) { // open pixel: the GET logs the open; any response body serves
    _track("open", _findById(p.o).email, "", p.o, "pixel fetched");
    return ContentService.createTextOutput("");
  }
  if (p.c && p.go) { // click: log, then meta-refresh to the destination
    _track("click", _findById(p.c).email, "", p.c, p.go);
    return HtmlService.createHtmlOutput('<meta http-equiv="refresh" content="0; url=' + _esc(p.go) + '">');
  }
  if (p.u) { // unsubscribe: mark Tracking, confirm on the page
    var lock = LockService.getScriptLock(); lock.waitLock(30000);
    try {
      var who = _findById(p.u);
      _track("unsub", who.email || p.m || "", who.study, p.u, "unsubscribed");
    } finally {
      lock.releaseLock();
    }
    return HtmlService.createHtmlOutput("<p>You are unsubscribed. No further emails will be sent to you.</p>");
  }
  return HtmlService.createHtmlOutput("<p>Unknown request.</p>");
}

// --- calendar-timed follow-ups (the one recurring trigger) ---
// The 15-minute recurring trigger (SETUP installs it). Reads calendar_name
// and event_regex from Config, scans the matched calendar inside the scan
// window, then, under one LockService script lock: a new match appends a
// Followups row at start + followup_hours; a due pending row sends and is
// stamped "sent"; a vanished match cancels rows - a pending row is stamped
// "cancelled" and Tracking logs route "cancelled", a sent row gets a Tracking
// note only (the pending-only cancellation guard never re-sends or rewrites).
// Prep rows exist only when prep_on is true.
function syncEvents() {
  var name = _cfgText("calendar_name"), pattern = _cfgText("event_regex");
  if (!name || !pattern) return;
  var calendars = CalendarApp.getCalendarsByName(name);
  if (!calendars.length) throw new Error("syncEvents: no calendar named " + name);
  var re = new RegExp(pattern), now = _now();
  var windowStart = new Date(now.getTime() - SCAN_BACK_HOURS * HOUR_MS);
  var windowEnd = new Date(now.getTime() + SCAN_AHEAD_HOURS * HOUR_MS);
  var matched = {};
  calendars[0].getEvents(windowStart, windowEnd).forEach(function (ev) {
    var title = ev.getTitle();
    if (!re.test(title)) return;
    var email = _guestEmail(ev);
    if (!email) return;
    matched[_iso(ev.getStartTime())] = {start: ev.getStartTime(), title: title, email: email};
  });
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return; // another pass holds the lock; the next run retries
  try {
    _syncFollowups(matched, windowStart, now);
    if (_cfgFlag("prep_on")) _syncPrep(matched, windowStart);
  } finally {
    lock.releaseLock();
  }
}
// The contact is the guest who is not the researcher.
function _guestEmail(ev) {
  var me = Session.getActiveUser().getEmail().toLowerCase();
  var guests = ev.getGuestList();
  for (var i = 0; i < guests.length; i++) {
    var email = String(guests[i].getEmail() || "").trim();
    if (email && (!me || email.toLowerCase() !== me)) return email;
  }
  return "";
}
function _syncFollowups(matched, windowStart, now) {
  var lead = _cfgNum("followup_hours"), sheet = _ensureTab(FOLLOWUPS_TAB, FOLLOWUP_HEADERS);
  var last = sheet.getLastRow();
  var rows = last > 1 ? sheet.getRange(2, 1, last - 1, FOLLOWUP_HEADERS.length).getValues() : [];
  var seen = {};
  for (var i = 0; i < rows.length; i++) {
    var when = _asDate(rows[i][0]);
    if (!when) continue;
    var evStart = new Date(when.getTime() - lead * HOUR_MS);
    var key = _iso(evStart);
    seen[key] = true;
    var status = String(rows[i][4]).trim() || "pending";
    var email = String(rows[i][1]).trim(), study = String(rows[i][3]).trim();
    var gone = !(key in matched) && evStart.getTime() >= windowStart.getTime();
    if (gone && status === "pending") {
      sheet.getRange(i + 2, FOLLOWUP_STATUS_COL).setValue("cancelled");
      _track("cancelled", email, study, key, "calendar event removed");
    } else if (gone && status === "sent") {
      _track("cancelled", email, study, key, "event removed after send");
    } else if (!gone && status === "pending" && when.getTime() <= now.getTime()) {
      if (email && !_isUnsubscribed(email)) _sendFollowup(email, study); // unsub: suppressed, never retried
      sheet.getRange(i + 2, FOLLOWUP_STATUS_COL).setValue("sent");
    }
  }
  for (var k in matched) {
    if (k in seen) continue;
    var m = matched[k];
    sheet.appendRow([new Date(m.start.getTime() + lead * HOUR_MS), m.email, FOLLOWUP_KEY, m.title, "pending"]);
  }
}
function _sendFollowup(email, study) {
  var booking = _cfgText("booking_url");
  var html = "<p>Hello,</p><p>Do you still want your " + _esc(study) + " session? Write back, or pick a new time";
  if (booking) html += ': <a href="' + _esc(booking) + '">book your session</a>';
  html += ".</p>" + _unsubHtml(null, email);
  _sendOne(email, "Re: " + study + " session", html);
}
function _syncPrep(matched, windowStart) {
  var lead = _cfgNum("prep_lead_hours"), sheet = _ensureTab(PREP_TAB, PREP_HEADERS);
  var last = sheet.getLastRow();
  var rows = last > 1 ? sheet.getRange(2, 1, last - 1, PREP_HEADERS.length).getValues() : [];
  var seen = {};
  for (var i = 0; i < rows.length; i++) {
    var when = _asDate(rows[i][0]);
    if (!when) continue;
    var evStart = new Date(when.getTime() + lead * HOUR_MS);
    var key = _iso(evStart);
    seen[key] = true;
    var label = String(rows[i][1]);
    if (label.indexOf("[cancelled] ") === 0) continue;
    if (!(key in matched) && evStart.getTime() >= windowStart.getTime()) {
      // Prep rows carry no status column, so the cancelled mark is a prefix.
      sheet.getRange(i + 2, 2).setValue("[cancelled] " + label);
      _track("cancelled", String(rows[i][2]).trim(), "", key, "prep row cancelled");
    }
  }
  for (var k in matched) {
    if (k in seen) continue;
    var m = matched[k];
    var prepWhen = new Date(m.start.getTime() - lead * HOUR_MS);
    sheet.appendRow([prepWhen, m.title + " " + _iso(m.start), m.email, ""]);
    _notifyPrep(m, prepWhen);
  }
}
function _notifyPrep(m, prepWhen) {
  var me = Session.getActiveUser().getEmail(); if (!me) return;
  var html = "<p>Prep brief for " + _esc(m.title) + "<br>Starts: " + _fmt(m.start) +
    "<br>Prep by: " + _fmt(prepWhen) + "<br>Guest: " + _esc(m.email) +
    "<br>Fill the items cell on the Prep tab before the session.</p>";
  _sendOne(me, "Prep: " + m.title, html);
}

// --- screener Form (booking link on the confirmation page) ---
// Builds or updates the screener Form, sets its confirmation text to
// "Book your session: <booking_url>", records form_id on Config, and
// installs the onFormSubmit trigger once. Set booking_url first; the
// researcher reviews answers after the fact (no per-respondent gate).
function setupScreener() {
  var booking = _cfgText("booking_url");
  if (!booking) throw new Error("setupScreener: set the booking_url cell on the Config tab first");
  var known = _cfgText("form_id");
  var form = known ? FormApp.openById(known) : FormApp.create("Research session screener");
  form.setConfirmationMessage("Book your session: " + booking);
  if (!known) {
    form.setDescription("Answer these questions to tell us about your fit for the study. After you submit, the next step opens: book your session.");
    form.setCollectEmail(true);
    form.addTextItem().setTitle("Your full name").setRequired(true);
    _setCfg("form_id", form.getId());
  }
  var installed = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === "onFormSubmit";
  });
  if (!installed) ScriptApp.newTrigger("onFormSubmit").forForm(form).onFormSubmit().create();
  return form.getEditUrl();
}
function _setCfg(name, value) {
  var sheet = _ensureTab(CONFIG_TAB, ["name", "value"]);
  var rows = sheet.getRange(1, 1, Math.max(sheet.getLastRow(), 1), 1).getValues();
  for (var i = 0; i < rows.length; i++) {
    if (String(rows[i][0]).trim() === name) return sheet.getRange(i + 1, 2).setValue(value);
  }
  sheet.appendRow([name, value]);
}
// Form submit: write the respondent to the Wave tab with a fresh Tracking ID.
// Subject and Body stay empty; the researcher merges before sending.
function onFormSubmit(e) {
  var response = e && e.response;
  var lock = LockService.getScriptLock(); lock.waitLock(30000);
  try {
    var email = response ? response.getRespondentEmail() : "", name = "";
    if (response) {
      response.getItemResponses().forEach(function (item) {
        if (!name && /name/i.test(item.getItem().getTitle())) name = String(item.getResponse());
      });
    }
    var study = response ? response.getFormTitle() : "";
    _ensureTab(WAVE_TAB, WAVE_HEADERS).appendRow([_newId(), email, name, study, "", "", ""]);
  } finally {
    lock.releaseLock();
  }
}
