import QtQuick
import "AppLooks.js" as Looks
import "AppNav.js" as Nav

// What AI agents may see of and do to apps' screens:
// the same choices the user has, through commands, and never anything
// an app sends while it runs.
//
// No id an app writes reaches an agent: rows and items are named by
// handles the guide makes. A row's handle ("r-" and 12 random hex digits)
// is kept per (source, app, incarnation, row id) while its entry is kept: at
// most 256 an app and 2,048 in all, the least recently used going first
// (being named in an answer or passed in a command is a use); an evicted
// one is stale, and the row gets a new one when it's next named. An item's
// handle ("i-" and 16) exists only for the view on the screen, at most 200,
// replaced when the view changes, and stops working on any mismatch of
// source, app, incarnation, generation, view or row. Handles aren't
// secrets: their job is to carry no app bytes and to fail when stale.
//
// Answers hold only what the guide owns (handles, positions, shapes,
// states) and text from reviewed bytes: a bundled app's name and its
// app.json row labels. A file app (nobody but you checked it) appears by its id only.
Item {
  id: agent

  required property var guide
  readonly property var apps: guide.apps
  readonly property var view: guide.appView
  readonly property var store: guide.appScreens

  readonly property int perApp: 256
  readonly property int total: 2048

  // row handles: handle -> { key, incarnation, row, used }; and back
  property var rowHandles: Object.create(null)
  property var rowByKey: Object.create(null)   // "<key>\n<incarnation>\n<row id>" -> handle
  property int clock: 0
  // item handles, for the view on the screen: handle -> { key, incarnation, gen, view, row, item, kind }
  property var itemHandles: Object.create(null)
  property string itemsFor: ""                 // the view id they were made for
  // the view on the screen, as an opaque id that changes on every new view
  property int viewSeq: 0
  property var viewOf: null
  readonly property string viewId: agent.view.topView && agent.viewOf === agent.view.topView ? "v-" + agent.viewSeq : ""
  Connections {
    target: agent.view
    function onTopViewChanged() { agent.viewSeq += 1; agent.viewOf = agent.view.topView; agent.itemHandles = Object.create(null); agent.itemsFor = "" }
  }

  function keyOf(a) { return (a.source || "") + "\n" + a.id }

  // ---- row handles -------------------------------------------------------------
  function newHandle(prefix, digits, taken) {
    for (var i = 0; i < 8; i++) {
      var h = prefix + agent.apps.randomHex(digits)
      if (h.length === prefix.length + digits && !taken[h]) return h
    }
    return ""
  }
  function rowHandle(a, rowId) {
    var k = agent.keyOf(a) + "\n" + a.incarnation + "\n" + rowId
    var h = agent.rowByKey[k]
    agent.clock += 1
    if (h && agent.rowHandles[h]) { agent.rowHandles[h].used = agent.clock; return h }
    h = agent.newHandle("r-", 12, agent.rowHandles)
    if (!h) return ""
    agent.rowHandles[h] = { key: agent.keyOf(a), incarnation: a.incarnation, row: rowId, used: agent.clock }
    agent.rowByKey[k] = h
    agent.evict(agent.keyOf(a))
    return h
  }
  // past 256 for the app or 2,048 in all, the least recently used go
  function evict(key) {
    var mine = []
    var all = []
    for (var h in agent.rowHandles) {
      var e = agent.rowHandles[h]
      all.push([e.used, h])
      if (e.key === key) mine.push([e.used, h])
    }
    var drop = function(list, keep) {
      if (list.length <= keep) return
      list.sort(function(x, y) { return x[0] - y[0] })
      list.slice(0, list.length - keep).forEach(function(x) {
        var e = agent.rowHandles[x[1]]
        if (!e) return
        delete agent.rowByKey[e.key + "\n" + e.incarnation + "\n" + e.row]
        delete agent.rowHandles[x[1]]
      })
    }
    drop(mine, agent.perApp)
    all = all.filter(function(x) { return !!agent.rowHandles[x[1]] })
    drop(all, agent.total)
  }
  // a handle back to its row id, for this app as installed now; "" if it's
  // stale, unknown, or another app's (a raw row id is just unknown)
  function rowOf(a, h) {
    var e = typeof h === "string" ? agent.rowHandles[h] : null
    if (!e || e.key !== agent.keyOf(a) || e.incarnation !== a.incarnation) return ""
    agent.clock += 1
    e.used = agent.clock
    return e.row
  }
  function rowCount(key) { var n = 0; for (var h in agent.rowHandles) if (agent.rowHandles[h].key === key) n++; return n }
  function handleCount() { return Object.keys(agent.rowHandles).length }

  // ---- what an app is, to an agent ------------------------------------------------
  function bundled(a) { return a.from === "bundled" }
  // its app.json row labels, only for a bundled app (reviewed bytes)
  function labelOf(a, rowId) {
    if (!agent.bundled(a)) return ""
    var r = ((a.layout && a.layout.rows) || []).filter(function(x) { return x.id === rowId })[0]
    return r ? r.label || "" : ""
  }
  // choices with rows and order by handle
  function byHandle(a, entry) {
    var out = {}
    for (var k in entry) {
      if (k === "incarnation") continue
      if (k === "rows") {
        var rows = {}
        for (var rk in entry.rows) { var h = agent.rowHandle(a, rk.slice(2)); if (h) rows[h] = entry.rows[rk] }
        out.rows = rows
      } else if (k === "order") out.order = entry.order.map(function(id) { return agent.rowHandle(a, id) }).filter(function(h) { return h })
      else out[k] = entry[k]
    }
    return out
  }
  // Why the app's screen isn't the uncovered top layer ("" if it is): the
  // guide open on it, nothing playing, and nothing of the guide's over it (a
  // box, the style panel, Customize, the rail, the app's own boxes, an app
  // coming up). appScreen's covered, and appSnapshot's check.
  function coverWhy() {
    var g = agent.guide
    var v = agent.view
    if (!g.opened) return "the guide isn't open"
    if (g.screen !== "app" || !v.shown) return "an app's screen isn't on"
    if (g.watching || g.vod || g.appPlaying || g.pip) return "something is playing"
    if (g.dialog) return "a box is open on the guide"
    if (g.appPanel && g.appPanel.open) return "Customize is open"
    if (g.railOpen || g.railEditing) return "the rail is open"
    if (v.settingsOpen || v.signIn !== null || v.editing !== null || v.certOffer !== null) return "an app's own box is open (its settings, signing in, typing or a certificate)"
    if (g.appOpening) return "an app is coming up"
    return ""
  }
  // and how often something has come over it
  readonly property string coverNow: agent.coverWhy()
  property int coverSeen: 0
  property string coverLast: ""
  onCoverNowChanged: if (agent.coverNow !== "") { agent.coverSeen += 1; agent.coverLast = agent.coverNow }
  function stateOf(a) {
    var shown = agent.view.shown && agent.view.appId === a.id
    if (!shown) return "elsewhere"
    var rt = agent.view.rt
    if (!rt || rt.phase === "starting" || rt.phase === "queued") return "starting"
    if (agent.view.failed) return "error"
    if (agent.view.loading) return "loading"
    return "ready"
  }
  function picturesPending() {
    var n = 0
    for (var t in agent.view.wanted) if (agent.view.imagePaths[t] === "" || agent.view.imagePaths[t] === undefined) n++
    return n
  }

  // appScreen <id|all>
  function appScreen(id) {
    if (id === "all") {
      var all = agent.store.now.all
      var theme = agent.guide.currentTheme && agent.guide.currentTheme.apps ? agent.guide.currentTheme.apps : {}
      var res = Looks.screenOf({ all: all, theme: theme }, Looks.lookOf({ all: all, theme: theme }, "").look)
      return { ok: true, id: "all", choices: JSON.parse(JSON.stringify(all)), theme: JSON.parse(JSON.stringify(theme)),
               result: { look: res.look, top: res.top, background: res.background, details: res.details, titles: res.titles, size: res.size, from: res.from },
               saving: agent.store.saving }
    }
    var a = agent.apps.record(id)
    if (!a || a.kind !== "app") return { ok: false, error: "no app with code " + id + " (apps lists them)" }
    if (!a.incarnation) return { ok: false, error: "it isn't ready yet: try again in a moment" }
    var onScreen = agent.view.shown && agent.view.appId === a.id
    var out = { ok: true, id: a.id, onScreen: onScreen, state: agent.stateOf(a), picturesPending: onScreen ? agent.picturesPending() : 0,
                covered: onScreen ? agent.coverWhy() !== "" : false, view: onScreen ? agent.viewId : "" }
    if (agent.bundled(a)) out.name = a.name
    var entry = agent.store.entryOf(a) || {}
    out.choices = agent.byHandle(a, entry)
    // the result after §3, and its rows in screen order
    var model = onScreen ? agent.view.model : Looks.model(null, { choices: { mine: entry, all: agent.store.now.all, theme: agent.guide.currentTheme ? agent.guide.currentTheme.apps || {} : {} },
                                                                     suggested: a.layout ? a.layout.look : "" })
    var sc = model.screen
    out.result = { look: sc.look, lookFrom: sc.lookFrom, top: sc.top, background: sc.background, details: sc.details, titles: sc.titles, size: sc.size, from: sc.from }
    var rows = []
    var seen = Object.create(null)
    if (onScreen && agent.view.topView && agent.view.topView.value) {
      var drawn = Object.create(null)
      model.lines.forEach(function(l) { if (l.kind === "row") drawn["r:" + l.id] = l })
      Looks.arranged(agent.view.topView.value.rows || [], entry).forEach(function(r, i) {
        if (!r || typeof r.id !== "string" || seen["r:" + r.id] || rows.length >= 30) return
        seen["r:" + r.id] = true
        var l = drawn["r:" + r.id]
        var row = { handle: agent.rowHandle(a, r.id), position: i, shown: !!l }
        var label = agent.labelOf(a, r.id)
        if (label) row.label = label
        if (l) { row.shape = l.shape; row.size = l.size; row.layout = l.layout; row.titles = l.titles
                 row.from = { shape: l.from, size: l.sizeFrom, layout: l.layoutFrom, titles: l.titlesFrom } }
        rows.push(row)
      })
    }
    out.rows = rows
    // rows the manifest names, rows seen, rows with choices and in your order: by handle
    var also = []
    var add = function(rid) { if (typeof rid !== "string" || seen["r:" + rid] || also.length >= 160) return; seen["r:" + rid] = true; var h = agent.rowHandle(a, rid); if (h) { var x = { handle: h }; var lb = agent.labelOf(a, rid); if (lb) x.label = lb; also.push(x) } }
    ;((a.layout && a.layout.rows) || []).forEach(function(r) { add(r.id) })
    ;(agent.guide.appPanel ? agent.guide.appPanel.seenRows(a) : []).forEach(function(r) { add(r.id) })
    for (var rk in (entry.rows || {})) add(rk.slice(2))
    ;(entry.order || []).forEach(add)
    out.otherRows = also
    // while it's the screen: its open and info items, by handle
    if (onScreen && agent.view.topView) {
      if (agent.itemsFor !== agent.viewId) agent.makeItems(a, model)
      var items = []
      for (var ih in agent.itemHandles) { var e2 = agent.itemHandles[ih]; items.push({ handle: ih, row: agent.rowHandle(a, e2.row), position: e2.position, kind: e2.kind }) }
      out.items = items
    }
    out.saving = agent.store.saving
    return out
  }

  function makeItems(a, model) {
    var hs = Object.create(null)
    var n = 0
    model.lines.forEach(function(l) {
      if (l.kind !== "row") return
      l.items.forEach(function(it, i) {
        if (n >= 200 || !it || (it.kind !== "open" && it.kind !== "info") || typeof it.id !== "string") return
        var h = agent.newHandle("i-", 16, hs)
        if (!h) return
        hs[h] = { key: agent.keyOf(a), incarnation: a.incarnation, gen: agent.view.rt ? agent.view.rt.gen : 0, view: agent.viewId, row: l.id, item: it.id, kind: it.kind, position: i }
        n++
      })
    })
    agent.itemHandles = hs
    agent.itemsFor = agent.viewId
  }
  // an item handle back to what it names, only for the view it was made for
  function itemOf(a, h) {
    var e = typeof h === "string" ? agent.itemHandles[h] : null
    if (!e || e.key !== agent.keyOf(a) || e.incarnation !== a.incarnation || e.view !== agent.viewId || agent.itemsFor !== agent.viewId) return null
    if ((agent.view.rt ? agent.view.rt.gen : 0) !== e.gen) return null
    return e
  }

  // ---- setAppScreen <id|all> '<json>' ------------------------------------------------
  // Changes the choices: screen keys (look, top, background, details, titles,
  // size; null takes one off), rows by handle (each { show, name, shape,
  // size, layout, titles }, null for a key takes it off; null for the row
  // takes all of it off) and order (a list of handles). Anything else, a raw
  // row id included, is ignored the same way whether or not such a row
  // exists. Answers what it will save, the result, what it ignored and why,
  // and its saving token.
  function setAppScreen(id, text) {
    // 64 KiB in UTF-8 bytes (a character can be up to four), counted before it's parsed
    if (typeof text !== "string" || text.length > 65536 || agent.store.bytes(text) > 65536) return { ok: false, error: "at most 64 KB of JSON" }
    var given
    try { given = JSON.parse(text) } catch (e) { return { ok: false, error: "not valid JSON: " + String(e.message).slice(0, 80) } }
    if (!given || typeof given !== "object" || Array.isArray(given)) return { ok: false, error: "an object: {look, top, background, details, titles, size, rows, order}" }
    var all = id === "all"
    var a = all ? null : agent.apps.record(id)
    if (!all && (!a || a.kind !== "app")) return { ok: false, error: "no app with code " + id + " (apps lists them)" }
    if (!all && !a.incarnation) return { ok: false, error: "it isn't ready yet: try again in a moment" }
    if (!all && agent.apps.changing && agent.apps.changing[a.id]) return { ok: false, error: "it's being changed: try again in a moment" }
    var ignored = []
    var screen = {}
    var unset = []
    var rows = Object.create(null)
    var rowUnset = []
    var order = null
    for (var k in given) {
      var v = given[k]
      if (["look", "top", "background", "details", "titles", "size"].indexOf(k) >= 0) { if (v === null) unset.push(k); else screen[k] = v }
      else if (k === "rows" && !all) {
        if (!v || typeof v !== "object" || Array.isArray(v)) { ignored.push("rows (an object: row handle to its choices)"); continue }
        for (var h in v) {
          var rid = agent.rowOf(a, h)
          if (!rid) { ignored.push("rows: a key that isn't a row handle (appScreen lists them)"); continue }
          if (v[h] === null) { rowUnset.push(rid); continue }
          var nulls = []
          var keep = {}
          for (var rk in v[h]) { if (v[h][rk] === null) nulls.push(rk); else keep[rk] = v[h][rk] }
          var c = Looks.checkRowChoices(keep, "rows." + h)
          ignored = ignored.concat(c.ignored)
          rows["r:" + rid] = { set: c.row, unset: nulls.filter(function(n) { return Looks.ROW_KEYS.indexOf(n) >= 0 }) }
        }
      } else if (k === "order" && !all) {
        if (!Array.isArray(v)) { ignored.push("order (a list of row handles)"); continue }
        order = []
        v.forEach(function(h) { var rid = agent.rowOf(a, h); if (rid && order.indexOf(rid) < 0) order.push(rid); else ignored.push("order: an entry that isn't a row handle, or one given twice") })
        if (order.length > 40) return { ok: false, error: "at most 40 rows in order", ignored: ignored }
      } else ignored.push(String(k).slice(0, 40) + (all && (k === "rows" || k === "order") ? " (each app's own: not for all)" : " (look, top, background, details, titles, size" + (all ? "" : ", rows, order") + ")"))
    }
    var checkedScreen = Looks.checkChoices(screen, all ? "all" : a.id, false, agent.store.pictureOk)
    ignored = ignored.concat(checkedScreen.ignored)
    var key = all ? "all" : agent.store.keyOf(a)
    var fn = function(st) {
      var e = all ? st.all : (st.apps[key] || { incarnation: a.incarnation })
      unset.forEach(function(x) { delete e[x] })
      for (var s in checkedScreen.choices) e[s] = checkedScreen.choices[s]
      if (!all) {
        var r2 = Object.create(null)
        for (var x in (e.rows || {})) r2[x] = JSON.parse(JSON.stringify(e.rows[x]))
        rowUnset.forEach(function(rid) { delete r2["r:" + rid] })
        for (var rk2 in rows) {
          var cur = r2[rk2] || {}
          rows[rk2].unset.forEach(function(n) { delete cur[n] })
          for (var y in rows[rk2].set) cur[y] = rows[rk2].set[y]
          if (Object.keys(cur).length) r2[rk2] = cur; else delete r2[rk2]
        }
        if (Object.keys(r2).length) e.rows = r2; else delete e.rows
        if (order) { if (order.length) e.order = order; else delete e.order }
        st.apps[key] = e
      }
    }
    var keys = Object.keys(checkedScreen.choices).concat(unset).concat(Object.keys(rows).length || rowUnset.length ? ["rows"] : []).concat(order ? ["order"] : [])
    var res = agent.store.change(key, fn, "command", (all ? "all apps" : a.id) + ": " + (keys.join(", ") || "nothing"))
    if (!res.ok) return { ok: false, error: res.error, ignored: ignored }
    if (keys.indexOf("background") >= 0 && agent.guide.appPanel) agent.guide.appPanel.dropPick(key)   // a newer choice than a picture still being copied
    var after = all ? agent.store.now.all : agent.store.entryOf(a) || {}
    return { ok: true, saving: res.token, will: all ? JSON.parse(JSON.stringify(after)) : agent.byHandle(a, after), ignored: ignored,
             note: "saved only once state's saving says so for this token" }
  }

  // resetAppScreen <id|all>: this app follows all apps' settings (all: the theme's)
  function resetAppScreen(id) {
    var all = id === "all"
    var a = all ? null : agent.apps.record(id)
    if (!all && (!a || a.kind !== "app")) return { ok: false, error: "no app with code " + id + " (apps lists them)" }
    if (!all && agent.apps.changing && agent.apps.changing[a.id]) return { ok: false, error: "it's being changed: try again in a moment" }
    var key = all ? "all" : agent.store.keyOf(a)
    var res = agent.store.change(key, function(st) { if (all) st.all = {}; else delete st.apps[key] }, "command", (all ? "all apps" : a.id) + ": reset")
    if (!res.ok) return { ok: false, error: res.error }
    if (agent.guide.appPanel) agent.guide.appPanel.dropPick(key)
    return { ok: true, saving: res.token, note: all ? "every app's screen follows the theme's look" : "it follows all apps' settings" }
  }

  // ---- openApp <id> "<handle or empty>" ---------------------------------------------
  // Why an agent can't open an app's screen now, checked in this order: a
  // box is open; an app's own box (its settings, signing in, typing, a
  // certificate); anything playing; why the user couldn't open it either;
  // not an app with code; not a bundled one; faulted, unavailable, being
  // changed or stopping. "" if it can.
  function refusal(id) {
    var g = agent.guide
    var v = agent.view
    if (g.dialog || (g.appPanel && g.appPanel.open) || g.railOpen || g.railEditing) return "a box is open on the guide (or Customize, or the rail)"
    if (v.settingsOpen || v.signIn !== null || v.editing !== null || v.certOffer !== null) return "an app's own box is open (its settings, signing in, typing or a certificate)"
    if (g.watching || g.vod || g.appPlaying || g.pip) return "something is playing"
    var why = agent.apps.cannotOpen(id)
    if (why) return why
    var a = agent.apps.record(id)
    if (!a || a.kind !== "app") return "it isn't an app with code"
    if (a.source !== "bundled") return "only an app that comes with the guide can be opened by an agent"
    if (agent.apps.faulted[id]) return "it stopped working (only the user's own open tries it again)"
    if (agent.apps.unavailable[id]) return "it can't run on this system"
    if (agent.apps.changing && agent.apps.changing[id]) return "it's being changed"
    var rt = agent.apps.runtime(id)
    if (rt && rt.phase === "stopping") return "it's stopping"
    return ""
  }
  // Opens an app's first screen, or (with a live item handle) that item:
  // browse for an open item, details for an info one. Its own function: the
  // user's open would clear a fault, close boxes and launch websites. Every
  // call it sends is checked again just before it goes: the seven checks
  // above, that it's the same install (source, id, incarnation), runtime and
  // generation, and that the item's handle still names it. Answers the view
  // id it asked for: appScreen says when that view is on the screen.
  function openApp(id, handle) {
    var why = agent.refusal(id)
    if (why) return { ok: false, error: why }
    var a = agent.apps.record(id)
    if (!a.incarnation) return { ok: false, error: "it isn't ready yet: try again in a moment" }
    var item = null
    if (handle) {
      if (agent.view.appId !== id || !agent.view.shown) return { ok: false, error: "an item handle is for the screen it came from: open the app first, without one" }
      item = agent.itemOf(a, handle)
      if (!item) return { ok: false, error: "that item handle is stale (appScreen lists the live ones)" }
    }
    var bound = { source: a.source, id: a.id, incarnation: a.incarnation, rt: null, gen: -1 }
    var guard = function(method) {
      var w = agent.refusal(id)
      if (w) return w
      var now = agent.apps.record(id)
      if (!now || now.source !== bound.source || now.incarnation !== bound.incarnation) return "it was installed again"
      var rt = agent.view.rt
      if (!rt) return "it isn't running"
      if (bound.rt === null) { bound.rt = rt; bound.gen = rt.gen }
      else if (rt !== bound.rt || rt.gen !== bound.gen) return "it started again"
      if (agent.view.appId !== id || agent.guide.screen !== "app") return "its screen isn't on any more"
      if (method !== "home" && item && (item.key !== agent.keyOf(now) || item.incarnation !== now.incarnation)) return "that item isn't there any more"
      return ""
    }
    var failed = agent.view.openForAgent(id, item, guard)
    if (failed) return { ok: false, error: String(failed).replace(/\.$/, "") }
    // bound to the runtime it started (or found), even before its first call
    if (bound.rt === null && agent.view.rt) { bound.rt = agent.view.rt; bound.gen = agent.view.rt.gen }
    // its first screen is the next view; the item's, the one after
    return { ok: true, view: "v-" + (agent.viewSeq + (item ? 2 : 1)),
             note: "poll appScreen until its view is this one, its state ready, covered false and picturesPending 0; a different view means the user moved or the app started again" }
  }

  // ---- appSnapshot <view> ------------------------------------------------------------
  // A picture of an app's screen, only while that view is the uncovered top
  // layer: checked when asked (an error answer) and again when it's grabbed
  // (refused, no file), where anything that came over it in between, even
  // for a moment, drops it too. The guide's own guard (Snapshots.qml) holds
  // as well. Answers the file's name; state's snapshot says how it went.
  function appSnapshot(view) {
    if (typeof view !== "string" || !/^v-[0-9]+$/.test(view)) return { ok: false, error: "a view id, as openApp or appScreen gave it" }
    var seen = agent.coverSeen
    var shot = agent.guide.snapshots.take(function(atGrab) {
      if (atGrab && agent.coverSeen !== seen) return agent.coverLast + " (while the picture was taken)"
      var why = agent.coverWhy()
      if (why) return why
      if (view !== agent.viewId) return "that view isn't the one on the screen (appScreen says which is)"
      return ""
    })
    if (shot.error) return { ok: false, error: shot.error }
    return { ok: true, name: shot.path, width: shot.width, height: shot.height,
             note: "read it once state's snapshot has this name and says written; refused says why not" }
  }
}
