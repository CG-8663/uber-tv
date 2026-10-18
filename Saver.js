.pragma library

// The screen saver (ScreenSaver.qml): pictures that
// fill every screen, with the clock, when nothing's playing and nobody's
// touched anything for a while, and the first press brings the TV back. With
// it on, Uber TV keeps the screen awake while it's on screen (Awake.js), so
// Omarchy's screen saver and lock wait and waking needs no password. These
// are its settings and its rules; settings.json keeps the settings.

var AFTER = [1, 2, 5, 10, 15, 30]          // minutes
var PICTURES = ["both", "omarchy", "folder"]
var EVERY = [10, 20, 30, 60]               // seconds
var CLOCK = ["bottomRight", "bottomLeft", "topRight", "topLeft", "middle", "off"]
var FOLDER_NAME = "Pictures/Screen Saver"  // inside your home folder

function defaults() {
  return { on: false, after: 5, pictures: "both", folder: "", every: 20, clock: "bottomRight" }
}

// Settings as saved, each one checked ("" folder: the one to begin with)
function checked(saved) {
  var s = saved && typeof saved === "object" ? saved : {}
  var d = defaults()
  return {
    on: s.on === true,
    after: AFTER.indexOf(s.after) >= 0 ? s.after : d.after,
    pictures: PICTURES.indexOf(s.pictures) >= 0 ? s.pictures : d.pictures,
    folder: typeof s.folder === "string" && s.folder.charAt(0) === "/" && s.folder.indexOf("\0") < 0 && s.folder.length <= 4096 ? s.folder : "",
    every: EVERY.indexOf(s.every) >= 0 ? s.every : d.every,
    clock: CLOCK.indexOf(s.clock) >= 0 ? s.clock : d.clock
  }
}

// The choice after this one, going round
function next(list, value) {
  var i = list.indexOf(value)
  return list[(i + 1) % list.length]
}

function folderOf(settings, home) {
  return settings.folder || home + "/" + FOLDER_NAME
}

function afterLabel(m) { return m === 1 ? "1 minute" : m + " minutes" }
function everyLabel(s) { return s === 60 ? "1 minute" : s + " seconds" }
function picturesLabel(p) {
  return { both: "Omarchy's + yours", omarchy: "Omarchy's", folder: "Yours" }[p] || ""
}
function clockLabel(c) {
  return { bottomRight: "Bottom right", bottomLeft: "Bottom left", topRight: "Top right", topLeft: "Top left", middle: "In the middle", off: "Off" }[c] || ""
}

// The pictures to show: your folder's, Omarchy's backgrounds, or both (your
// folder's first, then Omarchy's); an empty folder falls back to Omarchy's
function playlist(pictures, omarchy, folder) {
  var mine = folder || [], theirs = omarchy || []
  if (pictures === "omarchy") return theirs.slice()
  if (pictures === "folder") return mine.length ? mine.slice() : theirs.slice()
  return mine.concat(theirs)
}

// A shuffled copy (random: a function giving 0 ≤ x < 1)
function shuffled(list, random) {
  var a = list.slice()
  for (var i = a.length - 1; i > 0; i--) {
    var j = Math.floor(random() * (i + 1))
    var t = a[i]; a[i] = a[j]; a[j] = t
  }
  return a
}

// The picture a screen shows at a step: each screen a different one while
// there are enough (screen: its place among the screens; screens: how many)
function pictureAt(order, step, screen, screens) {
  if (!order.length) return ""
  var k = (step * Math.max(1, screens) + screen) % order.length
  return order[k < 0 ? k + order.length : k]
}

// Whether the screen saver may come: it's on, Uber TV is on screen, nothing
// plays (a paused video is nothing), and Omarchy's own screen saver isn't up
function eligible(now) {
  return !!now.on && !!now.shown && !now.playing && !now.omarchySaver
}

// Whether it comes now: it may (eligible), Hyprland has seen no key, mouse or
// touch for the chosen minutes (quiet: a steady stream of input keeps it from
// ever being quiet, however long it lasts), the chosen minutes have passed
// since it could come (waited: a video ending starts the wait over), and it
// isn't up already
function shouldShow(now) {
  return !!now.eligible && !!now.quiet && !!now.waited && !now.showing
}

// What an agent may change (setScreenSaver): the wait, the pictures, how
// often they change and the clock. Turning it on (it keeps the computer from
// locking) and the folder (which pictures of yours are read) stay yours.
// { settings, changed: [...], ignored: { key: why } }
function agentChange(settings, changes) {
  var out = checked(settings)
  var changed = [], ignored = {}
  var c = changes && typeof changes === "object" ? changes : {}
  for (var k in c) {
    var v = c[k]
    if (k === "on") ignored.on = "only you can turn the screen saver on or off, at the screen: it keeps your computer from locking while Uber TV is on screen"
    else if (k === "folder") ignored.folder = "only you can choose the folder, at the screen"
    else if (k === "after" && AFTER.indexOf(v) >= 0) { out.after = v; changed.push(k) }
    else if (k === "pictures" && PICTURES.indexOf(v) >= 0) { out.pictures = v; changed.push(k) }
    else if (k === "every" && EVERY.indexOf(v) >= 0) { out.every = v; changed.push(k) }
    else if (k === "clock" && CLOCK.indexOf(v) >= 0) { out.clock = v; changed.push(k) }
    else if (k === "after") ignored.after = "one of " + AFTER.join(", ") + " (minutes)"
    else if (k === "pictures") ignored.pictures = "one of " + PICTURES.join(", ")
    else if (k === "every") ignored.every = "one of " + EVERY.join(", ") + " (seconds)"
    else if (k === "clock") ignored.clock = "one of " + CLOCK.join(", ")
    else ignored[k] = "not a screen saver setting"
  }
  return { settings: out, changed: changed, ignored: ignored }
}
