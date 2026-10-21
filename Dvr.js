.pragma library

// The recorder's rules (DVR.qml, bin/om-pg-dvr): what a Record press
// records, a later show scheduled (and a series' episodes), whether it would
// be one recording too many then, the stop times on offer, what a
// recording's card says, the rows of the library's Recordings tab, and which
// provider a channel's stream comes from (two streams from one IPTV provider
// may be one too many).

// A channel's identity in a recording (for the channel lock): the SHA-256
// of its address, never the address (which can hold a provider's login).
function sha256(text) {
  var bytes = utf8(String(text))
  var K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
           0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
           0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
           0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
           0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
           0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
           0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
           0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]
  var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
  var bitLen = bytes.length * 8
  bytes.push(0x80)
  while (bytes.length % 64 !== 56) bytes.push(0)
  for (var s = 7; s >= 0; s--) bytes.push(s >= 4 ? 0 : (bitLen >>> (s * 8)) & 0xff)
  var w = new Array(64)
  for (var off = 0; off < bytes.length; off += 64) {
    for (var i = 0; i < 16; i++)
      w[i] = (bytes[off + i * 4] << 24) | (bytes[off + i * 4 + 1] << 16) | (bytes[off + i * 4 + 2] << 8) | bytes[off + i * 4 + 3]
    for (i = 16; i < 64; i++) {
      var a0 = w[i - 15], a1 = w[i - 2]
      var s0 = rotr(a0, 7) ^ rotr(a0, 18) ^ (a0 >>> 3)
      var s1 = rotr(a1, 17) ^ rotr(a1, 19) ^ (a1 >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0
    }
    var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7]
    for (i = 0; i < 64; i++) {
      var t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0
      var t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0
    }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0
    H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0
  }
  var hex = ""
  for (i = 0; i < 8; i++) hex += ("00000000" + (H[i] >>> 0).toString(16)).slice(-8)
  return hex
}

function rotr(x, n) { return (x >>> n) | (x << (32 - n)) }

// A channel's address hashed, worked out once a session: the guide asks
// again each time its channel list changes, and 1,400 addresses take a
// quarter of a second on the thread that draws the picture
var hashes = Object.create(null)
var hashCount = 0
function hashOf(url) {
  var key = String(url || "")
  var h = hashes[key]
  if (h === undefined) {
    if (hashCount >= 20000) { hashes = Object.create(null); hashCount = 0 }
    h = hashes[key] = sha256(key)
    hashCount++
  }
  return h
}

function utf8(s) {
  var out = []
  for (var i = 0; i < s.length; i++) {
    var c = s.charCodeAt(i)
    if (c >= 0xd800 && c < 0xdc00 && i + 1 < s.length) {
      var d = s.charCodeAt(i + 1)
      if (d >= 0xdc00 && d < 0xe000) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++ }
    }
    if (c < 0x80) out.push(c)
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63))
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
  }
  return out
}

// ---- settings ----

// Start early / end late, in minutes: one row, three choices
var PADDINGS = [[0, 0], [1, 2], [2, 5]]
var KEEP_FREE = [2, 5, 8, 10, 20]        // GB kept free on the drive
var QUALITIES = [1080, 720, 480]         // YouTube's; IPTV records as it comes
var MAX_HOURS = 12
var AT_ONCE = [1, 2, 3, 4]               // how many may record at once (each another stream, ~3 GB an hour)
var TIMESHIFT = [0, 5, 30]               // pause and rewind: the minutes its buffer keeps (0: off)
var GB = 1024 * 1024 * 1024

// Off until you turn it on (the strip asks, the first time; or Settings). 0
// means "as fits the place": on the system disk (your home folder's) under
// 64 GB, 8 GB kept free and 720p; anywhere else (a USB drive, another disk) 5
// GB and 1080p
function defaults() {
  return { on: false, place: null, keepFree: 0, quality: 0, padding: 1, atOnce: 2, timeshift: 0 }
}

