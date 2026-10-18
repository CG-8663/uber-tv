import QtQuick
import QtTest
import "../.."

// AppScreens.qml: your app-screen choices as
// confirmed operations, against a pretend store and helper that the test
// holds back, answers and fails: one write at a time, in order; saved only
// when the helper says so; a failure fails what's pending after it and puts
// the choices back; at most 16 pending; the panel never merges across a
// command's change; entries go with their app.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root

  QtObject {
    id: store
    property bool loaded: true
    property string helper: "/nonexistent"
    property var installed: [{ id: "tv.example.app", kind: "app", source: "bundled", incarnation: "0123456789abcdef" },
                             { id: "tv.example.two", kind: "app", source: "bundled", incarnation: "fedcba9876543210" }]
    function record(id) { return store.installed.filter(function(a) { return a.id === id })[0] || null }
    property int made: 0
    function randomHex(n) { store.made++; var s = ""; while (s.length < n) s += "a1b2c3d4e5f60718"; return s.slice(0, n) }
  }
  QtObject {
    id: guide
    readonly property var apps: store
    readonly property string configDir: "/tmp/om-pg-test-config"
  }

  // the helper, held: each write waits for the test to answer it
  property var writes: []           // [{ text, done }]
  property string fileText: ""
  function answer(i, outcome) { var w = root.writes[i]; w.done(outcome === "error" ? { ok: false } : { ok: outcome !== "failed", outcome: outcome }) }

  AppScreens {
    id: screens
    guide: guide
    reader: function(done) { done({ ok: true, text: root.fileText }) }
    writer: function(text, done) { root.writes = root.writes.concat([{ text: text, done: done }]) }
  }

  readonly property string key: "bundled\ntv.example.app"
  function setLook(v, from) {
    return screens.change(root.key, function(st) {
      var e = st.apps[root.key] || { incarnation: "0123456789abcdef" }
      e.look = v
      st.apps[root.key] = e
    }, from || "command", "tv.example.app: look")
  }

  TestCase {
    name: "AppScreens"

    function init() {
      root.writes = []
      root.fileText = ""
      screens.loaded = false
      screens.ops = []
      screens.done = []
      screens.counter = 0
      screens.writing = false
      screens.load()
    }

    function test_the_run_and_its_tokens() {
      verify(/^[0-9a-f]{32}$/.test(screens.run), "128 random bits, from the kernel: " + screens.run)
      var r = setLook("wall")
      compare(r.token, "w-" + screens.run + "-1")
      compare(screens.saving.run, screens.run)
    }

    function test_saved_only_when_the_helper_says_so() {
      var r = setLook("wall")
      verify(r.ok)
      compare(screens.now.apps[root.key].look, "wall", "shown at once")
      compare(screens.disk.apps[root.key], undefined, "not on disk yet")
      tryVerify(function() { return root.writes.length === 1 }, 1000)
      compare(screens.saving.items[0].outcome, "pending")
      compare(JSON.parse(root.writes[0].text).apps[root.key].look, "wall", "the exact state it will leave")
      root.answer(0, "saved")
      compare(screens.saving.items[0].outcome, "saved")
      compare(screens.disk.apps[root.key].look, "wall")
    }

    function test_one_write_at_a_time_in_order() {
      setLook("wall")
      setLook("cinematic")
      setLook("compact")
      tryVerify(function() { return root.writes.length === 1 }, 1000)
      wait(50)
      compare(root.writes.length, 1, "the second waits for the first")
      root.answer(0, "saved")
      tryVerify(function() { return root.writes.length === 2 }, 1000)
      compare(JSON.parse(root.writes[1].text).apps[root.key].look, "cinematic")
      root.answer(1, "unconfirmed")
      tryVerify(function() { return root.writes.length === 3 }, 1000, "unconfirmed isn't a failure: the next goes on top of it")
      root.answer(2, "saved")
      compare(screens.saving.items.map(function(x) { return x.outcome }), ["saved", "unconfirmed", "saved"])
      compare(screens.disk.apps[root.key].look, "compact")
    }

    function test_a_failure_fails_everything_after_it_data() {
      return [{ tag: "the first", at: 0 }, { tag: "a middle one", at: 2 }, { tag: "the last", at: 4 }]
    }
    function test_a_failure_fails_everything_after_it(d) {
      var looks = ["classic", "posters", "cinematic", "wall", "compact"]
      looks.forEach(function(v) { setLook(v) })
      for (var i = 0; i < d.at; i++) {
        tryVerify(function() { return root.writes.length === i + 1 }, 1000)
        root.answer(i, "saved")
      }
      tryVerify(function() { return root.writes.length === d.at + 1 }, 1000)
      root.answer(d.at, "failed")
      var outcomes = screens.saving.items.slice().reverse().map(function(x) { return x.outcome })
      var want = looks.map(function(v, i) { return i < d.at ? "saved" : "failed" })
      compare(outcomes, want, "it and every change after it")
      var last = d.at > 0 ? looks[d.at - 1] : undefined
      compare(screens.disk.apps[root.key] ? screens.disk.apps[root.key].look : undefined, last, "on disk: the last one written")
      compare(screens.now.apps[root.key] ? screens.now.apps[root.key].look : undefined, last, "and what's shown goes back to it")
      wait(50)
      compare(root.writes.length, d.at + 1, "nothing failed is written later")
    }

    function test_at_most_16_pending() {
      for (var i = 0; i < 16; i++) verify(setLook(i % 2 ? "wall" : "compact").ok)
      var r = setLook("posters")
      verify(!r.ok, "the 17th is refused")
      compare(r.error, "still saving: try again in a moment")
      compare(screens.saving.items.length, 16, "and the first stays listed, pending")
      verify(screens.saving.items.every(function(x) { return x.outcome === "pending" }))
    }

    function test_a_number_pushed_out_is_below_since() {
      setLook("wall")
      tryVerify(function() { return root.writes.length === 1 }, 1000)
      root.answer(0, "failed")
      for (var i = 0; i < 17; i++) {
        setLook(i % 2 ? "wall" : "compact")
        tryVerify(function() { return root.writes.length === i + 2 }, 1000)
        root.answer(i + 1, "saved")
      }
      verify(screens.saving.since > 1, "the first (failed) fell below since: " + screens.saving.since)
      compare(screens.saving.items.length, 16, "the last 16 finished")
      verify(screens.saving.items.every(function(x) { return x.number >= screens.saving.since }))
    }

    function test_the_panel_merges_but_never_across_a_command() {
      var a = setLook("wall", "panel")
      var b = setLook("compact", "panel")
      compare(b.number, a.number, "the panel's two quick changes are one write")
      verify(b.merged)
      var c = setLook("posters", "command")
      verify(c.number > b.number)
      var d = setLook("cinematic", "panel")
      verify(d.number > c.number && !d.merged, "after a command's change, the panel's is a new one")
      tryVerify(function() { return root.writes.length === 1 }, 1000)
      // once a panel change has started writing, a new panel change doesn't merge into it
      root.answer(0, "saved")
      tryVerify(function() { return root.writes.length === 2 }, 1000)
      var e = setLook("classic", "panel")
      verify(!e.merged || e.number === d.number, "merges only into one not writing")
      root.answer(1, "saved")
      tryVerify(function() { return root.writes.length === 3 }, 1000)
      compare(JSON.parse(root.writes[2].text).apps[root.key].look, "classic")
    }

    function test_entries_go_with_their_app() {
      root.fileText = JSON.stringify({ v: 1, all: { look: "wall" }, apps: {
        "bundled\ntv.example.app": { incarnation: "0123456789abcdef", look: "compact", rows: { "r:__proto__": { show: false }, "r:latest": { name: "Mine" } }, order: ["latest", "__proto__"] },
        "bundled\ntv.example.two": { incarnation: "0000000000000000", look: "wall" },
        "bundled\ntv.gone": { incarnation: "1111111111111111", look: "wall" } } })
      screens.loaded = false
      screens.load()
      compare(screens.now.all.look, "wall")
      compare(screens.now.apps[root.key].look, "compact")
      compare(screens.now.apps[root.key].rows["r:__proto__"].show, false, "a row named __proto__ is just a row")
      compare(Object.getPrototypeOf(screens.now.apps[root.key].rows), null)
      compare(screens.now.apps["bundled\ntv.example.two"], undefined, "a reinstall's incarnation doesn't match: dropped")
      compare(screens.now.apps["bundled\ntv.gone"], undefined, "a removed app's: dropped")
      tryVerify(function() { return root.writes.length === 1 }, 1000, "and the cleanup is written")
      // removing an app drops its entry, through a change
      root.answer(0, "saved")
      store.installed = store.installed.filter(function(a) { return a.id !== "tv.example.app" })
      tryVerify(function() { return root.writes.length === 2 }, 1000)
      compare(JSON.parse(root.writes[1].text).apps[root.key], undefined)
      store.installed = [{ id: "tv.example.app", kind: "app", source: "bundled", incarnation: "0123456789abcdef" },
                         { id: "tv.example.two", kind: "app", source: "bundled", incarnation: "fedcba9876543210" }]
    }

    function test_the_files_caps() {
      var big = screens.change(root.key, function(st) {
        var e = { incarnation: "0123456789abcdef", rows: Object.create(null), order: [] }
        for (var i = 0; i < 60; i++) e.rows["r:row" + i] = { name: "x".repeat(40) }
        st.apps[root.key] = e
      }, "command", "big")
      verify(!big.ok && big.error.indexOf("at most 40") >= 0, "past 40 rows an app: refused, never cut")
      compare(screens.now.apps[root.key], undefined, "and nothing changed")
      var forty = screens.change(root.key, function(st) {
        var e = { incarnation: "0123456789abcdef", rows: Object.create(null) }
        for (var i = 0; i < 40; i++) e.rows["r:row" + i] = { name: "x".repeat(40) }
        st.apps[root.key] = e
      }, "command", "forty")
      verify(forty.ok, "40 is fine")
      compare(Object.keys(screens.now.apps[root.key].rows).length, 40)
      var r = screens.change("all", function(st) { st.all = { look: "wall" }; for (var i = 0; i < 2000; i++) st["pad" + i] = "x".repeat(40) }, "command", "pad")
      verify(r.ok, "unknown keys are dropped, not kept")
      verify(screens.bytes(JSON.stringify(screens.now)) < 64 * 1024)
    }

    function test_unreadable_starts_empty_and_says_so() {
      screens.reader = function(done) { done({ ok: false, error: "it's bigger than 64 KB" }) }
      screens.loaded = false
      screens.load()
      verify(screens.loaded)
      verify(screens.problem.indexOf("bigger than 64 KB") >= 0, screens.problem)
      compare(Object.keys(screens.now.apps).length, 0)
      screens.reader = function(done) { done({ ok: true, text: root.fileText }) }
    }
  }
}
