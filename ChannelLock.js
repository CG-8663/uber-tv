.pragma library

// The channel lock's rules (ChannelLock.qml): which
// channels are locked, whether one is blocked now, typing a passcode. The
// passcode itself is checked by the helper (bin/om-pg-apps lock-*), which
// keeps only its hash.

var UNLOCK = ["tv", 60, 240]   // an unlock lasts until the TV is off, or minutes

function unlockLabel(v) {
  return v === 60 ? "1 hour" : v === 240 ? "4 hours" : "Until the TV is off"
}

function nextUnlock(v) {
  var i = UNLOCK.indexOf(v)
  return UNLOCK[(i + 1) % UNLOCK.length]
}

// The locked channels, indexed: by address, and by name for an entry whose
// address no channel has any more (a playlist refresh changed it), so the
// lock follows the channel, not its number
function index(entries, channels) {
  var have = {}, urls = {}, names = {}
  for (var i = 0; i < channels.length; i++) if (channels[i]) have[channels[i].url] = true
  for (var j = 0; j < entries.length; j++) {
    var e = entries[j]
    urls[e.url] = true
    if (!have[e.url] && e.name) names[e.name] = true
  }
  return { urls: urls, names: names }
}

function isLocked(idx, ch) {
  return !!ch && (idx.urls[ch.url] === true || idx.names[ch.name] === true)
}

// Whether a channel is blocked now: the lock on, the channel locked, and not
// unlocked (unlocked: address → until when, 0 for until the TV is off)
function blocks(on, idx, unlocked, ch, now) {
  if (!on || !isLocked(idx, ch)) return false
  var u = unlocked[ch.url]
  return !(u === 0 || (typeof u === "number" && u > now))
}

// An unlock for one channel: until the TV is off (0), or a time
function unlockUntil(unlockFor, now) {
  return unlockFor === 60 || unlockFor === 240 ? now + unlockFor * 60 : 0
}

// The entries with these channels locked (lock true) or unlocked: added by
// address; taken off by address, and by name for an entry whose address no
// channel has any more. all: every channel, to know which addresses are gone
function setLocked(entries, chans, lock, all) {
  var out = entries.slice()
  var have = {}
  for (var i = 0; i < all.length; i++) if (all[i]) have[all[i].url] = true
  for (var c = 0; c < chans.length; c++) {
    var ch = chans[c]
    if (!ch || !ch.url) continue
    if (lock) {
      if (!out.some(function(e) { return e.url === ch.url })) out.push({ url: ch.url, name: String(ch.name || "").slice(0, 200) })
    } else {
      out = out.filter(function(e) { return e.url !== ch.url && !(e.name === ch.name && !have[e.url]) })
    }
  }
  return out
}

// Your YouTube channels by address (for videoChannels)
function byAddress(channels) {
  var out = {}
  for (var i = 0; i < channels.length; i++) if (channels[i] && channels[i].kind !== "iptv") out[channels[i].url] = channels[i]
  return out
}

// The channels a video (On Demand) is from, any of which locks it: rows, the
// channels it's on now (one upload can be on several); owners, the addresses
// kept with what you watched or saved, so a channel renamed still counts, and
// one removed counts by its lock entry; name, for an older record kept with
// no addresses, every channel and lock entry of that name; incomplete, a
// record with more addresses than were kept: every locked channel, so it
// fails closed. byUrl: byAddress
function videoChannels(channels, byUrl, rows, owners, name, entries, incomplete) {
  var out = []
  for (var r = 0; r < rows.length; r++) if (channels[rows[r]]) out.push(channels[rows[r]])
  var own = Object.prototype.hasOwnProperty
  var gone = function(e) { return { url: e.url, name: e.name, kind: "youtube" } }
  for (var o = 0; o < owners.length; o++) {
    if (own.call(byUrl, owners[o])) out.push(byUrl[owners[o]])
    else for (var j = 0; j < entries.length; j++) if (entries[j].url === owners[o]) out.push(gone(entries[j]))
  }
  if (!owners.length && name) {
    for (var u in byUrl) if (byUrl[u].name === name) out.push(byUrl[u])
    for (var k = 0; k < entries.length; k++) if (entries[k].name === name && !own.call(byUrl, entries[k].url)) out.push(gone(entries[k]))
  }
  if (incomplete) for (var x = 0; x < entries.length; x++) out.push(own.call(byUrl, entries[x].url) ? byUrl[entries[x].url] : gone(entries[x]))
  return out
}

// Entries that match no channel now (neither address nor name): listed, so
// you notice
function missing(entries, channels) {
  var urls = {}, names = {}
  for (var i = 0; i < channels.length; i++) if (channels[i]) { urls[channels[i].url] = true; names[channels[i].name] = true }
  return entries.filter(function(e) { return !urls[e.url] && !names[e.name] })
}

// Typing a passcode: a digit adds (up to 8), "back" takes the last off
function typed(code, key) {
  if (key === "back") return code.slice(0, -1)
  if (/^[0-9]$/.test(key) && code.length < 8) return code + key
  return code
}

function complete(code) {
  return /^[0-9]{4,8}$/.test(code)
}

// The channels for the list, matching what's typed (name or number), in
// guide order: [{ row, number, name, locked }]
function listed(channels, numbers, idx, query) {
  var q = String(query || "").toLowerCase().trim()
  var out = []
  for (var r = 0; r < channels.length; r++) {
    var ch = channels[r]
    if (!ch) continue
    if (q && String(ch.name || "").toLowerCase().indexOf(q) < 0 && String(numbers[r]) !== q) continue
    out.push({ row: r, number: numbers[r], name: ch.name, locked: isLocked(idx, ch) })
  }
  return out
}

// The soonest a timed unlock runs out (0: none timed), and the unlocks still
// running: a channel playing when its unlock runs out stops (Guide.qml)
function nextExpiry(unlocked, now) {
  var soonest = 0
  for (var u in unlocked) {
    var t = unlocked[u]
    if (typeof t === "number" && t > 0 && (soonest === 0 || t < soonest)) soonest = t
  }
  return soonest
}

function pruned(unlocked, now) {
  var out = {}
  for (var u in unlocked) {
    var t = unlocked[u]
    if (t === 0 || (typeof t === "number" && t > now)) out[u] = t
  }
  return out
}
