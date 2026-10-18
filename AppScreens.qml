import QtQuick
import "AppLooks.js" as Looks

// How you've customized apps' screens: your
// choices for all apps ("all") and for each app (its look, top,
// background, details page, titles and card size, and its rows: shown or
// not, your name for one, its pictures, size, layout and titles, and their
// order), kept in ~/.config/om-pg/app-screens.json through the helper's
// private-file path (bin/om-pg-apps private-read and private-write: 0600,
// never a link, at most 64 KiB, written whole and made durable). Only your
// choices are kept, never what's learned.
//
// Every change is an operation, applied in order on top of the ones before
// it and written one at a time. Each answers the state it will leave on
// disk and its token ("w-<run>-<n>"; the run is 128 random bits from the
// kernel, made when the guide starts), and is reported saved only once its
// file has been read back, renamed into place and its folder synced
// (unconfirmed when only that last sync failed: the new file is in place,
// and the writes after it go on top of it). A failure fails that change and
// every change still pending after it, and what's shown goes back to what
// was last written into place. At most 16 changes and 256 KiB are pending;
// a change past that is refused, never dropped. The Customize panel's
// change merges into the panel's own last pending one that hasn't started
// writing (cycling a value quickly makes one write), never across a
// command's.
//
// An app's entry is keyed by its (source, id) and carries its incarnation;
// one that doesn't match an installed app is dropped on every load, install
// and removal, so a removal never depends on one save landing. Maps never
// inherit (Object.create(null)), so a row named __proto__ is just a row.
Item {
  id: screens

  required property var guide
  readonly property var apps: guide.apps
  readonly property string path: guide.configDir + "/app-screens.json"
  readonly property int maxBytes: 64 * 1024
  readonly property int maxPending: 16
  readonly property int maxPendingBytes: 256 * 1024

  property string run: ""
  property bool loaded: false
  property string problem: ""         // why the file couldn't be read (kept as it is until the first change)
  property var disk: empty()          // the state last written into place
  property var now: empty()           // what's shown: disk with every pending change on top
  property var ops: []                // pending, in order: { number, token, what, text, from, writing }
  property var done: []               // the last 16 finished, newest first: { number, token, what, outcome, why }
  property int counter: 0
  property bool writing: false
  // stand-ins for the helper (tests): reader(done(res)), writer(text, done(res))
  property var reader: null
  property var writer: null

  function empty() { return { v: 1, all: {}, apps: Object.create(null) } }
  function copy(state) {
    var out = empty()
    out.all = JSON.parse(JSON.stringify(state.all || {}))
    for (var k in state.apps) out.apps[k] = screens.copyEntry(state.apps[k])
    return out
  }
  function copyEntry(e) {
    var out = JSON.parse(JSON.stringify(e))
    if (e.rows) { out.rows = Object.create(null); for (var r in e.rows) out.rows[r] = JSON.parse(JSON.stringify(e.rows[r])) }
    return out
  }
  function bytes(text) {
    var n = 0
    for (var i = 0; i < text.length; i++) {
      var c = text.charCodeAt(i)
      if (c < 0x80) n += 1
      else if (c < 0x800) n += 2
      else if (c >= 0xd800 && c <= 0xdbff) { n += 4; i++ }
      else n += 3
    }
    return n
  }

  // An app's key: its source and id, as every store of an app's is
  function keyOf(a) { return a ? (a.source || "") + "\n" + a.id : "" }
  // The installed app an entry is for, if its incarnation still matches
  function installedFor(key, entry) {
    var parts = String(key).split("\n")
    if (parts.length !== 2) return null
    var a = screens.apps.record(parts[1])
    return a && a.kind === "app" && (a.source || "") === parts[0] && a.incarnation && entry && entry.incarnation === a.incarnation ? a : null
  }
  // A picture you picked for an app's screen: one the guide copied into its own folder
  function pictureOk(path) {
    var dir = screens.guide.configDir + "/app-pictures/"
    return typeof path === "string" && path.indexOf(dir) === 0 && /^[0-9a-f]{32}\.(png|jpg|webp)$/.test(path.slice(dir.length))
  }

  // The state as read (or about to be written), checked: "all" and each
  // installed app's entry; anything else is dropped. Answers { state, dropped }.
  function checked(raw) {
    var out = screens.empty()
    var dropped = 0
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { state: out, dropped: 0 }
    out.all = Looks.checkChoices(raw.all && typeof raw.all === "object" ? raw.all : {}, "all", false, screens.pictureOk).choices
    var given = raw.apps && typeof raw.apps === "object" && !Array.isArray(raw.apps) ? raw.apps : {}
    for (var k in given) {
      var e = Looks.checkEntry(given[k], "app", screens.pictureOk).entry
      if (e && screens.installedFor(k, e)) out.apps[k] = e
      else dropped++
    }
    return { state: out, dropped: dropped }
  }

  // ---- reading --------------------------------------------------------------
  function load() {
    if (screens.run === "") screens.run = screens.apps.randomHex(32)
    var got = function(res) {
      var state = screens.empty()
      var dropped = 0
      if (!res || !res.ok) screens.problem = res && res.error ? "Your app screens' file couldn't be read: " + res.error + "." : "Your app screens' file couldn't be read."
      else if (res.text) {
        try {
          var c = screens.checked(JSON.parse(res.text))
          state = c.state
          dropped = c.dropped
          screens.problem = ""
        } catch (e) { screens.problem = "Your app screens' file isn't one the guide can read." }
      } else screens.problem = ""
      screens.disk = state
      screens.now = screens.copy(state)
      screens.loaded = true
      if (dropped) screens.change("", function(st) {}, "guide", "a removed app's choices")
    }
    if (screens.reader) { screens.reader(got); return }
    var r = screens.newRun()
    r.finished.connect(function(ok, output) {
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, error: "the helper didn't answer" } }
      got(res)
      Qt.callLater(function() { r.destroy() })
    })
    r.start(["/usr/bin/python3", screens.apps.helper, "private-read", screens.path])
  }
  // the helper, through the bounded runner (ui/Run.qml), made only when it's needed
  property var runKind: null
  function newRun() {
    if (!screens.runKind) screens.runKind = Qt.createComponent(Qt.resolvedUrl("ui/Run.qml"))
    return screens.runKind.createObject(screens, { timeoutMs: 30000, maxBytes: 256 * 1024, okCodes: [0, 1], splitMarker: "\n" })
  }

  // ---- changing ----------------------------------------------------------------
  // A change: fn(state) changes a copy of what's shown now (the whole
  // state: "all", and apps by key). from: "panel", "command" or "guide";
  // what: a fixed summary (the app id, the keys and handles). Answers
  // { ok, number, token, merged } or { ok: false, error }.
  function change(key, fn, from, what) {
    if (!screens.loaded) return { ok: false, error: "your app screens are still being read: try again in a moment" }
    var next = screens.copy(screens.now)
    fn(next)
    // past a cap, a change is refused, never cut
    var e0 = key && key !== "all" ? next.apps[key] : null
    if (e0 && e0.rows && Object.keys(e0.rows).length > 40) return { ok: false, error: "at most 40 rows' choices for one app" }
    if (e0 && Array.isArray(e0.order) && e0.order.length > 40) return { ok: false, error: "at most 40 rows in your order" }
    // anything no longer installed goes with every change
    var c = screens.checked(JSON.parse(JSON.stringify(next)))
    var state = c.state
    // an app with nothing chosen keeps no entry
    for (var k in state.apps) {
      var e = state.apps[k]
      if (Object.keys(e).length === 1 && e.incarnation) delete state.apps[k]
    }
    var text = JSON.stringify(state)
    if (screens.bytes(text) > screens.maxBytes) return { ok: false, error: "that would make your app screens' file bigger than 64 KB" }
    var last = screens.ops.length ? screens.ops[screens.ops.length - 1] : null
    if (from === "panel" && last && last.from === "panel" && !last.writing) {
      last.text = text
      if (last.what.indexOf(what) < 0) last.what = last.what + "; " + what
      screens.ops = screens.ops.slice()
      screens.now = state
      return { ok: true, number: last.number, token: last.token, merged: true }
    }
    var pendingBytes = 0
    screens.ops.forEach(function(o) { pendingBytes += screens.bytes(o.text) })
    if (screens.ops.length >= screens.maxPending || pendingBytes + screens.bytes(text) > screens.maxPendingBytes)
      return { ok: false, error: "still saving: try again in a moment" }
    screens.counter += 1
    var op = { number: screens.counter, token: "w-" + screens.run + "-" + screens.counter, what: String(what || "").slice(0, 200), text: text, from: from, writing: false }
    screens.ops = screens.ops.concat([op])
    screens.now = state
    Qt.callLater(screens.pump)
    return { ok: true, number: op.number, token: op.token, merged: false }
  }

  // ---- writing, one at a time --------------------------------------------------
  function pump() {
    if (screens.writing || !screens.ops.length) return
    var op = screens.ops[0]
    op.writing = true
    screens.ops = screens.ops.slice()
    screens.writing = true
    var got = function(res) {
      screens.writing = false
      if (screens.ops[0] !== op) return                    // a reset meanwhile: nothing of it waits
      var outcome = res && res.ok && (res.outcome === "saved" || res.outcome === "unconfirmed") ? res.outcome : "failed"
      if (outcome !== "failed") {
        screens.disk = screens.checked(JSON.parse(op.text)).state
        screens.finish(op, outcome, outcome === "unconfirmed" ? "the disk hasn't confirmed it: a power cut could bring back the one before" : "")
        screens.ops = screens.ops.slice(1)
        Qt.callLater(screens.pump)
        return
      }
      // it and every change after it fail together, and what's shown goes
      // back to what's on disk: a failed change never lands under a later number
      var all = screens.ops
      screens.ops = []
      all.forEach(function(o, i) { screens.finish(o, "failed", i === 0 ? "it couldn't be saved" : "a change before it couldn't be saved") })
      screens.now = screens.copy(screens.disk)
    }
    if (screens.guide.wiping) { got({ ok: false }); return }   // a restore or a reset is replacing the files
    if (screens.writer) { screens.writer(op.text, got); return }
    var w = screens.newRun()
    w.finished.connect(function(ok, output) {
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false } }
      got(res)
      Qt.callLater(function() { w.destroy() })
    })
    w.start(["/usr/bin/python3", screens.apps.helper, "private-write", screens.path], op.text)
  }

  function finish(op, outcome, why) {
    screens.done = [{ number: op.number, token: op.token, what: op.what, outcome: outcome, why: why }].concat(screens.done).slice(0, 16)
    var w = screens.watchers[op.token]
    if (w) { delete screens.watchers[op.token]; w(outcome) }
  }
  // fn(outcome) once the change with that token has finished (once)
  property var watchers: ({})
  function whenDone(token, fn) {
    var done = screens.done.filter(function(d) { return d.token === token })[0]
    if (done) { fn(done.outcome); return }
    screens.watchers[token] = fn
  }

  // A theme save or removal (Themes.qml), reported here beside the changes:
  // begin(what) answers its token; end(token, outcome, why) finishes it
  property var outside: []            // pending: { number, token, what }
  function begin(what) {
    screens.counter += 1
    var op = { number: screens.counter, token: "w-" + screens.run + "-" + screens.counter, what: String(what).slice(0, 120) }
    screens.outside = screens.outside.concat([op])
    return op.token
  }
  function end(token, outcome, why) {
    var op = screens.outside.filter(function(o) { return o.token === token })[0]
    if (!op) return
    screens.outside = screens.outside.filter(function(o) { return o.token !== token })
    screens.finish(op, outcome, why)
  }

  // For state: every pending change, then the last 16 finished, newest
  // first, with this run's id and the oldest number still listed (a
  // finished number below it was pushed out; a pending one never is)
  readonly property var saving: {
    var pending = screens.ops.concat(screens.outside).map(function(o) { return { number: o.number, token: o.token, what: o.what, outcome: "pending", why: "" } })
    pending.sort(function(a, b) { return b.number - a.number })
    var items = pending.concat(screens.done)
    var since = screens.counter + 1
    items.forEach(function(x) { since = Math.min(since, x.number) })
    return { run: screens.run, since: since, items: items }
  }

  // ---- what an app's screen reads ----------------------------------------------
  function entryOf(a) {
    var e = a ? screens.now.apps[screens.keyOf(a)] : null
    return e && e.incarnation === a.incarnation ? e : null
  }
  readonly property var all: screens.now.all

  // installs and removals: what no longer matches goes, through a change
  Connections {
    target: screens.apps
    function onInstalledChanged() {
      if (!screens.loaded) return
      for (var k in screens.now.apps) if (!screens.installedFor(k, screens.now.apps[k])) { screens.change("", function(st) {}, "guide", "a removed app's choices"); return }
    }
    function onLoadedChanged() { if (screens.apps.loaded && !screens.loaded) screens.load() }
  }
  Component.onCompleted: if (screens.apps.loaded) screens.load()
}