function checked(s) {
  var d = defaults()
  if (!s || typeof s !== "object") return d
  var place = s.place && typeof s.place === "object" && typeof s.place.volume === "string" && typeof s.place.mount === "string"
              && typeof s.place.rel === "string" && s.place.mount.charAt(0) === "/" ? s.place : null
  return {
    on: s.on === true,
    place: place ? { volume: place.volume.slice(0, 300), mount: place.mount.slice(0, 1000), rel: place.rel.slice(0, 1000),
                     fstype: String(place.fstype || "").slice(0, 40), label: String(place.label || "").slice(0, 100),
                     removable: place.removable === true, system: place.system === true, path: String(place.path || "").slice(0, 2000) } : null,
    keepFree: KEEP_FREE.indexOf(s.keepFree) >= 0 ? s.keepFree : 0,
    quality: QUALITIES.indexOf(s.quality) >= 0 ? s.quality : 0,
    padding: s.padding === 0 || s.padding === 1 || s.padding === 2 ? s.padding : 1,
    atOnce: AT_ONCE.indexOf(s.atOnce) >= 0 ? s.atOnce : 2,
    timeshift: TIMESHIFT.indexOf(s.timeshift) >= 0 ? s.timeshift : 0     // pause and rewind: minutes kept, 0 off
  }
}

function small(placeInfo) {
  return !!placeInfo && placeInfo.system === true && placeInfo.size > 0 && placeInfo.size < 64 * GB
}

function keepFreeOf(s, placeInfo) { return s.keepFree || (small(placeInfo) ? 8 : 5) }
function qualityOf(s, placeInfo) { return s.quality || (small(placeInfo) ? 720 : 1080) }

function next(list, value) { return list[(list.indexOf(value) + 1) % list.length] }

function paddingLabel(i) {
  var p = PADDINGS[i] || PADDINGS[1]
  return !p[0] && !p[1] ? "None" : p[0] + " min early, " + p[1] + " late"
}

// ---- what a Record press records ----

// A job for bin/om-pg-dvr from a channel and what it's airing at now:
// with listings, to the show's end (+ the late padding); without, an hour.
// A scheduled YouTube channel's show is a video: saved whole.
function jobFor(ch, airing, now, padding) {
  if (!ch || !airing) return null
  var late = (PADDINGS[padding] || PADDINGS[1])[1] * 60
  var base = { channel: { name: ch.name || "", number: ch.number || 0, hash: hashOf(ch.url) }, category: ch.category || "", provider: providerOf(ch) }
  if (ch.kind === "iptv") {
    var listed = airing.epg === true && airing.end > now
    // a listed show: its episode and times too (a series' episode recorded now isn't recorded again)
    return merge(base, { kind: "iptv", url: ch.url, title: listed ? airing.title : ch.name, desc: airing.desc || "",
                         end: Math.round(listed ? Math.min(airing.end + late, now + MAX_HOURS * 3600) : now + 3600), listed: listed,
                         sub: listed ? airing.sub || "" : "", ep: listed ? airing.ep || "" : "",
                         show: listed ? { start: Math.round(airing.start), end: Math.round(airing.end) } : null })
  }
  if (ch.live && ch.live.id) return merge(base, { kind: "youtube-live", video: ch.live.id, title: ch.live.title || ch.name, end: Math.round(now + 3600), listed: false })
  if (airing.id && /^[A-Za-z0-9_-]{11}$/.test(airing.id)) return merge(base, { kind: "youtube-video", video: airing.id, title: airing.title || "", end: 0, listed: false })
  return null
}

function merge(a, b) {
  var o = {}
  for (var k in a) o[k] = a[k]
  for (k in b) o[k] = b[k]
  return o
}

// What a Record choice is called for that job
function recordLabel(job) { return job && job.kind === "youtube-video" ? "Save video" : "Record" }

// The stop times on offer while one records: the show's end (if it's still
// ahead), 30 minutes more, an hour or two from now, or the most a recording
// can run (12 hours from when it began: a scheduled one when it started, not
// when it was scheduled)
function stopChoices(rec, showEnd, now, clock) {
  var latest = (rec.start || rec.created || now) + MAX_HOURS * 3600
  var out = []
  if (showEnd && showEnd > now + 60 && showEnd <= latest) out.push({ key: "show", label: "End of show (" + clock(showEnd) + ")", end: showEnd })
  var plus = (rec.end || now) + 1800
  if (plus <= latest) out.push({ key: "more", label: "+30 min (" + clock(plus) + ")", end: plus })
  if (now + 3600 <= latest) out.push({ key: "1h", label: "1 hour (" + clock(now + 3600) + ")", end: now + 3600 })
  if (now + 7200 <= latest) out.push({ key: "2h", label: "2 hours (" + clock(now + 7200) + ")", end: now + 7200 })
  out.push({ key: "max", label: "Until I stop — 12 h maximum", end: latest })
  return out
}

