// node tests/appnav.test.mjs
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const load = (file, names) => new Function(readFileSync(new URL("../" + file, import.meta.url), "utf8").replace(".pragma library", "") + "; return { " + names + " }")()
const L = load("AppLooks.js", "model")
const N = load("AppNav.js", "lines, move, current, enter, details, normalize, locate, placement")

const item = (id, kind = "open") => ({ id, title: id, kind })
// u 10: a wide card is 155 wide (a 167 cell), a poster 86 (a 98 cell); at
// 600 wide a wide grid holds 3 to a line and a poster grid 5
const env = (width, learned = {}) => ({ width, u: 10, layout: { libraryPosterWidth: 8.6, libraryThumbWidth: 15.5 }, learned })
const screen = {
  title: "S", rows: [
    { id: "a", title: "A", layout: "row", items: [item("a1"), item("a2", "play"), item("a3", "info")] },
    { id: "empty", title: "Empty", layout: "row", items: [] },
    { id: "g", title: "G", layout: "grid", items: [1, 2, 3, 4, 5, 6, 7].map(i => item("g" + i)) },
    { id: "l", title: "L", layout: "list", items: [item("l1"), item("l2")] },
  ],
}
let v = { kind: "screen", value: screen, item: "", sel: null }
let m = L.model(v, env(600))
const step = key => { const s = N.move(m, v.sel, key); if (s) v.sel = s; return s }
const on = () => N.current(m, v.sel).thing.id

// empty rows aren't lines; a grid's columns come from its own cards
assert.deepEqual(N.lines(m).map(l => l.id), ["a", "g", "l"])
assert.equal(N.lines(m)[1].cols, 3)

// left at the start opens the rail (null); right moves along the row
assert.equal(N.move(m, v.sel, "left"), null)
step("right")
assert.equal(on(), "a2")
assert.deepEqual(N.enter(v, m), { method: "play", args: { item: "a2" } })
step("right")
assert.deepEqual(N.enter(v, m), { method: "details", args: { item: "a3" } })
assert.equal(N.move(m, v.sel, "right"), null, "the end of a row")

// down into the grid (3 to a line), then down within it, keeping columns
step("down")
assert.equal(on(), "g1")
step("right")
step("down")
assert.equal(on(), "g5")
step("down")
assert.equal(on(), "g7", "the last line of a grid, as near as there is")
assert.equal(N.move(m, v.sel, "right"), null, "the grid's edge")
step("down")
assert.equal(on(), "l1", "out of the grid into the list")
step("down")
assert.equal(on(), "l2")
assert.equal(N.move(m, v.sel, "down"), null)
assert.equal(N.move(m, v.sel, "left"), null, "a list has no left: the rail")
step("up")
step("up")
assert.equal(on(), "g7", "back up into the grid where it was")
step("up")
step("up")
step("up")
assert.equal(on(), "a3", "back to the row, its column remembered")

// the selection names its row and item
assert.equal(v.sel.row, "a")
assert.equal(v.sel.item, "a3")

// I: details of a row's item; Enter on an open item: browse
v.sel = N.normalize(m, { row: "g", item: "g1" })
assert.deepEqual(N.details(v, m), { method: "details", args: { item: "g1" } })
assert.deepEqual(N.enter(v, m), { method: "browse", args: { item: "g1" } })

// a refresh keeps the place by ids, even if things moved
const fresh = JSON.parse(JSON.stringify(screen))
fresh.rows[2].items.unshift(item("g0"))
fresh.rows.unshift({ id: "new", title: "New", layout: "row", items: [item("n1")] })
v.sel = N.normalize(m, { row: "g", item: "g5" })
let nv = { kind: "screen", value: fresh, sel: v.sel }
let nm = L.model(nv, env(600))
assert.equal(N.current(nm, nv.sel).thing.id, "g5")
nv.sel = N.normalize(nm, nv.sel)
assert.equal(nv.sel.col, 5, "the hint follows where it is now")
// its item gone: the nearest left in the same row
fresh.rows[3].items = fresh.rows[3].items.filter(i => i.id !== "g5")
nm = L.model(nv, env(600))
assert.equal(N.current(nm, nv.sel).line.id, "g")
assert.equal(N.current(nm, nv.sel).thing.id, "g6", "the nearest: the one now in its place")
// its row gone: the row now in its place, else the one above
const fewer = JSON.parse(JSON.stringify(fresh))
fewer.rows = fewer.rows.filter(r => r.id !== "g")
nm = L.model({ kind: "screen", value: fewer }, env(600))
assert.equal(N.current(nm, nv.sel).line.id, "l", "the row that was below it")
const last = { row: "l", item: "l2", line: 3, col: 1 }
const noList = JSON.parse(JSON.stringify(fresh))
noList.rows = noList.rows.filter(r => r.id !== "l")
nm = L.model({ kind: "screen", value: noList }, env(600))
assert.equal(N.current(nm, last).line.id, "g", "the last row went: the one above it")

