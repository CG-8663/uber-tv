import QtQuick
import QtTest
import "../.."
import "../../AppLooks.js" as Looks

// AppAgent.qml: what agents see and change of
// apps' screens, against the real AppScreens and a pretend guide, store and
// view. The boundary: no app-written text and no row or item id in any
// answer (only r- and i- handles), a raw row id answered like a made-up
// key, a file app by its id alone, stale handles failing, and the handle
// tables held at their caps however many rows go by.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root

  // a secret an app might copy into what it sends
  readonly property string secret: "tok_SECRET_9f8e7d6c5b4a"
  readonly property string nasty: "\"`$(rm -rf ~)`; __proto__ " + root.secret

  property int hexes: 0
  QtObject {
    id: store
    property bool loaded: true
    property string helper: "/nonexistent"
    property var changing: ({})
    property var installed: [
      { id: "tv.example.app", name: "Example", kind: "app", source: "bundled", from: "bundled", incarnation: "0123456789abcdef",
        layout: { look: "posters", rows: [{ id: "lib-tok_SECRET_9f8e7d6c5b4a", label: "Movies" }, { id: "latest", label: "Recently added" }] } },
      { id: "tv.example.file", name: "A file app " + root.secret, kind: "app", source: "file:0123456789abcdef", from: "file", incarnation: "fedcba9876543210",
        layout: { look: "", rows: [{ id: "x", label: "Label " + root.secret }] } }]
    function record(id) { return store.installed.filter(function(a) { return a.id === id })[0] || null }
    function randomHex(n) {
      root.hexes++
      var s = ""
      var x = root.hexes * 2654435761 % 4294967296
      while (s.length < n) { x = (x * 1103515245 + 12345) % 2147483648; s += ("0000000" + x.toString(16)).slice(-8) }
      return s.slice(0, n)
    }
  }
  QtObject { id: rtA; property string phase: "ready"; property int gen: 1 }
  QtObject { id: rtB; property string phase: "ready"; property int gen: 2 }
  QtObject {
    id: view
    property bool shown: true
    property string appId: "tv.example.app"
    property var rt: rtA
    property var record: store.record(view.appId)
    property var topView: null
    property bool settingsOpen: false
    property var signIn: null
    property var editing: null
    property var certOffer: null
    property string failed: ""
    property bool loading: false
    property var wanted: ({})
    property var imagePaths: ({})
    readonly property var model: Looks.model(view.topView, { width: 1280, u: 10, choices: { mine: screens.entryOf(view.record) || {}, all: screens.now.all, theme: {} },
                                                             suggested: view.record && view.record.layout ? view.record.layout.look : "" })
  }
  QtObject { id: panelStub; property bool open: false; property bool renaming: false; property var rows: ({}); property var dropped: []
              function seenRows(a) { return panelStub.rows[a.id + "|" + a.incarnation] || [] }
              function dropPick(key) { panelStub.dropped = panelStub.dropped.concat([key]) } }
  QtObject {
    id: guide
    property var byUser: ({})
    property bool opened: true
    property string screen: "app"
    property bool watching: false
    property var vod: null
    property bool appPlaying: false
    property bool pip: false
    property string dialog: ""
    property bool railOpen: false
    property bool railEditing: false
    property string appOpening: ""
    property bool styleNaming: false
    readonly property var snapshots: snaps
    property var currentTheme: ({ id: "retro", apps: {} })
    readonly property var apps: store
    readonly property var appView: view
    readonly property var appScreens: screens
    readonly property var appPanel: panelStub
    readonly property string configDir: "/tmp/om-pg-test-config"
  }
  property var writes: []
  AppScreens {
    id: screens
    guide: guide
    reader: function(done) { done({ ok: true, text: "" }) }
    writer: function(text, done) { root.writes = root.writes.concat([{ text: text, done: done }]); done({ ok: true, outcome: "saved" }) }
  }
  AppAgent { id: agent; guide: guide }

  // the guide's snapshots, the grab and the move stood in for
  Rectangle { id: shot; width: 320; height: 180 }
  property var grabs: []
  property var moves: []
  property var saved: []
  Snapshots {
    id: snaps
    guide: guide
    target: shot
    folder: "/tmp/om-pg-snaps"
    run: "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    grab: function(item, done, size) { root.grabs = root.grabs.concat([done]); return true }
    mover: function(argv, done) { root.moves = root.moves.concat([{ argv: argv, done: done }]) }
  }
  function grabNow() { root.grabs[root.grabs.length - 1]({ saveToFile: function(p) { root.saved = root.saved.concat([p]); return true } }) }
  function calm() {
    guide.opened = true
    guide.screen = "app"
    guide.watching = false
    guide.vod = null
    guide.appPlaying = false
    guide.pip = false
    guide.dialog = ""
    guide.railOpen = false
    guide.railEditing = false
    guide.appOpening = ""
    panelStub.open = false
    view.shown = true
    view.settingsOpen = false
    view.signIn = null
    view.editing = null
    view.certOffer = null
  }
  // what can come over an app's screen (or take it away), each undone by calm();
  // why: the words either check gives (the guide's own guard may answer first)
  readonly property var covers: [
    { tag: "the rail", why: "the rail", set: function() { guide.railOpen = true } },
    { tag: "the rail, customized", why: "the rail", set: function() { guide.railEditing = true } },
    { tag: "Customize", why: "Customize", set: function() { panelStub.open = true } },
    { tag: "help", why: "a box", set: function() { guide.dialog = "help" } },
    { tag: "the style panel", why: "a box", set: function() { guide.dialog = "style" } },
    { tag: "the phone remote's box", why: "pairing code", set: function() { guide.dialog = "remote" } },
    { tag: "an app's settings", why: "an app's", set: function() { view.settingsOpen = true } },
    { tag: "its sign-in", why: "an app's", set: function() { view.signIn = { code: "123456" } } },
    { tag: "its text field", why: "an app's|a text field", set: function() { view.editing = { type: "text", key: "k", label: "L", text: "" } } },
    { tag: "a certificate to pin", why: "an app's|a certificate", set: function() { view.certOffer = { sha256: "ab" } } },
    { tag: "the TV", why: "playing", set: function() { guide.watching = true } },
    { tag: "on demand", why: "playing", set: function() { guide.vod = { title: "x" } } },
    { tag: "the app's media", why: "playing", set: function() { guide.appPlaying = true } },
    { tag: "the mini player", why: "playing", set: function() { guide.pip = true } },
    { tag: "an app coming up", why: "coming up", set: function() { guide.appOpening = "tv.example.web" } },
    { tag: "another screen", why: "isn't on", set: function() { guide.screen = "home"; view.shown = false } },
    { tag: "the guide closed", why: "isn't open|the guide closed", set: function() { guide.opened = false } }
  ]

  function item(id, title, kind) { return { id: id, title: title, subtitle: root.nasty, badge: "", kind: kind || "open", image: null, progress: null, meta: root.nasty, text: root.nasty } }
  function screen(rows) { return { kind: "screen", value: { title: root.nasty, rows: rows } } }

  TestCase {
    name: "AppAgent"

    function init() {
      root.calm()
      if (snaps.live) snaps.finish(snaps.live, "refused", "test")
      root.grabs = []
      root.moves = []
      root.saved = []
      screens.ops = []
      screens.done = []
      screens.counter = 0
      screens.writing = false
      screens.loaded = false
      screens.load()
      view.appId = "tv.example.app"
      view.record = store.record("tv.example.app")
      view.shown = true
      view.topView = screen([
        { id: "lib-tok_SECRET_9f8e7d6c5b4a", title: root.nasty, layout: "grid", items: [item("tok_SECRET_item1", root.nasty), item("i2", "Season 2", "info")] },
        { id: "latest", title: "Latest " + root.secret, items: [item("lib-a", "Library A"), item("lib-b", "Library B " + root.secret)] }])
    }

    function test_no_app_text_and_no_ids_in_any_answer() {
      var answers = [agent.appScreen("tv.example.app"), agent.appScreen("tv.example.file"), agent.appScreen("all")]
      var h = answers[0].rows[0].handle
      answers.push(agent.setAppScreen("tv.example.app", JSON.stringify({ look: "wall", rows: (function() { var r = {}; r[h] = { name: "Mine" }; return r })() })))
      answers.push(agent.setAppScreen("tv.example.app", JSON.stringify({ rows: { "lib-tok_SECRET_9f8e7d6c5b4a": { show: false } } })))
      answers.forEach(function(a, i) {
        var text = JSON.stringify(a)
        verify(text.indexOf(root.secret) < 0, "answer " + i + " carries nothing the app wrote: " + text.slice(0, 300))
        verify(text.indexOf("tok_SECRET_item1") < 0 && text.indexOf("lib-a") < 0, "no item ids")
        verify(text.indexOf("$(") < 0 && text.indexOf("`") < 0, "none of its text")
      })
      var rows = answers[0].rows
      verify(rows.length === 2 && rows.every(function(r) { return /^r-[0-9a-f]{12}$/.test(r.handle) }), "rows by handle")
      compare(rows[0].label, "Movies", "a bundled app's app.json label (reviewed)")
      verify(answers[0].items.every(function(x) { return /^i-[0-9a-f]{16}$/.test(x.handle) && /^r-/.test(x.row) }), "items by handle")
      compare(answers[0].name, "Example")
    }

    function test_a_file_app_has_no_name_and_no_labels() {
      view.appId = "tv.example.file"
      view.record = store.record("tv.example.file")
      view.topView = screen([{ id: "x", title: "X", items: [item("a", "A")] }])
      var a = agent.appScreen("tv.example.file")
      verify(a.ok)
      compare(a.name, undefined, "no name")
      verify(a.rows.every(function(r) { return r.label === undefined }), "no labels")
      verify(a.otherRows.every(function(r) { return r.label === undefined }))
    }

    // the rows the panel saw on its screens, for this install (the panel
    // keeps them per install and run): by handle, never by their titles
    function test_rows_the_panel_saw_by_handle() {
      panelStub.rows = { "tv.example.app|0123456789abcdef": [{ id: "seen-row", title: "Seen " + root.secret }] }
      var a = agent.appScreen("tv.example.app")
      var h = agent.rowHandle(store.record("tv.example.app"), "seen-row")
      verify(a.otherRows.some(function(r) { return r.handle === h }), "a row seen on its screen, by handle")
      verify(JSON.stringify(a).indexOf(root.secret) < 0, "never its title")
      panelStub.rows = ({})
    }

    // a background set or taken off by a command, or a reset, is newer than
    // a picture still being copied for that layer in the panel
    function test_a_commands_background_drops_a_pick_on_its_way() {
      panelStub.dropped = []
      verify(agent.setAppScreen("tv.example.app", JSON.stringify({ size: "large" })).ok)
      compare(panelStub.dropped, [], "not for a change that leaves the background")
      verify(agent.setAppScreen("tv.example.app", JSON.stringify({ background: { mode: "none", dim: 0.5 } })).ok)
      compare(panelStub.dropped, [screens.keyOf(view.record)])
      verify(agent.setAppScreen("all", JSON.stringify({ background: null })).ok)
      compare(panelStub.dropped[1], "all", "taken off, for all apps")
      verify(agent.resetAppScreen("tv.example.app").ok)
      compare(panelStub.dropped[2], screens.keyOf(view.record), "a reset")
      agent.resetAppScreen("all")
      panelStub.dropped = []
    }

    function test_a_raw_id_is_answered_like_a_made_up_key() {
      var raw = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: { "latest": { show: false } } }))
      var madeUp = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: { "nosuchrow": { show: false } } }))
      compare(raw.ignored.length, 1)
      compare(madeUp.ignored.length, 1)
      compare(JSON.stringify(raw), JSON.stringify(madeUp).replace(/w-[0-9a-f]+-\d+/, raw.saving), "the same answer either way, byte for byte (but its token)")
      compare(screens.entryOf(view.record), null, "and nothing set")
    }

    function test_a_change_by_handle() {
      var a = agent.appScreen("tv.example.app")
      var latest = a.rows[1].handle
      var other = a.rows[0].handle
      var r = agent.setAppScreen("tv.example.app", JSON.stringify({ look: "wall", size: "large", rows: (function() { var o = {}; o[latest] = { show: false, shape: "poster" }; return o })(), order: [latest, other] }))
      verify(r.ok, JSON.stringify(r))
      verify(/^w-[0-9a-f]{32}-\d+$/.test(r.saving))
      var e = screens.entryOf(view.record)
      compare([e.look, e.size, e.rows["r:latest"].show, e.rows["r:latest"].shape, e.order.join(",")], ["wall", "large", false, "poster", "latest,lib-tok_SECRET_9f8e7d6c5b4a"])
      compare(r.will.rows[latest].show, false, "what it will save, by handle")
      var b = agent.appScreen("tv.example.app")
      compare(b.choices.look, "wall")
      compare(b.result.look, "wall")
      verify(b.rows.some(function(x) { return x.handle === latest && x.shown === false }), "a hidden row stays listed")
      // null takes a choice off
      agent.setAppScreen("tv.example.app", JSON.stringify({ size: null, rows: (function() { var o = {}; o[latest] = { shape: null }; return o })() }))
      e = screens.entryOf(view.record)
      compare(e.size, undefined)
      compare(e.rows["r:latest"].shape, undefined)
      // all takes no rows or order
      var all = agent.setAppScreen("all", JSON.stringify({ look: "cinematic", rows: {}, order: [] }))
      verify(all.ok)
      compare(screens.now.all.look, "cinematic")
      compare(all.ignored.length, 2)
      // reset
      verify(agent.resetAppScreen("tv.example.app").ok)
      compare(screens.entryOf(view.record), null)
    }

    function test_stale_handles_fail() {
      var h = agent.appScreen("tv.example.app").rows[0].handle
      // a reinstall: a new incarnation
      var was = store.installed
      store.installed = [{ id: "tv.example.app", name: "Example", kind: "app", source: "bundled", from: "bundled", incarnation: "1111111111111111", layout: was[0].layout }, was[1]]
      view.record = store.record("tv.example.app")
      var r = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: (function() { var o = {}; o[h] = { show: false } ; return o })() }))
      compare(r.ignored.length, 1, "a handle from before the reinstall doesn't address anything")
      compare(screens.entryOf(view.record), null)
      var h2 = agent.appScreen("tv.example.app").rows[0].handle
      verify(h2 !== h, "the row gets a new handle")
      store.installed = was
      view.record = store.record("tv.example.app")
      // another app's handle is unknown here
      view.appId = "tv.example.file"; view.record = store.record("tv.example.file"); view.topView = screen([{ id: "x", title: "X", items: [item("a", "A")] }])
      var hf = agent.appScreen("tv.example.file").rows[0].handle
      view.appId = "tv.example.app"; view.record = store.record("tv.example.app")
      var r2 = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: (function() { var o = {}; o[hf] = { show: false }; return o })() }))
      compare(r2.ignored.length, 1)
      // an item handle stops with its view
      view.topView = screen([{ id: "r", title: "R", items: [item("a", "A")] }])
      var ih = agent.appScreen("tv.example.app").items[0].handle
      verify(agent.itemOf(view.record, ih) !== null)
      view.topView = screen([{ id: "r", title: "R", items: [item("a", "A")] }])
      compare(agent.itemOf(view.record, ih), null, "a new view: the old item handle is stale")
    }

    function test_the_handle_tables_stay_at_their_caps() {
      var a = view.record
      var first = agent.rowHandle(a, "row0")
      for (var i = 1; i < 300; i++) agent.rowHandle(a, "row" + i)
      compare(agent.rowCount(agent.keyOf(a)), 256, "256 an app")
      compare(agent.rowOf(a, first), "", "the least recently used went: its handle addresses nothing")
      verify(agent.rowOf(a, agent.rowHandle(a, "row299")) === "row299")
      // across apps: 2,048 in all
      var many = []
      for (var k = 0; k < 10; k++) many.push({ id: "tv.many.a" + k, kind: "app", source: "bundled", from: "bundled", incarnation: "abcdef012345678" + k })
      many.forEach(function(m) { for (var j = 0; j < 256; j++) agent.rowHandle(m, "r" + j) })
      verify(agent.handleCount() <= 2048, "2,048 in all: " + agent.handleCount())
      many.forEach(function(m) { verify(agent.rowCount(agent.keyOf(m)) <= 256) })
    }

    function test_two_libraries_in_a_row_and_a_later_season_by_their_handles() {
      view.topView = screen([{ id: "libraries", title: "Libraries", items: [item("lib-a", "A"), item("lib-b", "B")] },
                             { id: "seasons", title: "Seasons", items: [item("s1", "Season 1", "info"), item("s2", "Season 2", "info")] }])
      var a = agent.appScreen("tv.example.app")
      var libs = a.items.filter(function(x) { return x.row === a.rows[0].handle })
      compare(libs.map(function(x) { return x.position }).sort().join(","), "0,1")
      var second = libs.filter(function(x) { return x.position === 1 })[0]
      compare(agent.itemOf(view.record, second.handle).item, "lib-b", "the second library, reachable by its handle")
      var seasons = a.items.filter(function(x) { return x.row === a.rows[1].handle && x.kind === "info" })
      compare(agent.itemOf(view.record, seasons[1].handle).item, "s2", "the later season")
    }

    // the 64 KiB cap is in UTF-8 bytes
    function test_the_cap_is_in_bytes() {
      var cjk = JSON.stringify({ x: "\u4e2d".repeat(30000) })        // ~30,000 code units, ~90,000 bytes
      verify(cjk.length < 65536)
      compare(agent.setAppScreen("tv.example.app", cjk).error, "at most 64 KB of JSON")
      var edge = JSON.stringify({ x: "a".repeat(65536 - 8) })          // exactly 65,536 bytes
      compare(screens.bytes(edge), 65536)
      verify(agent.setAppScreen("tv.example.app", edge).ok, "65,536 bytes is fine")
      verify(!agent.setAppScreen("tv.example.app", JSON.stringify({ x: "a".repeat(65536 - 7) })).ok, "one more byte isn't")
      var astral = JSON.stringify({ x: "\ud83d\ude00".repeat(16400) }) // 4 bytes each: past 64 KiB in 32,800 code units
      compare(agent.setAppScreen("tv.example.app", astral).error, "at most 64 KB of JSON")
    }

    // past a cap, refused with why, never cut or evicted
    function test_past_a_cap_its_refused() {
      var h = agent.appScreen("tv.example.app").rows[0].handle
      var long = "N".repeat(41)
      var r = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: (function() { var o = {}; o[h] = { name: long }; return o })() }))
      verify(r.ok && r.ignored.some(function(x) { return x.indexOf("at most 40 characters") >= 0 }), JSON.stringify(r))
      compare(((screens.entryOf(view.record) || {}).rows || {})["r:lib-tok_SECRET_9f8e7d6c5b4a"], undefined, "a name over 40 is never cut and kept")
      // 41 rows' choices for one app (handles for rows the app has shown)
      var handles = []
      for (var i = 0; i < 41; i++) handles.push(agent.rowHandle(view.record, "row" + i))
      var many = {}
      handles.forEach(function(x) { many[x] = { show: false } })
      r = agent.setAppScreen("tv.example.app", JSON.stringify({ rows: many }))
      verify(!r.ok && r.error.indexOf("at most 40") >= 0, JSON.stringify(r).slice(0, 200))
      compare(screens.entryOf(view.record), null, "nothing kept")
      r = agent.setAppScreen("tv.example.app", JSON.stringify({ order: handles }))
      verify(!r.ok && r.error === "at most 40 rows in order", JSON.stringify(r).slice(0, 200))
      r = agent.setAppScreen("tv.example.app", JSON.stringify({ order: handles.slice(0, 40) }))
      verify(r.ok, "40 is fine")
    }

    function test_covered_and_state() {
      var a = agent.appScreen("tv.example.app")
      compare([a.onScreen, a.state, a.covered], [true, "ready", false])
      verify(/^v-\d+$/.test(a.view))
      guide.railOpen = true
      compare(agent.appScreen("tv.example.app").covered, true, "the rail over it")
      guide.railOpen = false
      view.settingsOpen = true
      compare(agent.appScreen("tv.example.app").covered, true, "its settings")
      view.settingsOpen = false
      view.shown = false
      compare(agent.appScreen("tv.example.app").state, "elsewhere")
      view.shown = true
    }

    // ---- appSnapshot ----------------------------------------------------------------
    function test_a_snapshot_of_the_view_on_the_screen() {
      var v = agent.appScreen("tv.example.app").view
      var a = agent.appSnapshot(v)
      verify(a.ok, a.error)
      verify(/^\/tmp\/om-pg-snaps\/snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-[0-9]+\.png$/.test(a.name), a.name)
      compare(JSON.stringify(snaps.report), JSON.stringify({ name: a.name, outcome: "pending", why: "" }))
      root.grabNow()
      compare(root.moves.length, 1)
      root.moves[0].done(true)
      compare(snaps.report.outcome, "written")
      compare(snaps.report.name, a.name)
    }

    function test_a_snapshot_needs_a_view_id() {
      ["", "v-", "1", "v-1; rm", "v-1\n", "../v-1", null, 7].forEach(function(x) {
        var a = agent.appSnapshot(x)
        verify(!a.ok && a.error === "a view id, as openApp or appScreen gave it", String(x) + ": " + a.error)
      })
      compare(root.grabs.length, 0)
    }

    function test_covered_and_refused_when_asked_data() { return root.covers }
    function test_covered_and_refused_when_asked(d) {
      var v = agent.appScreen("tv.example.app").view
      d.set()
      if (guide.screen === "app" && guide.opened && view.shown) compare(agent.appScreen("tv.example.app").covered, true, "appScreen says covered")
      var a = agent.appSnapshot(v)
      verify(!a.ok && new RegExp(d.why).test(a.error), String(a.error))
      compare(root.grabs.length, 0, "nothing grabbed")
    }

    function test_refused_at_the_grab_data() { return root.covers }
    function test_refused_at_the_grab(d) {
      var v = agent.appScreen("tv.example.app").view
      verify(agent.appSnapshot(v).ok)
      d.set()
      root.grabNow()
      compare(snaps.report.outcome, "refused")
      verify(new RegExp(d.why).test(snaps.report.why), snaps.report.why)
      compare(root.saved.length, 0, "no file")
      compare(root.moves.length, 0)
      // over it and gone again before the grab: refused all the same
      root.calm()
      verify(agent.appSnapshot(v).ok)
      d.set()
      root.calm()
      root.grabNow()
      compare(snaps.report.outcome, "refused", "it came over the screen while the picture was taken")
      verify(new RegExp(d.why).test(snaps.report.why), snaps.report.why)
      compare(root.saved.length, 0)
    }

    // the view an agent asked for, gone: moving on, Back, the app starting again
    function test_another_view_fails_explicitly_data() {
      return [
        { tag: "moving on", go: function(first) { view.topView = screen([{ id: "next", title: "Next", items: [item("n1", "N1")] }]) } },
        { tag: "Back", go: function(first) { var deeper = screen([{ id: "d", title: "D", items: [] }]); view.topView = deeper; view.topView = first } },
        { tag: "a restart", go: function(first) { view.rt = rtB; view.topView = null; view.topView = screen([{ id: "latest", title: "L", items: [] }]) } }
      ]
    }
    function test_another_view_fails_explicitly(d) {
      var first = view.topView
      var v = agent.appScreen("tv.example.app").view
      // between the poll and the capture: an error answer
      d.go(first)
      var now = agent.appScreen("tv.example.app").view
      verify(now !== v, "a new view id: " + v + " then " + now)
      var a = agent.appSnapshot(v)
      verify(!a.ok && a.error.indexOf("that view isn't the one on the screen") >= 0, String(a.error))
      // between the request and the grab: refused, no file
      view.rt = rtA
      view.topView = first
      v = agent.appScreen("tv.example.app").view
      verify(agent.appSnapshot(v).ok)
      d.go(first)
      root.grabNow()
      compare(snaps.report.outcome, "refused")
      verify(snaps.report.why.indexOf("that view isn't the one on the screen") >= 0, snaps.report.why)
      compare(root.saved.length, 0)
      view.rt = rtA
    }
  }
}
