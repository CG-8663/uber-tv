.pragma library

// Keeping the screen awake: while it's held, Omarchy's screen saver doesn't
// start and the computer doesn't lock, as with Omarchy's own stay-awake. It's
// held the way video players do it (asking the compositor, through the
// window on screen), so it ends by itself when Uber TV closes or goes away,
// and Omarchy's own settings are never changed. Settings → General.

// The choices Settings offers, in order: never, while a video plays (and
// shows: in Uber TV or the mini player), or while Uber TV is on screen
var MODES = ["off", "playing", "open"]
var DEFAULT = "playing"

function checked(mode) {
  return MODES.indexOf(mode) >= 0 ? mode : DEFAULT
}

function next(mode) {
  return MODES[(MODES.indexOf(checked(mode)) + 1) % MODES.length]
}

function label(mode) {
  return { off: "Off", playing: "While a video plays", open: "While Uber TV is on" }[checked(mode)]
}

// Whether to hold it now. now: { shown: Uber TV on screen, mini: the mini
// player on screen, playing: a video playing (not paused), saver: the screen
// saver is on, which keeps it awake while Uber TV shows, as "open" does
// (Saver.js) }
function holding(mode, now) {
  var m = checked(mode)
  if ((m === "open" || !!now.saver) && now.shown) return true
  return m !== "off" && !!now.playing && (!!now.shown || !!now.mini)
}

// Whether the guide's player counts as playing: it says it's playing, the
// guide has the channel or movie on (not still tuning, and not called lost
// after a dead stream or an error, which leave the player "playing"), and
// it isn't stalled waiting for data. now: { playing, stalled, reception }
function videoPlays(now) {
  return !!now.playing && !now.stalled && now.reception === "on"
}

// Whether the guide's window shows on a screen. Hyprland honors a window's
// hold on any desktop, shown or not, so this decides. tops: Hyprland's
// windows as { title, pid, workspace: { name, active }, monitor }; the
// guide's is the one with its title from this shell's process (a window
// whose process isn't known yet counts as maybe the guide's), and it shows
// when its desktop is the one on its screen, or it's on the special
// workspace shown there (specials: screen name → the special workspace it
// shows, "" for none). None found yet (it's just appearing): yes.
function windowSeen(tops, title, pid, specials) {
  var found = false
  for (var i = 0; i < tops.length; i++) {
    var t = tops[i]
    if (!t || t.title !== title || (t.pid !== undefined && t.pid !== pid)) continue
    found = true
    var ws = t.workspace
    if (!ws || ws.active) return true
    if (String(ws.name).indexOf("special:") === 0 && t.monitor && specials[t.monitor] === ws.name) return true
  }
  return !found
}

// Omarchy's own screen saver: a fullscreen terminal window of this class,
// one a screen. It quits as soon as it isn't the active window, and Omarchy
// takes its closing as you dismissing it, lock and all, so Uber TV must get
// out of its way (NativeSaver.qml).
var SAVER_CLASS = "org.omarchy.screensaver"

// A window address as Hyprland's dispatchers take it: 0x and lowercase hex
function address(a) {
  var s = String(a === undefined || a === null ? "" : a).trim().toLowerCase()
  if (!/^(0x)?[0-9a-f]+$/.test(s)) return ""
  return s.indexOf("0x") === 0 ? s : "0x" + s
}

// What a Hyprland event means for Omarchy's screen saver: { open: address }
// for one of its windows opening, { close: address } for any window closing
// (it's ours to know whether it was one), or null. parts: the event's
// fields (openwindow: address, workspace, class, title; closewindow: address)
function saverEvent(name, parts) {
  var p = parts || []
  if (name === "openwindow") return p.length >= 3 && String(p[2]) === SAVER_CLASS && address(p[0]) ? { open: address(p[0]) } : null
  if (name === "closewindow") return address(p[0]) ? { close: address(p[0]) } : null
  return null
}

// Which of Omarchy's saver windows to focus now, if any (NativeSaver.qml):
// none while one of them is the active window; otherwise the one on the
// screen that has focus. Omarchy opens them a screen at a time, moving focus
// to the next screen before its saver appears, and a window appears on the
// screen with focus, so while focus is on a screen whose saver isn't there
// yet, none: pulling focus back would put that screen's saver on the wrong
// one. savers: [{ address, monitor }] (monitor "" while not known yet).
function focusTarget(savers, active, monitor) {
  for (var i = 0; i < savers.length; i++) if (savers[i].address === active) return ""
  for (var j = 0; j < savers.length; j++) if (savers[j].monitor && savers[j].monitor === monitor) return savers[j].address
  return ""
}
