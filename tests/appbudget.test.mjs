// node tests/appbudget.test.mjs
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const src = readFileSync(new URL("../AppBudget.js", import.meta.url), "utf8").replace(".pragma library", "")
const B = new Function(src + "; return { makeRoom }")()

const rt = (phase, leases = [], busy = false, lastUsed = 0) =>
  ({ phase, leases: Object.fromEntries(leases.map(l => [l, true])), busy, lastUsed })

// an idle one at the limit is the one that goes, the least recently used first
assert.deepEqual(B.makeRoom({ a: rt("ready", [], false, 30), b: rt("ready", [], false, 10), c: rt("ready", ["foreground"]) }, {}, "foreground"),
                 { stop: "b", refuse: false })

// one that only holds Home rows makes room for a screen
assert.deepEqual(B.makeRoom({ a: rt("ready", ["home:now"], true, 5), b: rt("ready", ["foreground"]), c: rt("ready", ["playback"]) }, {}, "foreground"),
                 { stop: "a", refuse: false })

// three on screen, playing or starting: refused, nothing stops
assert.deepEqual(B.makeRoom({ a: rt("ready", ["foreground"]), b: rt("ready", ["playback"]), c: rt("starting") }, {}, "foreground"),
                 { stop: "", refuse: true })
assert.deepEqual(B.makeRoom({ a: rt("starting"), b: rt("starting"), c: rt("starting") }, {}, "foreground"),
                 { stop: "", refuse: true })

// one already stopping: wait for its slot, stop nothing else
assert.deepEqual(B.makeRoom({ a: rt("stopping"), b: rt("ready", ["foreground"]), c: rt("ready", ["playback"]) }, {}, "foreground"),
                 { stop: "", refuse: false })

// a sign-out still out (ready, no lease, its call pending, the app changing),
// two others starting: refused, the signing-out app isn't stopped
assert.deepEqual(B.makeRoom({ a: rt("ready", [], true), b: rt("starting"), c: rt("starting") }, { a: true }, "foreground"),
                 { stop: "", refuse: true })
// ...and once it's stopping, the open waits for its slot
assert.deepEqual(B.makeRoom({ a: rt("stopping"), b: rt("starting"), c: rt("starting") }, {}, "foreground"),
                 { stop: "", refuse: false })

// a ready runtime with no lease and a call still out, not changing: never
// stopped (an empty lease list doesn't count as "only Home's")
assert.deepEqual(B.makeRoom({ a: rt("ready", [], true), b: rt("starting"), c: rt("starting") }, {}, "foreground"),
                 { stop: "", refuse: true })

// an idle runtime whose app is changing isn't taken either
assert.deepEqual(B.makeRoom({ a: rt("ready", [], false, 1), b: rt("ready", [], false, 9), c: rt("starting") }, { a: true }, "foreground"),
                 { stop: "b", refuse: false })

// a Home-only runtime whose app is changing isn't taken by the fallback
assert.deepEqual(B.makeRoom({ a: rt("ready", ["home:x"], true), b: rt("ready", ["foreground"]), c: rt("starting") }, { a: true }, "foreground"),
                 { stop: "", refuse: true })

// a Home row's own ask ("home:<key>") does take a Home-only runtime (as in v1)
assert.deepEqual(B.makeRoom({ a: rt("ready", ["home:x"], true, 4), b: rt("ready", ["foreground"]), c: rt("starting") }, {}, "home:y"),
                 { stop: "a", refuse: false })
// only guide-made Home leases ("home:<key>") count as Home's
assert.deepEqual(B.makeRoom({ a: rt("ready", ["homework"], true), b: rt("ready", ["foreground"]), c: rt("starting") }, {}, "foreground"),
                 { stop: "", refuse: true })

// a plain "home" lease never takes the fallback (as in v1)
assert.deepEqual(B.makeRoom({ a: rt("ready", ["home:x"], true), b: rt("ready", ["foreground"]), c: rt("starting") }, {}, "home"),
                 { stop: "", refuse: true })

console.log("appbudget: all passed")