// with the old model, several rows gone at once: the nearest survivor below,
// in the old order, else above
const four = { kind: "screen", value: { rows: ["A", "B", "C", "D"].map(id => ({ id, title: id, layout: "row", items: [item(id + "1"), item(id + "2")] })) } }
const fourM = L.model(four, env(600))
const onB = N.normalize(fourM, { row: "B", item: "B1" })
const twoLeft = { kind: "screen", value: { rows: four.value.rows.filter(r => r.id === "C" || r.id === "D") } }
assert.equal(N.current(L.model(twoLeft, env(600)), N.normalize(L.model(twoLeft, env(600)), onB, fourM)).line.id, "C", "B and A gone: C, the nearest below B")
const aboveOnly = { kind: "screen", value: { rows: four.value.rows.filter(r => r.id === "A") } }
assert.equal(N.current(L.model(aboveOnly, env(600)), N.normalize(L.model(aboveOnly, env(600)), { row: "C", item: "C1", line: 2, col: 0 }, fourM)).line.id, "A", "everything below gone: the nearest above")
// several items gone at once: the first still there after it, in the old order
const five = { kind: "screen", value: { rows: [{ id: "r", title: "R", layout: "row", items: [1, 2, 3, 4, 5].map(i => item("x" + i)) }] } }
const fiveM = L.model(five, env(600))
const onX3 = N.normalize(fiveM, { row: "r", item: "x3" })
const fewerX = { kind: "screen", value: { rows: [{ id: "r", title: "R", layout: "row", items: [item("x1"), item("x5")] }] } }
assert.equal(N.current(L.model(fewerX, env(600)), N.normalize(L.model(fewerX, env(600)), onX3, fiveM)).thing.id, "x5", "x2 to x4 gone: x5, the next one after x3")
const onlyFirst = { kind: "screen", value: { rows: [{ id: "r", title: "R", layout: "row", items: [item("x1")] }] } }
assert.equal(N.current(L.model(onlyFirst, env(600)), N.normalize(L.model(onlyFirst, env(600)), onX3, fiveM)).thing.id, "x1", "none after it: the nearest before")

// mixed grids: posters (5 to a line at 600) above wide pictures (3)
const mixed = {
  title: "M", rows: [
    { id: "p", title: "P", layout: "grid", items: [1, 2, 3, 4, 5, 6, 7].map(i => item("p" + i)) },
    { id: "w", title: "W", layout: "grid", items: [1, 2, 3, 4, 5, 6, 7].map(i => item("w" + i)) },
    { id: "z", title: "Z", layout: "list", items: [item("z1")] },
  ],
}
const shapes = { "r:p": "poster", "r:w": "wide" }
v = { kind: "screen", value: mixed, item: "", sel: null }
m = L.model(v, env(600, shapes))
assert.deepEqual(N.lines(m).map(l => [l.id, l.shape, l.cols]), [["p", "poster", 5], ["w", "wide", 3], ["z", "wide", 1]])
for (let i = 0; i < 4; i++) step("right")
assert.equal(on(), "p5")
assert.equal(N.move(m, v.sel, "right"), null, "the poster grid's right edge, at its own 5")
step("down")
assert.equal(on(), "p7", "an incomplete last line: as near as there is")
assert.equal(N.move(m, v.sel, "right"), null, "the end of an incomplete line")
step("down")
assert.equal(on(), "w1", "down out of the posters, into the wide grid's first line")
step("right")
step("right")
assert.equal(N.move(m, v.sel, "right"), null, "the wide grid's right edge, at its own 3")
step("down")
step("down")
assert.equal(on(), "w7", "the wide grid's incomplete last line")
step("down")
assert.equal(on(), "z1")
step("up")
assert.equal(on(), "w7", "back up where it was")
step("up")
step("up")
assert.equal(on(), "w1")
step("up")
assert.equal(on(), "p7", "up out of the wide grid, back where it left the posters")
// resizing: more to a line, the same item kept
m = L.model(v, env(900, shapes))
assert.deepEqual(N.lines(m).map(l => l.cols), [8, 5, 1])
assert.equal(on(), "p7", "a resize keeps the item")
step("down")
assert.equal(on(), "w1", "the poster grid is one line now: down goes straight to the wide grid")
step("right")
step("right")
step("right")
step("right")
assert.equal(on(), "w5")
assert.equal(N.move(m, v.sel, "right"), null, "its edge moved with the width")
m = L.model(v, env(600, shapes))
assert.equal(on(), "w5", "narrower again: still w5")
step("down")
assert.equal(on(), "w7", "w5 is on the second of three lines now; down is the last")

