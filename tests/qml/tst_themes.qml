import QtQuick
import QtTest
import "../.."

// Themes.qml: one theme change at a time, the
// sweep taking the same turn, loads a change overtook run again, the theme
// put on only once its save says saved, and every outcome in saving. The
// helper and the theme files are stood in for, each answer held until the
// test gives it, so every ordering is exact.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root

  property var calls: []      // the helper: { command, req, done }
  property var reads: []      // the theme files: done(text)
  property var shown: []      // what themesRead was given
  QtObject {
    id: guide
    readonly property string themesDir: "/tmp/om-pg-themes-test"
    readonly property string pluginDir: "/tmp/om-pg-plugin"
    readonly property string configDir: "/tmp/om-pg-test-config"
    readonly property var apps: ({ helper: "/nonexistent", installed: [], record: function() { return null },
                                   randomHex: function(n) { var s = ""; while (s.length < n) s += "0123456789abcdef"; return s.slice(0, n) } })
    readonly property var appScreens: screens
    function themesRead(text) { root.shown = root.shown.concat([text]) }
  }
  AppScreens {
    id: screens
    guide: guide
    reader: function(done) { done({ ok: true, text: "" }) }
    writer: function(text, done) { done({ ok: true, outcome: "saved" }) }
  }
  Themes {
    id: themes
    guide: guide
    helper: function(command, req, done) { root.calls = root.calls.concat([{ command: command, req: req, done: done }]) }
    reader: function(done) { root.reads = root.reads.concat([done]) }
  }

  function lastCall() { return root.calls[root.calls.length - 1] }
  function outcomeOf(token) { var x = screens.saving.items.filter(function(i) { return i.token === token })[0]; return x ? x.outcome : "" }
  function whyOf(token) { var x = screens.saving.items.filter(function(i) { return i.token === token })[0]; return x ? x.why : "" }

  TestCase {
    name: "Themes"

    function init() {
      root.calls = []
      root.reads = []
      root.shown = []
      themes.turn = ""
      themes.waiting = null
      themes.loadSeq = 0
      screens.load()
    }

    // a save, answered saved, the guide's part done and the tidy answered
    function saveAll(id, res) {
      var log = []
      var r = themes.save(id, { name: id }, "theme " + id, function(outcome, got, done) { log.push(outcome); if (done) done("") })
      verify(r.ok, r.error)
      lastCall().done(res || { ok: true, outcome: "saved", theme: { name: id }, old: ["pic-old.png"] })
      if (lastCall().command === "theme-tidy") lastCall().done({ ok: true, removed: 1 })
      return { token: r.token, log: log }
    }

    function test_a_load_sweeps_first_when_the_turn_is_free() {
      themes.load()
      compare(root.calls.length, 1)
      compare(lastCall().command, "theme-sweep")
      compare(themes.turn, "sweep", "the sweep holds the turn")
      compare(root.reads.length, 0, "nothing read before the sweep is done")
      lastCall().done({ ok: true, removed: 0 })
      compare(themes.turn, "", "and lets it go")
      compare(root.reads.length, 1)
      root.reads[0]("\u001e/x/theme.json\n{}")
      compare(JSON.stringify(root.shown), JSON.stringify(["\u001e/x/theme.json\n{}"]))
    }

    function test_a_load_while_a_save_is_out_skips_the_sweep() {
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function() {})
      compare(lastCall().command, "theme-save")
      themes.load()
      compare(root.calls.length, 1, "no sweep while a save is out")
      compare(root.reads.length, 1, "it still reads")
      root.reads[0]("x")
      compare(root.shown.length, 1)
    }

    function test_a_load_overtaken_by_a_save_is_run_again() {
      themes.load()
      lastCall().done({ ok: true })           // its sweep
      compare(root.reads.length, 1)            // its read, held
      var s = saveAll("neon")
      compare(outcomeOf(s.token), "saved")
      root.reads[0]("the old list")            // let go: thrown away, and the load runs again
      compare(root.shown.length, 0, "the old list never lands")
      compare(lastCall().command, "theme-sweep", "a new load, sweeping first")
      lastCall().done({ ok: true })
      root.reads[root.reads.length - 1]("the new list")
      compare(JSON.stringify(root.shown), JSON.stringify(["the new list"]))
    }

    function test_a_load_overtaken_by_a_removal_is_run_again() {
      themes.load()
      lastCall().done({ ok: true })
      var gone = ""
      var r = themes.remove("neon", "theme neon removed", function(outcome) { gone = outcome })
      lastCall().done({ ok: true, outcome: "saved" })
      compare(gone, "saved")
      root.reads[0]("a list with neon in it")
      compare(root.shown.length, 0, "a removed theme isn't brought back")
      lastCall().done({ ok: true })
      root.reads[root.reads.length - 1]("the list without it")
      compare(JSON.stringify(root.shown), JSON.stringify(["the list without it"]))
    }

    function test_one_theme_change_at_a_time() {
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function() {})
      verify(r.ok)
      verify(themes.changing, "putting one on, the resets and the picker all check this")
      var again = themes.save("neon", { name: "Neon 2" }, "theme neon", function() {})
      verify(!again.ok && again.error === themes.busyWhy, "two saves of one theme")
      verify(!themes.save("other", {}, "x", function() {}).ok, "save then save another")
      verify(!themes.remove("neon", "x", function() {}).ok, "save then remove")
      compare(root.calls.length, 1, "nothing else sent")
      lastCall().done({ ok: false, outcome: "failed", why: "a picture isn't a PNG, JPEG or WebP" })
      verify(!themes.changing)
      verify(themes.save("neon", { name: "Neon" }, "theme neon", function() {}).ok, "then the next can go")
    }

    function test_a_change_asked_during_a_sweep_waits_for_it() {
      themes.load()
      compare(lastCall().command, "theme-sweep")
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function() {})
      verify(r.ok, "accepted")
      compare(root.calls.length, 1, "but it waits the moment the sweep takes")
      compare(outcomeOf(r.token), "pending")
      verify(themes.changing, "and nothing else goes meanwhile")
      verify(!themes.remove("other", "x", function() {}).ok)
      lastCall().done({ ok: true })            // the sweep's done
      compare(lastCall().command, "theme-save", "then the save goes")
      compare(themes.turn, "save")
    }

    function test_put_on_only_once_saved_then_the_old_pictures_go() {
      var log = []
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function(outcome, res, done) {
        log.push(outcome + (done ? ":done" : ""))
        compare(root.calls.length, 1, "the guide's part comes before the old pictures go")
        if (done) done("")
      })
      compare(outcomeOf(r.token), "pending")
      compare(log.length, 0, "nothing put on before the helper answers")
      lastCall().done({ ok: true, outcome: "saved", theme: { name: "Neon" }, old: ["background.png", "pic-0011223344556677.png"] })
      compare(JSON.stringify(log), JSON.stringify(["saved:done"]))
      compare(lastCall().command, "theme-tidy")
      compare(JSON.stringify(lastCall().req.drop), JSON.stringify(["background.png", "pic-0011223344556677.png"]), "what only the old theme.json named")
      compare(outcomeOf(r.token), "pending", "saved once its tidy is done")
      lastCall().done({ ok: true, removed: 2 })
      compare(outcomeOf(r.token), "saved")
      compare(themes.turn, "")
    }

    function test_unconfirmed_and_failed_change_nothing_that_depends_on_them() {
      var log = []
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function(outcome, res, done) { log.push(outcome + (done ? ":done" : "")) })
      lastCall().done({ ok: true, outcome: "unconfirmed", why: "the disk hasn't confirmed it", theme: {}, old: [] })
      compare(JSON.stringify(log), JSON.stringify(["unconfirmed"]), "not put on")
      compare(outcomeOf(r.token), "unconfirmed")
      compare(whyOf(r.token), "the disk hasn't confirmed it")
      compare(lastCall().command, "theme-sweep", "no tidy; a load, so the list shows it")
      lastCall().done({ ok: true })
      log = []
      r = themes.save("neon", { name: "Neon" }, "theme neon", function(outcome, res, done) { log.push(outcome + (done ? ":done" : "")) })
      lastCall().done({ ok: false, outcome: "failed", why: "a picture couldn't be read (it isn't there, it's a link, or it isn't yours)" })
      compare(JSON.stringify(log), JSON.stringify(["failed"]))
      compare(outcomeOf(r.token), "failed")
      compare(whyOf(r.token), "a picture couldn't be read (it isn't there, it's a link, or it isn't yours)", "in the guide's words")
      r = themes.save("neon", { name: "Neon" }, "theme neon", function() {})
      lastCall().done({ ok: false, error: "something went wrong: /home/u/x" })
      compare(whyOf(r.token), "it couldn't be saved", "never the helper's error")
      r = themes.save("neon", { name: "Neon" }, "theme neon", function() {})
      lastCall().done({ ok: false, outcome: "failed", why: "couldn't read /home/u/secret/picture.png" })
      compare(whyOf(r.token), "it couldn't be saved", "never a path")
    }

    function test_a_failed_clean_up_keeps_saved_and_says_so() {
      var r = themes.save("neon", { name: "Neon" }, "theme neon", function(outcome, res, done) { if (done) done("saved and on, but the values for all apps it now gives couldn't be cleared") })
      lastCall().done({ ok: true, outcome: "saved", theme: {}, old: [] })
      lastCall().done({ ok: true, removed: 0 })
      compare(outcomeOf(r.token), "saved")
      verify(whyOf(r.token).indexOf("couldn't be cleared") > 0, whyOf(r.token))
    }

    function test_a_removal_reports_its_outcome() {
      var gone = []
      var r = themes.remove("neon", "theme neon: removed", function(outcome) { gone.push(outcome) })
      compare(lastCall().command, "theme-remove")
      compare(lastCall().req.id, "neon")
      compare(outcomeOf(r.token), "pending")
      lastCall().done({ ok: false, outcome: "failed", why: "it couldn't be removed" })
      compare(JSON.stringify(gone), JSON.stringify(["failed"]))
      compare(outcomeOf(r.token), "failed")
      r = themes.remove("neon", "theme neon: removed", function(outcome) { gone.push(outcome) })
      lastCall().done({ ok: true, outcome: "unconfirmed" })
      compare(outcomeOf(r.token), "unconfirmed")
      compare(gone[1], "unconfirmed", "gone from disk: the guide drops it")
    }

    function test_tokens_are_this_runs_in_order() {
      var a = saveAll("one")
      var b = saveAll("two")
      verify(a.token.indexOf("w-" + screens.run + "-") === 0 && b.token.indexOf("w-" + screens.run + "-") === 0)
      verify(Number(b.token.split("-").pop()) > Number(a.token.split("-").pop()))
    }
  }
}
