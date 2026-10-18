import QtQuick

// Settings → About: OK 7 times on the version shows Developer mode's row in
// Settings → Developer. From
// the third press it counts down ("4 more for Developer mode"); a pause of 3
// seconds starts over. Only you count (byUser: the keys, the mouse, your
// paired phone), never an agent or a shell call. Showing the row changes
// nothing: turning Developer mode on still takes the computer's password.
QtObject {
  id: dp

  property var byUser: null
  property var apps: null                // Apps.qml: developerShown, developer, showDeveloper()
  property int presses: 0
  property string note: ""               // what the About row says after its version

  property Timer pause: Timer {
    interval: 3000
    onTriggered: { dp.presses = 0; dp.note = "" }
  }

  function press(by) {
    if (by !== dp.byUser || !dp.byUser) return "only the user, at the screen"
    dp.pause.restart()
    if (dp.apps.developerShown || dp.apps.developer) { dp.note = "Developer mode is in Settings → Developer"; return "ok" }
    dp.presses += 1
    if (dp.presses >= 7) {
      dp.apps.showDeveloper()
      dp.presses = 0
      dp.note = "Developer mode is in Settings → Developer now"
    } else dp.note = dp.presses >= 3 ? (7 - dp.presses) + " more for Developer mode" : ""
    return "ok"
  }
}