// coming up into a grid from below with nowhere remembered: its last line
v = { kind: "screen", value: mixed, item: "", sel: N.normalize(L.model({ kind: "screen", value: mixed }, env(600, shapes)), { row: "z", item: "z1" }) }
m = L.model(v, env(600, shapes))
v.sel.cols = {}
step("up")
assert.equal(on(), "w7", "the first item of its last line")

// a detail: actions first, then its rows
const detail = { title: "D", actions: [{ id: "watch", label: "Watch", kind: "play" }, { id: "fav", label: "Favorite", kind: "action" }],
                 rows: [{ id: "more", title: "More", layout: "row", items: [item("m1", "info")] }], facts: [] }
const dv = { kind: "detail", value: detail, item: "movie-9", sel: null }
const dm = L.model(dv, env(600))
assert.deepEqual(N.enter(dv, dm), { method: "play", args: { item: "watch" } })
dv.sel = N.move(dm, dv.sel, "right")
assert.equal(dv.sel.row, "", "a detail's actions are row \"\"")
assert.deepEqual(N.enter(dv, dm), { method: "action", args: { item: "movie-9", action: "fav" } })
assert.equal(N.details(dv, dm), null, "I on an action does nothing")
dv.sel = N.move(dm, dv.sel, "down")
assert.deepEqual(N.enter(dv, dm), { method: "details", args: { item: "m1" } })

// nothing to select
const none = { kind: "screen", value: { rows: [] } }
assert.equal(N.enter(none, L.model(none, env(600))), null)
assert.equal(N.move(L.model(none, env(600)), null, "down"), null)
assert.equal(N.placement("action", "message"), "message")
assert.equal(N.placement("browse", "screen"), "push")

// remembered columns don't grow with rows that are gone: a thousand
// refreshes, each with new row ids, and a move in each
let churn = null
for (let i = 0; i < 1000; i++) {
  const v2 = { kind: "screen", value: { rows: [{ id: "a" + i, title: "A", layout: "row", items: [item("x"), item("y")] }, { id: "b" + i, title: "B", layout: "row", items: [item("x")] }] } }
  const m2 = L.model(v2, env(600))
  churn = N.normalize(m2, churn)
  churn = N.move(m2, churn, "down") || churn
  churn = N.move(m2, churn, "up") || churn
}
assert.ok(Object.keys(churn.cols).length <= 2, "only the rows on the screen: " + Object.keys(churn.cols).length)

// one response that inserts, removes and reorders: the nearest survivor
// below in the old order
const agl = { kind: "screen", value: { rows: ["a", "g", "l"].map(id => ({ id, title: id, layout: "row", items: [item(id + "1")] })) } }
const aglM = L.model(agl, env(600))
const onG = N.normalize(aglM, { row: "g", item: "g1" })
const xal = { kind: "screen", value: { rows: ["x", "a", "l"].map(id => ({ id, title: id, layout: "row", items: [item(id + "1")] })) } }
assert.equal(N.current(L.model(xal, env(600)), N.normalize(L.model(xal, env(600)), onG, aglM)).line.id, "l", "g gone, x inserted, a moved: l, which was below g")

// a row id like __proto__ is just a row
const proto = { kind: "screen", value: { rows: [{ id: "__proto__", title: "X", layout: "row", items: [item("x1"), item("x2")] }] }, sel: null }
const pm = L.model(proto, env(600, { "r:__proto__": "poster" }))
assert.equal(N.lines(pm)[0].shape, "poster")
proto.sel = N.move(pm, proto.sel, "right")
assert.equal(proto.sel.row, "__proto__")
assert.equal(N.current(pm, proto.sel).thing.id, "x2")

