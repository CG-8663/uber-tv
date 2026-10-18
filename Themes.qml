import QtQuick

// Your themes on disk, changed one at a time.
//
// A save is one confirmed transaction in the helper (bin/om-pg-apps
// theme-save): its pictures checked and copied in under new names, its
// theme.json written whole, read back and renamed into place, and synced.
// Only once that says saved does the guide add the theme and put it on (and
// drop what now matches it); then what only the old theme.json named goes
// (theme-tidy). unconfirmed (the disk hasn't confirmed the rename) changes
// nothing that depends on it; failed changes nothing at all. A removal is
// confirmed the same way (theme-remove). Each reports in state's saving.
//
// The turn: while a save or removal is out, every other theme change is
// refused ("a theme change is still being made"): saving, adding, removing,
// putting one on, the resets and the style panel's picker. So a save that
// finishes late can't put its theme on over a later choice, or bring back
// one removed after it. A load takes the turn for its sweep (a crash's
// leftovers: theme-sweep) when it's free, and skips the sweep when it isn't;
// a save or removal asked for during a sweep waits the moment it takes.
// Each load carries the count of changes it started at, and one that a
// change overtook is thrown away and run again, so a slow load can't bring
// back an older list.
Item {
  id: themes

  required property var guide
  readonly property var screens: guide.appScreens
  readonly property string dir: guide.themesDir

  property string turn: ""            // "", "save", "remove" or "sweep"
  property var waiting: null          // a save or removal asked for during a sweep
  property int changes: 0             // saves and removals that committed
  property int loadSeq: 0
  property bool loading: false
  // stand-ins (tests): helper(command, request, done(res)); reader(done(text))
  property var helper: null
  property var reader: null
  readonly property string busyWhy: "a theme change is still being made: try again in a moment"
  // a save or removal is out (or waiting on a sweep)
  readonly property bool changing: themes.turn === "save" || themes.turn === "remove" || themes.waiting !== null

  // ---- loading -------------------------------------------------------------------
  function load() {
    themes.loadSeq += 1
    var mine = themes.loadSeq
    var at = themes.changes
    themes.loading = true
    var read = function() {
      themes.read(function(text) {
        if (mine !== themes.loadSeq) return                       // a later load is under way
        if (themes.changes !== at) { themes.load(); return }      // a change committed meanwhile: read again
        themes.loading = false
        themes.guide.themesRead(text)
      })
    }
    if (themes.turn !== "") { read(); return }                   // a change is out: no sweep this time
    themes.turn = "sweep"
    themes.call("theme-sweep", { dir: themes.dir }, function() { themes.release(); read() })
  }
  function release() {
    themes.turn = ""
    if (themes.waiting) { var w = themes.waiting; themes.waiting = null; w() }
  }

  // ---- saving and removing -----------------------------------------------------------
  // theme: checked, its pictures by full path. what: a fixed summary for
  // saving. committed(outcome, res, done): with "saved", the guide puts it
  // on and drops what now matches, then calls done(why) ("" or why its
  // clean-up failed); with "unconfirmed" or "failed", nothing depends on it
  // (done is null). Answers { ok, token } or { ok: false, error }.
  function save(id, theme, what, committed) {
    if (themes.changing) return { ok: false, error: themes.busyWhy }
    var token = themes.screens.begin(what)
    var go = function() {
      themes.turn = "save"
      themes.call("theme-save", { dir: themes.dir, id: id, theme: theme }, function(res) {
        var outcome = res && (res.outcome === "saved" || res.outcome === "unconfirmed") ? res.outcome : "failed"
        if (outcome !== "failed") themes.changes += 1
        var end = function(why) {
          themes.screens.end(token, outcome, why || "")
          themes.release()
          if (outcome === "unconfirmed") themes.load()             // it's in place: the list shows it
        }
        if (outcome !== "saved") {
          committed(outcome, res, null)
          end(outcome === "failed" ? themes.said(res, "it couldn't be saved") : "the disk hasn't confirmed it")
          return
        }
        committed("saved", res, function(why) {
          themes.call("theme-tidy", { dir: themes.dir, id: id, drop: res.old || [] }, function() { end(why) })
        })
      })
    }
    if (themes.turn === "sweep") themes.waiting = go
    else go()
    return { ok: true, token: token }
  }
  // removed(outcome, res): with "saved" or "unconfirmed" it's gone from disk
  function remove(id, what, removed) {
    if (themes.changing) return { ok: false, error: themes.busyWhy }
    var token = themes.screens.begin(what)
    var go = function() {
      themes.turn = "remove"
      themes.call("theme-remove", { dir: themes.dir, id: id }, function(res) {
        var outcome = res && (res.outcome === "saved" || res.outcome === "unconfirmed") ? res.outcome : "failed"
        if (outcome !== "failed") themes.changes += 1
        removed(outcome, res)
        themes.screens.end(token, outcome, outcome === "failed" ? themes.said(res, "it couldn't be removed") : outcome === "unconfirmed" ? "the disk hasn't confirmed it" : "")
        themes.release()
      })
    }
    if (themes.turn === "sweep") themes.waiting = go
    else go()
    return { ok: true, token: token }
  }
  // the helper's why, in the guide's words (it never gives a path), or ours
  function said(res, otherwise) {
    var w = res && typeof res.why === "string" ? res.why : ""
    return w && w.indexOf("/") < 0 ? w.slice(0, 120) : otherwise
  }

  // ---- the helper and the files ---------------------------------------------------------
  property var runKind: null
  function newRun(opts) {
    if (!themes.runKind) themes.runKind = Qt.createComponent(Qt.resolvedUrl("ui/Run.qml"))
    return themes.runKind.createObject(themes, opts)
  }
  function call(command, req, done) {
    if (themes.helper) { themes.helper(command, req, done); return }
    var r = themes.newRun({ timeoutMs: 60000, maxBytes: 1024 * 1024, okCodes: [0, 1], splitMarker: "\n" })
    r.finished.connect(function(ok, output) {
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, outcome: "failed", why: "" } }
      done(res)
      Qt.callLater(function() { r.destroy() })
    })
    r.start(["/usr/bin/python3", themes.guide.apps.helper, command], JSON.stringify(req))
  }
  // every theme file, the plugin's and yours, in one go: "\x1e<path>\n<its JSON>"
  function read(done) {
    if (themes.reader) { themes.reader(done); return }
    var r = themes.newRun({ timeoutMs: 15000, maxBytes: 16 * 1024 * 1024, splitMarker: "\n" })
    r.finished.connect(function(ok, output) {
      done(ok ? output : "")
      Qt.callLater(function() { r.destroy() })
    })
    r.start(["/usr/bin/sh", "-c", "PATH=/usr/bin; for f in \"$1\"/*.json \"$1\"/*/theme.json \"$2\"/*.json \"$2\"/*/theme.json; do [ -f \"$f\" ] || continue; printf '\\036%s\\n' \"$f\"; head -c 262144 -- \"$f\"; done",
             "sh", themes.guide.pluginDir + "/themes", themes.dir])
  }
}