// ---- later: scheduled shows and series ----

function fold(text) { return String(text || "").replace(/\s+/g, " ").trim().toLowerCase() }

// A show's identity on its channel (as bin/om-pg-dvr has it): its title
// with its episode number, else with its episode's title, else when it starts
function identity(show) {
  if (fold(show.ep)) return "ep:" + fold(show.title) + "|" + fold(show.ep)
  if (fold(show.sub)) return "sub:" + fold(show.title) + "|" + fold(show.sub)
  var at = show.show && show.show.start ? show.show.start : show.start
  return "at:" + Math.floor(at || 0)
}

// A listed IPTV show to record later, for bin/om-pg-dvr's schedule: its
// window padded (early, late), its series rule if it's one of a series'
function slotFor(ch, show, padding, rule) {
  // (a listed show of 5 minutes or more, as bin/om-pg-dvr schedules)
  if (!ch || ch.kind !== "iptv" || !show || show.epg !== true || !(show.end >= show.start + 300)) return null
  var p = PADDINGS[padding] || PADDINGS[1]
  return { kind: "iptv", channel: { name: ch.name || "", number: ch.number || 0, hash: hashOf(ch.url) }, provider: providerOf(ch),
           title: show.title || "", sub: show.sub || "", ep: show.ep || "", desc: show.desc || "", category: show.category || ch.category || "",
           showStart: Math.round(show.start), showEnd: Math.round(show.end), early: p[0] * 60, late: p[1] * 60, rule: rule || "" }
}

// Every show a recording holds (episodes back to back are joined into one)
function identities(rec) {
  return rec.ids && rec.ids.length ? rec.ids : [identity(rec)]
}

// Every series a recording's shows are of
function rulesOf(rec) {
  var held = (rec.rules || []).slice()
  if (rec.rule && held.indexOf(rec.rule) < 0) held.unshift(rec.rule)
  return held
}

// What takes one stream: a channel (shows back to back on it are one; an
// IPTV channel by its provider and name, as its address may turn), or a
// video being saved, on its own (as bin/om-pg-dvr's stream_key)
function streamKey(rec) {
  var ch = rec.channel || {}
  if (rec.kind === "youtube-video") return rec.id
  if (rec.kind === "iptv" && rec.provider && fold(ch.name)) return "ch:" + rec.provider + "|" + fold(ch.name)
  return ch.hash || rec.id
}

// A series' episodes to schedule from a channel's listings: its title,
// not started yet, and not one already scheduled, recording or recorded
// (by its identity, under its channel or its series: the channel's address
// may have changed since; a failed or missed one may be tried again)
function seriesShows(rule, shows, recs, now) {
  var hash = rule.channel ? rule.channel.hash : ""
  var have = {}
  for (var i = 0; i < recs.length; i++) {
    var r = recs[i]
    if (((r.channel && r.channel.hash === hash) || (rule.id && rulesOf(r).indexOf(rule.id) >= 0)) && r.state !== "failed" && r.state !== "missed"
        && !(r.state === "conflict" && r.end <= now)) {
      var ids = identities(r)
      for (var k = 0; k < ids.length; k++) have[ids[k]] = true
    }
  }
  return shows.filter(function(s) { return s.epg === true && s.start > now && fold(s.title) === fold(rule.title) && !have[identity(s)] })
}

