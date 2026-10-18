import QtQuick
import QtTest
import "../.."

// AppHome.qml against a pretend store and runtime: Home rows load only while
// Home shows, are kept 10 minutes for the same app, version, server,
// settings and sign-in, keep their cards when they fail, and open the app at
// the card's item. Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root

  QtObject {
    id: rt
    property string phase: "ready"
    property var calls: []
    property var leases: ({})
    signal readyNow()
    signal stopped(string why, string text)
    property var cancelled: []
    function call(method, args, done) { rt.calls = rt.calls.concat([{ method: method, args: args, done: done }]); return rt.calls.length }
    function cancel(id) { rt.cancelled = rt.cancelled.concat([id]); var c = rt.calls[id - 1]; if (c) c.done("error", { code: "cancelled", text: "cancelled" }) }
    function lease(name, on) { var l = {}; for (var k in rt.leases) l[k] = true; if (on) l[name] = true; else delete l[name]; rt.leases = l }
    property var sizes: ({})           // token -> [w, h], as the helper gives them
    property var askedFor: []
    property var letGo: []             // tokens the helper no longer knows
    property var refuse: []            // tokens the rules won't fetch
    property var fail: []              // tokens that can't be fetched
    property bool holdPictures: false  // answers wait (in held) until the test gives them
    property var held: []              // [{ token, done, consumer }]
    property var brokenAsks: []        // tokens asked for again because their file couldn't be drawn
    function image(token, done, epoch, prio, consumer, broken) {
      rt.askedFor = rt.askedFor.concat([token])
      if (broken === true) rt.brokenAsks = rt.brokenAsks.concat([token])
      if (rt.holdPictures) { rt.held = rt.held.concat([{ token: token, done: done, consumer: consumer }]); return }
      var sz = rt.sizes[token] || [0, 0]
      var code = rt.letGo.indexOf(token) >= 0 ? "unknown" : rt.refuse.indexOf(token) >= 0 ? "refused" : rt.fail.indexOf(token) >= 0 ? "failed" : ""
      Qt.callLater(function() { if (code) done("", { code: code }); else done("/tmp/pic-" + token + ".png", { w: sz[0], h: sz[1] }) })
    }
    property var released: []
    property int demand: 0
    function release(results) { rt.released = rt.released.concat(results) }
    property var lived: []             // "on:<id>", "off:<id>" (api 4's live rows)
    function viewOn(v) { rt.lived = rt.lived.concat(["on:" + v]); return true }
    function viewOff(v) { rt.lived = rt.lived.concat(["off:" + v]); return true }
  }

  QtObject {
    id: store
    property bool on: true
    property var authGens: ({})
    property var ready: [{ id: "tv.example.app" }]
    property string version: "1.0.0"
    property var values: ({})
    property string refuse: ""
    property var cleared: []
    property var homeRows: [{ key: "now", label: "Now" }]
    property int api: 3
    signal liveUpdated(string id, var rt, int view, var rows, var items)
    function record(id) {
      if (id !== "tv.example.app") return null
      return { id: id, name: "Example", kind: "app", api: store.api, source: "bundled", version: store.version, server: "", pin: "", values: store.values,
               home: store.homeRows, settings: [{ key: "league", type: "choice", choices: ["A", "B"] }] }
    }
    function valuesOf(a) { return a.values || {} }
    function ensure(id, lease) {
      if (store.refuse) return { rt: null, why: store.refuse }
      rt.lease(lease, true)
      return { rt: rt, why: "" }
    }
    function withKey(map, key, value) { var o = {}; for (var k in map) o[k] = map[k]; o[key] = value; return o }
    function clearFault(id) { store.cleared = store.cleared.concat([id]) }
  }

  QtObject {
    id: view
    property var opened: []
    property var rt: null
    property int trims: 0
    function trim() { view.trims += 1 }
    function openAt(id, method, args, by, from) { view.opened = view.opened.concat([[id, method, args.item, from]]) }
  }

  QtObject {
    id: guide
    property var byUser: ({})
    property bool opened: true
    property string screen: "guide"
    property bool watching: false
    property var homeSections: [{ type: "appRow", key: "tv.example.app/now", on: true }]
    readonly property var apps: store
    readonly property var appView: view
  }

  AppHome { id: home; guide: guide }

  function items(n) {
    var out = []
    for (var i = 0; i < n; i++) out.push({ id: "i" + i, title: "Item " + i, subtitle: "", kind: i === 0 ? "play" : "info", badge: i === 1 ? "LIVE" : "", progress: 0.5, image: { token: "t" + i } })
    return out
  }

  TestCase {
    name: "AppHome"

    function init() {
      rt.calls = []
      rt.cancelled = []
      rt.phase = "ready"
      rt.leases = ({})
      store.authGens = ({})
      store.version = "1.0.0"
      store.values = ({})
      store.refuse = ""
      home.rows = ({})
      home.calls = ({})
      home.waits = ({})
      guide.screen = "guide"
      view.opened = []
      store.homeRows = [{ key: "now", label: "Now" }]
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true }]
      rt.sizes = ({})
      rt.askedFor = []
      rt.released = []
      rt.letGo = []
      rt.refuse = []
      rt.fail = []
      rt.holdPictures = false
      rt.held = []
      rt.brokenAsks = []
      home.reloaded = ({})
      home.picFailed = ({})
      home.brokenTried = ({})
      home.asking = ({})
    }

    // ---- milestone 1: each card its shape, one row height --------------
    function pictured(n) {
      var out = items(n)
      out.forEach(function(it, i) { it.images = { poster: { token: "p" + i }, wide: { token: "w" + i } } })
      return out
    }

    function test_a_row_in_its_home_shape() {
      store.homeRows = [{ key: "now", label: "Now", shape: "poster" }]
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", pictured(2))
      var cards = home.cardsFor("tv.example.app/now")
      compare(cards.map(function(c) { return c.shape }), ["poster", "poster"], "the shape app.json gives the row")
      compare(rt.askedFor.sort(), ["p0", "p1"], "each card's poster, not its other pictures")
      tryVerify(function() { return home.cardsFor("tv.example.app/now")[1].poster === "/tmp/pic-p1.png" }, 2000)
      compare(home.cardsFor("tv.example.app/now")[1].shape, "poster", "kept whatever the picture's size")
    }

    function test_each_card_takes_its_pictures_shape() {
      rt.sizes = { t0: [200, 300], t1: [300, 300], t2: [1920, 1080] }
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", pictured(4))
      compare(home.cardsFor("tv.example.app/now").map(function(c) { return c.shape }), ["wide", "wide", "wide", "wide"], "wide until their sizes come")
      compare(rt.askedFor.sort(), ["t0", "t1", "t2", "t3"], "with no Home shape, each card's own picture")
      tryVerify(function() { return home.cardsFor("tv.example.app/now")[2].poster !== "" }, 2000)
      compare(home.cardsFor("tv.example.app/now").map(function(c) { return c.shape }), ["poster", "square", "wide", "wide"],
              "a poster, a square shown whole, a wide picture, and one whose size isn't known")
    }

    function test_a_row_lets_go_of_what_it_held() {
      guide.screen = "home"
      home.refresh()
      var first = 1
      rt.calls[0].done("rows", items(2))
      compare(rt.released, [], "kept while it's shown")
      home.rows = store.withKey(home.rows, "tv.example.app/now", store.withKey(home.rows["tv.example.app/now"], "at", 0))   // ten minutes on
      home.refresh()
      rt.calls[1].done("rows", items(2))
      compare(rt.released, [first], "replaced: the old result let go")
      store.authGens = store.withKey(store.authGens, "tv.example.app", 3)   // signed out
      home.refresh()
      compare(rt.released, [first, 2], "its cards dropped: let go")
    }

    function test_a_picture_let_go_loads_the_row_again_once() {
      rt.letGo = ["t0"]
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(1))
      tryVerify(function() { return rt.calls.length === 2 }, 2000, "the helper had let its picture go: the row loads again")
      compare(rt.calls[1].method, "homeRow")
      rt.calls[1].done("rows", items(1))
      wait(100)
      compare(rt.calls.length, 2, "only once")
      compare(home.cardsFor("tv.example.app/now")[0].poster, "", "then the card shows its title")
    }

    function test_a_live_row_while_home_shows() {
      store.api = 4
      rt.lived = []
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      wait(0)
      compare(rt.lived, ["on:1"], "an api 4 app's row: on while Home shows (by the result its cards came in)")
      store.liveUpdated("tv.example.app", rt, 1, null, [{ id: "n", title: "New one", subtitle: "", kind: "info", badge: "", progress: null, image: { token: "tn" } }])
      var cards = home.cardsFor("tv.example.app/now")
      compare(cards.length, 1)
      compare(cards[0].title, "New one", "its items replaced")
      store.liveUpdated("tv.example.app", rt, 7, null, [])
      compare(home.cardsFor("tv.example.app/now")[0].title, "New one", "another result's update changes nothing")
      // the app's screen keeps within the 4,000 pictures with what the row holds now
      view.rt = rt
      view.trims = 0
      store.liveUpdated("tv.example.app", rt, 1, null, items(3))
      compare(view.trims, 1, "its screen trimmed, as a load trims it")
      view.rt = null
      guide.screen = "guide"
      wait(0)
      compare(rt.lived[rt.lived.length - 1], "off:1", "off when Home goes")
      store.api = 3
    }

    function test_an_older_apps_row_is_never_live() {
      rt.lived = []
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      wait(0)
      compare(rt.lived, [])
    }

    function test_loads_only_while_home_shows() {
      home.refresh()
      compare(rt.calls.length, 0, "Home isn't on the screen")
      guide.screen = "home"
      home.refresh()
      compare(rt.calls.length, 1)
      compare(rt.calls[0].method, "homeRow")
      compare(rt.calls[0].args.key, "now")
      verify(rt.leases["home:now"] === true, "a home lease while it loads")
      compare(home.cardsFor("tv.example.app/now")[0].title, "Loading…")
      rt.calls[0].done("rows", items(3))
      verify(rt.leases["home:now"] !== true, "given back")
      var cards = home.cardsFor("tv.example.app/now")
      compare(cards.length, 3)
      compare(cards[1].live, true)
      compare(cards[0].kind, "appItem")
      tryVerify(function() { return home.cardsFor("tv.example.app/now")[2].poster === "/tmp/pic-t2.png" }, 2000, "pictures through the broker")
    }

    function test_kept_ten_minutes_for_the_same_things() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      home.refresh()
      compare(rt.calls.length, 1, "kept")
      store.authGens = store.withKey(store.authGens, "tv.example.app", 1)   // signed in or out
      home.refresh()
      compare(rt.calls.length, 2, "a sign-in change makes it stale")
      rt.calls[1].done("rows", items(2))
      store.values = { league: "B" }
      home.refresh()
      compare(rt.calls.length, 3, "a setting changed")
      rt.calls[2].done("rows", items(2))
      store.version = "1.0.1"
      home.refresh()
      compare(rt.calls.length, 4, "an update")
    }

    function test_answer_for_changed_settings_dropped() {
      guide.screen = "home"
      home.refresh()
      store.values = { league: "B" }               // changed while it was out
      rt.calls[0].done("rows", items(2))
      compare(home.cardsFor("tv.example.app/now")[0].kind, "appStatus", "the old settings' rows aren't shown")
    }

    function test_failure_keeps_the_cards() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      home.rows = store.withKey(home.rows, "tv.example.app/now", store.withKey(home.rows["tv.example.app/now"], "at", 0))   // ten minutes on
      home.refresh()
      rt.calls[1].done("error", { code: "fetch", text: "offline" })
      compare(home.cardsFor("tv.example.app/now").length, 2, "a failed row stays in place")
      verify(home.stale("tv.example.app/now"))
    }

    function test_a_stopped_app_isnt_started_by_home() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      home.rows = store.withKey(home.rows, "tv.example.app/now", store.withKey(home.rows["tv.example.app/now"], "at", 0))
      store.refuse = "it stopped working: it crashed"
      home.refresh()
      compare(rt.calls.length, 1, "not started")
      compare(home.cardsFor("tv.example.app/now").length, 2, "its last rows, marked")
      verify(home.stale("tv.example.app/now"))
    }

    function test_an_error_with_nothing_to_show() {
      guide.screen = "home"
      store.refuse = "three apps are busy"
      home.refresh()
      var c = home.cardsFor("tv.example.app/now")
      compare(c.length, 1)
      compare(c[0].title, "Couldn't load it")
      store.refuse = ""
      home.open(c[0], guide.byUser)                  // Enter tries again
      compare(rt.calls.length, 1)
    }

    function test_open_a_card() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(3))
      var cards = home.cardsFor("tv.example.app/now")
      home.open(cards[0], guide.byUser)
      home.open(cards[2], guide.byUser)
      home.open(cards[1], {})                        // not the user: nothing
      compare(view.opened, [["tv.example.app", "play", "i0", "home"], ["tv.example.app", "details", "i2", "home"]])
    }

    function test_sign_out_leaves_nothing_of_the_old_rows() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      store.authGens = store.withKey(store.authGens, "tv.example.app", 7)   // signed out
      compare(home.cardsFor("tv.example.app/now")[0].kind, "appStatus", "the old cards are gone at once")
      store.refuse = "it isn't running"
      home.refresh()
      var c = home.cardsFor("tv.example.app/now")
      compare(c.length, 1)
      compare(c[0].title, "Couldn't load it", "a failed reload shows the error, never the signed-out user's cards")
      verify(!home.stale("tv.example.app/now"))
    }

    function test_an_app_that_never_starts() {
      guide.screen = "home"
      rt.phase = "starting"
      home.refresh()
      compare(rt.calls.length, 0, "waiting for it to start")
      rt.stopped("start", "it didn't start")
      var c = home.cardsFor("tv.example.app/now")
      compare(c[0].title, "Couldn't load it", "not loading for ever")
      verify(rt.leases["home:now"] !== true, "its lease given back")
    }

    function test_leaving_home_cancels() {
      guide.screen = "home"
      home.refresh()
      compare(rt.calls.length, 1)
      guide.screen = "guide"
      compare(rt.cancelled, [1], "the row's call is called off")
      verify(rt.leases["home:now"] !== true)
      verify(!home.rows["tv.example.app/now"].loading)
    }

    function test_rows_of_an_app_not_ready() {
      store.ready = []
      compare(home.cardsFor("tv.example.app/now").length, 0)
      store.ready = [{ id: "tv.example.app" }]
    }

    // ---- milestone 1, ycodex round 1 ---------------------------------------
    function test_a_row_taken_off_home_lets_go() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      guide.homeSections = []                          // taken off Home
      home.refresh()
      compare(rt.released, [1], "what it held is let go")
      verify(!home.rows["tv.example.app/now"], "and it's gone")
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true }]
    }

    function test_an_answer_for_a_row_taken_off_is_let_go() {
      guide.screen = "home"
      home.refresh()
      guide.homeSections = []
      rt.calls[0].done("rows", items(2))
      compare(rt.released, [1], "it came after the row went: let go, not shown")
      verify(!home.rows["tv.example.app/now"])
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true }]
    }

    function test_an_answer_dropped_for_a_change_is_let_go() {
      guide.screen = "home"
      home.refresh()
      store.values = { league: "B" }                   // changed while it was out
      rt.calls[0].done("rows", items(2))
      compare(rt.released, [1], "dropped, and let go")
    }

    function test_a_stopped_runtime_isnt_asked_to_let_go() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      rt.phase = "stopped"                             // it stopped (three idle minutes)
      store.version = "1.0.1"                          // the row loads again, its old cards dropped
      rt.phase = "ready"
      var k = "tv.example.app/now"
      home.set(k, { cards: [], at: 0, sig: "x", error: "", loading: false, holder: { rt: null, id: 9 } })
      home.set(k, { cards: [{ id: "c" }], at: 0, sig: "y", error: "", loading: false })   // a holder whose runtime is gone: no error
      verify(rt.released.indexOf(9) < 0)
    }

    function test_one_picture_for_two_cards() {
      guide.screen = "home"
      home.refresh()
      var two = items(2)
      two[1].image = { token: "t0" }                   // both cards show the same picture
      rt.calls[0].done("rows", two)
      tryVerify(function() { var c = home.cardsFor("tv.example.app/now"); return c[0].poster !== "" && c[1].poster !== "" }, 2000,
                "both filled by its one answer")
      compare(rt.askedFor.filter(function(t) { return t === "t0" }).length, 1, "asked for once")
    }

    function test_a_late_answer_doesnt_fill_a_newer_rows_cards() {
      rt.sizes = ({})
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(1))               // its picture's answer comes on the next turn
      var k = "tv.example.app/now"
      home.rows = store.withKey(home.rows, k, store.withKey(home.rows[k], "at", 0))
      home.refresh()
      var newer = items(1)
      newer[0].image = { token: "other" }
      rt.calls[1].done("rows", newer)
      wait(50)
      compare(home.cardsFor(k)[0].poster, "/tmp/pic-other.png", "the newer card has its own picture, never the old answer's")
    }

    function test_a_refused_picture_isnt_asked_for_again() {
      rt.letGo = []
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(1))
      var k = "tv.example.app/now"
      home.picFailed = ({})
      home.picFailed[k + "\n" + "t0"] = "never"
      home.rows = store.withKey(home.rows, k, store.withKey(home.rows[k], "cards", home.rows[k].cards.map(function(c) { return store.withKey(c, "poster", "") })))
      var n = rt.askedFor.length
      home.fillPictures("tv.example.app", "now")
      compare(rt.askedFor.length, n, "refused: never asked again")
      home.picFailed = ({})
    }

    // ---- milestone 1, ycodex round 2 ---------------------------------------
    readonly property string k: "tv.example.app/now"
    function reload(n, items2) {
      home.set(k, store.withKey(home.rows[k], "at", 0))
      home.refresh()
      rt.calls[n].done("rows", items2)
    }

    function test_a_refused_picture_isnt_asked_for_by_a_new_result() {
      rt.refuse = ["t1"]
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      tryVerify(function() { return home.picFailed[k + "\nt1"] === "never" }, 2000)
      rt.askedFor = []
      reload(1, items(2))
      compare(rt.askedFor, ["t0"], "the new result's pictures, but not the refused one")
    }

    function test_a_row_taken_off_while_home_is_hidden_is_let_go() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      var id = home.rows[k].holder.id
      guide.screen = "guide"
      guide.homeSections = []
      home.refresh()
      compare(home.rows[k], undefined, "gone, though Home isn't on the screen")
      verify(rt.released.indexOf(id) >= 0, "with what it held")
    }

    function test_a_row_taken_off_while_its_app_starts_never_asks() {
      rt.phase = "starting"
      guide.screen = "home"
      home.refresh()
      verify(home.waits[k] !== undefined, "waiting for the app")
      guide.homeSections = []
      home.refresh()
      compare(home.waits[k], undefined, "no longer waiting")
      verify(!rt.leases["home:now"], "its lease given back")
      rt.phase = "ready"
      rt.readyNow()
      compare(rt.calls.length, 0, "nothing asked of the app")
    }

    function test_a_row_taken_off_while_it_loads_is_called_off() {
      guide.screen = "home"
      home.refresh()
      compare(rt.calls.length, 1)
      guide.homeSections = []
      home.refresh()
      compare(rt.cancelled, [1], "its call called off")
      verify(!rt.leases["home:now"], "its lease given back")
      compare(home.rows[k], undefined)
    }

    function test_what_a_row_knows_of_its_pictures_goes_with_them() {
      rt.refuse = ["t1"]
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      tryVerify(function() { return home.picFailed[k + "\nt1"] === "never" }, 2000)
      var other = items(2)
      other[1].image = { token: "t9" }
      rt.refuse = ["t1", "t9"]
      reload(1, other)
      compare(home.picFailed[k + "\nt1"], undefined, "a picture its cards no longer show: forgotten")
      tryVerify(function() { return home.picFailed[k + "\nt9"] === "never" }, 2000)
      guide.homeSections = []
      home.refresh()
      compare(Object.keys(home.picFailed).length, 0, "taken off: all of it forgotten")
      compare(Object.keys(home.asking).length, 0)
    }

    function test_a_result_replaced_before_its_pictures_come_leaves_no_ask() {
      rt.holdPictures = true
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      compare(Object.keys(home.asking).length, 2)
      reload(1, items(2))                               // the same pictures, in a new result
      compare(Object.keys(home.asking).length, 2, "the old result's asks are over")
      // the runtime calls only the newest answer for each row and picture
      rt.held.slice(2).forEach(function(h) { h.done("/tmp/pic-" + h.token + ".png", { w: 0, h: 0 }) })
      compare(Object.keys(home.asking).length, 0, "nothing left behind")
      compare(home.cardsFor(k)[1].poster, "/tmp/pic-t1.png")
    }

    function test_a_home_picture_that_cant_be_drawn_is_fetched_again_once() {
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      tryVerify(function() { return home.cardsFor(k)[1].poster !== "" }, 2000)
      home.pictureBroken(k, home.cardsFor(k)[0])
      compare(home.cardsFor(k)[0].poster, "", "its title meanwhile")
      compare(rt.brokenAsks, ["t0"], "fetched again, telling the helper its file was bad")
      tryVerify(function() { return home.cardsFor(k)[0].poster !== "" }, 2000)
      home.pictureBroken(k, home.cardsFor(k)[0])        // still can't be drawn
      compare(home.picFailed[k + "\nt0"], "never", "its title from now on")
      compare(rt.brokenAsks, ["t0"], "not fetched a third time")
      // one drawn fine since may be repaired again
      home.pictureBroken(k, home.cardsFor(k)[1])
      tryVerify(function() { return home.cardsFor(k)[1].poster !== "" }, 2000)
      home.pictureDrawn(k, home.cardsFor(k)[1])
      home.pictureBroken(k, home.cardsFor(k)[1])
      compare(rt.brokenAsks, ["t0", "t1", "t1"], "repaired again")
    }

    function test_a_failed_home_picture_is_tried_again_the_next_visit() {
      rt.fail = ["t1"]
      guide.screen = "home"
      home.refresh()
      rt.calls[0].done("rows", items(2))
      tryVerify(function() { return home.picFailed[k + "\nt1"] === 1 }, 2000)
      home.fillPictures("tv.example.app", "now")
      tryVerify(function() { return home.picFailed[k + "\nt1"] === 2 }, 2000, "tried once more")
      rt.askedFor = []
      home.fillPictures("tv.example.app", "now")
      compare(rt.askedFor, [], "then left as its title")
      guide.screen = "guide"
      guide.screen = "home"
      compare(home.picFailed[k + "\nt1"], undefined, "Home shown again: forgiven")
      home.fillPictures("tv.example.app", "now")
      compare(rt.askedFor, ["t1"], "tried again")
    }

    // ---- milestone 3: your Pictures for a Home row ----------------------------
    function test_your_shape_for_an_app_row() {
      store.homeRows = [{ key: "now", label: "Now", shape: "wide" }]
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true, shape: "poster" }]
      guide.screen = "home"
      home.refresh()
      compare(home.homeShape("tv.example.app", "now"), "poster", "yours beats app.json's")
      rt.calls[0].done("rows", pictured(2))
      compare(home.cardsFor(k).map(function(c) { return c.shape }), ["poster", "poster"])
      compare(rt.askedFor.sort(), ["p0", "p1"], "each card's poster")
      // changing it: the row's cards were made for the other shape, so it loads again
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true, shape: "wide" }]
      home.refresh()
      compare(rt.calls.length, 2, "loaded again for its new shape")
      rt.calls[1].done("rows", pictured(2))
      compare(home.cardsFor(k).map(function(c) { return c.shape }), ["wide", "wide"])
      guide.homeSections = [{ type: "appRow", key: "tv.example.app/now", on: true }]
      compare(home.homeShape("tv.example.app", "now"), "wide", "auto: app.json's again")
    }
  }
}
