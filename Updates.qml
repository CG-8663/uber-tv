import QtQuick
import "ui"

// Uber TV's own updates (Settings → About): whether a newer version is out,
// asked of the git address it was installed from (bin/om-pg-update), and
// its release notes. Update notifications are off until you turn them on,
// there or on the strip the first time; then it looks when the shell starts
// and 12 hours after each look. Check for updates looks once, on or off.
// Nothing is installed here: omarchy plugin update does that.
Item {
  id: updates

  required property var guide

  property bool on: false            // Update notifications (settings.json)
  property bool asked: false         // the strip answered, or the switch used (settings.json)
  property bool checking: false
  property string status: ""         // after a look: current, available or failed
  property string latest: ""         // the newest version found, "" for none
  property string tag: ""            // its tag, for its release notes
  property real checkedAt: 0         // when the last look ended (seconds)
  property string strip: ""          // the strip after Turn on: what the look found, for a while
  property bool stripWaiting: false  // Turn on's look is still going
  property string notes: ""          // release notes, Markdown
  property string notesFor: ""       // the version they're for
  property string notesStatus: ""    // loading, ok or failed
  readonly property string installed: (guide.manifest && guide.manifest.version) || ""
  readonly property bool available: latest !== ""
  readonly property string notesShown: html(notes)

  readonly property string helper: guide.pluginDir + "/bin/om-pg-update"
  readonly property var versionLike: /^v?\d{1,9}\.\d{1,9}\.\d{1,9}(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$/

  // Turn on, on the strip: notifications on, and a look now whose result
  // the strip says
  function turnOn() {
    updates.on = true
    updates.asked = true
    guide.saveSettings()
    updates.check(true)
  }

  // Dismiss, on the strip: away for good (the switch stays in Settings)
  function dismiss() {
    updates.asked = true
    guide.saveSettings()
  }

  // The switch in Settings → About
  function setOn(value) {
    updates.on = value
    updates.asked = true
    guide.saveSettings()
    if (value) updates.check(false)
  }

  // A look now (fromStrip: Turn on's, its result said on the strip)
  function check(fromStrip) {
    if (fromStrip) {
      updates.stripWaiting = true
      updates.strip = "Update notifications are on."
      stripTimer.stop()
    }
    if (updates.checking) return
    if (!versionLike.test(updates.installed)) { updates.finished(false, ""); return }
    updates.checking = true
    checkRun.start(["/usr/bin/python3", updates.helper, "check", guide.pluginDir, updates.installed])
  }

  function finished(ok, output) {
    updates.checking = false
    updates.checkedAt = Date.now() / 1000
    every.restart()
    var r = null
    if (ok) { try { r = JSON.parse(output) } catch (e) { r = null } }
    if (r && r.ok === true && typeof r.latest === "string" && (r.latest === "" || versionLike.test(r.latest))) {
      if (r.latest !== updates.latest) { updates.notes = ""; updates.notesFor = ""; updates.notesStatus = "" }
      updates.latest = r.latest
      updates.tag = typeof r.tag === "string" && versionLike.test(r.tag) ? r.tag : ""
      updates.status = r.latest ? "available" : "current"
    } else {
      updates.status = "failed"     // an update found before stays known
    }
    if (updates.stripWaiting) {
      updates.stripWaiting = false
      updates.strip = updates.status === "failed" ? "Couldn't check for updates."
                    : updates.status === "available" ? "Update notifications are on. Version " + updates.latest + " is available."
                    : "Update notifications are on. You're up to date."
      stripTimer.restart()
    }
  }

  // What the rows in Settings → About say at their right
  function result(long) {
    return updates.checking ? "Checking…" : updates.status === "current" ? "Up to date"
         : updates.status === "available" ? updates.latest + " available"
         : updates.status === "failed" ? (long ? "Couldn't check for updates" : "Couldn't check") : ""
  }
  function value(key) {
    if (key === "updateNotify") return updates.on ? updates.result(false) : ""
    if (key === "updateCheck") return updates.result(true)
    if (key === "updateAvailable") return updates.latest
    return ""
  }

  function ago(seconds) {
    var m = Math.max(0, Math.round((guide.now - seconds) / 60))
    if (m < 1) return "just now"
    if (m < 60) return m + (m === 1 ? " minute ago" : " minutes ago")
    var h = Math.round(m / 60)
    if (h < 48) return h + (h === 1 ? " hour ago" : " hours ago")
    return Math.round(h / 24) + " days ago"
  }

  // And what they're about, under the rows
  function note(key) {
    if (key === "updateNotify" || key === "updateCheck")
      return "Looks for a new version of Uber TV when it starts and about every 12 hours." + (updates.checkedAt ? " Last checked " + updates.ago(updates.checkedAt) + "." : "")
    if (key === "updateAvailable")
      return "To update, run omarchy plugin update " + ((guide.manifest && guide.manifest.id) || "marcho78.om-pg") + " in a terminal, then restart the shell."
    return ""
  }

  // Release notes: what's new in the newer version, or what's in this one
  function loadNotes() {
    var newer = updates.available && updates.tag !== ""
    var want = newer ? updates.latest : updates.installed
    if (notesRun.running || (updates.notesFor === want && updates.notesStatus === "ok")) return
    updates.notesFor = want
    updates.notesStatus = "loading"
    updates.notes = ""
    var argv = ["/usr/bin/python3", updates.helper, "notes", guide.pluginDir, updates.installed]
    if (newer) argv.push(updates.tag)
    notesRun.start(argv)
  }

  // Markdown as the guide's own styled text: what the notes say, never
  // markup or a picture of theirs (everything they hold is escaped first).
  // A paragraph's or a list item's lines join up, so they flow in the box.
  function html(md) {
    if (!md) return ""
    var inline = function(s) {
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
              .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "$1").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    }
    var out = []
    var cur = null      // the paragraph or list item being joined: its lead and its text
    var flush = function() { if (cur) out.push(cur.lead + inline(cur.text)); cur = null }
    var lines = md.split("\n")
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i]
      var h = /^(#{1,6})\s+(.*)$/.exec(line)
      var b = /^(\s*)[-*]\s+(.*)$/.exec(line)
      if (!line.trim()) {
        flush()
        if (out.length && out[out.length - 1] !== "") out.push("")
      } else if (h) {
        flush()
        out.push("<b><font size=\"" + (h[1].length <= 2 ? 5 : 4) + "\">" + inline(h[2].replace(/^\[([^\]]+)\]/, "$1")) + "</font></b>")
      } else if (b) {
        flush()
        cur = { lead: new Array(Math.floor(b[1].length / 2) + 1).join("&nbsp;&nbsp;&nbsp;&nbsp;") + "•&nbsp;&nbsp;", text: b[2] }
      } else if (cur) {
        cur.text += " " + line.trim()
      } else {
        cur = { lead: "", text: line.trim() }
      }
    }
    flush()
    return out.join("<br>")
  }

  Run {
    id: checkRun
    timeoutMs: 40000
    maxBytes: 16 * 1024
    onFinished: function(ok, output) { updates.finished(ok, output) }
  }

  Run {
    id: notesRun
    timeoutMs: 150000
    maxBytes: 1536 * 1024
    onFinished: function(ok, output) {
      var r = null
      if (ok) { try { r = JSON.parse(output) } catch (e) { r = null } }
      if (r && r.ok === true && typeof r.notes === "string") { updates.notes = r.notes; updates.notesStatus = "ok" }
      else { updates.notes = ""; updates.notesStatus = "failed" }
    }
  }

  // A look as the shell starts (once settings are read), then 12 hours
  // after each one
  Timer {
    interval: 20000
    running: true
    onTriggered: if (updates.on) updates.check(false)
  }
  Timer {
    id: every
    interval: 12 * 3600 * 1000
    repeat: true
    running: updates.on
    onTriggered: updates.check(false)
  }
  Timer {
    id: stripTimer
    interval: 6000
    onTriggered: updates.strip = ""
  }
}