// One pass of the series' episodes to schedule, at most n: one from each
// series in turn (a busy one doesn't keep the others waiting), each walked
// with a cursor through its channel's listed shows (as Listings keeps them:
// [start, end, title, description, category, episode title, episode]), so
// only what's sent is ever made. sources: [{ rule, list }]; passed: rule|
// identity -> true, sent before and passed by. { picks: [{ rule, show }],
// more: some may be left for the next pass }
function seriesPass(sources, recs, now, horizon, passed, n) {
  var cur = []
  for (var i = 0; i < sources.length; i++) {
    var rule = sources[i].rule
    var have = {}
    for (var j = 0; j < recs.length; j++) {
      var r = recs[j]
      if (((r.channel && rule.channel && r.channel.hash === rule.channel.hash) || rulesOf(r).indexOf(rule.id) >= 0)
          && r.state !== "failed" && r.state !== "missed" && !(r.state === "conflict" && r.end <= now)) {
        var ids = identities(r)
        for (var k = 0; k < ids.length; k++) have[ids[k]] = true
      }
    }
    cur.push({ rule: rule, list: sources[i].list || [], at: 0, have: have, done: false, title: fold(rule.title) })
  }
  var picks = []
  var going = cur.length
  while (picks.length < n && going > 0) {
    going = 0
    for (var c = 0; c < cur.length && picks.length < n; c++) {
      var one = cur[c]
      if (one.done) continue
      var show = null
      while (one.at < one.list.length) {
        var t = one.list[one.at++]
        if (t[0] <= now) continue
        if (t[0] >= now + horizon) { one.at = one.list.length; break }
        if (fold(t[2]) !== one.title) continue
        var s = { epg: true, id: "", title: t[2], desc: t[3], category: t[4], start: t[0], end: t[1], sub: t[5] || "", ep: t[6] || "" }
        var key = identity(s)
        if (one.have[key] || passed[one.rule.id + "|" + key]) continue
        one.have[key] = true
        show = s
        break
      }
      if (show) { picks.push({ rule: one.rule, show: show }); going++ } else one.done = true
    }
  }
  return { picks: picks, more: picks.length >= n && cur.some(function(x) { return !x.done && x.at < x.list.length }) }
}

// When one takes a stream (as bin/om-pg-dvr's span): a waiting one its
// window, a running one from now to its stop (a video being saved: an hour)
function waiting(rec) { return !!rec && (rec.state === "scheduled" || rec.state === "conflict") }
function spanOf(rec, now) {
  if (waiting(rec)) return [Math.max(rec.start || 0, now), rec.end || 0]
  return [now, rec.end || now + 3600]
}

// Would a show recorded from..to as the stream keyed so (streamKey) be one
// too many (cap: how many may record at once)? The others then, one a
// stream (two shows back to back on a channel are one), if it would; [] if
// it fits (as bin/om-pg-dvr's recheck, for the note on the Record choice
// before it's pressed)
function clashes(recs, key, from, to, now, cap) {
  var cover = []
  for (var i = 0; i < recs.length; i++) {
    var o = recs[i]
    if (!(active(o) || o.state === "scheduled")) continue
    var sp = spanOf(o, now)
    if (sp[0] < to && sp[1] > Math.max(from, now) && streamKey(o) !== key) cover.push({ a: sp[0], b: sp[1], r: o })
  }
  var a = Math.max(from, now)
  var points = [a].concat(cover.filter(function(c) { return c.a > a }).map(function(c) { return c.a }))
  var peak = 0
  for (var p = 0; p < points.length; p++) {
    var here = {}
    for (var k = 0; k < cover.length; k++) if (cover[k].a <= points[p] && points[p] < cover[k].b) here[streamKey(cover[k].r)] = true
    peak = Math.max(peak, Object.keys(here).length)
  }
  if (peak < (cap || 2)) return []
  // one a stream, soonest first
  var seen = {}, out = []
  cover.sort(function(x, y) { return x.a - y.a })
  for (var c = 0; c < cover.length; c++) {
    var stream = streamKey(cover[c].r)
    if (!seen[stream]) { seen[stream] = true; out.push(cover[c].r) }
  }
  return out
}

// The recording or schedule for a show on the channel hashed so (by when it
// starts, or a recording running then), or null
function forShow(recs, hash, show, now) {
  if (!hash || !show) return null
  for (var i = 0; i < recs.length; i++) {
    var r = recs[i]
    if (!r.channel || r.channel.hash !== hash || r.kind === "youtube-video") continue
    if (waiting(r) && r.show && r.show.start === show.start) return r
    if (active(r) && show.start <= now && now < show.end) return r
  }
  return null
}

