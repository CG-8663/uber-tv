import QtQuick
import QtTest
import "../.."

// Snapshots.qml: a name
// used once, answered at once, the picture moved into place whole, and every
// outcome in its report. Never while a sensitive screen is up, checked when
// asked and again at the grab, including one that came up in between and
// went again. The grab and the move are stood in for, so each test says
// exactly when the picture is taken; the last test takes a real one.
// tests/snapshots.test.py runs the move script itself.
// Run: /usr/lib/qt6/bin/qmltestrunner -input tests/qml
Item {
  id: root
  width: 640
  height: 360

  QtObject { id: viewStub; property var signIn: null; property bool settingsOpen: false; property var certOffer: null; property var editing: null }
  QtObject { id: panelStub; property bool open: false; property bool renaming: false }
  QtObject {
    id: guide
    property bool opened: true
    property string dialog: ""
    property string screen: "app"
    property bool listingsAdding: false
    property bool styleNaming: false
    property string styleEditing: ""
    property bool homeRenaming: false
    readonly property var appView: viewStub
    readonly property var appPanel: panelStub
  }
  Rectangle { id: shot; width: 320; height: 180; color: "#204080" }

  property var grabs: []
  property var moves: []
  property var saved: []
  property bool saveOk: true
  Snapshots {
    id: snaps
    guide: guide
    target: shot
    folder: "/tmp/om-pg-snaps"
    run: "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
    dpr: 2
    grab: function(item, done, size) { root.grabs = root.grabs.concat([{ done: done, size: size }]); return true }
    mover: function(argv, done) { root.moves = root.moves.concat([{ argv: argv, done: done }]) }
  }
  Component {
    id: snapsKind
    Snapshots {
      target: shot
      folder: "/tmp/om-pg-snaps"
      grab: function(item, done, size) { return true }
      mover: function(argv, done) {}
    }
  }
  // the guide's own, with the real grab (and a folder that can't be written)
  property var realMoves: []
  Snapshots {
    id: real
    guide: guide
    target: shot
    folder: "/nonexistent-om-pg-snapshot-test"
    run: "4e5f6a7b4e5f6a7b4e5f6a7b4e5f6a7b"
    mover: function(argv, done) { root.realMoves = root.realMoves.concat([argv]); done(true) }
  }

  // the picture is taken now
  function grabNow() {
    root.grabs[root.grabs.length - 1].done({ saveToFile: function(p) { root.saved = root.saved.concat([p]); return root.saveOk } })
  }
  function calm() {
    guide.opened = true
    guide.dialog = ""
    guide.screen = "app"
    guide.listingsAdding = false
    guide.styleNaming = false
    guide.styleEditing = ""
    guide.homeRenaming = false
    viewStub.signIn = null
    viewStub.settingsOpen = false
    viewStub.certOffer = null
    viewStub.editing = null
    panelStub.open = false
    panelStub.renaming = false
  }

  TestCase {
    name: "Snapshots"
    when: windowShown

    function init() {
      root.calm()
      if (snaps.live) snaps.finish(snaps.live, "refused", "test")
      if (real.live) real.finish(real.live, "refused", "test")
      root.grabs = []
      root.moves = []
      root.saved = []
      root.realMoves = []
      root.saveOk = true
      snaps.waitMs = 10000
    }

    function test_a_name_used_once_answered_at_once_and_moved_whole() {
      var a = snaps.snapshot("")
      verify(!a.error, a.error)
      var m = /^\/tmp\/om-pg-snaps\/snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-([0-9]+)\.png$/.exec(a.path)
      verify(m, "this start's run, then its count: " + a.path)
      var n = Number(m[1])
      compare(a.width, 640, "at the screen's scale")
      compare(a.height, 360)
      compare(JSON.stringify(snaps.report), JSON.stringify({ name: a.path, outcome: "pending", why: "" }))
      compare(root.grabs.length, 1)
      compare(root.grabs[0].size.width, 320)
      root.grabNow()
      var part = "/tmp/om-pg-snaps/.snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-" + n + ".part.png"
      compare(JSON.stringify(root.saved), JSON.stringify([part]), "grabbed to a temporary name")
      compare(root.moves.length, 1)
      compare(JSON.stringify(root.moves[0].argv), JSON.stringify(["/usr/bin/sh", "-c", snaps.moveScript, "sh", "/tmp/om-pg-snaps", "0a1b2c3d4e5f60718293a4b5c6d7e8f9", String(n), part, a.path, "5"]))
      compare(snaps.report.outcome, "pending", "pending until it's in place")
      root.moves[0].done(true)
      compare(JSON.stringify(snaps.report), JSON.stringify({ name: a.path, outcome: "written", why: "" }))
      var b = snaps.snapshot("")
      compare(b.path, "/tmp/om-pg-snaps/snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-" + (n + 1) + ".png", "the next one, its own name")
    }

    function test_only_into_the_cache_folder_and_only_while_open() {
      var before = JSON.stringify(snaps.report)
      var a = snaps.snapshot("/home/u/x.png")
      verify(a.error && a.error.indexOf("snapshot-<run>-<n>.png") >= 0, a.error)
      guide.opened = false
      verify(snaps.snapshot("").error.indexOf("isn't open") >= 0)
      compare(root.grabs.length, 0)
      compare(JSON.stringify(snaps.report), before, "nothing reported")
    }

    function test_no_snapshot_while_a_sensitive_screen_is_up_data() {
      return [
        { tag: "the phone remote's box", why: "pairing code", set: function() { guide.dialog = "remote" } },
        { tag: "an app's sign-in", why: "sign-in", set: function() { viewStub.signIn = { code: "123456" } } },
        { tag: "an app's settings", why: "settings", set: function() { viewStub.settingsOpen = true } },
        { tag: "a certificate to pin", why: "certificate", set: function() { viewStub.certOffer = { sha256: "ab", verified: false } } },
        { tag: "an app's text field", why: "text field", set: function() { viewStub.editing = { type: "secret", key: "k", label: "Password", text: "" } } },
        { tag: "renaming a channel", why: "text field", set: function() { guide.dialog = "rename" } },
        { tag: "a category", why: "text field", set: function() { guide.dialog = "category" } },
        { tag: "the file picker", why: "text field", set: function() { guide.dialog = "pick" } },
        { tag: "adding channels", why: "text field", set: function() { guide.dialog = "add" } },
        { tag: "a listings link", why: "text field", set: function() { guide.dialog = "listings"; guide.listingsAdding = true } },
        { tag: "a theme's name", why: "text field", set: function() { guide.dialog = "style"; guide.styleNaming = true } },
        { tag: "a color", why: "text field", set: function() { guide.dialog = "style"; guide.styleEditing = "accent" } },
        { tag: "a Home row's name", why: "text field", set: function() { guide.screen = "home"; guide.homeRenaming = true } },
        { tag: "a row's name in Customize", why: "text field", set: function() { panelStub.open = true; panelStub.renaming = true } }
      ]
    }
    function test_no_snapshot_while_a_sensitive_screen_is_up(d) {
      // when asked: an error, nothing grabbed, nothing reported
      d.set()
      var before = JSON.stringify(snaps.report)
      var a = snaps.snapshot("")
      verify(a.error && a.error.indexOf(d.why) >= 0, String(a.error))
      compare(root.grabs.length, 0)
      compare(JSON.stringify(snaps.report), before)
      // between asking and the grab: refused, and no file
      root.calm()
      a = snaps.snapshot("")
      verify(!a.error, a.error)
      d.set()
      root.grabNow()
      compare(snaps.report.outcome, "refused")
      verify(snaps.report.why.indexOf(d.why) >= 0, snaps.report.why)
      compare(root.saved.length, 0, "no file")
      compare(root.moves.length, 0)
      // up and gone again before the grab: refused all the same
      root.calm()
      a = snaps.snapshot("")
      verify(!a.error, a.error)
      d.set()
      root.calm()
      root.grabNow()
      compare(snaps.report.outcome, "refused", "it came up while the picture was taken")
      verify(snaps.report.why.indexOf(d.why) >= 0, snaps.report.why)
      compare(root.saved.length, 0)
    }

    function test_the_askers_own_check_runs_when_asked_and_at_the_grab() {
      var blocked = ""
      var calls = []
      var check = function(atGrab) { calls.push(atGrab); return blocked }
      blocked = "something is over it"
      verify(snaps.take(check).error.indexOf("something is over it") >= 0, "when asked: an error")
      compare(root.grabs.length, 0)
      blocked = ""
      verify(!snaps.take(check).error)
      blocked = "that view isn't the one on the screen"
      root.grabNow()
      compare(JSON.stringify(calls), JSON.stringify([false, false, true]), "asked, then at the grab")
      compare(snaps.report.outcome, "refused")
      compare(snaps.report.why, "that view isn't the one on the screen")
      compare(root.saved.length, 0, "no file")
    }

    function test_an_apps_boxes_count_only_on_its_screen() {
      viewStub.signIn = { code: "123456" }
      guide.screen = "home"
      verify(!snaps.snapshot("").error, "its screen isn't drawn")
    }

    function test_the_guide_closing_before_the_grab_drops_it() {
      verify(!snaps.snapshot("").error)
      guide.opened = false
      root.grabNow()
      compare(snaps.report.outcome, "refused")
      compare(snaps.report.why, "the guide closed")
      compare(root.saved.length, 0)
    }

    function test_one_at_a_time() {
      var a = snaps.snapshot("")
      verify(snaps.snapshot("").error.indexOf("being taken") >= 0)
      root.grabNow()
      root.moves[0].done(true)
      verify(!snaps.snapshot("").error, "then the next")
    }

    // two starts in the same moment, or a clock gone back, never share a name: each has its own run
    // each start's run is 128 bits (32 hex digits), so two starts' names
    // differ (the same 128 bits twice is negligible); a picture is linked
    // in, never over anything at its name (tests/snapshots.test.py runs that)
    function test_two_starts_never_share_a_name() {
      var other = snapsKind.createObject(root, { run: "ffee0011ffee0011ffee0011ffee0011", guide: guide })
      var a = snaps.snapshot("")
      var b = other.snapshot("")
      verify(!a.error && !b.error, (a.error || "") + (b.error || ""))
      verify(a.path !== b.path, a.path + " / " + b.path)
      other.destroy()
      verify(snaps.moveScript.indexOf("ln -T -- \"$part\" \"$name\"") >= 0 && snaps.moveScript.indexOf("mv ") < 0, "linked in, never moved over")
      // without a run of its own (the kernel's random unread), or with a
      // short one, none is taken
      ;["", "0a1b2c3d", "0a1b2c3d4e5f60718293a4b5c6d7e8f", "0A1B2C3D4E5F60718293A4B5C6D7E8F9"].forEach(function(run) {
        var none = snapsKind.createObject(root, { run: run, guide: guide })
        verify(none.snapshot("").error.indexOf("can't be grabbed") >= 0, "run " + JSON.stringify(run))
        none.destroy()
      })
    }

    function test_a_grab_that_never_comes_is_given_up() {
      snaps.waitMs = 30
      var a = snaps.snapshot("")
      tryVerify(function() { return snaps.report.outcome === "refused" }, 2000)
      verify(snaps.report.why.indexOf("wasn't drawn in time") >= 0, snaps.report.why)
      root.grabNow()     // late: dropped
      compare(root.saved.length, 0)
      compare(root.moves.length, 0)
      compare(snaps.report.outcome, "refused")
      verify(!snaps.snapshot("").error, "and the next can go")
    }

    function test_a_failed_write_or_move_is_refused() {
      root.saveOk = false
      var a = snaps.snapshot("")
      root.grabNow()
      compare(snaps.report.outcome, "refused")
      compare(snaps.report.why, "it couldn't be written")
      var n = /snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-([0-9]+)\.png$/.exec(a.path)[1]
      compare(JSON.stringify(root.moves[0].argv), JSON.stringify(["/usr/bin/rm", "-f", "--", "/tmp/om-pg-snaps/.snapshot-0a1b2c3d4e5f60718293a4b5c6d7e8f9-" + n + ".part.png"]), "what was begun is taken away")
      root.saveOk = true
      root.moves = []
      verify(!snaps.snapshot("").error)
      root.grabNow()
      root.moves[0].done(false)
      compare(snaps.report.outcome, "refused")
      compare(snaps.report.why, "it couldn't be written")
    }

    function test_the_real_grab() {
      // the guide's own grab calls back, and its checks run then: here the
      // folder can't be written, so it's refused and what was begun removed
      var a = real.snapshot("")
      verify(!a.error, a.error)
      tryVerify(function() { return real.report.outcome === "refused" }, 3000)
      compare(real.report.why, "it couldn't be written")
      compare(root.realMoves.length, 1)
      compare(root.realMoves[0][0], "/usr/bin/rm")
      // and a sensitive screen up right after asking is there at the grab
      a = real.snapshot("")
      verify(!a.error, a.error)
      guide.dialog = "remote"
      tryVerify(function() { return real.report.outcome === "refused" }, 3000)
      verify(real.report.why.indexOf("pairing code") >= 0, real.report.why)
      compare(root.realMoves.length, 1, "nothing written or moved")
    }
  }
}
