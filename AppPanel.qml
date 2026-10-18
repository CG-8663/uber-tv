import QtQuick
import "AppLooks.js" as Looks

// Customize an app's screen (C on it, or Options on the phone), or every
// app's (Settings → Apps → How apps look): TV-style rows, like Customize
// Home.
//   LOOK: the look, the top of the screen, the background and how dark,
//     the details page, the titles under cards, the card size; each with
//     "As the look", and "As for all apps" (one app) or "As the theme"
//     (all apps) for leaving it to the layer below.
//   ROWS (one app): the rows its app.json names, then others seen on its
//     screens (kept in memory only, the 40 most recent, for that install's
//     one run: cleared when the app starts again or is installed again, not
//     when you leave its screen); a hidden one stays listed. A row's options: shown, your
//     name for it, its pictures, size, layout (a hero only where the app made
//     one), titles, and moving it up or down.
//   Follow all apps' settings: this app's choices go.
// Each change is saved as it's made, through AppScreens (confirmed, and the
// panel says "Saving…" and then how it went); the screen behind changes at
// once and keeps its selection. The panel is bound to the app it opened for
// (its source, id, incarnation, runtime and generation): it closes, saying
// why, if the app is removed, replaced, changes source, restarts or stops,
// and takes no change while the app is being changed.
Item {
  id: panel

  required property var guide
  readonly property var view: guide.appView
  readonly property var store: guide.appScreens
  readonly property var apps: guide.apps

  property bool open: false
  property string mode: "app"         // "app" (one app's screen) or "all" (every app's)
  property var bound: null            // one app: { source, id, incarnation, rt, gen }
  property int cursor: 1
  property string rowOpen: ""         // a row's options: its id
  property bool renaming: false
  property string note: ""            // the last change: Saving…, saved, or why not
  property string token: ""           // its saving token
  // each time it opens is a session of its own; a picture you pick is for
  // the session (and app or all apps) that asked, and only the latest one,
  // and only while nothing else has changed that layer's background since
  // (yours here, a command's, a reset; its darkness alone aside: it lands
  // with the new darkness)
  property int session: 0
  property int pickSeq: 0
  property var pickReq: null
  // rows seen on an app's screens: "<source>\n<id>" -> { id, incarnation,
  // gen, rows: [{ id, title }] }, the 40 most recent, for that install and
  // that run (generation) of it only
  property var seen: ({})

  readonly property var app: panel.bound ? panel.apps.record(panel.bound.id) : null
  readonly property string key: panel.mode === "all" ? "all" : panel.store && panel.app ? panel.store.keyOf(panel.app) : ""
  // what's chosen at this layer now (yours for this app, or for all apps)
  readonly property var mine: {
    if (!panel.store) return ({})
    if (panel.mode === "all") return panel.store.now.all || ({})
    return panel.app ? panel.store.entryOf(panel.app) || ({}) : ({})
  }

  // What this layer's choices give now: for one app, its screen after yours,
  // all apps', the theme's and its own suggestion (whether or not it's on the
  // screen); for all apps, what the theme gives (each app's suggestion comes
  // after it, so an unset look reads "as each app suggests")
  readonly property var themeApps: panel.guide.currentTheme && panel.guide.currentTheme.apps ? panel.guide.currentTheme.apps : ({})
  readonly property var result: {
    var th = panel.themeApps
    if (panel.mode === "all") return Looks.screenOf({ theme: th }, Looks.lookOf({ theme: th }, "").look)
    var c = { mine: panel.mine, all: panel.store ? panel.store.now.all || ({}) : ({}), theme: th }
    return Looks.screenOf(c, Looks.lookOf(c, panel.app && panel.app.layout ? panel.app.layout.look || "" : "").look)
  }
  // how dark this layer's background is now
  function dimNow() {
    var b = panel.mine.background
    return b && typeof b === "object" && typeof b.dim === "number" ? b.dim : panel.result.background.dim
  }

  // ---- the values each row cycles through ("" leaves it to the layer below) ----
  readonly property var looks: ["app", "classic", "posters", "cinematic", "wall", "compact", ""]
  readonly property var tops: ["selected", "off", "look", ""]
  readonly property var details: ["classic", "cinematic", "app", "look", ""]
  readonly property var titleModes: ["below", "selected", "off", "look", ""]
  readonly property var sizes: ["small", "medium", "large", "look", ""]
  readonly property var backgrounds: {
    var b = ["focus", "details", "guide", "wallpaper"]
    var bg = panel.mine.background
    if (bg && typeof bg === "object" && bg.mode === "image") b.push("image")
    return b.concat(["none", "look", ""])
  }
  readonly property var rowShapes: ["", "poster", "wide", "square", "logo", "circle"]
  readonly property var rowSizes: ["", "small", "medium", "large"]
  readonly property var rowTitles: ["", "below", "selected", "off"]

  function below() { return panel.mode === "all" ? "As the theme" : "As for all apps" }
  function label(kind, v) {
    if (v === "" || v === undefined) return panel.below()
    if (v === "look") return "As the look"
    var t = {
      look: { app: "As the app suggests", classic: "Classic", posters: "Posters", cinematic: "Cinematic", wall: "Wall", compact: "Compact" },
      top: { selected: "What's selected", off: "Off" },
      details: { classic: "Classic", cinematic: "Cinematic", app: "As the app says" },
      titles: { below: "Every card", selected: "Selected only", off: "Off" },
      size: { small: "Small", medium: "Medium", large: "Large" },
      background: { focus: "What's selected", details: "Details only", guide: "Guide's", wallpaper: "Wallpaper", image: "A picture", none: "None" }
    }[kind]
    return t && t[v] ? t[v] : String(v)
  }
  // what a row of the panel shows: the choice here, and (left to the layer
  // below) what that gives now
  function shown(kind) {
    var v = kind === "background" ? (panel.mine.background ? (panel.mine.background === "look" ? "look" : panel.mine.background.mode) : "") : panel.mine[kind]
    var here = panel.label(kind, v === undefined ? "" : v)
    if (v !== undefined && v !== "") return here
    var m = panel.result
    if (panel.mode === "all" && kind === "look" && !(typeof panel.themeApps.look === "string" && panel.themeApps.look !== "look" && panel.themeApps.look !== "app"))
      return here + " (as each app suggests)"
    var now = kind === "look" ? m.look : kind === "background" ? m.background.mode : m[kind]
    if (now === "app") return here + " (" + (panel.mode === "all" ? "as each app says" : "as the app says") + ")"
    return here + " (" + panel.label(kind, now) + ")"
  }

  // ---- the rows of the panel ----------------------------------------------------
  readonly property var rows: {
    if (!panel.open) return []
    if (panel.rowOpen !== "") {
      var r = panel.rowInfo(panel.rowOpen)
      var opts = [{ type: "header", label: (r ? r.title : panel.rowOpen).toUpperCase() }, { type: "rowShow" }, { type: "rowName" },
                  { type: "rowShape" }, { type: "rowSize" }, { type: "rowLayout" }, { type: "rowTitles" }, { type: "rowUp" }, { type: "rowDown" }]
      return opts
    }
    var out = [{ type: "header", label: "LOOK" }, { type: "look" }, { type: "top" }, { type: "background" }, { type: "bgPick" }, { type: "dim" },
               { type: "details" }, { type: "titles" }, { type: "size" }]
    if (panel.mode === "app") {
      var list = panel.rowList()
      if (list.length) out.push({ type: "header", label: "ROWS" })
      list.forEach(function(x) { out.push({ type: "row", id: x.id, label: x.title }) })
      out.push({ type: "header", label: "" })
      out.push({ type: "follow" })
    } else {
      out.push({ type: "header", label: "" })
      out.push({ type: "follow" })
    }
    return out
  }

  // The rows it lists: app.json's, then others seen, in your order first
  function rowList() {
    var a = panel.app
    if (!a) return []
    var out = []
    var seen = Object.create(null)
    ;((a.layout && a.layout.rows) || []).forEach(function(r) { if (!seen["r:" + r.id]) { seen["r:" + r.id] = true; out.push({ id: r.id, title: r.label || r.id }) } })
    panel.seenRows(a).forEach(function(r) { if (!seen["r:" + r.id]) { seen["r:" + r.id] = true; out.push({ id: r.id, title: r.title || r.id }) } })
    return Looks.arranged(out, panel.mine)
  }
  function rowInfo(id) { var l = panel.rowList(); for (var i = 0; i < l.length; i++) if (l[i].id === id) return l[i]; return null }
  function rowChoice(id) { var rows = panel.mine.rows; return rows && Object.prototype.hasOwnProperty.call(rows, "r:" + id) ? rows["r:" + id] : ({}) }
  // A row's summary in the list: hidden, or its pictures and size
  function rowSummary(id) {
    var c = panel.rowChoice(id)
    if (c.show === false) return "Hidden"
    var bits = []
    if (c.shape) bits.push({ poster: "Posters", wide: "Wide", square: "Square", logo: "Logos", circle: "Round" }[c.shape])
    if (c.size) bits.push(panel.label("size", c.size))
    if (c.layout) bits.push({ row: "Row", grid: "Grid", list: "List", hero: "Hero" }[c.layout])
    if (c.name) bits.push("“" + c.name + "”")
    return bits.length ? bits.join(" · ") : "As the app says"
  }
  // the app made this row a hero (its hint or app.json): only then can it be
  // one. Its hints count only from its own screen: the view showing the very
  // install and run the panel is bound to (away from it, app.json alone)
  function appHero(id) {
    var a = panel.app
    var d = ((a && a.layout && a.layout.rows) || []).filter(function(r) { return r.id === id })[0]
    if (d && d.layout === "hero") return true
    if (!panel.viewIsBound()) return false
    var top = panel.view.topView
    return !!(top && top.value && (top.value.rows || []).some(function(r) { return r.id === id && r.layout === "hero" }))
  }
  function viewIsBound() {
    var b = panel.bound
    var v = panel.view
    var r = v ? v.record : null
    return !!(panel.mode === "app" && b && b.rt && v.rt === b.rt && b.rt.gen === b.gen && v.appId === b.id
              && r && (r.source || "") === b.source && r.incarnation === b.incarnation)
  }

  // ---- opening and closing -------------------------------------------------------
  function openFor(appId, by) {
    if (by !== panel.guide.byUser) return "only the user, at the screen"
    var a = panel.apps.record(appId)
    if (!a || a.kind !== "app") return "it isn't an app with code"
    if (!a.incarnation) return "it isn't ready to customize yet" + (panel.apps.incarnationProblem ? " (its record couldn't be saved: " + panel.apps.incarnationProblem + "; tried again shortly)" : "")
    var rt = panel.view.appId === appId ? panel.view.rt : null
    panel.bound = { source: a.source || "", id: a.id, incarnation: a.incarnation, rt: rt, gen: rt ? rt.gen : 0 }
    panel.mode = "app"
    panel.start()
    return "ok"
  }
  function openAll(by) {
    if (by !== panel.guide.byUser) return "only the user, at the screen"
    panel.bound = null
    panel.mode = "all"
    panel.start()
    return "ok"
  }
  function start() {
    panel.session += 1
    panel.pickReq = null
    if (panel.view && panel.view.userActs) panel.view.userActs()   // you opening Customize ends an agent's open
    panel.rowOpen = ""
    panel.renaming = false
    panel.note = ""
    panel.token = ""
    panel.cursor = 1
    panel.open = true
  }
  // Esc: out of renaming, a row's options, then the panel
  function close() {
    if (panel.renaming) { panel.renaming = false; return }
    if (panel.rowOpen !== "") { var id = panel.rowOpen; panel.rowOpen = ""; panel.cursor = panel.indexOf("row", id); return }
    panel.open = false
  }
  function closeWith(why) {
    panel.open = false
    panel.renaming = false
    panel.rowOpen = ""
    if (why && panel.view) { panel.view.message = why; panel.view.messageBad = true }
  }
  function indexOf(type, id) {
    var r = panel.rows
    for (var i = 0; i < r.length; i++) if (r[i].type === type && (id === undefined || r[i].id === id)) return i
    return 1
  }

  // the app it's bound to is still the one it opened for, untouched
  function stillBound() {
    if (panel.mode === "all") return ""
    var b = panel.bound
    var a = b ? panel.apps.record(b.id) : null
    if (!a) return "it was removed"
    if ((a.source || "") !== b.source) return "it was installed again from somewhere else"
    if (a.incarnation !== b.incarnation) return "it was installed again"
    if (b.rt && (panel.view.rt !== b.rt || b.rt.phase === "stopped" || b.rt.gen !== b.gen)) return "it started again"
    return ""
  }
  function check() {
    if (!panel.open || panel.mode === "all") return
    var why = panel.stillBound()
    if (why) panel.closeWith("Customize closed: " + (panel.app ? panel.app.name : "the app") + " " + why + ".")
  }
  Connections {
    target: panel.apps
    function onInstalledChanged() { panel.check(); panel.forgetSeen() }
    function onRuntimesChanged() { panel.forgetSeen() }
  }
  Connections {
    target: panel.view
    function onRtChanged() { panel.check() }
  }

  // ---- moving and changing ---------------------------------------------------------
  function move(d) {
    var r = panel.rows
    var n = r.length
    if (!n) return
    var c = panel.cursor
    do { c = (c + d + n) % n } while (r[c].type === "header")
    panel.cursor = c
  }

  // A change to this layer's choices, saved as it's made
  function change(what, fn) {
    var why = panel.stillBound()
    if (why) { panel.closeWith("Customize closed: " + (panel.app ? panel.app.name : "the app") + " " + why + "."); return false }
    if (panel.mode === "app" && panel.apps.changing && panel.apps.changing[panel.bound.id]) { panel.note = "It's being changed: try again in a moment."; return false }
    var k = panel.key
    var a = panel.app
    var res = panel.store.change(k, function(st) {
      if (k === "all") { fn(st.all); return }
      var e = st.apps[k] || { incarnation: a.incarnation }
      fn(e)
      st.apps[k] = e
    }, "panel", (k === "all" ? "all apps" : a.id) + ": " + what)
    if (!res.ok) { panel.note = "Not saved: " + res.error + "."; return false }
    panel.token = res.token
    panel.note = "Saving…"
    return true
  }
  // how the last change went, once it's known
  readonly property var outcome: {
    if (!panel.token || !panel.store) return null
    var items = panel.store.saving.items
    for (var i = 0; i < items.length; i++) if (items[i].token === panel.token) return items[i]
    return null
  }
  onOutcomeChanged: {
    if (!panel.outcome) return
    var o = panel.outcome.outcome
    panel.note = o === "pending" ? "Saving…" : o === "saved" ? "Saved." : o === "unconfirmed" ? "Saved (not yet confirmed by the disk)." : "Not saved: " + (panel.outcome.why || "it couldn't be saved") + "."
  }

  function cycle(list, v, d) {
    var i = list.indexOf(v === undefined ? "" : v)
    if (i < 0) i = list.length - 1
    return list[(i + (d >= 0 ? 1 : -1) + list.length) % list.length]
  }
  function setKey(k, v) { panel.change(k, function(e) { if (v === "" || v === undefined) delete e[k]; else e[k] = v }) }

  // ←/→ (d -1 or 1) or Enter (0) on the row under the cursor
  function act(d) {
    var r = panel.rows[panel.cursor]
    if (!r) return
    var step = d === 0 ? 1 : d
    var t = r.type
    if (t === "look" || t === "top" || t === "details" || t === "titles" || t === "size") {
      var list = t === "look" ? panel.looks : t === "top" ? panel.tops : t === "details" ? panel.details : t === "titles" ? panel.titleModes : panel.sizes
      panel.setKey(t, panel.cycle(list, panel.mine[t], step))
    } else if (t === "background") {
      panel.dropPick(panel.key)
      var bg = panel.mine.background
      var cur = bg === "look" ? "look" : bg && bg.mode ? bg.mode : ""
      var next = panel.cycle(panel.backgrounds, cur, step)
      panel.change("background", function(e) {
        if (next === "") delete e.background
        else if (next === "look") e.background = "look"
        else { var b = { mode: next }; if (bg && typeof bg === "object" && bg.dim !== undefined) b.dim = bg.dim; if (next === "image" && bg && bg.image) b.image = bg.image; e.background = b }
      })
    } else if (t === "dim") {
      // how dark: this layer's background, in 5% steps (it takes the background
      // shown now if this layer sets none)
      var b0 = panel.mine.background
      var m = panel.result.background
      var base = b0 && typeof b0 === "object" ? b0 : { mode: m.mode === "image" ? "none" : m.mode, dim: m.dim }
      var dim = Math.round(Math.max(0, Math.min(0.95, (typeof base.dim === "number" ? base.dim : Looks.DIM) + 0.05 * step)) * 100) / 100
      panel.change("darken", function(e) { var b = { mode: base.mode, dim: dim }; if (base.image) b.image = base.image; e.background = b })
      if (panel.pickReq) panel.pickReq.bg = panel.bgSig()   // the darkness alone: a picture on its way lands with it
    } else if (t === "bgPick") {
      // a picture of yours: the file picker, then the helper checks it and
      // copies it in (only the copy is shown); setPicture takes it from there
      if (d === 0 || d > 0) {
        panel.pickSeq += 1
        panel.pickReq = { seq: panel.pickSeq, session: panel.session, mode: panel.mode, key: panel.key, bg: panel.bgSig() }
        panel.guide.openPicker(true, "appScreen")
      }
    } else if (t === "follow") {
      panel.dropPick(panel.key)
      panel.change("follow all apps' settings", function(e) { for (var key in e) if (key !== "incarnation") delete e[key] })
    } else if (t === "row") {
      if (d === 0 || d > 0) { panel.rowOpen = r.id; panel.cursor = 1 }
    } else if (t === "rowShow") {
      panel.setRow("show", panel.rowChoice(panel.rowOpen).show === false ? undefined : false)
    } else if (t === "rowName") {
      panel.renaming = true
    } else if (t === "rowShape") {
      panel.setRow("shape", panel.cycle(panel.rowShapes, panel.rowChoice(panel.rowOpen).shape, step))
    } else if (t === "rowSize") {
      panel.setRow("size", panel.cycle(panel.rowSizes, panel.rowChoice(panel.rowOpen).size, step))
    } else if (t === "rowLayout") {
      var layouts = ["", "row", "grid", "list"].concat(panel.appHero(panel.rowOpen) ? ["hero"] : [])
      panel.setRow("layout", panel.cycle(layouts, panel.rowChoice(panel.rowOpen).layout, step))
    } else if (t === "rowTitles") {
      panel.setRow("titles", panel.cycle(panel.rowTitles, panel.rowChoice(panel.rowOpen).titles, step))
    } else if (t === "rowUp" || t === "rowDown") {
      panel.moveRow(panel.rowOpen, t === "rowUp" ? -1 : 1)
    }
  }
  // the picture you picked, copied in: the background shows it (or why not)
  function setPicture(res, req) {
    // only for the panel that asked, still open on the same app (or all
    // apps), and only the latest pick: a late one never lands elsewhere
    var r = panel.pickReq
    if (!panel.open || !req || req !== r || req.session !== panel.session || req.mode !== panel.mode || req.key !== panel.key) return
    panel.pickReq = null
    if (panel.bgSig() !== req.bg) { panel.note = "Not used: the background was changed meanwhile."; return }
    if (!res || !res.ok) { panel.note = "Not used: " + (res && res.error ? res.error : "it couldn't be copied") + "."; return }
    if (!panel.store.pictureOk(res.path)) { panel.note = "Not used: it isn't one of the guide's copies."; return }
    var bg = panel.mine.background
    var dim = bg && typeof bg === "object" && typeof bg.dim === "number" ? bg.dim : panel.dimNow()
    panel.change("a background picture", function(e) { e.background = { mode: "image", image: res.path, dim: dim } })
  }
  // a picture still being copied for that layer (all, or an app's key) no
  // longer lands: its background was changed since it was picked
  function dropPick(key) { if (panel.pickReq && panel.pickReq.key === key) panel.pickReq = null }
  // this layer's background, but for its darkness
  function bgSig() {
    var b = panel.mine.background
    return b === "look" ? "look" : b && typeof b === "object" ? String(b.mode) + "\n" + String(b.image || "") : ""
  }
  function setRow(k, v) {
    var id = panel.rowOpen
    panel.change("a row's " + k, function(e) {
      var rows = Object.create(null)
      for (var x in (e.rows || {})) rows[x] = e.rows[x]
      var c = {}
      var old = rows["r:" + id] || {}
      for (var y in old) c[y] = old[y]
      if (v === "" || v === undefined) delete c[k]; else c[k] = v
      if (Object.keys(c).length) rows["r:" + id] = c; else delete rows["r:" + id]
      if (Object.keys(rows).length) e.rows = rows; else delete e.rows
    })
  }
  // your name for a row (empty: its own)
  function rename(text) {
    panel.renaming = false
    panel.setRow("name", Looks.plainName(String(text || "")))
  }
  // moving a row: the whole listed order becomes yours
  function moveRow(id, d) {
    var ids = panel.rowList().map(function(x) { return x.id })
    var i = ids.indexOf(id)
    var j = i + d
    if (i < 0 || j < 0 || j >= ids.length) return
    var t = ids[i]; ids[i] = ids[j]; ids[j] = t
    panel.change("the rows' order", function(e) { e.order = ids })   // past 40, refused (the note says so)
  }

  // ---- rows seen on its screens ------------------------------------------------------
  // the rows seen for this install of the app (none for another install)
  function seenRows(a) {
    var s = a && panel.store ? panel.seen[panel.store.keyOf(a)] : null
    return s && s.id === a.id && s.incarnation === a.incarnation ? s.rows : []
  }
  // what its screen shows now, noted for its install and run: another run's
  // or install's rows don't carry over
  function noteRows() {
    var a = panel.view.record
    var rt = panel.view.rt
    var top = panel.view.topView
    if (!a || !rt || !a.incarnation || !top || !top.value || !panel.store) return
    var k = panel.store.keyOf(a)
    var had = panel.seen[k]
    var now = had && had.id === a.id && had.incarnation === a.incarnation && had.gen === rt.gen ? had.rows.slice() : []
    ;(top.value.rows || []).forEach(function(r) {
      if (!r || typeof r.id !== "string") return
      now = now.filter(function(x) { return x.id !== r.id })
      now.push({ id: r.id, title: Looks.plainName(String(r.title || "")) || r.id })
    })
    var next = {}
    for (var x in panel.seen) next[x] = panel.seen[x]
    next[k] = { id: a.id, incarnation: a.incarnation, gen: rt.gen, rows: now.slice(-40) }
    panel.seen = next
  }
  // what was seen for an install that's gone or replaced, or for a run
  // that isn't the app's now (it started again), goes; an app that's only
  // stopped, or whose screen you left, keeps its own
  function forgetSeen() {
    if (!panel.store) return
    var next = {}
    var gone = false
    for (var k in panel.seen) {
      var s = panel.seen[k]
      var a = panel.apps.record(s.id)
      var rt = panel.apps.runtime ? panel.apps.runtime(s.id) : null
      if (!a || panel.store.keyOf(a) !== k || a.incarnation !== s.incarnation || (rt && rt.gen !== s.gen)) { gone = true; continue }
      next[k] = s
    }
    if (gone) panel.seen = next
  }
  Connections {
    target: panel.view
    function onTopViewChanged() { panel.noteRows() }
  }
}
