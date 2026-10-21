import QtQuick
import Quickshell
import Quickshell.Io

// Program listings (EPG) for IPTV channels: XMLTV files you add (a link, or
// a file on this computer; a playlist can bring its own), fetched by
// bin/om-pg-epg about twice a day and on R, matched to your channels by
// tvg-id and name, kept for today and tomorrow in ~/.cache/om-pg/epg.json.
// A channel with listings shows its shows in the guide; one without stays
// a LIVE block. Sources are in settings.json.
Scope {
  id: listings

  required property var guide

  property var sources: []            // [{ url, from: "you"|"playlist", added }]
  property var shows: ({})            // channel url -> [[start, end, title, description, category, episode title, episode]]
  property var report: []             // the last fetch: [{ url, ok, error, channels, matched, shows }]
  property real fetched: 0
  property bool busy: false
  property string status: ""          // what the fetch is doing, as it goes
  property bool again: false

  readonly property string path: guide.cacheDir + "/epg.json"
  readonly property string requestPath: guide.cacheDir + "/epg-request.json"
  readonly property int matched: Object.keys(shows).length

  function has(url) { return !!listings.shows[url] && listings.shows[url].length > 0 }

  // A channel's shows overlapping a time span, as the guide's shows
  function between(url, from, to) {
    var out = []
    listings.each(url, from, to, function(s) { out.push(listings.show(s)) })
    return out
  }
  // the same, each as it's kept ([start, end, title, desc, category, sub, ep]),
  // without making a show of it; show(s) makes one
  function each(url, from, to, visit) {
    var list = listings.shows[url] || []
    for (var i = 0; i < list.length; i++) {
      var s = list[i]
      if (s[1] <= from) continue
      if (s[0] >= to) break
      visit(s)
    }
  }
  function show(s) { return { epg: true, id: "", title: s[2], desc: s[3], category: s[4], start: s[0], end: s[1], sub: s[5] || "", ep: s[6] || "" } }

  function at(url, t) {
    var list = listings.shows[url] || []
    for (var i = 0; i < list.length; i++) if (t >= list[i][0] && t < list[i][1]) return listings.between(url, t, t + 1)[0]
    return null
  }

  // The next show starting at or after t
  function after(url, t) {
    var list = listings.shows[url] || []
    for (var i = 0; i < list.length; i++) if (list[i][0] >= t) return listings.between(url, list[i][0], list[i][0] + 1)[0]
    return null
  }

  function sourceReport(url) {
    for (var i = 0; i < listings.report.length; i++) if (listings.report[i].url === url) return listings.report[i]
    return null
  }

  // A link (http/https) or a full path to an .xml, .xml.gz or .xml.xz file
  function checkSource(text) {
    var t = String(text || "").trim().replace(/^~(?=\/)/, Quickshell.env("HOME"))
    if (/^https?:\/\/[^\s"'<>]+$/.test(t) && t.length < 2048) return t
    if (/^\/[^\0]+$/.test(t) && t.length < 1024) return t
    return ""
  }

  function add(text, from) {
    var url = listings.checkSource(text)
    if (!url) return "a link (https://…) or a full path to an XMLTV file (.xml, .xml.gz)"
    if (listings.sources.some(function(s) { return s.url === url })) return "already there"
    if (listings.sources.length >= 20) return "20 sources at most"
    listings.sources = listings.sources.concat([{ url: url, from: from === "playlist" ? "playlist" : "you", added: Math.floor(Date.now() / 1000) }])
    guide.saveSettings()
    listings.fetch()
    return "ok"
  }

  function remove(url) {
    var before = listings.sources.length
    listings.sources = listings.sources.filter(function(s) { return s.url !== url })
    if (listings.sources.length === before) return "not one of the sources"
    guide.saveSettings()
    if (listings.sources.length) listings.fetch()
    else { listings.shows = ({}); listings.report = []; listings.fetched = 0; if (!listings.guide.wiping) dataFile.setText("{}\n") }
    return "ok"
  }

  // Fetches every source now (or once the one fetching ends)
  function fetch() {
    if (!listings.sources.length || listings.guide.wiping) return false
    if (fetcher.running) { listings.again = true; return true }
    var now = Math.floor(Date.now() / 1000)
    var chans = guide.channels.filter(function(c) { return c.kind === "iptv" })
                              .map(function(c) { return { url: c.url, tvgId: c.tvgId || "", name: c.name } })
    if (!chans.length) return false   // no IPTV channels (or not loaded yet): nothing to match
    listings.busy = true
    listings.status = "Getting the listings…"
    requestFile.setText(JSON.stringify({ sources: listings.sources.map(function(s) { return s.url }), channels: chans,
                                         from: now - 3 * 3600, to: now + 36 * 3600, out: listings.path }))
    return true
  }

  // About twice a day, and when the guide opens after that
  function freshen() {
    if (listings.sources.length && !listings.busy && Date.now() / 1000 - listings.fetched > 12 * 3600) listings.fetch()
  }

  function progress(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.done) return
    var name = String(msg.source || "").split("/").pop() || "listings"
    listings.status = msg.status === "fetching" ? "Downloading " + name + "…"
                    : msg.status === "reading" ? "Reading " + name + "…"
                    : msg.status === "failed" ? name + ": " + (msg.error || "failed")
                    : name + ": " + (msg.matched || 0) + " channels"
  }

  FileView {
    id: requestFile
    path: listings.requestPath
    printErrors: false
    onSaved: fetcher.running = true
    onSaveFailed: { listings.busy = false; listings.status = "Couldn't start the fetch" }
  }

  Process {
    id: fetcher
    command: ["/usr/bin/python3", guide.pluginDir + "/bin/om-pg-epg", listings.requestPath]
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { listings.progress(line) }
    }
    onExited: function(code) {
      listings.busy = false
      if (code !== 0) listings.status = "The listings couldn't be fetched"
      dataFile.reload()
      if (listings.again) { listings.again = false; listings.fetch() }
    }
  }

  FileView {
    id: dataFile
    path: listings.path
    printErrors: false
    onLoaded: {
      try {
        var d = JSON.parse(text())
        var shows = {}
        var raw = d.shows || {}
        for (var url in raw) if (Array.isArray(raw[url]) && raw[url].length) shows[url] = raw[url]
        listings.shows = shows
        listings.report = Array.isArray(d.sources) ? d.sources : []
        listings.fetched = Number(d.fetched) || 0
        if (!listings.busy) listings.status = ""
      } catch (e) {}
    }
  }

  Timer {
    interval: 30 * 60 * 1000
    repeat: true
    running: true
    onTriggered: listings.freshen()
  }
}
