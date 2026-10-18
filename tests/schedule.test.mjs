// node tests/schedule.test.mjs
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const src = readFileSync(new URL("../Schedule.js", import.meta.url), "utf8").replace(".pragma library", "")
const S = new Function(src + "; return { EPOCH, programs, locate, airing, lineup, totalLength }")()

const items = S.programs({ entries: [
  { id: "a", title: "A", duration: 600 },
  { id: "short", title: "Short", duration: 30 },
  { id: "b", title: "B", duration: 1200 },
  { id: "nolen", title: "No length" },
  { id: "c", title: "C", duration: 300 },
  { id: "members", title: "Members only", duration: 900, availability: "subscriber_only" },
  { id: "private", title: "Private", duration: 900, availability: "private" },
] })
assert.deepEqual(items.map(i => i.id), ["a", "b", "c"])
assert.equal(S.totalLength(items), 2100)

// At the epoch the first video starts; the loop repeats every 2100s.
assert.deepEqual(S.locate(items, S.EPOCH), { index: 0, offset: 0 })
assert.deepEqual(S.locate(items, S.EPOCH + 700), { index: 1, offset: 100 })
assert.deepEqual(S.locate(items, S.EPOCH + 2100 + 1850), { index: 2, offset: 50 })
assert.deepEqual(S.locate(items, S.EPOCH - 100), { index: 2, offset: 200 })

// The airing list starts with the show already on and runs past the window.
const shows = S.airing(items, S.EPOCH + 700, S.EPOCH + 700 + 1800)
assert.equal(shows[0].title, "B")
assert.equal(shows[0].start, S.EPOCH + 600)
assert.ok(shows.at(-1).end >= S.EPOCH + 2500)
for (let i = 1; i < shows.length; i++) assert.equal(shows[i].start, shows[i - 1].end)

const tuned = S.lineup(items, S.EPOCH + 700, 12)
assert.equal(tuned.offset, 100)
assert.deepEqual(tuned.queue.map(i => i.id), ["b", "c", "a"])

assert.equal(S.locate([], S.EPOCH), null)
assert.deepEqual(S.airing([], 0, 1), [])
console.log("schedule: ok")
