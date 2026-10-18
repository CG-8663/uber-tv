.pragma library

// Moving around an app's screens: what the arrows select, what Enter and I
// ask the app for, and keeping your place when a screen comes back new.
// A view is { kind: "screen"|"detail"|"page", value (the normalized block),
// item (the id that opened it), sel }. Its lines come from the presentation
// model (AppLooks.js): a screen's rows, or a detail's actions then its rows,
// each with its own layout and, for a grid, its own columns.
//
// The selection is kept by ids: { row, item, line, col, cols }. row is the
// line's row id ("" for a detail's actions), item the item's (or action's)
// id; line and col say where it was, for when those have gone; cols holds
// the column last used in each row ("r:<row id>"). Kept apart from the QML
// so it can be tested on its own (tests/appnav.test.mjs).

function lines(model) { return model && model.lines ? model.lines.slice() : [] }

function rowOf(line) { return line.kind === "actions" ? "" : line.id }

// a ticker is one stop for the cursor, whatever it holds (api 4); a table
// moves like a list
function stops(line) { return line.layout === "ticker" ? 1 : line.items.length }
function vertical(line) { return line.layout === "list" || line.layout === "table" }

function clampCol(line, c) { return Math.max(0, Math.min(stops(line) - 1, c || 0)) }

// The selection on line, col. Remembered columns are kept only for rows in
// these lines, so an app sending new row ids can't grow them for ever.
function make(ls, line, col, cols) {
  var copy = {}
  if (cols) for (var i = 0; i < ls.length; i++) {
    var k = "r:" + rowOf(ls[i])
    if (Object.prototype.hasOwnProperty.call(cols, k)) copy[k] = cols[k]
  }
  return { row: rowOf(ls[line]), item: ls[line].items[col].id, line: line, col: col, cols: copy }
}

function rowIndex(ls, id) {
  for (var i = 0; i < ls.length; i++) if (rowOf(ls[i]) === id) return i
  return -1
}

function itemIndex(line, id) {
  for (var j = 0; j < line.items.length; j++) if (line.items[j].id === id) return j
  return -1
}

// Where the selection is in these lines, by its ids. If its item has gone,
// the nearest one left in the same row: with oldLs (the lines it was chosen
// in), the first still here after it in the old order, else before it;
// without, the one now in its place. If its row has gone, the nearest row
// still here: below it in the old order, else above; without oldLs, the row
// now in its place, or the last.
function locate(ls, sel, oldLs) {
  if (!ls.length || !sel) return { line: 0, col: 0 }
  if (sel.row !== undefined) {
    var i = rowIndex(ls, sel.row)
    var o = oldLs ? rowIndex(oldLs, sel.row) : -1
    if (i >= 0) {
      var j = itemIndex(ls[i], sel.item)
      if (j >= 0) return { line: i, col: j }
      if (o >= 0) {
        var was = itemIndex(oldLs[o], sel.item)
        if (was >= 0) {
          for (var a = was + 1; a < oldLs[o].items.length; a++) { var k = itemIndex(ls[i], oldLs[o].items[a].id); if (k >= 0) return { line: i, col: k } }
          for (var b = was - 1; b >= 0; b--) { var k2 = itemIndex(ls[i], oldLs[o].items[b].id); if (k2 >= 0) return { line: i, col: k2 } }
        }
      }
      return { line: i, col: clampCol(ls[i], sel.col) }
    }
    if (o >= 0) {
      var to = -1
      for (var d = o + 1; d < oldLs.length && to < 0; d++) to = rowIndex(ls, rowOf(oldLs[d]))
      for (var u = o - 1; u >= 0 && to < 0; u--) to = rowIndex(ls, rowOf(oldLs[u]))
      if (to >= 0) {
        var c = remembered(sel.cols, ls[to])
        return { line: to, col: clampCol(ls[to], c !== undefined ? c : sel.col) }
      }
    }
  }
  var line = Math.max(0, Math.min(ls.length - 1, sel.line || 0))
  return { line: line, col: clampCol(ls[line], sel.col) }
}

