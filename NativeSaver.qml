import QtQuick
import Quickshell
import Quickshell.Hyprland
import "Awake.js" as AwakeRules

// Omarchy's own screen saver, given room. It opens one fullscreen terminal
// window a screen (class org.omarchy.screensaver) and quits as soon as one
// of them isn't the active window, which Omarchy takes as you dismissing it:
// the lock is called off, and isn't armed again until you touch something.
// Uber TV full screen is a layer over everything with the keyboard to
// itself, so the saver opened under it without focus and quit at once: with
// Uber TV open, the computer never locked. While a saver window is open (up),
// the guide hides its layers and lets go of the keyboard (Guide.qml binds to
// up), and the saver on the screen that has focus is focused, asked again a
// moment later until a saver is the active window (never one on another
// screen: Awake.js focusTarget). When the last one closes, the guide comes
// back, and keys wait a moment (settling) so the key that closed it doesn't
// act too.
Item {
  id: native

  property var addresses: ({})        // its windows open now: address → true
  readonly property bool up: Object.keys(native.addresses).length > 0
  property bool settling: false

  // Hyprland's window events, read as Omarchy's idle service reads them
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      var name = String(event.name)
      if (name !== "openwindow" && name !== "closewindow") return
      var e = AwakeRules.saverEvent(name, event.parse(name === "openwindow" ? 4 : 1))
      if (e && e.open) native.opened(e.open)
      else if (e && e.close) native.closed(e.close)
    }
  }

  function opened(a) {
    var next = Object.assign({}, native.addresses)
    next[a] = true
    native.addresses = next
    native.settling = false
    Qt.callLater(native.focusHere)   // once Hyprland's list has the window and its screen
    focusAgain.n = 0
    focusAgain.interval = 150
    focusAgain.restart()
  }

  function closed(a) {
    if (!native.addresses[a]) return
    var next = Object.assign({}, native.addresses)
    delete next[a]
    native.addresses = next
    if (!native.up) { native.settling = true; settle.restart() }
  }

  // Its windows open now, each with the screen it's on ("" not known yet)
  function savers() {
    var tops = Hyprland.toplevels ? Hyprland.toplevels.values : []
    var out = []
    for (var i = 0; i < tops.length; i++) {
      var a = AwakeRules.address(tops[i] ? tops[i].address : "")
      if (a && native.addresses[a]) out.push({ address: a, monitor: tops[i].monitor ? String(tops[i].monitor.name) : "" })
    }
    return out
  }

  // The saver on the screen that has focus, focused, unless a saver is the
  // active window already
  function focusHere() {
    if (!native.up || !Hyprland.usingLua) return
    var t = Hyprland.activeToplevel
    var m = Hyprland.focusedMonitor
    var a = AwakeRules.focusTarget(native.savers(), t ? AwakeRules.address(t.address) : "", m ? String(m.name) : "")
    if (a) Hyprland.dispatch('hl.dsp.focus({ window = "address:' + a + '" })')
  }

  // Asked again at 150 ms and 600 ms: a window just made can drop the first
  // ask, and the guide's layer may not be gone yet
  Timer {
    id: focusAgain
    property int n: 0
    interval: 150
    onTriggered: {
      native.focusHere()
      if (native.up && n++ === 0) { interval = 450; restart() }
    }
  }

  Timer {
    id: settle
    interval: 400
    onTriggered: native.settling = false
  }

  // Ones already open when the guide starts (a shell restart while it's up)
  Component.onCompleted: {
    var tops = Hyprland.toplevels ? Hyprland.toplevels.values : []
    var found = {}
    for (var i = 0; i < tops.length; i++) {
      var t = tops[i]
      var cls = t && t.wayland ? t.wayland.appId : ((t && t.lastIpcObject) || {}).class
      if (cls === AwakeRules.SAVER_CLASS && AwakeRules.address(t.address)) found[AwakeRules.address(t.address)] = true
    }
    if (Object.keys(found).length) native.addresses = found
  }
}
