import QtQuick
import Quickshell
import "Dvr.js" as Dvr
import "ui"

// Recordings (the DVR): channels recorded to disk by bin/om-pg-dvr, each its
// own systemd service, so a recording goes on with Uber TV closed. This is
// the guide's side: the settings (Settings → Recordings), the list (checked
// every two seconds while one records, every minute otherwise, and when
// Recordings opens), Record, Stop, a new stop time and Delete, the place
// recordings go (your Videos folder, a folder of yours, or a USB drive),
// and what the Record choice says before it's pressed. Later shows too:
// scheduled, a series' episodes (Record every episode) scheduled from the
// listings, and the checker that starts each one when it's due, guide open
// or not. Rules in Dvr.js.
Scope {
  id: dvr

  required property var guide
  property var listings: null         // Listings.qml: a series' episodes come from it

  property var settings: Dvr.defaults()
  property bool loaded: false
  // from the helper: [{ id, kind, state, reason, title, titles, desc, channel:
  // { name, number, hash }, created, started, finished, end, bytes, duration,
  // thumb, file, private, video, present, path, placeLabel }], newest first
  property var recordings: []
  property var byId: ({})
  // Record every episode: [{ id, channel: { name, number, hash }, title, private, provider, created }]
  property var rules: []
  // the place now: { problem: ""|"readonly"|"drive", path, free, size }, or
  // null until it's been looked at
  property var placeInfo: null
  property var drives: []
  property string defaultFolder: Quickshell.env("HOME") + "/Videos"
  property string said: ""            // the last thing to say about a recording ("" once it's fine)
  property bool busy: false           // a start on its way
  property var stopping: ({})         // id -> true: Stop pressed, the worker finishing
  property var allowed: ({})          // provider -> true: "Watch anyway" said while it records
  property bool listing: false
  property bool again: false
  property var thens: []              // what waits for the list on its way
  property string listText: ""        // the list as it last came (a list unchanged isn't given again)
  property string rulesText: "[]"
  property var claiming: ({})         // id -> true: a due one being started
  property bool limitBusy: false      // the limit on its way to the helper (one at a time, the newest last)
  property bool seriesBusy: false     // a series' episodes on their way to the helper
  property bool seriesAgain: false
  // rule|identity -> true: an episode sent once this session and passed by
  // (cancelled before, scheduled or recorded already, refused): not sent again
  property var seriesPassed: ({})
  property var seriesPending: null    // { slots, from, more }: a batch the helper failed, tried again

  readonly property string helper: guide.pluginDir + "/bin/om-pg-dvr"
  readonly property var active: recordings.filter(Dvr.active)
  readonly property bool anyActive: active.length > 0
  readonly property int keepFreeGB: Dvr.keepFreeOf(settings, placeInfo)
  readonly property int quality: Dvr.qualityOf(settings, placeInfo)

  // ---- the helper ----

  Component { id: runner; Run {} }
  Item { id: runs }                   // where the helper's runs live (an Item, so they're placed)

  function call(args, input, done, timeoutMs) {
    var r = runner.createObject(runs, { timeoutMs: timeoutMs || 45000, maxBytes: 4 * 1024 * 1024 })
    r.finished.connect(function(ok, output) {
      var res = null
      var lines = String(output || "").trim().split("\n")
      try { res = JSON.parse(lines[lines.length - 1]) } catch (e) { res = null }
      r.destroy()
      if (done) done(res && typeof res === "object" ? res : { ok: false, error: "helper" })
    })
    r.start(["/usr/bin/python3", "-I", dvr.helper].concat(args), input === undefined ? undefined : String(input))
  }

  // The list, from the helper (then(), if given, once it's in). Given to
  // the guide only when it changed: the checker asks every 30 seconds, and
  // every card and cell built from it would be made again
  function refresh(then) {
    if (then) dvr.thens = dvr.thens.concat([then])
    if (dvr.listing) { dvr.again = true; return }
    dvr.listing = true
    call(["list"], undefined, function(res) {
      dvr.listing = false
      if (res.ok && Array.isArray(res.recordings)) {
        var text = JSON.stringify(res.recordings)
        if (text !== dvr.listText) {
          dvr.listText = text
          dvr.recordings = res.recordings
          var m = {}
          for (var i = 0; i < res.recordings.length; i++) m[res.recordings[i].id] = res.recordings[i]
          dvr.byId = m
        }
        var rulesText = JSON.stringify(Array.isArray(res.rules) ? res.rules : [])
        if (rulesText !== dvr.rulesText) { dvr.rulesText = rulesText; dvr.rules = JSON.parse(rulesText) }
        // stopping ones that have finished: no longer stopping
        var still = {}
        for (var s in dvr.stopping) if (dvr.byId[s] && Dvr.active(dvr.byId[s])) still[s] = true
        if (Object.keys(still).length !== Object.keys(dvr.stopping).length) dvr.stopping = still
        // "Watch anyway" lasts while that provider's recordings do
        var keep = {}
        for (var p in dvr.allowed) if (dvr.recordingFrom(p)) keep[p] = true
        if (Object.keys(keep).length !== Object.keys(dvr.allowed).length) dvr.allowed = keep
      }
      if (dvr.again) { dvr.again = false; dvr.refresh(); return }
      var waiting = dvr.thens
      dvr.thens = []
      for (var t = 0; t < waiting.length; t++) waiting[t]()
    })
  }

  // The place, looked at again (free space, the drive there or not)
  function checkPlace() {
    if (dvr.settings.place) {
      call(["where"], JSON.stringify(dvr.settings.place), function(res) { if (res.ok) dvr.placeInfo = res })
    } else {
      call(["check", dvr.defaultFolder], undefined, function(res) {
        dvr.placeInfo = res.ok ? { problem: "", path: dvr.defaultFolder + "/Uber TV Recordings", free: res.free, size: res.size, fresh: true, system: res.system === true }
                               : { problem: "", path: dvr.defaultFolder + "/Uber TV Recordings", free: 0, size: 0, fresh: true, missing: true }
      })
    }
  }

  function listDrives() {
    call(["drives"], undefined, function(res) { if (res.ok && Array.isArray(res.drives)) dvr.drives = res.drives })
  }

  // every 2 seconds while one records and the guide is open (its banner and
  // cards follow along), every 30 while it's closed, every minute otherwise
  // (and on until every start and stop has settled, Recordings off or not)
  Timer {
    interval: dvr.anyActive || dvr.busy ? (guide.opened ? 2000 : 30000) : 60000
    running: dvr.loaded && (dvr.anyActive || dvr.busy || Object.keys(dvr.stopping).length > 0 || (dvr.settings.on && dvr.recordings.length > 0))
    repeat: true
    // (and each time, a running recording whose channel's link the playlist turned follows it)
    onTriggered: { dvr.refresh(dvr.followLinks); if (!dvr.anyActive) dvr.checkPlace() }
  }

  onLoadedChanged: if (loaded) { dvr.sayLimit(); dvr.checkPlace() }

  // ---- later: the checker ----

  // Every 30 seconds, guide open or not (Uber TV stays loaded while you're
  // logged in), and when it comes back from sleep (the timer is late): a
  // scheduled one that's due starts, its channel's address looked up now
  // (the helper claims it: it starts once, whoever asks). Not before the
  // recordings and the channels are in.
  readonly property bool hasWaiting: recordings.some(Dvr.waiting)
  Timer {
    interval: 30000
    repeat: true
    triggeredOnStart: true
    running: dvr.loaded && dvr.settings.on && (dvr.hasWaiting || dvr.rules.length > 0)
    onTriggered: dvr.check()
  }

  function check() {
    if (!dvr.loaded || !dvr.settings.on || !guide.channels.length) return
    dvr.refresh(dvr.startDue)
  }

  function startDue() {
    if (dvr.limitBusy) return          // the helper's limit isn't settled yet: next time
    var now = Date.now() / 1000
    for (var i = 0; i < dvr.recordings.length; i++) {
      var r = dvr.recordings[i]
      if (r.state === "scheduled" && r.start <= now + 30 && r.end > now && !dvr.claiming[r.id]) dvr.claim(r)
    }
  }

  // A playlist that turned a channel's link while it records (its channel
  // found now by name, from the same provider, at another address): the
  // recording moves to it, the same file going on
  property var following: ({})        // id -> true: told, its list not back yet
  function followLinks() {
    for (var i = 0; i < dvr.active.length; i++) {
      var r = dvr.active[i]
      if (r.kind !== "iptv" || !r.channel || dvr.following[r.id]) continue
      var ch = dvr.channelByHash(r.channel, r.provider)
      if (!ch || Dvr.hashOf(ch.url) === r.channel.hash) continue
      var f = {}
      for (var k in dvr.following) f[k] = true
      f[r.id] = true
      dvr.following = f
      dvr.call(["follow"], JSON.stringify({ id: r.id, url: ch.url }), (function(id) { return function() {
        var left = {}
        for (var k2 in dvr.following) if (k2 !== id) left[k2] = true
        dvr.following = left
        dvr.refresh()
      } })(r.id))
    }
  }

  function claim(rec) {
    var c = {}
    for (var k in dvr.claiming) c[k] = true
    c[rec.id] = true
    dvr.claiming = c
    var done = function(res) {
      var left = {}
      for (var k2 in dvr.claiming) if (k2 !== rec.id) left[k2] = true
      dvr.claiming = left
      // turned off while it was starting: it stops at once, new or joined (as record())
      if (res && res.ok && res.id && !dvr.settings.on) dvr.stop(res.id)
      dvr.refresh()
    }
    var ch = dvr.channelByHash(rec.channel, rec.provider)
    if (!ch) { dvr.call(["start"], JSON.stringify({ slot: rec.id, gone: true }), done); return }
    dvr.ready(function(place) {
      dvr.call(["start"], JSON.stringify({ slot: rec.id, url: ch.url, place: place, keepFree: dvr.keepFreeGB * Dvr.GB, quality: dvr.quality }), done)
    })
  }

  // A recording's (or a rule's) channel by its address hashed; one whose
  // address has changed since (a playlist that turns its links) by its name,
  // from the same provider
  function channelByHash(c, provider) {
    if (!c) return null
    var ch = c.hash ? dvr.hashMap[c.hash] : null
    if (ch) return ch
    for (var i = 0; i < guide.channels.length; i++) {
      var x = guide.channels[i]
      if (x.kind === "iptv" && c.name && x.name === c.name && (!provider || Dvr.providerOf(x) === provider)) return x
    }
    return null
  }

  // A series' episodes, scheduled from the listings (when new ones come, and
  // when a rule's added): the ones not scheduled or recorded already
  function updateSeries() {
    if (!dvr.loaded || !dvr.settings.on || !dvr.rules.length || !dvr.listings || !guide.channels.length) return
    if (dvr.seriesBusy) { dvr.seriesAgain = true; return }
    var now = Date.now() / 1000
    var sources = [], rows = {}
    for (var i = 0; i < dvr.rules.length; i++) {
      var rule = dvr.rules[i]
      var ch = dvr.channelByHash(rule.channel, rule.provider)
      var row = ch ? guide.channels.indexOf(ch) : -1
      if (row < 0 || ch.kind !== "iptv") continue
      rows[rule.id] = row
      sources.push({ rule: rule, list: dvr.listings.shows[ch.url] || [] })
    }
    // 2,000 at a time, one from each series in turn, made only as they're
    // picked; the rest once these are in
    var pass = Dvr.seriesPass(sources, dvr.recordings, now, 40 * 3600, dvr.seriesPassed, 2000)
    var slots = []
    for (var k = 0; k < pass.picks.length; k++) {
      var pick = pass.picks[k]
      var slot = Dvr.slotFor(dvr.chanFor(rows[pick.rule.id]), pick.show, dvr.settings.padding, pick.rule.id)
      if (slot) { slot.private = pick.rule.private === true; slots.push(slot) }
    }
    if (!slots.length) return
    dvr.seriesBusy = true
    dvr.sendSeries(slots, 0, pass.more)
  }
  // In batches of 100, one after another, every batch sent whatever the last
  // one said. An episode passed by for good (cancelled before, scheduled or
  // recorded already, refused) isn't sent again this session, so it ends;
  // one refused because the list is full is tried again in 5 minutes (once
  // recordings are deleted it fits); the helper failing: that batch again
  // in 30 seconds
  function sendSeries(slots, from, more) {
    var batch = slots.slice(from, from + 100)
    dvr.call(["schedule"], JSON.stringify({ slots: batch }), function(res) {
      if (!res.ok || !Array.isArray(res.slots)) { dvr.seriesPending = { slots: slots, from: from, more: more }; seriesRetry.restart(); return }
      for (var i = 0; i < res.slots.length && i < batch.length; i++) {
        var one = res.slots[i]
        if (one.ok && one.id && !one.already) continue
        if (!one.ok && one.error === "full") { dvr.seriesFull = true; continue }
        dvr.seriesPassed[batch[i].rule + "|" + Dvr.identity({ title: batch[i].title, ep: batch[i].ep, sub: batch[i].sub, start: batch[i].showStart })] = true
      }
      if (from + 100 < slots.length) { dvr.sendSeries(slots, from + 100, more); return }
      dvr.seriesBusy = false
      var full = dvr.seriesFull
      dvr.seriesFull = false
      if (full) seriesFullRetry.restart()
      var again = dvr.seriesAgain || (more && !full)
      dvr.seriesAgain = false
      dvr.refresh(again ? dvr.updateSeries : undefined)
    })
  }
  property bool seriesFull: false     // the list was full for some this time
  Timer {
    id: seriesFullRetry
    interval: 300000
    onTriggered: dvr.updateSeries()
  }
  Timer {
    id: seriesRetry
    interval: 30000
    onTriggered: { var p = dvr.seriesPending; dvr.seriesPending = null; if (p) dvr.sendSeries(p.slots, p.from, p.more) }
  }
  Connections {
    target: dvr.listings
    function onShowsChanged() { dvr.updateSeries() }
  }
  onRulesChanged: updateSeries()

  // ---- settings ----

  function set(changes) {
    var s = {}
    for (var k in dvr.settings) s[k] = dvr.settings[k]
    for (var c in changes) s[c] = changes[c]
    var placeChanged = JSON.stringify(s.place) !== JSON.stringify(dvr.settings.place)
    var was = dvr.settings.atOnce
    dvr.settings = Dvr.checked(s)
    if (dvr.settings.on) guide.recAsked = true     // on: the strip has nothing to ask
    guide.saveSettings()
    if (placeChanged) { dvr.placeInfo = null; dvr.checkPlace() }
    if (dvr.settings.atOnce !== was) dvr.sayLimit()
  }

  // How many may record at once, told to the helper (it starts them and
  // checks the scheduled ones): when it changes, and once the guide's loaded.
  // One at a time: changed again meanwhile, the newest goes once it's in
  // (so the helper never ends up with an older choice)
  function sayLimit() {
    if (dvr.limitBusy) return
    var n = dvr.settings.atOnce
    dvr.limitBusy = true
    dvr.call(["limit", String(n)], undefined, function(res) {
      // not in: the scheduled ones go on waiting, and it's tried again
      if (!res.ok || res.atOnce !== n) { limitRetry.restart(); return }
      dvr.limitBusy = false
      if (dvr.settings.atOnce !== n) dvr.sayLimit()
      else dvr.refresh()
    })
  }
  Timer {
    id: limitRetry
    interval: 10000
    onTriggered: { dvr.limitBusy = false; dvr.sayLimit() }
  }

  // The place: your Videos folder (made ready at the first recording)
  function useDefault() { dvr.set({ place: null }); dvr.said = "" }

  // A folder of yours, or a drive's (made ready now: its "Uber TV Recordings" folder)
  function useFolder(path, done) {
    call(["prepare", String(path)], undefined, function(res) {
      if (res.ok) {
        dvr.set({ place: dvr.withPath(res.place, res.path) })
        dvr.placeInfo = { problem: "", path: res.path, free: res.free, size: res.size, private: res.private, system: res.system === true }
        dvr.said = res.private === false ? "That drive can't keep files private: anyone with the drive can open them." : ""
      } else dvr.said = dvr.placeProblem(res.error)
      if (done) done(res)
    })
  }

  // A USB drive from the list: mounted first if it isn't (no password in your session)
  function useDrive(device, done) {
    var d = dvr.drives.filter(function(x) { return x.device === device })[0]
    if (!d) { if (done) done({ ok: false, error: "drive" }); return }
    if (d.mount) { dvr.useFolder(d.mount, done); return }
    call(["mount", device], undefined, function(res) {
      if (!res.ok) { dvr.said = "Couldn't open that drive."; if (done) done(res); return }
      dvr.listDrives()
      dvr.useFolder(res.mount, done)
    })
  }

  function withPath(place, path) {
    var p = {}
    for (var k in place) p[k] = place[k]
    p.path = path
    return p
  }

  function placeProblem(code) {
    return code === "hidden" ? "That's a hidden folder: choose another."
         : code === "own" ? "Uber TV and your settings keep their files there: choose another folder."
         : code === "temporary" ? "That location is temporary or system storage; choose a disk or a folder that's kept."
         : code === "system" ? "That's a system folder: choose one of yours."
         : code === "readonly" ? "You can't save there."
         : code === "missing" ? "That folder isn't there."
         : "That can't hold recordings."
  }

  // Your Videos folder (not chosen yet, or chosen and made ready)
  readonly property bool placeIsDefault: !settings.place || settings.place.path === defaultFolder + "/Uber TV Recordings"
  // Where recordings go, in a few words
  readonly property string placeLabel: placeIsDefault ? "Videos folder"
                                     : settings.place.removable ? (settings.place.label || "USB drive")
                                     : guide.shownPath(settings.place.path || (settings.place.mount + "/" + settings.place.rel))

  // ---- a channel, recording ----

  // The recording on a channel now (its channel's address hashed), or null
  function onChannel(ch) {
    if (!ch || !dvr.anyActive) return null
    var h = Dvr.hashOf(ch.url)
    // (an IPTV channel by its provider and name too: its address may have turned since it started)
    var key = ch.kind === "iptv" ? Dvr.streamKey({ kind: "iptv", provider: Dvr.providerOf(ch), channel: { name: ch.name, hash: h } }) : ""
    for (var i = 0; i < dvr.active.length; i++) {
      var r = dvr.active[i]
      if (r.kind === "youtube-video" || !r.channel) continue
      if (r.channel.hash === h || (key && r.kind === "iptv" && Dvr.streamKey(r) === key)) return r
    }
    return null
  }

  // Recording now, in a few words, for the top of the guide: "● Recording
  // CBS News", "● 2 recording" (a locked channel's not named); a video being
  // saved isn't a channel recording, so it isn't counted
  function elsewhere() {
    var live = dvr.active.filter(function(r) { return r.kind !== "youtube-video" })
    var n = live.length
    if (!n) return ""
    if (n > 1) return "● " + n + " recording"
    var r = live[0]
    return "● Recording " + (r.private || dvr.hidden(r) ? "a locked channel" : (r.channel || {}).name || r.title || "")
  }

  // Watching ch while a recording takes another stream from its provider:
  // two streams, which a one-stream plan may not allow
  function sharesProvider(ch) {
    var p = Dvr.providerOf(ch)
    if (!p) return false
    for (var i = 0; i < dvr.active.length; i++) {
      var c = dvr.channelOf(dvr.active[i])
      if (c && c !== ch && Dvr.providerOf(c) === p) return true
    }
    return false
  }

  // The channel a recording was made from (for the lock), or null: by its
  // address hashed (worked out once there are recordings, and again when
  // the channels change)
  readonly property bool needHashes: recordings.length > 0 || rules.length > 0
  readonly property var hashMap: {
    var m = {}
    if (!needHashes) return m
    var chs = guide.channels
    for (var i = 0; i < chs.length; i++) m[Dvr.hashOf(chs[i].url)] = chs[i]
    return m
  }
  function channelOf(rec) {
    var h = rec && rec.channel ? rec.channel.hash : ""
    return h ? dvr.hashMap[h] || null : null
  }

  // The channel a recording's lock goes by, as the lock itself goes: the
  // channel now (its address hashed), else a lock entry with that address
  // (the channel removed or changed since: as { url, name }, so it can still
  // be unlocked), else a channel or lock entry of its name
  function lockChannelOf(rec) {
    var ch = dvr.channelOf(rec)
    if (ch) return ch
    var h = rec && rec.channel ? rec.channel.hash : ""
    var name = rec && rec.channel ? rec.channel.name : ""
    var entries = guide.channelLock ? guide.channelLock.entries : []
    for (var i = 0; i < entries.length; i++)
      if (h && Dvr.hashOf(entries[i].url) === h) return { url: entries[i].url, name: entries[i].name, kind: "iptv" }
    if (!name) return null
    for (var c = 0; c < guide.channels.length; c++) if (guide.channels[c].name === name) return guide.channels[c]
    for (var j = 0; j < entries.length; j++) if (entries[j].name === name) return { url: entries[j].url, name: entries[j].name, kind: "iptv" }
    return null
  }

  // A recording's channel locked now: its titles hidden (unless the lock shows them)
  function hidden(rec) { var ch = dvr.lockChannelOf(rec); return !!ch && guide.titlesHidden(ch) }
  function locked(rec) { var ch = dvr.lockChannelOf(rec); return !!ch && guide.blocksChannel(ch) }

  // A recording from this provider running now (any of its channels): by
  // the provider kept with it (its channel may have gone since), else by
  // its channel now
  function recordingFrom(p) {
    for (var i = 0; i < dvr.active.length; i++) {
      var r = dvr.active[i]
      if (r.provider) { if (r.provider === p) return true; continue }
      var c = dvr.channelOf(r)
      if (c && Dvr.providerOf(c) === p) return true
    }
    return false
  }
  // Watching ch would take a 2nd stream from a provider a recording is
  // using, and nobody's said Watch anyway for it yet
  function needsAsk(ch) {
    var p = Dvr.providerOf(ch)
    return !!p && !dvr.allowed[p] && dvr.recordingFrom(p)
  }
  function allow(ch) {
    var p = Dvr.providerOf(ch)
    if (!p) return
    var a = {}
    for (var k in dvr.allowed) a[k] = true
    a[p] = true
    dvr.allowed = a
  }

  // What a Record choice on the channel at row would say: { label, note,
  // unavailable, job } (the reason it can't start, or what to know, before
  // it's pressed). show: a show picked in the guide instead of what's on
  // now: a scheduled YouTube channel's is its video (saved whenever); a live
  // or IPTV one only while it's on (a later one is scheduling, for later)
  function offer(row, show) {
    var ch = guide.channels[row]
    if (!ch || !dvr.settings.on) return null
    var now = Date.now() / 1000
    if (show && (ch.kind === "iptv" || ch.live) && !(show.start <= now + 60 && now < show.end)) return null
    var job = null
    try { job = Dvr.jobFor(dvr.chanFor(row), show || guide.airing(ch, now), now, dvr.settings.padding) } catch (e) { job = null }
    if (!job) return null
    var out = { label: Dvr.recordLabel(job), note: "", unavailable: false, job: job }
    if (dvr.active.length >= dvr.settings.atOnce) {
      out.unavailable = true
      out.note = "Too many recordings right now"
    } else if (dvr.settings.place && dvr.placeInfo && dvr.placeInfo.problem === "drive") {
      out.unavailable = true
      out.note = (dvr.settings.place.label || "The drive") + " isn't there"
    } else if (dvr.placeInfo && dvr.placeInfo.problem === "readonly") {
      out.unavailable = true
      out.note = "Can't save to " + dvr.placeLabel
    } else if (dvr.placeInfo && !dvr.placeInfo.missing && dvr.placeInfo.free > 0 && dvr.placeInfo.free < (dvr.keepFreeGB + 1) * Dvr.GB) {
      out.unavailable = true
      out.note = "Not enough space (" + dvr.keepFreeGB + " GB kept free)"
    } else if (dvr.secondStream(ch)) {
      out.note = "Uses a 2nd stream from this provider"
    }
    return out
  }

  // Would recording this channel open a second stream from its provider?
  // (watching it, or another of its channels, recording, Multiview's tiles)
  function secondStream(ch) {
    var p = Dvr.providerOf(ch)
    if (!p) return false
    var tuned = guide.channels[guide.tunedRow]
    if (guide.reception !== "off" && tuned && Dvr.providerOf(tuned) === p) return true
    for (var i = 0; i < dvr.active.length; i++) {
      var c = dvr.channelOf(dvr.active[i])
      if (c && Dvr.providerOf(c) === p) return true
    }
    return guide.multiviewProviders().indexOf(p) >= 0
  }

  function chanFor(row) {
    var ch = guide.channels[row]
    return { name: ch.name, url: ch.url, kind: ch.kind, live: ch.live, category: ch.category, src: ch.src || "", number: guide.numbers[row] || 0 }
  }

  // Record the channel at row, from now: to its show's end (listings), an
  // hour (none), or its scheduled video saved whole; end (Unix seconds), if
  // given, instead (an agent's length). A locked channel asks for its
  // passcode first. done(result) once the helper has answered.
  function record(row, done, end, show, rule) {
    var ch = guide.channels[row]
    if (!ch) return "no such channel"
    if (!dvr.settings.on) return "Recordings are off (Settings → Recordings)"
    if (guide.askToWatch(row, function() { dvr.record(row, done, end, show, rule) })) return "asked for the passcode"
    var o = dvr.offer(row, show)
    if (!o) return "nothing to record there"
    if (o.unavailable) { dvr.said = o.note; return o.note }
    var job = o.job
    if (end && job.kind !== "youtube-video") job.end = Math.round(Math.min(end, Date.now() / 1000 + Dvr.MAX_HOURS * 3600))
    job.private = guide.lockProtects(ch)
    if (rule) job.rule = rule              // a series' episode, recorded now
    dvr.busy = true
    dvr.ready(function(place) {
      if (!place) { dvr.busy = false; if (done) done({ ok: false, error: "place" }); return }
      // turned off meanwhile: nothing starts
      if (!dvr.settings.on) { dvr.busy = false; if (done) done({ ok: false, error: "off" }); return }
      job.place = place
      job.keepFree = dvr.keepFreeGB * Dvr.GB
      job.quality = dvr.quality
      dvr.call(["start"], JSON.stringify(job), function(res) {
        dvr.busy = false
        // turned off while it was starting: it stops at once
        if (res.ok && !dvr.settings.on) dvr.stop(res.id)
        dvr.said = res.ok ? "" : dvr.startProblem(res)
        dvr.refresh()
        if (done) done(res)
      })
    })
    return "ok"
  }

  // The place, ready to record into: your Videos folder made ready the first time
  function ready(then) {
    if (dvr.settings.place) { then(dvr.settings.place); return }
    dvr.call(["prepare", dvr.defaultFolder, "make"], undefined, function(res) {
      if (!res.ok) { dvr.said = dvr.placeProblem(res.error); then(null); return }
      dvr.set({ place: dvr.withPath(res.place, res.path) })
      dvr.placeInfo = { problem: "", path: res.path, free: res.free, size: res.size, private: res.private, system: res.system === true }
      then(dvr.settings.place)
    })
  }

  function startProblem(res) {
    if (res.error === "cap") return "Too many recordings right now"
    if (res.error === "space") return "Not enough space to record (" + dvr.keepFreeGB + " GB kept free)"
    if (res.error === "drive") return (dvr.settings.place && dvr.settings.place.label ? dvr.settings.place.label : "The drive") + " isn't there"
    if (res.error === "readonly") return "Can't save to " + dvr.placeLabel
    return "Couldn't start the recording"
  }

  function stop(id) {
    var s = {}
    for (var k in dvr.stopping) s[k] = true
    s[id] = true
    dvr.stopping = s
    dvr.call(["stop", String(id)], undefined, function() { dvr.refresh() })
  }

  // A new stop time (Unix seconds), within the 12 hours from its start
  function setEnd(id, end, done) {
    dvr.call(["until", String(id), String(Math.round(end))], undefined, function(res) {
      dvr.refresh()
      if (done) done(res)
    })
  }

  // Deletes a recording: its file, its details, its picture (a running one stops first)
  function remove(id, done) {
    dvr.call(["remove", String(id)], undefined, function(res) {
      dvr.refresh()
      if (done) done(res)
    }, 90000)
  }

  // ---- later shows ----

  // What a Record choice on a later show would say (IPTV, from its
  // listings): { label, note, why, unavailable, slot }: what to know before
  // it's pressed (as many as may record at once already then, the drive not
  // plugged in now); note is short, for the choice's row, why names the
  // others, for the box's text, where a long title wraps
  function laterOffer(row, show) {
    var ch = guide.channels[row]
    if (!ch || !dvr.settings.on || ch.kind !== "iptv" || !show || show.epg !== true) return null
    var now = Date.now() / 1000
    if (show.start <= now + 60) return null      // on now: Record records it now (offer)
    var slot = Dvr.slotFor(dvr.chanFor(row), show, dvr.settings.padding, "")
    if (!slot) return null
    var out = { label: "Record", note: "", why: "", unavailable: false, slot: slot }
    var others = Dvr.clashes(dvr.recordings, Dvr.streamKey({ kind: "iptv", provider: slot.provider, channel: slot.channel }),
                             slot.showStart - slot.early, slot.showEnd + slot.late, now, dvr.settings.atOnce)
    if (others.length) {
      out.note = "Conflict: too many recordings at this time"
      out.why = "Already scheduled: " + dvr.namesOf(others).join(", ")
    }
    else if (dvr.settings.place && dvr.placeInfo && dvr.placeInfo.problem === "drive") out.note = (dvr.settings.place.label || "The drive") + " isn't plugged in now"
    return out
  }

  function namesOf(recs) {
    return recs.map(function(r) { return r.private || dvr.hidden(r) ? "a locked channel" : (r.title || (r.channel || {}).name || "a recording") })
  }
  // A conflict's others (kept by their ids), named as the lock is now
  function othersOf(ids) {
    return (ids || []).map(function(id) { var r = dvr.byId[id]; return r ? dvr.namesOf([r])[0] : "a recording" })
  }
  // A recording's one plain reason (a conflict naming the others)
  function reasonOf(rec) { return Dvr.reasonOf(rec, rec && rec.state === "conflict" ? dvr.othersOf(rec.others) : null) }

  // The series a show's title is on this channel: by its address, or (its
  // address changed since) by its name from the same provider; or null
  function ruleFor(ch, title) {
    var hash = Dvr.hashOf(ch.url), p = Dvr.providerOf(ch)
    for (var i = 0; i < dvr.rules.length; i++) {
      var x = dvr.rules[i]
      if (Dvr.fold(x.title) !== Dvr.fold(title) || !x.channel) continue
      if (x.channel.hash === hash || (p && x.provider === p && Dvr.fold(x.channel.name) === Dvr.fold(ch.name))) return x
    }
    return null
  }

  // A later show recorded (IPTV, from its listings): Scheduled, or a
  // Conflict when two would be recording then. A locked channel asks for
  // its passcode first (and records later all the same).
  function schedule(row, show, done) {
    var ch = guide.channels[row]
    if (!ch) return "no such channel"
    if (!dvr.settings.on) return "Recordings are off (Settings → Recordings)"
    if (guide.askToWatch(row, function() { dvr.schedule(row, show, done) })) return "asked for the passcode"
    var slot = Dvr.slotFor(dvr.chanFor(row), show, dvr.settings.padding, "")
    if (!slot) return "that show can't be scheduled"
    slot.private = guide.lockProtects(ch)
    dvr.call(["schedule"], JSON.stringify({ slots: [slot] }), function(res) {
      var one = res.ok && Array.isArray(res.slots) ? res.slots[0] : null
      dvr.said = !one || !one.ok ? "Couldn't schedule it"
               : one.state === "conflict" ? "Conflict: too many recordings at this time" : ""
      dvr.refresh()
      if (done) done(one || res)
    })
    return "ok"
  }

  // Record every episode: a rule (the channel and the show's title); this
  // one recorded now if it's on, the next ones scheduled as the listings
  // have them. A locked channel asks for its passcode first.
  function recordSeries(row, show, done) {
    var ch = guide.channels[row]
    if (!ch || ch.kind !== "iptv" || !show || show.epg !== true || !show.title) return "that show can't be recorded as a series"
    if (!dvr.settings.on) return "Recordings are off (Settings → Recordings)"
    if (guide.askToWatch(row, function() { dvr.recordSeries(row, show, done) })) return "asked for the passcode"
    var chan = dvr.chanFor(row)
    var rule = { channel: { name: chan.name, number: chan.number, hash: Dvr.hashOf(chan.url) }, title: show.title,
                 provider: Dvr.providerOf(chan), private: guide.lockProtects(ch) }
    dvr.call(["series", "add"], JSON.stringify(rule), function(res) {
      if (!res.ok) { dvr.said = "Couldn't record the series"; if (done) done(res); return }
      var now = Date.now() / 1000
      var finish = function(result) {
        dvr.refresh(function() { dvr.updateSeries() })
        if (done) done(result)
      }
      // this episode now (the one picked, even a minute before it starts), as one of the series'
      if (!(show.start <= now + 60 && now < show.end)) { finish(res); return }
      var going = dvr.onChannel(ch)
      if (!going) { dvr.record(row, null, 0, show, res.id); finish(res); return }
      // already recording on that channel: joined to that recording (its stop
      // moved to this show's end); one that's ended meanwhile: recorded itself
      var late = (Dvr.PADDINGS[dvr.settings.padding] || Dvr.PADDINGS[1])[1] * 60
      dvr.call(["tag"], JSON.stringify({ id: going.id, rule: res.id, title: show.title, sub: show.sub || "", ep: show.ep || "", late: late, url: ch.url,
                                         show: { start: Math.round(show.start), end: Math.round(show.end) } }), function(t) {
        if (!t.ok && t.error === "ended") dvr.record(row, null, 0, show, res.id)
        else if (!t.ok) dvr.said = "Couldn't add this episode to the recording on that channel"
        finish(res)
      })
    })
    return "ok"
  }

  // A scheduled one cancelled (a series' episode isn't scheduled again)
  function cancel(id, done) {
    dvr.call(["cancel", String(id)], undefined, function(res) { dvr.refresh(); if (done) done(res) })
  }

  // Stop recording this series: its rule, and its shows not started yet
  function stopSeries(ruleId, done) {
    dvr.call(["series", "remove", String(ruleId)], undefined, function(res) { dvr.refresh(); if (done) done(res) })
  }

  function ruleOf(rec) {
    for (var i = 0; rec && rec.rule && i < dvr.rules.length; i++) if (dvr.rules[i].id === rec.rule) return dvr.rules[i]
    return null
  }

  // The recording or schedule for a show on the channel at row, or null
  function forShow(row, show) {
    var ch = guide.channels[row]
    if (!ch || !show) return null
    var now = Date.now() / 1000
    if (ch.kind === "iptv") return Dvr.forShow(dvr.recordings, Dvr.hashOf(ch.url), show, now)
    // a YouTube channel: what's recording on it, for the show on now (its
    // live stream, or its lineup's video); a video being saved isn't one
    return show.start <= now && now < show.end ? dvr.onChannel(ch) : null
  }

  // For the guide's cells: each channel's address -> its shows recording or
  // scheduled [{ from, to, state }]
  readonly property var marks: {
    var m = {}
    for (var i = 0; i < recordings.length; i++) {
      var r = recordings[i]
      // IPTV's, recording or scheduled; a YouTube live stream's, recording
      if (!(r.kind === "iptv" && (Dvr.active(r) || Dvr.waiting(r))) && !(r.kind === "youtube-live" && Dvr.active(r))) continue
      var ch = dvr.channelOf(r)
      if (!ch) continue
      if (!m[ch.url]) m[ch.url] = []
      m[ch.url].push(Dvr.active(r) ? { from: r.started || r.created || 0, to: r.end || 0, state: "recording" }
                                   : { from: r.show ? r.show.start : r.start, to: r.show ? r.show.end : r.end, state: r.state })
    }
    return m
  }
  // What a cell says about its show: "recording", "scheduled", "conflict" or "".
  // Recording: one that covers a real part of the show (half of it, or five
  // minutes of a long one), not the minute or two of padding at its edges
  function markFor(ch, show) {
    var list = ch && show ? dvr.marks[ch.url] : null
    for (var i = 0; list && i < list.length; i++) {
      var m = list[i]
      if (m.state === "recording") {
        // a LIVE block (no listings): recording now covers it, however short
        if (show.live && m.from < show.end && m.to > show.start) return m.state
        var covered = Math.min(show.end, m.to) - Math.max(show.start, m.from)
        if (covered >= Math.min(300, (show.end - show.start) / 2)) return m.state
      } else if (show.start === m.from) return m.state
    }
    return ""
  }

  // Off, with recordings running or scheduled: the running ones stop, the
  // scheduled ones are cancelled (asked first, by the caller); a series'
  // rule stays, and schedules again once Recordings is on
  function turnOff() {
    for (var i = 0; i < dvr.active.length; i++) dvr.stop(dvr.active[i].id)
    // (all taken off the list at once, not cancelled: a series' episodes come back with it)
    if (dvr.hasWaiting) dvr.call(["clear"], undefined, function() { dvr.refresh() })
    dvr.set({ on: false })
  }
}
