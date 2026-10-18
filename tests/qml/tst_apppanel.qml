import QtQuick
import QtTest
import "../.."
import "../../AppLooks.js" as Looks

// AppPanel.qml: the Customize panel's rows and
// changes, against the real AppScreens and a pretend store, view and helper.
// Only you open it; its rows are app.json's then others seen; each change
// goes through AppScreens as the panel's; hero only where the app made one;
// it closes, saying why, when its app is removed, reinstalled or restarted;
// nothing changes while the app is being changed.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root

  QtObject {
    id: store
    property bool loaded: true
    property string helper: "/nonexistent"
    property var changing: ({})
    property string incarnationProblem: ""
    property var installed: [{ id: "tv.example.app", name: "Example", kind: "app", source: "bundled", incarnation: "0123456789abcdef",
                               layout: { look: "posters", rows: [{ id: "latest", label: "Recently added" }, { id: "featured", label: "Featured", layout: "hero" }] } }]
    function record(id) { return store.installed.filter(function(a) { return a.id === id })[0] || null }
    property var runtimes: ({})
    function runtime(id) { return store.runtimes[id] || null }
    function randomHex(n) { var s = ""; while (s.length < n) s += "0123456789abcdef"; return s.slice(0, n) }
  }
  QtObject { id: rtA; property string phase: "ready"; property int gen: 1 }
  QtObject { id: rtB; property string phase: "ready"; property int gen: 2 }
  QtObject {
    id: view
    property string appId: "tv.example.app"
    property var rt: rtA
    property var record: store.record("tv.example.app")
    property var topView: ({ kind: "screen", value: { rows: [{ id: "continue", title: "Continue watching", items: [] }, { id: "latest", title: "Latest", items: [] }] } })
    property string message: ""
    property bool messageBad: false
    property var model: ({ screen: { look: "posters", top: "off", details: "app", titles: "below", size: "app", background: { mode: "details", dim: 0.75 }, from: {} } })
  }
  QtObject {
    id: guide
    property var byUser: ({})
    readonly property var apps: store
    readonly property var appView: view
    readonly property var appScreens: screens
    readonly property string configDir: "/tmp/om-pg-test-config"
    property var currentTheme: ({ id: "retro", apps: {} })
    property var picked: []
    function openPicker(images, area) { guide.picked = guide.picked.concat([area]) }
  }

  property var writes: []
  AppScreens {
    id: screens
    guide: guide
    reader: function(done) { done({ ok: true, text: "" }) }
    writer: function(text, done) { root.writes = root.writes.concat([{ text: text, done: done }]) }
  }
  AppPanel { id: panel; guide: guide }

  readonly property string key: "bundled\ntv.example.app"
  function mine() { return screens.now.apps[root.key] || ({}) }
  function rowAt(type, id) { var r = panel.rows; for (var i = 0; i < r.length; i++) if (r[i].type === type && (id === undefined || r[i].id === id)) return i; return -1 }

  TestCase {
    name: "AppPanel"

    function init() {
      root.writes = []
      screens.ops = []
      screens.done = []
      screens.counter = 0
      screens.writing = false
      screens.loaded = false
      screens.load()
      store.changing = ({})
      store.runtimes = ({})
      view.appId = "tv.example.app"
      view.record = store.record("tv.example.app")
      view.topView = { kind: "screen", value: { rows: [{ id: "continue", title: "Continue watching", items: [] }, { id: "latest", title: "Latest", items: [] }] } }
      view.rt = rtA
      rtA.phase = "ready"
      rtA.gen = 1
      view.message = ""
      panel.open = false
      panel.seen = ({})
      panel.noteRows()
    }

    function test_only_you_open_it() {
      compare(panel.openFor("tv.example.app", {}), "only the user, at the screen")
      verify(!panel.open)
      compare(panel.openFor("tv.example.app", guide.byUser), "ok")
      verify(panel.open)
    }

    function test_not_until_its_incarnation_is_on_disk() {
      var was = store.installed
      store.installed = [{ id: "tv.example.app", name: "Example", kind: "app", source: "bundled", incarnation: "", layout: was[0].layout }]
      compare(panel.openFor("tv.example.app", guide.byUser), "it isn't ready to customize yet")
      store.incarnationProblem = "Permission denied"
      compare(panel.openFor("tv.example.app", guide.byUser), "it isn't ready to customize yet (its record couldn't be saved: Permission denied; tried again shortly)")
      verify(!panel.open)
      store.incarnationProblem = ""
      store.installed = was
    }

    function test_its_rows_app_json_then_seen() {
      panel.openFor("tv.example.app", guide.byUser)
      var listed = panel.rows.filter(function(r) { return r.type === "row" }).map(function(r) { return r.id + ":" + r.label })
      compare(listed, ["latest:Recently added", "featured:Featured", "continue:Continue watching"], "app.json's (its labels), then the ones seen")
      verify(rowAt("look") > 0 && rowAt("follow") > rowAt("row", "continue"))
    }

    function test_a_change_is_the_panels_and_saved() {
      panel.openFor("tv.example.app", guide.byUser)
      panel.cursor = rowAt("look")
      panel.act(1)
      compare(mine().look, "app", "the next after unset: as the app suggests")
      panel.act(1)
      compare(mine().look, "classic")
      compare(screens.ops.length, 1, "two quick changes: one write (the panel's own merge)")
      compare(panel.note, "Saving…")
      tryVerify(function() { return root.writes.length === 1 }, 1000)
      root.writes[0].done({ ok: true, outcome: "saved" })
      compare(panel.note, "Saved.")
      panel.act(1)
      tryVerify(function() { return root.writes.length === 2 }, 1000)
      root.writes[1].done({ ok: false, outcome: "failed" })
      verify(panel.note.indexOf("Not saved") === 0, panel.note)
      compare(mine().look, "classic", "a failed change puts it back")
    }

    function test_each_look_row_cycles_to_unset() {
      panel.openFor("tv.example.app", guide.byUser)
      ;["top", "details", "titles", "size"].forEach(function(k) {
        panel.cursor = rowAt(k)
        panel.act(-1)
        compare(mine()[k], k === "top" ? "look" : "look", k + ": back from unset is As the look")
        panel.act(1)
        compare(mine()[k], undefined, k + ": As for all apps leaves it unset")
      })
      panel.cursor = rowAt("background")
      panel.act(1)
      compare(mine().background.mode, "focus")
      panel.cursor = rowAt("dim")
      panel.act(1)
      compare(mine().background.dim, 0.8, "darken goes in 5% steps")
    }

    function test_a_rows_options() {
      panel.openFor("tv.example.app", guide.byUser)
      panel.cursor = rowAt("row", "latest")
      panel.act(0)
      compare(panel.rowOpen, "latest")
      panel.cursor = rowAt("rowShow")
      panel.act(0)
      compare(mine().rows["r:latest"].show, false, "hidden")
      compare(panel.rowSummary("latest"), "Hidden")
      panel.act(0)
      compare(mine().rows, undefined, "shown again: nothing kept")
      panel.cursor = rowAt("rowShape")
      panel.act(1)
      compare(mine().rows["r:latest"].shape, "poster")
      // a hero only where the app made one
      panel.cursor = rowAt("rowLayout")
      for (var i = 0; i < 6; i++) { panel.act(1); verify(mine().rows["r:latest"].layout !== "hero") }
      panel.close()
      panel.cursor = rowAt("row", "featured")
      panel.act(0)
      panel.cursor = rowAt("rowLayout")
      var seenHero = false
      for (var j = 0; j < 6; j++) { panel.act(1); if (mine().rows && mine().rows["r:featured"] && mine().rows["r:featured"].layout === "hero") seenHero = true }
      verify(seenHero, "app.json made it a hero: it can be one again")
      // your name for it
      panel.rename("  My shows\u0007  ")
      compare(mine().rows["r:featured"].name, "My shows", "plain text")
      panel.rename("")
      compare(mine().rows["r:featured"].name, undefined, "empty: its own")
    }

    function test_moving_rows_makes_the_order_yours() {
      panel.openFor("tv.example.app", guide.byUser)
      panel.cursor = rowAt("row", "continue")
      panel.act(0)
      panel.cursor = rowAt("rowUp")
      panel.act(0)
      compare(mine().order, ["latest", "continue", "featured"])
      panel.act(0)
      compare(mine().order, ["continue", "latest", "featured"])
      panel.close()
      compare(panel.rows.filter(function(r) { return r.type === "row" }).map(function(r) { return r.id }), ["continue", "latest", "featured"], "listed in your order")
    }

    function test_follow_all_apps_settings() {
      panel.openFor("tv.example.app", guide.byUser)
      panel.cursor = rowAt("look")
      panel.act(1)
      verify(mine().look !== undefined)
      panel.cursor = rowAt("follow")
      panel.act(0)
      compare(screens.now.apps[root.key], undefined, "this app's choices gone")
    }

    function test_it_closes_when_its_app_changes_under_it() {
      panel.openFor("tv.example.app", guide.byUser)
      view.rt = rtB
      verify(!panel.open, "the app started again: closed")
      verify(view.message.indexOf("started again") >= 0, view.message)
      view.rt = rtA
      panel.openFor("tv.example.app", guide.byUser)
      var was = store.installed
      store.installed = [{ id: "tv.example.app", name: "Example", kind: "app", source: "bundled", incarnation: "ffffffffffffffff", layout: was[0].layout }]
      verify(!panel.open, "installed again: closed")
      verify(view.message.indexOf("installed again") >= 0, view.message)
      store.installed = was
      panel.openFor("tv.example.app", guide.byUser)
      store.installed = []
      verify(!panel.open, "removed: closed")
      store.installed = was
    }

    function test_nothing_changes_while_its_being_changed() {
      panel.openFor("tv.example.app", guide.byUser)
      store.changing = { "tv.example.app": true }
      panel.cursor = rowAt("look")
      panel.act(1)
      compare(mine().look, undefined)
      verify(panel.note.indexOf("being changed") >= 0, panel.note)
      store.changing = ({})
    }

    function test_every_apps_look() {
      compare(panel.openAll(guide.byUser), "ok")
      compare(panel.mode, "all")
      compare(rowAt("row"), -1, "no rows: they're each app's")
      panel.cursor = rowAt("look")
      panel.act(1)
      compare(screens.now.all.look, "app")
      compare(panel.label("look", ""), "As the theme", "left to the layer below: the theme")
    }

    // a picture of yours as the background: picked, checked and copied by the
    // helper (the guide), and only a copy of the guide's is taken
    function copyNamed(c) { return guide.configDir + "/app-pictures/" + c.repeat(32) + ".webp" }
    function pick() { panel.cursor = rowAt("bgPick"); panel.act(0); return panel.pickReq }
    function test_a_picture_for_the_background() {
      panel.openFor("tv.example.app", guide.byUser)
      verify(rowAt("bgPick") > 0, "a Pick a picture row")
      var req = pick()
      compare(guide.picked[guide.picked.length - 1], "appScreen", "the file picker, for an app's screen")
      panel.setPicture({ ok: true, path: copyNamed("e") }, req)
      compare(JSON.stringify(mine().background), JSON.stringify({ mode: "image", image: copyNamed("e"), dim: 0.75 }))
      req = pick()
      panel.setPicture({ ok: true, path: "/home/u/Pictures/raw.png" }, req)
      verify(panel.note.indexOf("Not used") === 0, "never a path that isn't the guide's copy")
      compare(mine().background.image, copyNamed("e"))
      req = pick()
      panel.setPicture({ ok: false, error: "a picture isn't a PNG, JPEG or WebP" }, req)
      compare(panel.note, "Not used: a picture isn't a PNG, JPEG or WebP.")
      panel.close()
      panel.openAll(guide.byUser)
      verify(rowAt("bgPick") > 0, "every app's too")
      panel.close()
      guide.picked = []
    }

    // a copy that comes back late lands only for the panel that asked, and only the latest
    function test_a_late_picture_never_lands_elsewhere() {
      panel.openFor("tv.example.app", guide.byUser)
      var before = JSON.stringify(mine().background)
      var reqA = pick()
      panel.close()
      panel.openFor("tv.example.app", guide.byUser)      // closed and opened again: another session
      panel.setPicture({ ok: true, path: copyNamed("a") }, reqA)
      compare(JSON.stringify(mine().background), before, "a pick from a panel since closed doesn't land")
      var reqB = pick()
      panel.close()
      panel.openAll(guide.byUser)                         // from one app to every app's
      panel.setPicture({ ok: true, path: copyNamed("b") }, reqB)
      verify(!screens.now.all.background, "an app's pick never lands on every app's")
      panel.close()
      panel.openFor("tv.example.app", guide.byUser)
      var first = pick()
      var second = pick()
      panel.setPicture({ ok: true, path: copyNamed("c") }, first)
      compare(JSON.stringify(mine().background), before, "the older pick, finishing first, doesn't land")
      panel.setPicture({ ok: true, path: copyNamed("d") }, second)
      compare(mine().background.image, copyNamed("d"), "the latest does")
      panel.setPicture({ ok: true, path: copyNamed("c") }, first)
      compare(mine().background.image, copyNamed("d"), "and the older one, late, never overwrites it")
      panel.close()
      guide.picked = []
    }

    // a later choice for that background, from anywhere, wins over a pick
    // still being copied; the darkness alone doesn't (it lands with it)
    function test_a_later_background_choice_wins_over_a_late_picture_data() {
      return [
        { tag: "the background row", later: function() { panel.cursor = rowAt("background"); panel.act(1) } },
        { tag: "follow all apps' settings", later: function() { panel.cursor = rowAt("look"); panel.act(1); panel.cursor = rowAt("follow"); panel.act(0) } },
        { tag: "a command's change", later: function() { screens.change(root.key, function(st) { var e = st.apps[root.key] || { incarnation: "0123456789abcdef" }; e.background = { mode: "none", dim: 0.5 }; st.apps[root.key] = e }, "command", "test") } },
        { tag: "a reset (dropPick)", later: function() { panel.dropPick(root.key) } }
      ]
    }
    function test_a_later_background_choice_wins_over_a_late_picture(d) {
      panel.openFor("tv.example.app", guide.byUser)
      var req = pick()
      d.later()
      var was = JSON.stringify(mine().background)
      panel.setPicture({ ok: true, path: copyNamed("f") }, req)
      compare(JSON.stringify(mine().background), was, "the late picture doesn't land")
      panel.close()
      screens.change(root.key, function(st) { delete st.apps[root.key] }, "command", "test")
      guide.picked = []
    }
    function test_darker_meanwhile_the_picture_lands_with_it() {
      panel.openFor("tv.example.app", guide.byUser)
      var req = pick()
      panel.cursor = rowAt("dim")
      panel.act(1)
      var dim = mine().background.dim
      panel.dropPick("all")                      // another layer's: not this one
      panel.setPicture({ ok: true, path: copyNamed("a") }, req)
      compare(JSON.stringify(mine().background), JSON.stringify({ mode: "image", image: copyNamed("a"), dim: dim }), "the picture, with the newer darkness: " + panel.note)
      panel.close()
      screens.change(root.key, function(st) { delete st.apps[root.key] }, "command", "test")
      guide.picked = []
    }

    // left to the theme, the all-apps panel shows what the theme gives
    function test_every_apps_look_shows_what_the_theme_gives() {
      screens.change("all", function(st) { st.all = {} }, "command", "test")
      panel.openAll(guide.byUser)
      compare(panel.shown("look"), "As the theme (as each app suggests)", "a theme with no look: each app's suggestion, then Classic")
      compare(panel.shown("top"), "As the theme (Off)", "Classic's")
      compare(panel.shown("size"), "As the theme (as each app says)")
      guide.currentTheme = { id: "cinema", apps: { look: "cinematic", top: "off", background: { mode: "none", dim: 0.4 } } }
      compare(panel.shown("look"), "As the theme (Cinematic)")
      compare(panel.shown("top"), "As the theme (Off)", "the theme's own")
      compare(panel.shown("titles"), "As the theme (Selected only)", "the theme's look's")
      compare(panel.shown("background"), "As the theme (None)")
      compare(panel.dimNow(), 0.4, "Darken shows the theme's")
      // Darken from there starts at what the theme gives
      panel.cursor = rowAt("dim")
      panel.act(1)
      compare(JSON.stringify(screens.now.all.background), JSON.stringify({ mode: "none", dim: 0.45 }))
      guide.currentTheme = { id: "retro", apps: {} }
      screens.change("all", function(st) { st.all = {} }, "command", "test")
    }

    // an app's panel opened from Settings (its screen not on): what it gets,
    // worked out the same way the screen would
    // two apps with a row of the same id: another app's screen making it a
    // hero doesn't let this app's panel (from Settings) make this app's one;
    // its own screen's hint, for the install and run it's bound to, does
    function test_hero_hints_only_from_its_own_screen() {
      var was = store.installed
      store.installed = was.concat([{ id: "tv.example.two", name: "Two", kind: "app", source: "bundled", incarnation: "2222222222222222", layout: { look: "", rows: [] } }])
      view.appId = "tv.example.two"
      view.record = store.record("tv.example.two")
      view.topView = { kind: "screen", value: { rows: [{ id: "latest", title: "Latest", layout: "hero", items: [] }] } }
      compare(panel.openFor("tv.example.app", guide.byUser), "ok")
      verify(!panel.appHero("latest"), "another app's hint doesn't count")
      panel.cursor = rowAt("row", "latest")
      panel.act(0)
      panel.cursor = rowAt("rowLayout")
      for (var i = 0; i < 6; i++) { panel.act(1); verify(!(mine().rows && mine().rows["r:latest"] && mine().rows["r:latest"].layout === "hero"), "never offered") }
      panel.close()
      panel.close()
      view.appId = "tv.example.app"
      view.record = store.record("tv.example.app")
      compare(panel.openFor("tv.example.app", guide.byUser), "ok")
      verify(panel.appHero("latest"), "its own screen's hint counts")
      panel.close()
      store.installed = was
    }

    // the rows seen are for one install's one run: leaving its screen and
    // coming back to the same run keeps them; a new run, or another install
    // while the panel is closed, clears them
    function test_rows_seen_for_one_install_and_run() {
      var A = function() { return store.record("tv.example.app") }
      var ids = function() { return panel.seenRows(A()).map(function(r) { return r.id }) }
      store.runtimes = { "tv.example.app": rtA }
      compare(ids(), ["continue", "latest"], "seen on its screen")
      view.rt = null                    // you leave its screen; it keeps running
      view.appId = ""
      view.appId = "tv.example.app"
      view.rt = rtA                     // and come back to the same run
      compare(ids(), ["continue", "latest"], "leaving and coming back to the same run keeps them")
      view.rt = null                    // away from its screen, it starts again
      view.appId = ""
      store.runtimes = { "tv.example.app": rtB }
      compare(ids(), [], "a new run: cleared")
      view.appId = "tv.example.app"
      view.rt = rtB
      view.topView = { kind: "screen", value: { rows: [{ id: "fresh", title: "Fresh", items: [] }] } }
      compare(ids(), ["fresh"], "and what the new run shows is noted afresh")
      // a run's rows never carry into another's, whatever came first
      panel.seen = { "bundled\ntv.example.app": { id: "tv.example.app", incarnation: "0123456789abcdef", gen: 1, rows: [{ id: "old", title: "Old" }] } }
      view.topView = { kind: "screen", value: { rows: [{ id: "newer", title: "Newer", items: [] }] } }
      compare(ids(), ["newer"], "the old run's rows aren't added to")
      var was = store.installed
      store.installed = [{ id: "tv.example.app", name: "Example", kind: "app", source: "bundled", incarnation: "ffffffffffffffff", layout: was[0].layout }]
      compare(ids(), [], "installed again, the panel closed: the old install's rows go")
      compare(Object.keys(panel.seen).length, 0, "and aren't kept")
      store.installed = was
      // another install's entry is never read as this one's
      panel.seen = { "bundled\ntv.example.app": { id: "tv.example.app", incarnation: "ffffffffffffffff", gen: 2, rows: [{ id: "old", title: "Old" }] } }
      compare(ids(), [], "another install's rows aren't this one's")
      view.rt = rtA
    }

    function test_an_apps_panel_away_from_its_screen() {
      var was = view.appId
      view.appId = ""
      view.model = ({ screen: { look: "wall", top: "selected", details: "app", titles: "off", size: "small", background: { mode: "focus", dim: 0.75 }, from: {} } })
      compare(panel.openFor("tv.example.app", guide.byUser), "ok")
      compare(panel.shown("look"), "As for all apps (Posters)", "its app.json suggestion, not another screen's model")
      compare(panel.shown("titles"), "As for all apps (Every card)", "Posters' titles")
      screens.change("all", function(st) { st.all = { look: "compact" } }, "command", "test")
      compare(panel.shown("look"), "As for all apps (Compact)", "all apps' choice over its suggestion")
      screens.change("all", function(st) { st.all = {} }, "command", "test")
      view.appId = was
      view.model = ({ screen: { look: "posters", top: "off", details: "app", titles: "below", size: "app", background: { mode: "details", dim: 0.75 }, from: {} } })
      panel.close()
    }
  }
}