// ---- cards ----

var REASONS = {
  drive: "The drive isn't there.", readonly: "The drive can't be written to.", space: "The disk got too full.",
  size: "It reached the largest size a recording can be.", refused: "The provider refused the stream (a plan allowing one stream at a time?).",
  network: "The stream stopped answering.", unreadable: "The stream couldn't be read.", stopped: "The stream stopped.",
  service: "It couldn't start.", offline: "The channel isn't live right now.",
  job: "That can't be recorded.", gone: "Its channel isn't in your list anymore.",
  notRunning: "Uber TV wasn't running when it was on: recordings happen while you're logged in, with the computer awake."
}

function reasonText(code) { return REASONS[code] || "" }

// A card's one plain reason (a conflict names the others, as the guide
// names them now: names, given)
function reasonOf(rec, names) {
  if (rec && rec.state === "conflict")
    return names && names.length ? "Already scheduled: " + names.join(", ") : "Conflict: too many recordings at this time"
  return reasonText(rec ? rec.reason : "")
}

// The state a card shows: Starting, Recording, Saving (a video), Done,
// Incomplete, Failed, or Drive missing (a finished one whose drive isn't here)
function stateOf(rec) {
  if (!rec) return ""
  if (rec.state === "scheduled") return "Scheduled"
  if (rec.state === "conflict") return "Conflict"
  if (rec.state === "missed") return "Missed"
  if (rec.state === "starting") return "Starting"
  if (rec.state === "recording") return rec.kind === "youtube-video" ? "Saving" : "Recording"
  if ((rec.state === "done" || rec.state === "incomplete") && rec.present === false) return "Drive missing"
  return rec.state === "done" ? "Done" : rec.state === "incomplete" ? "Incomplete" : rec.state === "failed" ? "Failed" : ""
}

function active(rec) { return !!rec && (rec.state === "starting" || rec.state === "recording") }
function playable(rec) { return !!rec && (rec.state === "done" || rec.state === "incomplete") && rec.present !== false && !!rec.path }
function needsYou(rec) {
  var s = stateOf(rec)
  return s === "Failed" || s === "Missed" || s === "Incomplete" || s === "Conflict" || s === "Drive missing"
}

// The tab's rows: what needs you first (Failed, Missed, Incomplete,
// Conflict, Drive missing), then what's recording now, then what's coming
// (soonest first), then what's recorded (newest first)
function rows(recs) {
  var attention = [], now = [], upcoming = [], done = []
  for (var i = 0; i < recs.length; i++) {
    var r = recs[i]
    if (active(r)) now.push(r)
    else if (needsYou(r)) attention.push(r)
    else if (r.state === "scheduled") upcoming.push(r)
    else if (r.state === "done") done.push(r)
  }
  var order = ["Failed", "Missed", "Incomplete", "Conflict", "Drive missing"]
  var newest = function(a, b) { return (b.created || 0) - (a.created || 0) }
  attention.sort(function(a, b) { return order.indexOf(stateOf(a)) - order.indexOf(stateOf(b)) || newest(a, b) })
  now.sort(newest); done.sort(newest)
  upcoming.sort(function(a, b) { return (a.start || 0) - (b.start || 0) })
  var out = []
  if (attention.length) out.push({ key: "rec-attention", title: "Needs attention", list: attention })
  if (now.length) out.push({ key: "rec-now", title: "Recording now", list: now })
  if (upcoming.length) out.push({ key: "rec-upcoming", title: "Upcoming", list: upcoming })
  if (done.length) out.push({ key: "rec-done", title: "Recorded", list: done })
  return out
}

// ---- providers ----

// A playlist's own id, given to its channels when they come in (opaque)
function sourceId(source) { return source ? sha256(String(source)).slice(0, 12) : "" }

// Which provider a channel's stream comes from: its playlist's id, or (a
// stream pasted on its own, or from before) its host, as a best guess
function providerOf(ch) {
  if (!ch || ch.kind !== "iptv") return ""
  if (ch.src) return "src:" + ch.src
  var m = String(ch.url || "").match(/^https?:\/\/(?:[^@\/?#]*@)?([^\/:?#]+)/i)
  return m ? "host:" + m[1].toLowerCase() : ""
}
