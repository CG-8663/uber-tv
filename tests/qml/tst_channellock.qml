import QtQuick
import QtTest
import "../.."

// ChannelLock.qml with the helper stood in (runner): every call waits until
// the test answers it. Until the lock's been read, every channel is blocked;
// closing the box or Uber TV abandons a passcode session, and an answer that
// comes back for an abandoned one changes nothing; a timed unlock running out
// asks the guide to check the channel on; a reset needs the computer's
// password first.
Item {
  id: top
  width: 400
  height: 300

  Component {
    id: guideKind
    QtObject {
      property string dialog: ""
      property var channels: [{ url: "u1", name: "One" }, { url: "u2", name: "Two" }]
      property var numbers: [1, 2]
      property var lockItem: null
      function closeDialog() { if (lockItem) lockItem.abandon(); dialog = "" }
    }
  }
  Component {
    id: lockKind
    ChannelLock {}
  }

  TestCase {
    name: "ChannelLock"

    property var calls: []
    property var g: null
    property var l: null

    function make() {
      calls = []
      g = createTemporaryObject(guideKind, top)
      var self = this
      l = createTemporaryObject(lockKind, top, { guide: g, runner: function(cmd, req, done) { self.calls.push({ cmd: cmd, req: req, done: done }) } })
      g.lockItem = l
      wait(0)   // its first read is asked for
    }
    function answer(cmd, res) {
      for (var i = 0; i < calls.length; i++) {
        if (calls[i].cmd === cmd && !calls[i].answered) { calls[i].answered = true; calls[i].done(res); return calls[i] }
      }
      fail("no " + cmd + " call waiting")
    }
    function state(extra) {
      return Object.assign({ ok: true, set: true, on: true, channels: [{ url: "u1", name: "One" }], unlockFor: "tv", titles: false, wait: 0 }, extra || {})
    }
    function type(code) {
      for (var i = 0; i < code.length; i++) l.key({ key: Qt.Key_0 + Number(code[i]), text: code[i] })
      l.key({ key: Qt.Key_Return, text: "\r" })
    }

    function test_fails_closed_until_read() {
      make()
      verify(l.blocks(g.channels[1]), "not read yet: every channel is blocked, even one that isn't on the list")
      verify(l.isLocked(g.channels[1]), "and agents see it as locked")
      answer("lock-read", { ok: false, error: "the lock file isn't readable" })
      verify(!l.loaded)
      compare(l.failed, "The lock file isn't readable.")
      verify(l.blocks(g.channels[1]), "a read that failed doesn't turn the lock off")
      l.read()                        // tried again (every 5 s while it fails)
      answer("lock-read", { ok: false })
      verify(l.blocks(g.channels[0]), "an answer that isn't one: still blocked")
      l.read()
      answer("lock-read", { ok: true, set: false, on: false, channels: [], unlockFor: "tv", titles: false, wait: 0 })
      verify(l.loaded)
      verify(!l.blocks(g.channels[0]), "read, with no lock: nothing is blocked")
    }

    function test_close_and_reopen_from_the_settings() {
      make()
      answer("lock-read", state())
      l.openSettings()
      compare(g.dialog, "lockCode")
      type("2468")
      answer("lock-check", { ok: true })
      compare(g.dialog, "lockSettings", "the passcode opened the settings")
      l.abandon()                     // Uber TV closed (Guide.qml closeNow)
      compare(g.dialog, "", "the settings went with it")
      verify(!l.boxUp, "and reopening Uber TV doesn't bring them back")
      verify(l.code === "" && l.then === null)
    }

    function test_an_answer_after_close_changes_nothing() {
      make()
      answer("lock-read", state())
      l.openSettings()
      type("2468")
      g.closeDialog()                 // closed while the check was running
      answer("lock-check", { ok: true })
      compare(g.dialog, "", "the late answer doesn't open the settings")
    }

    function test_an_answer_after_cancel_unlocks_nothing() {
      make()
      answer("lock-read", state())
      var played = false
      verify(l.askUnlock(g.channels[0], function() { played = true }))
      type("2468")
      l.cancel()
      answer("lock-check", { ok: true })
      verify(!played, "what you asked for doesn't go on")
      verify(l.blocks(g.channels[0]), "and the channel stays locked")
      verify(l.askUnlock(g.channels[0], function() { played = true }))
      type("2468")
      answer("lock-check", { ok: true })
      verify(played, "asked again and answered: it goes on")
      verify(!l.blocks(g.channels[0]), "unlocked")
      l.relock()
      verify(l.blocks(g.channels[0]), "the TV off: locked again")
    }

    function test_an_old_answer_never_counts_for_a_new_ask() {
      make()
      answer("lock-read", state({ channels: [{ url: "u1", name: "One" }, { url: "u2", name: "Two" }] }))
      verify(l.askUnlock(g.channels[0], null))
      type("2468")                    // its check is on its way...
      l.cancel()
      var played = false
      verify(l.askUnlock(g.channels[1], function() { played = true }))   // ...and another channel is asked for
      answer("lock-check", { ok: true })                                // the first one's answer arrives
      verify(!played && l.blocks(g.channels[1]), "the new channel isn't unlocked by the old answer")
      compare(g.dialog, "lockCode", "it's still asking for its own passcode")
      l.abandon()
      verify(l.askUnlock(g.channels[0], null))
      type("1111")
      l.openSettings()                // a new ask without a cancel in between
      answer("lock-check", { ok: true })
      compare(g.dialog, "lockCode", "nor does it open the settings")
    }

    function test_backing_out_of_a_change_keeps_no_passcode() {
      make()
      answer("lock-read", state())
      l.openSettings()
      type("2468")
      answer("lock-check", { ok: true })
      l.act("change")                 // the passcode now...
      type("2468")
      l.key({ key: Qt.Key_Escape, text: "" })   // ...and Esc while it's checked: back to the settings
      compare(g.dialog, "lockSettings")
      answer("lock-check", { ok: true })
      compare(l.old, "", "the late answer doesn't keep the passcode in memory")
      compare(g.dialog, "lockSettings")
    }

    function test_a_timed_unlock_runs_out() {
      make()
      answer("lock-read", state({ unlockFor: 60 }))
      var spy = createTemporaryObject(spyKind, top, { target: l })
      var u = {}
      u["u1"] = Date.now() / 1000 + 0.6
      l.unlocked = u
      verify(!l.blocks(g.channels[0]))
      spy.clear()
      tryVerify(function() { return l.blocks(g.channels[0]) }, 3000, "blocked again once its time is up")
      tryVerify(function() { return spy.count >= 1 }, 3000, "and the guide is asked to check the channel on, which stops it")
      compare(Object.keys(l.unlocked).length, 0, "the unlock that ran out is gone")
    }

    function test_a_four_hour_unlock_is_checked_at_four_hours() {
      make()
      answer("lock-read", state({ unlockFor: 240 }))
      verify(l.askUnlock(g.channels[0], null))
      type("2468")
      answer("lock-check", { ok: true })
      verify(!l.blocks(g.channels[0]), "unlocked for four hours")
      var hours = l.expiryTimer.interval / 3600000
      verify(l.expiryTimer.running && hours > 3.99 && hours < 4.01, "the timer is set for the real four hours, not capped: " + hours)
      l.expiryTimer.triggered()       // a timer that fires early (or a clock that moved)...
      verify(l.expiryTimer.running, "...is set again: it never stops while an unlock is still running")
      verify(!l.blocks(g.channels[0]), "and the unlock still stands")
      l.relock()                      // the TV off doesn't end a timed unlock
      verify(l.expiryTimer.running)
    }

    function test_the_phone_types_the_passcode() {
      make()
      answer("lock-read", state())
      var played = false
      verify(l.askUnlock(g.channels[0], function() { played = true }))
      l.remote("code", "12")          // too short: nothing
      l.remote("code", "12a4")        // not digits: nothing
      compare(calls.filter(function(c) { return c.cmd === "lock-check" }).length, 0, "only 4 to 8 digits are tried")
      l.remote("code", "0246")
      var c = answer("lock-check", { ok: true })
      compare(c.req.code, "0246", "the phone's digits, a leading 0 and all, are checked")
      verify(played, "and the channel plays")
      l.remote("code", "0246")        // nothing asking for it now
      compare(calls.filter(function(c) { return c.cmd === "lock-check" }).length, 1, "a passcode with nothing asking is ignored")
    }

    function test_a_reset_needs_the_computers_password() {
      make()
      answer("lock-read", state())
      verify(l.askUnlock(g.channels[0], null))
      l.key({ key: Qt.Key_F, text: "f" })
      compare(l.step, "reset")
      l.key({ key: Qt.Key_Return, text: "\r" })
      answer("auth", { ok: false })
      verify(l.problem.indexOf("password wasn't given") >= 0, l.problem)
      compare(calls.filter(function(c) { return c.cmd === "lock-reset" }).length, 0, "no password: nothing reset")
      l.key({ key: Qt.Key_Return, text: "\r" })
      answer("auth", { ok: true })
      answer("lock-reset", { ok: true, set: false, on: false, channels: [], unlockFor: "tv", titles: false, wait: 0 })
      compare(g.dialog, "")
      verify(!l.set && !l.on && !l.blocks(g.channels[0]), "reset: no passcode, nothing locked")
    }
  }

  Component {
    id: spyKind
    SignalSpy { signalName: "recheck" }
  }
}
