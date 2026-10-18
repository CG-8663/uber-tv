import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import "Awake.js" as AwakeRules

// Keeps the screen awake while Settings says (Awake.js): Omarchy's screen
// saver doesn't start and the computer doesn't lock. It's asked of the
// compositor through the window on screen, the way video players do, and it
// ends with the window; Omarchy's idle respects it. Hyprland honors a hold
// from a desktop you can't see too, so the guide's window holds it only
// while it shows.
Item {
  id: awake

  property string mode: AwakeRules.DEFAULT
  property bool opened: false         // Uber TV is open
  property bool playing: false        // a video plays (not paused)
  property var fullScreen: null       // full screen (a layer of the shell)
  property var ownWindow: null        // the guide's window
  property var miniPlayer: null       // the mini player
  property bool saverOn: false        // the screen saver is on: held while Uber TV shows

  // The guide's window shows on a screen (Awake.js windowSeen): Hyprland
  // would honor its hold on a desktop you can't see, so this decides
  readonly property bool windowSeen: {
    var tops = (Hyprland.toplevels ? Hyprland.toplevels.values : []).map(function(t) {
      var ipc = t.lastIpcObject || {}
      return { title: t.title, pid: typeof ipc.pid === "number" ? ipc.pid : undefined, monitor: t.monitor ? t.monitor.name : "",
               workspace: t.workspace ? { name: t.workspace.name, active: t.workspace.active } : null }
    })
    var specials = {}
    var mons = Hyprland.monitors ? Hyprland.monitors.values : []
    for (var i = 0; i < mons.length; i++) {
      var sp = (mons[i].lastIpcObject || {}).specialWorkspace
      specials[mons[i].name] = sp && sp.name ? String(sp.name) : ""
    }
    return AwakeRules.windowSeen(tops, awake.ownWindow ? awake.ownWindow.title : "", Quickshell.processId, specials)
  }
  readonly property bool fullScreenShown: awake.opened && !!awake.fullScreen && awake.fullScreen.visible
  readonly property bool windowShown: awake.opened && !!awake.ownWindow && awake.ownWindow.visible && awake.windowSeen
  readonly property bool miniShown: !!awake.miniPlayer && awake.miniPlayer.visible
  readonly property bool holding: AwakeRules.holding(awake.mode, { shown: awake.fullScreenShown || awake.windowShown, mini: awake.miniShown, playing: awake.playing, saver: awake.saverOn })

  // Which special workspace each screen shows comes from asking Hyprland
  // again when one is shown or hidden
  Connections {
    target: Hyprland
    function onRawEvent(event) { if (/^activespecial/.test(String(event.name))) Hyprland.refreshMonitors() }
  }
  Component.onCompleted: { Hyprland.refreshMonitors(); Hyprland.refreshToplevels() }

  IdleInhibitor { window: awake.fullScreen; enabled: awake.holding && awake.fullScreenShown }
  IdleInhibitor { window: awake.ownWindow; enabled: awake.holding && awake.windowShown }
  IdleInhibitor { window: awake.miniPlayer; enabled: awake.holding && awake.miniShown }
}
