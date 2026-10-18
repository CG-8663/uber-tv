import QtQuick

// Home rows from apps with code: a row an app declares in its app.json
// ("home"), off until you add it (Customize Home, C). It's loaded only while
// Home is on the screen, within the apps' budget (a "home" lease while it
// loads), and kept 10 minutes for the same app, version, server, settings,
// sign-in and row; anything of those changing makes it stale. A row that
// fails keeps what it had, marked; an app that stopped working shows its
// last rows marked, and Home doesn't start it again (only you opening it
// does). Opening a card opens the app at that item, and Esc comes back here.
//
// A card's shape: the row's Home shape from app.json (poster or wide), with
// the item's picture for it; with none, the item's own picture, and the card
// takes the shape that picture is (a poster, a square shown whole, wide),
// from its size as the helper gives it. A row holds its pictures in the
// helper (by its result) while it's kept, and lets go when it's replaced;
// what the rows hold counts toward the 4,000 the app's screen keeps under.
Item {
  id: home

  required property var guide
  readonly property var apps: guide.apps
  readonly property int keep: 10 * 60 * 1000

  // "<app id>/<row key>" -> { cards, at, sig, error, loading, holder: { rt, id } (the result its cards came in), tokens (its pictures' count) }
  property var rows: ({})
  readonly property bool shown: guide.opened && guide.screen === "home" && !guide.watching

  function rowKey(appId, key) { return appId + "/" + key }

  // What a row's cache is good for: these, as they were when it loaded
  function sig(a, key) {
    return [a.source, a.id, a.version, a.server || "", a.pin || "", JSON.stringify(apps.valuesOf(a)), apps.authGens[a.id] || 0,
            key === undefined ? "" : home.homeShape(a.id, key)].join("|")
  }

  function set(k, v) {
    var was = home.rows[k]
    // the result the old cards came in, let go once nothing shows them (and
    // what was asked for it is over: a newer result asks for its own)
    if (was && was.holder && (!v.holder || v.holder.id !== was.holder.id || v.holder.rt !== was.holder.rt) && v.cards !== was.cards) {
      home.releaseHolder(was.holder)
      home.dropAsks(k)
    }
    if (was && was.holder && !v.holder && v.cards === was.cards) v = apps.withKey(apps.withKey(v, "holder", was.holder), "tokens", was.tokens || 0)
    home.rows = apps.withKey(home.rows, k, v)
  }

  // A row Home no longer shows: let go, with what it held, what it was
  // still asking for and waiting on, and what it knew of its pictures
  function forget(k) {
    var c = home.calls[k]
    if (c) {
      delete home.calls[k]
      c.rt.lease("home:" + c.key, false)
      c.rt.cancel(c.id)
    }
    var w = home.waits[k]
    if (w) {
      w.unhook()
      w.rt.lease("home:" + w.key, false)
    }
    home.dropAsks(k)
    home.keepFailures(k, null)
    delete home.reloaded[k]
    var r = home.rows[k]
    if (!r) return
    home.releaseHolder(r.holder)
    var left = {}
    for (var x in home.rows) if (x !== k) left[x] = home.rows[x]
    home.rows = left
  }

  // What a row asked for, over: its answers are for a result it no longer
  // shows (the runtime keeps one waiting answer per row and picture, so an
  // older one is never called)
  function dropAsks(k) {
    for (var a in home.asking) if (a.indexOf(k + "\n") === 0) delete home.asking[a]
  }

  // What a row knows of its pictures' failures, kept only for the pictures
  // its cards show now (tokens: the ones they show; null: none)
  function keepFailures(k, tokens) {
    var keep = Object.create(null)
    ;(tokens || []).forEach(function(t) { keep[k + "\n" + t] = true })
    for (var f in home.picFailed) if (f.indexOf(k + "\n") === 0 && !keep[f]) delete home.picFailed[f]
    for (var b in home.brokenTried) if (b.indexOf(k + "\n") === 0 && !keep[b]) delete home.brokenTried[b]
  }

  // A row's result let go in its helper, if that's still running (a runtime
  // that stopped took everything with it, and is gone)
  function releaseHolder(h) {
    if (h && h.rt && h.rt.phase !== "stopped" && typeof h.rt.release === "function") h.rt.release([h.id])
  }

  // Whether Home shows row k now: an app row that's on, of an app that's
  // ready and still offers that row
  function isLive(k) {
    var secs = guide.homeSections
    var on = false
    for (var i = 0; i < secs.length && !on; i++) on = secs[i].type === "appRow" && secs[i].on && String(secs[i].key) === k
    if (!on) return false
    var parts = String(k).split("/")
    var a = apps.record(parts[0])
    return !!a && a.kind === "app" && apps.ready.some(function(x) { return x.id === parts[0] }) &&
           (a.home || []).some(function(h) { return h.key === parts.slice(1).join("/") })
  }

  // How many pictures the rows from one runtime hold in its helper
  function heldBy(rt) {
    var n = 0
    for (var k in home.rows) { var r = home.rows[k]; if (r && r.holder && r.holder.rt === rt) n += r.tokens || 0 }
    return n
  }
  function countTokens(list) {
    var seen = Object.create(null)
    var n = 0
    var add = function(img) { if (img && typeof img.token === "string" && !seen[img.token]) { seen[img.token] = true; n++ } }
    ;(list || []).forEach(function(it) {
      add(it.image)
      var pics = it.images && typeof it.images === "object" ? it.images : {}
      for (var x in pics) add(pics[x])
    })
    return n
  }

  // An app's Home row's shape: yours for the row (Customize Home's
  // Pictures), else its app.json's (api 3), poster or wide; or "" (each
  // card its own)
  function homeShape(appId, key) {
    var secs = guide.homeSections || []
    for (var i = 0; i < secs.length; i++)
      if (secs[i].type === "appRow" && String(secs[i].key) === appId + "/" + key && (secs[i].shape === "poster" || secs[i].shape === "wide")) return secs[i].shape
    var a = apps.record(appId)
    var h = ((a && a.home) || []).filter(function(x) { return x.key === key })[0]
    return h && (h.shape === "poster" || h.shape === "wide") ? h.shape : ""
  }
  function pictureOf(it, shape) {
    var pics = it.images && typeof it.images === "object" ? it.images : {}
    return (shape && pics[shape]) || it.image || null
  }
  // a card's shape from its picture's width over height (0: not known yet)
  function shapeFor(ratio) { return !(ratio > 0) ? "wide" : ratio < 0.8 ? "poster" : ratio <= 1.25 ? "square" : "wide" }

  // The rows Home shows now, loaded if they need to be, and pictures they
  // still lack asked for again (an app's screen may have moved its demand
  // on). Rows Home no longer shows (taken off, their app off or changed) are
  // let go, and so is what they held.
  function refresh() {
    // let go of rows Home no longer shows even while it isn't on the screen
    Object.keys(home.rows).filter(function(k) { return !home.isLive(k) }).forEach(home.forget)
    if (!home.shown || !apps.on) return
    var secs = guide.homeSections
    for (var i = 0; i < secs.length; i++) {
      if (secs[i].type !== "appRow" || !secs[i].on) continue
      var parts = String(secs[i].key).split("/")
      home.load(parts[0], parts.slice(1).join("/"))
      home.fillPictures(parts[0], parts.slice(1).join("/"))
    }
  }

  // Pictures a row's cards still lack, asked for again: never one the rules
  // refused or one let go, and one that failed only once more
  function fillPictures(appId, key) {
    var k = home.rowKey(appId, key)
    var r = home.rows[k]
    var rt = r && r.holder ? r.holder.rt : null
    if (!r || !rt || rt.phase !== "ready") return
    var shape = home.homeShape(appId, key)
    r.cards.forEach(function(c) {
      var pic = c.kind === "appItem" ? home.pictureOf(c.item, shape) : null
      if (!pic || !pic.token || c.poster) return
      home.picture(rt, k, r.holder, pic.token, shape)
    })
  }

  function load(appId, key) {
    var a = apps.record(appId)
    if (!a || a.kind !== "app" || !apps.ready.some(function(x) { return x.id === appId })) return
    if (!(a.home || []).some(function(h) { return h.key === key })) return
    var k = home.rowKey(appId, key)
    var cur = home.rows[k]
    var s = home.sig(a, key)
    if (cur && cur.loading) return
    if (cur && cur.sig === s && !cur.error && Date.now() - cur.at < home.keep) return
    // only cards of the same app, version, server, settings and sign-in are
    // ever kept: a sign-out or a new server leaves nothing of the old ones
    var same = cur && cur.sig === s
    var keepCards = same ? cur.cards : []
    var got = apps.ensure(appId, "home:" + key)
    if (!got.rt) {
      home.set(k, { cards: keepCards, at: same ? cur.at : 0, sig: s, error: got.why, loading: false })
      return
    }
    var rt = got.rt
    home.set(k, { cards: keepCards, at: same ? cur.at : 0, sig: s, error: "", loading: true })
    var ready = null, gone = null
    var unhook = function() { if (ready) rt.readyNow.disconnect(ready); if (gone) rt.stopped.disconnect(gone); ready = gone = null; delete home.waits[k] }
    var ask = function() {
      unhook()
      var callId = rt.call("homeRow", { key: key }, function(kind, value) {
        delete home.calls[k]
        rt.lease("home:" + key, false)
        // taken off Home meanwhile: what it answered is let go, not shown
        if (!home.isLive(k)) { if (kind === "rows") rt.release([callId]); home.forget(k); return }
        var now = apps.record(appId)
        if (!now || home.sig(now, key) !== s) {   // changed meanwhile: dropped (and let go), and loaded again for what it is now
          if (kind === "rows") rt.release([callId])
          home.set(k, apps.withKey(home.rows[k] || { cards: [], at: 0, sig: "" }, "loading", false))
          Qt.callLater(home.refresh)
          return
        }
        var was = home.rows[k] || {}
        var kept = was.sig === s ? was.cards || [] : []
        if (kind === "rows") {
          var shape = home.homeShape(appId, key)
          var cards = value.map(function(it) { return home.card(appId, it, shape) })
          var holder = { rt: rt, id: callId }
          home.set(k, { cards: cards, at: Date.now(), sig: s, error: "", loading: false, holder: holder, tokens: home.countTokens(value) })
          var shown = []
          value.forEach(function(it) { var pic = home.pictureOf(it, shape); if (pic && pic.token) shown.push(pic.token) })
          home.keepFailures(k, shown)
          shown.forEach(function(t) { home.picture(rt, k, holder, t, shape) })
          // the app's screen keeps what it holds under what's left
          if (guide.appView && guide.appView.rt === rt) guide.appView.trim()
        } else if (value && value.code === "cancelled") {
          home.set(k, { cards: kept, at: was.sig === s ? was.at || 0 : 0, sig: s, error: "", loading: false })   // Home went away
        } else {
          home.set(k, { cards: kept, at: was.sig === s ? was.at || 0 : 0, sig: s, error: value && value.text ? value.text : "it didn't answer", loading: false })
        }
      })
      home.calls[k] = { rt: rt, id: callId, key: key }
    }
    if (rt.phase === "ready") ask()
    else {
      // it may start, or fail to: either way the row doesn't stay loading
      ready = function() { ask() }
      gone = function(why, text) {
        unhook()
        rt.lease("home:" + key, false)
        var was = home.rows[k] || {}
        home.set(k, { cards: was.sig === s ? was.cards || [] : [], at: 0, sig: s, error: text || "the app stopped", loading: false })
      }
      rt.readyNow.connect(ready)
      rt.stopped.connect(gone)
      home.waits[k] = { rt: rt, key: key, unhook: unhook }
    }
  }

  // what's out for rows, to call off when Home goes away
  property var calls: ({})            // row key -> { rt, id, key }
  property var waits: ({})            // row key -> { rt, key, unhook } (waiting for the app to start)

  function cancelAll() {
    for (var k in home.calls) {
      var c = home.calls[k]
      delete home.calls[k]
      c.rt.cancel(c.id)               // its answer says cancelled: the row keeps what it had
    }
    for (var w in home.waits) {
      var x = home.waits[w]
      x.unhook()
      x.rt.lease("home:" + x.key, false)
      var r = home.rows[w]
      if (r) home.set(w, apps.withKey(r, "loading", false))
    }
  }

  // ---- live rows (api 4) -------------------------
  // While Home is on the screen, each row of an api 4 app is a live view in
  // its helper (viewOn, by the result its cards came in): the app may
  // replace its items, every 5 seconds at most. Off when Home goes, the row
  // is replaced or let go.
  property var liveSent: ({})          // row key -> { rt, id }
  onRowsChanged: Qt.callLater(home.syncLive)
  function syncLive() {
    var want = {}
    if (home.shown) for (var k in home.rows) {
      var r = home.rows[k]
      var a = apps.record(String(k).split("/")[0])
      if (r && r.holder && r.holder.rt && r.holder.rt.phase === "ready" && a && a.api >= 4) want[k] = r.holder
    }
    var sent = {}
    for (var s in home.liveSent) {
      var was = home.liveSent[s], w = want[s]
      if (w && w.id === was.id && w.rt === was.rt) { sent[s] = was; continue }
      if (was.rt && was.rt.phase === "ready") was.rt.viewOff(was.id)
    }
    for (var n in want) if (!sent[n] && want[n].rt.viewOn(want[n].id)) sent[n] = want[n]
    home.liveSent = sent
  }
  // a live row's new items: its cards made again, the same result holding them
  function liveUpdate(rt, vid, items) {
    if (!items) return
    items = JSON.parse(JSON.stringify(items))   // a plain copy: since Qt 6.12 a list through a signal isn't an array
    for (var k in home.rows) {
      var r = home.rows[k]
      if (!r || !r.holder || r.holder.rt !== rt || r.holder.id !== vid) continue
      var parts = String(k).split("/")
      var appId = parts[0], key = parts.slice(1).join("/")
      var shape = home.homeShape(appId, key)
      home.set(k, apps.withKey(apps.withKey(apps.withKey(r, "cards", items.map(function(it) { return home.card(appId, it, shape) })),
                                           "tokens", home.countTokens(items)), "at", Date.now()))
      var shown = []
      items.forEach(function(it) { var pic = home.pictureOf(it, shape); if (pic && pic.token) shown.push(pic.token) })
      home.keepFailures(k, shown)
      shown.forEach(function(t) { home.picture(rt, k, r.holder, t, shape) })
    }
    // the app's screen keeps what it holds under what's left, as a load does
    if (guide.appView && guide.appView.rt === rt) guide.appView.trim()
  }
  Connections {
    target: apps
    function onLiveUpdated(id, rt, vid, rows, items) { home.liveUpdate(rt, vid, items) }
  }

  // a picture that failed is tried once more the next time Home is shown
  // (never one the rules refused, or one let go)
  onShownChanged: {
    Qt.callLater(home.syncLive)
    if (!home.shown) { home.cancelAll(); return }
    for (var f in home.picFailed) if (home.picFailed[f] !== "never") delete home.picFailed[f]
  }

  function card(appId, it, shape) {
    var a = apps.record(appId) || {}
    var pic = home.pictureOf(it, shape)
    var ratio = pic && pic.path && pic.w > 0 && pic.h > 0 ? pic.w / pic.h : 0
    return { id: "ai:" + appId + ":" + it.id, kind: "appItem", appId: appId, item: it, title: it.title, sub: it.subtitle || a.name || "",
             poster: pic && pic.path ? pic.path : "", shape: shape || home.shapeFor(ratio), live: it.badge === "LIVE", progress: it.progress || 0 }
  }

  // A picture of a row's cards through the image broker, once it's fetched:
  // only for the result it was asked for (a later one's cards are never
  // given an older answer), and to every card of it showing that picture.
  // With no Home shape, a card takes the shape its picture's size says. A
  // picture the helper had let go loads the row again, once; one the rules
  // refused (or let go again) isn't asked for again, one that failed once more.
  property var reloaded: ({})         // row key -> true: loaded again for a picture let go
  property var asking: ({})           // "<row key>\n<token>\n<result>" -> true while it's asked for
  property var picFailed: ({})        // "<row key>\n<token>" -> "never", or how many times it failed
  property var brokenTried: ({})      // "<row key>\n<token>" -> true: fetched again once, its file couldn't be drawn
  function picture(rt, k, holder, token, shape, broken) {
    var fk = k + "\n" + token
    var failed = home.picFailed[fk]
    if (failed === "never" || failed >= 2) return
    var ask = fk + "\n" + holder.id
    if (home.asking[ask] && broken !== true) return
    home.asking[ask] = true
    rt.image(token, function(path, info) {
      delete home.asking[ask]
      var r = home.rows[k]
      if (!r || !r.holder || r.holder.id !== holder.id || r.holder.rt !== holder.rt) return
      if (!path) {
        var code = info && info.code
        if (code === "unknown" && !home.reloaded[k]) {
          home.reloaded[k] = true
          home.set(k, apps.withKey(r, "at", 0))
          Qt.callLater(home.refresh)
        } else if (code === "refused" || code === "unknown") home.picFailed[fk] = "never"
        else if (code !== "stale" && code !== "busy") home.picFailed[fk] = (home.picFailed[fk] || 0) + 1
        return
      }
      var ratio = info && info.w > 0 && info.h > 0 ? info.w / info.h : 0
      var cards = r.cards.map(function(c) {
        var pic = c.kind === "appItem" ? home.pictureOf(c.item, shape) : null
        if (!pic || pic.token !== token) return c
        var copy = {}
        for (var x in c) copy[x] = c[x]
        copy.poster = path
        if (!shape && ratio > 0) copy.shape = home.shapeFor(ratio)
        return copy
      })
      home.set(k, apps.withKey(r, "cards", cards))
    }, rt.demand, "visible", "home:" + k, broken === true)
  }

  // A card's picture came but couldn't be drawn (spoiled, or gone from the
  // helper's folder since): its cards show the title, and it's fetched again
  // once (the helper deletes the file first); again after that, it stays the
  // title. A picture drawn fine since may be fetched again once more.
  function pictureBroken(k, c) {
    var r = home.rows[k]
    if (!r || !r.holder || !c || c.kind !== "appItem" || !c.poster) return
    var parts = String(k).split("/")
    var shape = home.homeShape(parts[0], parts.slice(1).join("/"))
    var pic = home.pictureOf(c.item, shape)
    if (!pic || !pic.token) return                   // the app's own picture: nothing to fetch
    var fk = k + "\n" + pic.token
    var cards = r.cards.map(function(x) {
      var p = x.kind === "appItem" ? home.pictureOf(x.item, shape) : null
      if (!p || p.token !== pic.token || !x.poster) return x
      var copy = {}
      for (var y in x) copy[y] = x[y]
      copy.poster = ""
      return copy
    })
    home.set(k, apps.withKey(r, "cards", cards))
    if (home.brokenTried[fk]) { home.picFailed[fk] = "never"; return }
    home.brokenTried[fk] = true
    home.picture(r.holder.rt, k, r.holder, pic.token, shape, true)
  }
  function pictureDrawn(k, c) {
    if (!c || c.kind !== "appItem") return
    var parts = String(k).split("/")
    var pic = home.pictureOf(c.item, home.homeShape(parts[0], parts.slice(1).join("/")))
    if (pic && pic.token) delete home.brokenTried[k + "\n" + pic.token]
  }

  // The cards Home shows for a row: its cards, or one saying it's loading
  // or why it failed (a row that failed stays in place)
  function cardsFor(key) {
    var parts = String(key).split("/")
    var appId = parts[0]
    var r = home.rows[key]
    var a = apps.record(appId)
    if (!a || !apps.ready.some(function(x) { return x.id === appId })) return []
    var now = home.sig(a, parts.slice(1).join("/"))
    if (r && r.cards.length && r.sig === now) return r.cards
    if (!r || r.loading || r.sig !== now) return [{ id: "as:" + key, kind: "appStatus", shape: "wide", appId: appId, title: "Loading…", sub: a.name }]
    if (r.error) return [{ id: "as:" + key, kind: "appStatus", shape: "wide", appId: appId, title: "Couldn't load it", sub: r.error }]
    return []
  }

  function stale(key) {
    var r = home.rows[key]
    var parts = String(key).split("/")
    var a = apps.record(parts[0])
    return !!r && !!a && r.sig === home.sig(a, parts.slice(1).join("/")) && !!r.error && r.cards.length > 0
  }

  // Enter on a card: the app opens at that item; Esc comes back to Home
  function open(c, by) {
    if (by !== guide.byUser) return
    if (c.kind === "appStatus") {
      apps.clearFault(c.appId)
      var k = String(c.id).slice(3)
      home.set(k, apps.withKey(home.rows[k] || { cards: [], at: 0, sig: "" }, "at", 0))
      var parts = k.split("/")
      home.load(parts[0], parts.slice(1).join("/"))
      return
    }
    var it = c.item
    var method = it.kind === "play" ? "play" : it.kind === "info" ? "details" : "browse"
    guide.appView.openAt(c.appId, method, { item: it.id }, by, "home")
  }

  Connections {
    target: guide
    function onScreenChanged() { Qt.callLater(home.refresh) }
    function onOpenedChanged() { Qt.callLater(home.refresh) }
    function onHomeSectionsChanged() { Qt.callLater(home.refresh) }
  }
  Connections {
    target: apps
    function onReadyChanged() { Qt.callLater(home.refresh) }
    function onAuthGensChanged() { Qt.callLater(home.refresh) }
    function onChangingChanged() { Qt.callLater(home.refresh) }   // let go: its rows load again
  }
  Timer {
    interval: 60000
    repeat: true
    running: home.shown
    onTriggered: home.refresh()
  }
}