// The selection made to name what it's on now (after its item or row went);
// oldModel, the model it was chosen in, finds the nearest survivor
function normalize(model, sel, oldModel) {
  var ls = lines(model)
  if (!ls.length) return sel || null
  var at = locate(ls, sel, oldModel ? lines(oldModel) : null)
  return make(ls, at.line, at.col, sel && sel.cols)
}

function remembered(cols, line) {
  var k = "r:" + rowOf(line)
  return cols && Object.prototype.hasOwnProperty.call(cols, k) ? cols[k] : undefined
}

// Into another line: where you were in it before; else, coming up from
// below, a list's last item or a grid's last line; else its first
function toLine(ls, target, cols, fromBelow) {
  var line = ls[target]
  var n = stops(line)
  var col = remembered(cols, line)
  if (fromBelow && vertical(line)) col = n - 1
  else if (col === undefined) col = fromBelow && line.layout === "grid" ? Math.floor((n - 1) / Math.max(1, line.cols)) * Math.max(1, line.cols) : 0
  return make(ls, target, Math.min(n - 1, col), cols)
}

// The selection after an arrow (key: left, right, up, down), or null when
// it can't move that way (left at the start: the rail opens)
function move(model, sel, key) {
  var ls = lines(model)
  if (!ls.length) return null
  var at = locate(ls, sel)
  var line = ls[at.line]
  var n = stops(line)
  var lay = vertical(line) ? "list" : line.layout
  var c = lay === "grid" ? Math.max(1, line.cols || 1) : 1
  var prev = sel && sel.cols ? sel.cols : {}
  var cols = {}
  for (var k in prev) cols[k] = prev[k]
  cols["r:" + rowOf(line)] = at.col
  if (key === "left") {
    if (lay === "list") return null
    if (lay === "grid" ? at.col % c === 0 : at.col === 0) return null
    return make(ls, at.line, at.col - 1, prev)
  }
  if (key === "right") {
    if (lay === "list") return null
    if (lay === "grid" && at.col % c === c - 1) return null
    if (at.col + 1 >= n) return null
    return make(ls, at.line, at.col + 1, prev)
  }
  if (key === "up") {
    if (lay === "list" && at.col > 0) return make(ls, at.line, at.col - 1, prev)
    if (lay === "grid" && at.col >= c) return make(ls, at.line, at.col - c, prev)
    if (at.line === 0) return null
    return toLine(ls, at.line - 1, cols, true)
  }
  if (key === "down") {
    if (lay === "list" && at.col < n - 1) return make(ls, at.line, at.col + 1, prev)
    if (lay === "grid" && Math.floor(at.col / c) < Math.floor((n - 1) / c)) return make(ls, at.line, Math.min(n - 1, at.col + c), prev)
    if (at.line >= ls.length - 1) return null
    return toLine(ls, at.line + 1, cols, false)
  }
  return null
}

// What the cursor is on: { line, thing, at } (thing: an item or an action)
function current(model, sel) {
  var ls = lines(model)
  if (!ls.length) return null
  var at = locate(ls, sel)
  return { line: ls[at.line], thing: ls[at.line].items[at.col], at: at }
}

// What Enter asks the app: { method, args }, or null
function enter(view, model) {
  var c = current(model, view ? view.sel : null)
  if (!c) return null
  if (c.line.kind === "actions") {
    if (c.thing.kind === "play") return { method: "play", args: { item: c.thing.id } }
    return { method: "action", args: { item: view.item || "", action: c.thing.id } }
  }
  if (c.line.layout === "ticker") return null   // its items are text
  var it = c.thing
  if (it.kind === "play") return { method: "play", args: { item: it.id } }
  if (it.kind === "info") return { method: "details", args: { item: it.id } }
  return { method: "browse", args: { item: it.id } }
}

// What I asks the app: an item's details
function details(view, model) {
  var c = current(model, view ? view.sel : null)
  if (!c || c.line.kind !== "row" || c.line.layout === "ticker") return null
  return { method: "details", args: { item: c.thing.id } }
}

// Where an answer goes: a new view on the stack, or a message over the one
// that's there
function placement(method, kind) {
  if (kind === "message") return "message"
  if (kind === "screen" || kind === "detail" || kind === "page") return "push"
  if (kind === "play") return "play"
  return "none"
}
