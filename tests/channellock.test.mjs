// node tests/channellock.test.mjs
// ChannelLock.js: which channels are locked (following the channel, not its
// number), whether one is blocked now, typing a passcode, the list to lock from
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const L = new Function(readFileSync(new URL("../ChannelLock.js", import.meta.url), "utf8").replace(".pragma library", "") +
  "; return { UNLOCK, unlockLabel, nextUnlock, index, isLocked, blocks, unlockUntil, setLocked, missing, typed, complete, listed, nextExpiry, pruned, byAddress, videoChannels }")()

const chans = [{ url: "https://a/1", name: "News" }, { url: "https://a/2", name: "Movies" }, { url: "https://a/3", name: "Kids" }]

// which are locked: by address, and by name only for an entry whose address is gone
let idx = L.index([{ url: "https://a/2", name: "Movies" }], chans)
assert.equal(L.isLocked(idx, chans[1]), true, "by address")
assert.equal(L.isLocked(idx, chans[0]), false)
idx = L.index([{ url: "https://old/3", name: "Kids" }], chans)
assert.equal(L.isLocked(idx, chans[2]), true, "a playlist refresh changed its address: by its name")
idx = L.index([{ url: "https://a/1", name: "Kids" }], chans)
assert.equal(L.isLocked(idx, chans[2]), false, "a name doesn't count while the entry's own address is still a channel")
assert.equal(L.isLocked(idx, null), false, "no channel")

// blocked now: on, locked, and not unlocked
idx = L.index([{ url: "https://a/2", name: "Movies" }], chans)
assert.equal(L.blocks(true, idx, {}, chans[1], 1000), true, "locked, no unlock")
assert.equal(L.blocks(false, idx, {}, chans[1], 1000), false, "the lock off: nothing is blocked")
assert.equal(L.blocks(true, idx, {}, chans[0], 1000), false, "not locked")
assert.equal(L.blocks(true, idx, { "https://a/2": 0 }, chans[1], 1000), false, "unlocked until the TV is off")
assert.equal(L.blocks(true, idx, { "https://a/2": 2000 }, chans[1], 1000), false, "unlocked for an hour, still in it")
assert.equal(L.blocks(true, idx, { "https://a/2": 900 }, chans[1], 1000), true, "that hour's over")
assert.equal(L.blocks(true, idx, { "https://a/1": 0 }, chans[1], 1000), true, "another channel's unlock doesn't count")
assert.equal(L.unlockUntil("tv", 1000), 0)
assert.equal(L.unlockUntil(60, 1000), 1000 + 3600)
assert.equal(L.unlockUntil(240, 1000), 1000 + 4 * 3600)
assert.equal(L.unlockUntil("forever", 1000), 0, "anything else: until the TV is off")
assert.equal(L.unlockLabel("tv"), "Until the TV is off")
assert.equal(L.nextUnlock(240), "tv", "Enter goes round")

// locking and unlocking
let e = L.setLocked([], [chans[0], chans[2]], true, chans)
assert.deepEqual(e, [{ url: "https://a/1", name: "News" }, { url: "https://a/3", name: "Kids" }], "locked by address and name")
assert.deepEqual(L.setLocked(e, [chans[0]], true, chans), e, "locking one again changes nothing")
assert.deepEqual(L.setLocked(e, [chans[0]], false, chans), [{ url: "https://a/3", name: "Kids" }], "unlocked by address")
e = [{ url: "https://old/3", name: "Kids" }, { url: "https://a/9", name: "Kids" }]
assert.deepEqual(L.setLocked(e, [chans[2]], false, chans.concat([{ url: "https://a/9", name: "Kids" }])), [{ url: "https://a/9", name: "Kids" }],
  "unlocking takes off the entry it matched by name (its address gone), not another channel's with the same name")
assert.deepEqual(L.missing([{ url: "https://x", name: "Gone" }, { url: "https://a/1", name: "News" }], chans), [{ url: "https://x", name: "Gone" }],
  "an entry matching nothing is listed, so you notice")

// typing
assert.equal(L.typed("12", "3"), "123")
assert.equal(L.typed("12345678", "9"), "12345678", "at most 8 digits")
assert.equal(L.typed("12", "a"), "12", "only digits")
assert.equal(L.typed("12", "back"), "1")
assert.equal(L.complete("123"), false, "4 to 8 digits")
assert.equal(L.complete("0123"), true, "a leading 0 counts")
assert.equal(L.complete("123456789"), false)

// the list to lock from: search by name or number
const numbers = [101, 102, 103]
idx = L.index([{ url: "https://a/2", name: "Movies" }], chans)
assert.deepEqual(L.listed(chans, numbers, idx, "").map(x => [x.number, x.locked]), [[101, false], [102, true], [103, false]])
assert.deepEqual(L.listed(chans, numbers, idx, "mov").map(x => x.row), [1], "by name, any case")
assert.deepEqual(L.listed(chans, numbers, idx, "103").map(x => x.row), [2], "by number")
// timed unlocks running out
assert.equal(L.nextExpiry({ a: 0, b: 500, c: 300 }, 100), 300, "the soonest timed one")
assert.equal(L.nextExpiry({ a: 0 }, 100), 0, "until the TV is off: none timed")
assert.deepEqual(L.pruned({ a: 0, b: 500, c: 50 }, 100), { a: 0, b: 500 }, "the ones run out go; until the TV is off stays")
// the channels a video is from: every one it's on, the addresses kept with
// it (a removed one by its lock entry), or for an older record an exact name
{
  const a = { kind: "youtube", url: "https://y/a", name: "Bob" }, b = { kind: "youtube", url: "https://y/b", name: "Bob" }, tv = { kind: "iptv", url: "https://i/1", name: "Bob" }
  const all = [a, b, tv], by = L.byAddress(all)
  assert.deepEqual(Object.keys(by), ["https://y/a", "https://y/b"], "YouTube channels only")
  const ents = [{ url: "https://y/gone", name: "Gone" }]
  assert.deepEqual(L.videoChannels(all, by, [1, 0], [], "", ents), [b, a], "every channel it's on")
  assert.deepEqual(L.videoChannels(all, by, [], ["https://y/a", "https://y/gone", "https://y/never"], "Bob", ents), [a, { url: "https://y/gone", name: "Gone", kind: "youtube" }],
    "kept addresses: yours, or a lock entry's; the name doesn't count")
  assert.deepEqual(L.videoChannels(all, by, [], [], "Bob", ents), [a, b], "no addresses: every YouTube channel of that name")
  assert.deepEqual(L.videoChannels(all, by, [], [], "Gone", ents), [{ url: "https://y/gone", name: "Gone", kind: "youtube" }], "or lock entry")
  assert.deepEqual(L.videoChannels(all, by, [], ["constructor"], "", []), [], "an address that's a JavaScript word")
  assert.deepEqual(L.videoChannels(all, by, [], ["https://y/b"], "", [{ url: "https://y/a", name: "Bob" }, ents[0]], true),
    [b, a, { url: "https://y/gone", name: "Gone", kind: "youtube" }], "more addresses than were kept: every locked channel too")
}

console.log("channellock: all good")
