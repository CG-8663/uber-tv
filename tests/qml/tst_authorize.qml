import QtQuick
import QtTest
import "../.."

// The shared computer-password gate and Developer mode's hidden row. Signed
// app-file installs use the same one-at-a-time, stale-answer-safe gate as
// turning on Unknown sources; Developer mode remains separate.
Item {
  id: top
  width: 320
  height: 240

  property var prompts: []
  property var you: ({ who: "you" })
  property var agent: ({ who: "agent" })

  Authorize {
    id: auth
    ask: function(done) { top.prompts = top.prompts.concat([{ done: done }]) }
  }

  QtObject {
    id: apps
    property bool developer: false
    property bool developerShown: false
    property int shown: 0
    function showDeveloper() { apps.developerShown = true; apps.shown++ }
  }

  DeveloperPresses { id: presses; byUser: top.you; apps: apps }

  function answer(given, why) { top.prompts[top.prompts.length - 1].done(given, why) }

  TestCase {
    name: "Authorize"
    when: windowShown

    function init() {
      top.prompts = []
      apps.developer = false
      apps.developerShown = false
      apps.shown = 0
      presses.pause.stop()
      presses.presses = 0
      presses.note = ""
    }

    function test_one_prompt_and_known_kinds_only() {
      var got = []
      verify(auth.authorize("unknownSourcesOn", null, function(g, w) { got.push(["unknown", g, w]) }))
      verify(auth.busy)
      compare(auth.asked.kind, "unknownSourcesOn")
      verify(!auth.authorize("appFileInstall", { id: "tv.alex.clock" }, function(g, w) { got.push(["install", g, w]) }))
      compare(got, [["install", false, "busy"]])
      compare(top.prompts.length, 1, "never two system prompts")
      answer(true)
      compare(got[1], ["unknown", true, ""])
      verify(!auth.busy)

      auth.authorize("appFileInstall", { id: "tv.alex.clock" }, function(g, w) { got.push(["file", g, w]) })
      compare(auth.asked.kind, "appFileInstall")
      answer(false, "refused")
      compare(got[2], ["file", false, "refused"])
      auth.authorize("addSource", null, function(g, w) { got.push(["old", g, w]) })
      compare(got[3], ["old", false, "unavailable"], "removed link-source actions are not authorized")
    }

    function test_a_stale_yes_does_nothing() {
      var got = null, still = true
      auth.authorize("appFileInstall", { id: "tv.alex.clock", source: "app:0123456789abcdef" },
                     function(g, w) { got = [g, w] }, function() { return still })
      still = false
      answer(true)
      compare(got, [false, "changed"])
    }

    function test_developer_row_stays_separate_and_hides_when_off() {
      for (var i = 0; i < 6; i++) compare(presses.press(top.you), "ok")
      verify(!apps.developerShown)
      presses.press(top.you)
      verify(apps.developerShown)
      compare(apps.shown, 1)
      compare(presses.press(top.agent), "only the user, at the screen")
      apps.developer = true
      apps.developerShown = false
      presses.pause.stop()
      presses.presses = 0
      presses.note = ""
      presses.press(top.you)
      compare(apps.shown, 1, "already-on Developer mode does not reveal another row")
    }
  }
}
