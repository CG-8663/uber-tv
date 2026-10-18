.pragma library

// Every channel loops its videos end to end, forever, starting from this
// fixed moment. Anyone who tunes in at the same time lands on the same
// video at the same second, which is what makes it feel like broadcast TV.
var EPOCH = Date.UTC(2026, 0, 1) / 1000

var MIN_LENGTH = 5 * 60      // skips Shorts, trailers and clips too short to read in the grid
var MAX_LENGTH = 4 * 3600    // skips the 8-hour marathons

// The videos in a `yt-dlp --flat-playlist -J` listing that can air.
function programs(listing) {
  var entries = (listing && listing.entries) || []
  var out = []
  for (var i = 0; i < entries.length; i++) {
    var e = entries[i]
    if (!e || !e.id || !(e.duration >= MIN_LENGTH && e.duration <= MAX_LENGTH)) continue
    if (!watchable(e)) continue
    out.push({
      id: e.id,
      title: e.title || e.id,
      duration: Math.round(e.duration),
      url: "https://www.youtube.com/watch?v=" + e.id
    })
  }
  return out
}

// Members-only, private and paywalled videos can't air.
function watchable(entry) {
  var a = entry.availability
  return !a || a === "public" || a === "unlisted"
}

function totalLength(items) {
  var total = 0
  for (var i = 0; i < items.length; i++) total += items[i].duration
  return total
}

// What a channel is airing at time t (seconds): the video's index, and how
// far into it the broadcast is.
function locate(items, t) {
  var total = totalLength(items)
  if (total <= 0) return null
  var into = ((t - EPOCH) % total + total) % total
  for (var i = 0; i < items.length; i++) {
    if (into < items[i].duration) return { index: i, offset: into }
    into -= items[i].duration
  }
  return { index: 0, offset: 0 }
}

// The programs airing between from and to, with their start and end times.
function airing(items, from, to) {
  var here = locate(items, from)
  if (!here) return []
  var out = []
  var i = here.index
  var start = from - here.offset
  while (start < to && out.length < 200) {
    var item = items[i]
    out.push({ index: i, title: item.title, url: item.url, start: start, end: start + item.duration })
    start += item.duration
    i = (i + 1) % items.length
  }
  return out
}

// The videos to queue when tuning in at time t: the one on now (joined
// partway through), then the ones after it.
function lineup(items, t, count) {
  var here = locate(items, t)
  if (!here) return null
  var queue = []
  for (var k = 0; k < Math.min(count, items.length); k++)
    queue.push(items[(here.index + k) % items.length])
  return { queue: queue, offset: Math.floor(here.offset) }
}
