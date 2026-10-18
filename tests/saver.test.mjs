// node tests/saver.test.mjs
// Saver.js: the screen saver's settings, its pictures, when it may come, and
// what an agent may change
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const S = new Function(readFileSync(new URL("../Saver.js", import.meta.url), "utf8").replace(".pragma library", "") +
  "; return { AFTER, PICTURES, EVERY, CLOCK, defaults, checked, next, folderOf, afterLabel, everyLabel, picturesLabel, clockLabel, playlist, shuffled, pictureAt, eligible, shouldShow, agentChange }")()

// settings
assert.deepEqual(S.defaults(), { on: false, after: 5, pictures: "both", folder: "", every: 20, clock: "bottomRight" }, "off to begin with, 5 minutes, both, 20 s, bottom right")
assert.deepEqual(S.checked(undefined), S.defaults(), "nothing saved yet")
assert.deepEqual(S.checked({ on: "yes", after: 7, pictures: "photos", folder: "rel/path", every: 5, clock: "corner" }), S.defaults(), "every bad value falls back")
assert.equal(S.checked({ on: true }).on, true)
assert.equal(S.checked({ folder: "/home/u/Pics" }).folder, "/home/u/Pics")
assert.equal(S.checked({ folder: "/home/u/a\0b" }).folder, "", "no NUL in a path")
assert.equal(S.checked({ folder: "/" + "x".repeat(5000) }).folder, "", "not too long")
assert.equal(S.next(S.AFTER, 30), 1, "Enter goes round")
assert.equal(S.next(S.CLOCK, "middle"), "off")
assert.equal(S.next(S.CLOCK, "nonsense"), "bottomRight", "an unknown one starts at the first")
assert.equal(S.folderOf(S.defaults(), "/home/u"), "/home/u/Pictures/Screen Saver", "the designated folder")
assert.equal(S.folderOf({ folder: "/data/pics" }, "/home/u"), "/data/pics", "or the one picked")
assert.equal(S.afterLabel(1), "1 minute")
assert.equal(S.afterLabel(15), "15 minutes")
assert.equal(S.everyLabel(60), "1 minute")
assert.equal(S.everyLabel(20), "20 seconds")
assert.equal(S.clockLabel("off"), "Off")
assert.equal(S.picturesLabel("both"), "Omarchy's + yours")

// the pictures
const om = ["/o/1.jpg", "/o/2.jpg"], mine = ["/m/a.png"]
assert.deepEqual(S.playlist("both", om, mine), ["/m/a.png", "/o/1.jpg", "/o/2.jpg"], "both: yours, then Omarchy's")
assert.deepEqual(S.playlist("omarchy", om, mine), om)
assert.deepEqual(S.playlist("folder", om, mine), mine)
assert.deepEqual(S.playlist("folder", om, []), om, "an empty folder falls back to Omarchy's")
assert.deepEqual(S.playlist("both", [], []), [], "nothing at all: black, with the clock")
let seed = 1
const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646 }
const list = Array.from({ length: 20 }, (_, i) => "/p/" + i)
const sh = S.shuffled(list, rnd)
assert.deepEqual([...sh].sort(), [...list].sort(), "a shuffle keeps every picture once")
assert.notDeepEqual(sh, list, "and changes the order")
assert.deepEqual(list[0], "/p/0", "the list given isn't changed")
// each screen a different picture, and every picture comes round
const two = [0, 1, 2, 3].map(step => [S.pictureAt(list, step, 0, 2), S.pictureAt(list, step, 1, 2)])
two.forEach(([a, b]) => assert.notEqual(a, b, "two screens, two pictures"))
assert.deepEqual(two.flat(), list.slice(0, 8), "screen by screen, step by step, in order")
assert.equal(S.pictureAt(["/only"], 5, 1, 2), "/only", "one picture: every screen shows it")
assert.equal(S.pictureAt([], 0, 0, 1), "", "none")

// when it may come
const now = (on, shown, playing, omarchySaver) => ({ on, shown, playing, omarchySaver })
assert.equal(S.eligible(now(true, true, false, false)), true, "on, on screen, nothing playing")
assert.equal(S.eligible(now(false, true, false, false)), false, "off")
assert.equal(S.eligible(now(true, false, false, false)), false, "Uber TV isn't on screen")
assert.equal(S.eligible(now(true, true, true, false)), false, "a video plays")
assert.equal(S.eligible(now(true, true, false, true)), false, "Omarchy's own screen saver is up")

// whether it comes now: only once Hyprland has seen nothing for the whole
// wait, and the wait since it could come has passed
const may = (eligible, quiet, waited, showing) => S.shouldShow({ eligible, quiet, waited, showing })
assert.equal(may(true, true, true, false), true, "quiet for the whole wait, and waited since it could come")
assert.equal(may(true, false, true, false), false, "a steady stream of input (never a quiet stretch): never, however long it goes on")
assert.equal(may(true, true, false, false), false, "a video just ended: quiet for ages, but the wait starts over")
assert.equal(may(false, true, true, false), false, "it may not (playing, off, Uber TV not on screen, Omarchy's up)")
assert.equal(may(true, true, true, true), false, "up already")

// what an agent may change
const base = S.defaults()
let r = S.agentChange(base, { after: 10, pictures: "folder", every: 60, clock: "middle" })
assert.deepEqual(r.changed, ["after", "pictures", "every", "clock"])
assert.deepEqual(r.ignored, {})
assert.equal(r.settings.after, 10)
r = S.agentChange(base, { on: true, folder: "/home/u/Private" })
assert.equal(r.settings.on, false, "an agent can't turn it on: it keeps the computer from locking")
assert.equal(r.settings.folder, "", "nor pick which of your pictures are read")
assert.ok(r.ignored.on && r.ignored.folder)
assert.deepEqual(r.changed, [])
r = S.agentChange({ ...base, on: true }, { on: false })
assert.equal(r.settings.on, true, "nor turn it off")
r = S.agentChange(base, { after: 7, clock: "corner", colour: "red" })
assert.deepEqual(r.changed, [])
assert.ok(r.ignored.after && r.ignored.clock && r.ignored.colour, "bad values and unknown settings say why")
console.log("saver: all good")
