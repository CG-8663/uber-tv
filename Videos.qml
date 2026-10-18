import QtQuick
import Quickshell
import Quickshell.Io
import "ui"

// My Videos: the video files in a folder of yours (your Videos folder, unless
// you pick another), each with its length and a picture from it, found by
// bin/om-pg-videos. Nothing is copied or uploaded; where you stopped in each
// is kept with the rest (history.json). On or off in Settings.
Scope {
  id: videos

  required property var guide

  property bool enabled: true
  property string folder: ""          // "" until settings say, then your Videos folder
  readonly property string usedFolder: folder || defaultFolder
  property string defaultFolder: Quickshell.env("HOME") + "/Videos"

  // [{ id, path, title, folder, mtime, size, duration, thumb }], newest first
  property var items: []
  property var byId: ({})
  property bool scanning: false
  property bool missing: false
  property real scannedAt: 0
  property bool scanAgain: false

  // An Omarchy screen recording's name says when it was made
  function titleFor(name) {
    var m = String(name).match(/^screenrecording-(\d{4})-(\d\d)-(\d\d)_(\d\d)-(\d\d)-(\d\d)$/)
    if (m) {
      var d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]))
      return "Screen recording, " + Qt.formatDateTime(d, "MMM d") + ", " + guide.clock(d.getTime() / 1000)
    }
    return String(name).replace(/[._]+/g, " ").replace(/\s+/g, " ").trim() || String(name)
  }

  function scan() {
    if (!videos.enabled) return
    if (finder.running) { videos.scanAgain = true; return }
    videos.scanning = true
    finder.running = true
  }

  // Looks again if it's been a while (the guide opening, My Videos opening)
  function freshen() {
    if (videos.enabled && Date.now() / 1000 - videos.scannedAt > 60) videos.scan()
  }

  function item(id) { return videos.byId[id] || null }

  // The folders, each with its videos, newest first; the folder itself first
  readonly property var folders: {
    var at = {}
    var out = []
    for (var i = 0; i < items.length; i++) {
      var f = items[i].folder
      if (!(f in at)) { at[f] = out.length; out.push({ folder: f, items: [] }) }
      out[at[f]].items.push(items[i])
    }
    return out
  }

  function found(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (Array.isArray(msg.videos)) {
      var list = []
      var map = {}
      for (var i = 0; i < msg.videos.length; i++) {
        var v = msg.videos[i]
        if (!v || typeof v.path !== "string" || v.path.charAt(0) !== "/") continue
        var it = { id: guide.libraryIdFor("file://" + v.path), path: v.path, title: videos.titleFor(v.name || ""), folder: String(v.folder || ""),
                   mtime: Number(v.mtime) || 0, size: Number(v.size) || 0, duration: Number(v.duration) || 0, thumb: typeof v.thumb === "string" ? v.thumb : "" }
        list.push(it)
        map[it.id] = it
      }
      list.sort(function(a, b) { return b.mtime - a.mtime })
      videos.items = list
      videos.byId = map
      videos.missing = msg.missing === true
    } else if (typeof msg.path === "string") {
      var id = guide.libraryIdFor("file://" + msg.path)
      var had = videos.byId[id]
      if (!had) return
      var now = {}
      for (var k in had) now[k] = had[k]
      now.duration = Number(msg.duration) || had.duration
      now.thumb = typeof msg.thumb === "string" && msg.thumb ? msg.thumb : had.thumb
      var m2 = {}
      for (var j in videos.byId) m2[j] = videos.byId[j]
      m2[id] = now
      videos.byId = m2
      videos.items = videos.items.map(function(x) { return x.id === id ? now : x })
    }
  }

  Process {
    id: finder
    command: ["/usr/bin/python3", guide.pluginDir + "/bin/om-pg-videos", videos.usedFolder, guide.cacheDir]
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { videos.found(line) }
    }
    onExited: {
      videos.scanning = false
      videos.scannedAt = Date.now() / 1000
      if (videos.scanAgain) { videos.scanAgain = false; videos.scan() }
    }
  }

  // Your Videos folder, as your desktop names it
  Run {
    id: userDir
    timeoutMs: 5000
    maxBytes: 4096
    Component.onCompleted: start(["/usr/bin/xdg-user-dir", "VIDEOS"])
    onFinished: function(ok, output) {
      var d = ok ? output.trim() : ""
      if (!d || d.charAt(0) !== "/" || d === Quickshell.env("HOME") || d === videos.defaultFolder) return
      videos.defaultFolder = d
      if (!videos.folder && (videos.scanning || videos.scannedAt)) videos.scan()
    }
  }
}
