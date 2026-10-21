.pragma library

// Pause and rewind's rules (Timeshift.qml): what the buffer takes, where
// each move goes in it, how far behind live the picture is, when it has
// stalled, and what Pause says when it can't. Times are the buffer's own:
// milliseconds from its first segment, summed from their lengths (what the
// player seeks by). A window is the buffer's status: { oldest, live, edge,
// headSeq, longest, completedAgo, ready }, live being where Live is (the
// start of the second-newest finished segment).

var MINUTES = [0, 5, 30]
var STEP = 30000            // Back 30 s, Forward 30 s
var NEAR = 1000             // this close to Live is Live

function minutesOf(s) { return MINUTES.indexOf(s) >= 0 ? s : 0 }
function minutesLabel(m) { return m ? m + " min" : "Off" }

// What it takes: a live channel on the TV (IPTV, or a YouTube channel's live
// stream), not a video
function supported(onAir) { return !!onAir && !onAir.vod && onAir.live === true }

// Where the writer copies from: the IPTV stream, or the streamer's playlist
// for a YouTube live stream (so YouTube is pulled once)
function upstream(onAir, streamBase) {
  if (!supported(onAir)) return ""
  if (onAir.iptv) return onAir.stream || ""
  return streamBase && onAir.id ? streamBase + "/play/" + onAir.id + ".m3u8" : ""
}

// One open of the buffer: a new address each time (Qt keeps a source's
// length from when it opened), from the window's head as the status said
function openUrl(base, gen, headSeq) { return base + "/live.m3u8?open=" + gen + "&from=" + (headSeq || 0) }

// A place in the window: never before its oldest part, never past Live
function clamp(t, w) { return Math.max(w.oldest, Math.min(w.live, t)) }
function backTarget(point, w) { return clamp(point - STEP, w) }
function reachesLive(point, w) { return point + STEP >= w.live - NEAR }
function forwardTarget(point, w) { return reachesLive(point, w) ? w.live : clamp(point + STEP, w) }

// How far behind Live the picture is, against the window's own Live point
function behind(point, w) { return Math.max(0, w.live - point) }

// How far the writer has got now, moving smoothly: the end of its newest
// finished segment plus what it has taken in since (as long as a segment
// takes, then it holds: a stall). The edge moves by exactly the segment just
// finished, so uneven segments don't make it jump (Live, the second-newest's
// start, moves by the one before)
function liveNow(w, sinceMs) {
  return (w.edge || 0) + Math.min(Math.max(0, w.completedAgo || 0) + Math.max(0, sinceMs), Math.max(w.longest || 0, 2000))
}

// "2:15", "1:02:03"
function span(ms) {
  var s = Math.floor(Math.max(0, ms) / 1000)
  var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60
  return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (r < 10 ? "0" : "") + r
}

// The chip on the picture
function chip(atLive, behindMs) { return atLive ? "Live" : span(behindMs) + " behind live" }

// A stall: no segment finished for longer than this channel's take, and the
// picture has stopped (a long segment still being written isn't one)
function stallAfter(w) { return Math.max(8000, 2 * (w.longest || 0) + 2000) }
function stalled(w, quietMs) { return !!w.ready && w.completedAgo > stallAfter(w) && quietMs > 2000 }
// and over once segments come again
function flowing(w) { return w.completedAgo >= 0 && w.completedAgo < stallAfter(w) }

// What Pause says when it can't run (the channel goes on live)
function cantPause(reason) {
  return reason === "drive" ? "Can't pause: the drive isn't plugged in"
       : reason === "readonly" ? "Can't pause: can't save to the drive"
       : reason === "space" ? "Can't pause: not enough space"
       : "Can't pause right now"
}

// The generation an address was opened as (0: not one of the buffer's)
function genOf(source, base) {
  var s = String(source || "")
  if (!base || s.indexOf(base + "/live.m3u8?open=") !== 0) return 0
  return parseInt(s.slice(base.length + 16), 10) || 0
}