// ---- milestone 2: a hero row and a look change ---------------------------
{
  // a hero: one item at a time; ← and → change items, ↑ and ↓ leave it
  const hv = { kind: "screen", value: { rows: [
    { id: "hero", title: "Featured", layout: "hero", items: [item("h1"), item("h2"), item("h3")] },
    { id: "r", title: "R", layout: "row", items: [item("r1"), item("r2")] }] }, sel: null }
  const hm = L.model(hv, env(1280))
  assert.deepEqual(N.lines(hm).map(l => l.layout), ["hero", "row"])
  const mv = key => { const s = N.move(hm, hv.sel, key); if (s) hv.sel = s; return s }
  assert.equal(mv("left"), null, "at its first item: the rail")
  mv("right"); mv("right")
  assert.equal(N.current(hm, hv.sel).thing.id, "h3")
  assert.equal(mv("right"), null, "at its last item")
  mv("down")
  assert.equal(N.current(hm, hv.sel).thing.id, "r1")
  mv("up")
  assert.equal(N.current(hm, hv.sel).thing.id, "h3", "back to the item it showed")
  assert.deepEqual(N.enter(hv, hm), { method: "browse", args: { item: "h3" } }, "Enter opens it")
  // a look change re-draws in place: the same row and item are selected
  const lv = { kind: "screen", value: { rows: [
    { id: "a", title: "A", layout: "row", items: [1, 2, 3, 4].map(i => Object.assign(item("a" + i), { images: { poster: { token: "p" + i }, wide: { token: "w" + i } } })) },
    { id: "b", title: "B", layout: "grid", items: [1, 2, 3, 4, 5, 6, 7, 8].map(i => item("b" + i)) }] }, sel: null }
  const before = L.model(lv, Object.assign(env(1280), { suggested: "cinematic" }))
  lv.sel = N.normalize(before, { row: "b", item: "b6" })
  const after = L.model(lv, Object.assign(env(1280), { suggested: "wall" }))
  assert.notEqual(before.lines[0].shape, after.lines[0].shape, "the look changed the row's shape")
  assert.equal(N.current(after, N.normalize(after, lv.sel, before)).thing.id, "b6", "the selection stays on its item")
}

console.log("appnav: all passed")

// api 4: a table moves like a list (up and down within it, no left or
// right); a ticker is one stop, Enter and I do nothing on it; a page has no
// lines (its arrows scroll it, in AppView) and goes on the stack
{
  const tv = { kind: "screen", value: { title: "T", rows: [
    { id: "news", title: "News", layout: "ticker", items: [item("n1"), item("n2"), item("n3")] },
    { id: "st", title: "Standings", layout: "table", columns: [{ label: "#", align: "end" }, { label: "Team", align: "start" }],
      items: [{ id: "t1", title: "A", kind: "info", cells: ["1", "A"] }, { id: "t2", title: "B", kind: "info", cells: ["2", "B"] }] },
    { id: "after", title: "After", layout: "row", items: [item("x1")] },
  ] }, item: "", sel: null }
  const tm = L.model(tv, env(600))
  let sel = null
  const go = key => { const s = N.move(tm, sel, key); if (s) sel = s; return s }
  const at = () => N.current(tm, sel).thing.id
  assert.equal(at(), "n1", "the ticker first")
  assert.equal(go("right"), null, "a ticker is one stop")
  assert.equal(go("left"), null)
  assert.equal(N.enter({ sel }, tm), null, "its items are text: Enter does nothing")
  assert.equal(N.details({ sel }, tm), null)
  go("down")
  assert.equal(at(), "t1", "into the table")
  assert.equal(go("right"), null, "a table has no left or right")
  go("down")
  assert.equal(at(), "t2", "down within it")
  assert.deepEqual(N.enter({ sel }, tm), { method: "details", args: { item: "t2" } })
  go("down")
  assert.equal(at(), "x1")
  go("up")
  assert.equal(at(), "t2", "coming up from below: its last line")
  go("up"); go("up")
  assert.equal(at(), "n1", "and back to the ticker")
  // a ticker remembered at a column it doesn't have: still its one stop
  const s2 = N.normalize(tm, { row: "news", item: "n3", line: 0, col: 2, cols: {} })
  assert.equal(N.current(tm, s2).thing.id, "n3")
  assert.equal(N.placement("browse", "page"), "push", "a page goes on the stack")
  assert.deepEqual(N.lines(L.model({ kind: "page", value: { title: "A", sections: [] } }, env(600))), [], "and has no lines")
}
console.log("appnav: api 4 all passed")
