import QtQuick
import Quickshell
import Quickshell.Io

// One code app running: its helper (bin/om-pg-apprun), started by a tracked
// Process (stdin open, a clean environment) inside a systemd user scope of
// its own, with the app's limits (320 MB, half a core, 48 tasks). The named
// scope is what stops it: a stop that doesn't finish in time kills the
// unit. Every call has an id and is answered once (an answer for a call
// that's gone is dropped); the helper enforces the deadlines, and a helper
// that dies answers everything still waiting with an error.
//
// Apps.qml makes one per running app, within the budget (3 at once), and
// keeps its leases (foreground, playback, home:<key>): with none and nothing
// waiting for 3 minutes, it stops.
Item {
  id: rt

  required property var store         // Apps.qml
  required property var record        // the app's record when it started
  property int gen: 0
  readonly property string unit: "om-pg-app-" + record.sourceDir + "-" + Qt.md5(record.id).slice(0, 12) + "-" + gen
  property string phase: "stopped"    // queued (waiting for a slot), starting, ready, stopping, stopped
  property string why: ""             // why it stopped: normal, crash, violation, timeout, start, unavailable, guide
  property string whyText: ""
  property var settings: ({})         // the non-secret settings it was started with
  property string server: ""
  property var pending: ({})          // call id -> done(kind, value)
  property int nextId: 1
  property var leases: ({})
  property real lastUsed: Date.now()
  property var imageWaits: ({})       // token -> { consumer -> done(path, info) }: one each, while it's asked for
  property var sentEpoch: ({})        // token -> the newest demand epoch it's asked for, until it's answered
  // the demand epoch of this app's pictures: what its screen (AppView) and
  // its Home rows (AppHome) want now; the app's screen raises it on a change
  // of view, focus or runtime, and the helper drops what an older one queued
  property int demand: 0
  // its init is written: until then nothing else goes to the helper (the
  // first line it reads must be the init; a demand or a drop sent as the
  // process starts would come first and stop it starting)
  property bool introduced: false
  property string stopForget: ""
  property bool stopAsked: false
  readonly property bool busy: Object.keys(pending).length > 0
  readonly property bool leased: Object.keys(leases).length > 0

  signal readyNow()
  property var cleanup: ({ forget: [], clear: [] })   // what the init asked the helper to clear first
  signal stopped(string why, string text)
  signal signInCode(string flow, string code, string url, real expires)
  signal signInDone(string flow, bool ok, string message, string server)
  signal signInServers(string flow, var servers)     // an account's servers, for you to choose from
  signal signInServerRefused(string flow, string why)
  signal refused(string site)       // a request it wasn't allowed, the first time in this run
  signal updated(int view, var rows, var items)   // a live view's rows (a screen's) or items (a Home row's), replaced (api 4)

  function env() {
    var e = {}
    var keep = ["HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]
    for (var i = 0; i < keep.length; i++) {
      var v = Quickshell.env(keep[i])
      if (v) e[keep[i]] = String(v)
    }
    e.LANG = "C.UTF-8"
    return e
  }

  function start() {
    if (rt.phase !== "stopped" && rt.phase !== "queued") return
    rt.phase = "starting"
    rt.why = ""
    rt.whyText = ""
    rt.stopAsked = false
    rt.introduced = false
    proc.environment = rt.env()
    proc.command = ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--unit=" + rt.unit,
                    "-p", "MemoryMax=320M", "-p", "MemorySwapMax=0", "-p", "CPUQuota=50%", "-p", "TasksMax=48", "--",
                    "/usr/bin/python3", "-I", "-S", "-B", "-u", rt.store.guide.pluginDir + "/bin/om-pg-apprun", "run"]
    proc.running = true
    startWatch.restart()
  }

  function send(frame) {
    if (!proc.running || !rt.introduced) return false
    proc.write(JSON.stringify(frame) + "\n")
    return true
  }

  // A call: done(kind, value) once, kind one of screen, detail, play, rows,
  // message, ok or error ({code, text})
  function call(method, args, done) {
    rt.lastUsed = Date.now()
    if (rt.phase !== "ready") {
      if (done) done("error", { code: "stopped", text: "the app isn't running" })
      return 0
    }
    var id = rt.nextId++
    var p = {}
    for (var k in rt.pending) p[k] = rt.pending[k]
    p[id] = done || function() {}
    rt.pending = p
    rt.send({ t: "call", id: id, method: method, args: args || {} })
    return id
  }

  // Called off: its answer, if it comes, is dropped (done is told now)
  function cancel(id) {
    var d = rt.pending[id]
    if (!d) return
    rt.drop(id)
    rt.send({ t: "cancel", id: id })
    d("error", { code: "cancelled", text: "cancelled" })
  }

  function drop(id) {
    var p = {}
    for (var k in rt.pending) if (String(k) !== String(id)) p[k] = rt.pending[k]
    rt.pending = p
  }

  // A picture the app named by a link: fetched and checked by the helper,
  // then a local file. Every ask goes to the helper, which answers one it
  // already has at once, read again through its descriptor (so a file
  // pruned or spoiled since is fetched again). epoch: the guide's demand
  // epoch (asked again under a newer one, it's asked of the helper again);
  // prio: focus, visible or rest; consumer: who's asking (the view, a Home
  // row): one callback each, the newest; broken: the file it gave couldn't
  // be drawn, so it's fetched again. done(path, info): info is { w, h } with
  // a path (0 when not known), else { code }: unknown (no such token, or let
  // go), refused, failed, stale (an older demand), busy (the helper's queue
  // was full), stopped
  function image(token, done, epoch, prio, consumer, broken) {
    var e = Number(epoch) > 0 ? Math.floor(Number(epoch)) : 0
    var w = {}
    for (var k in rt.imageWaits) w[k] = rt.imageWaits[k]
    var first = !w[token]
    var mine = {}
    for (var c in (w[token] || {})) mine[c] = w[token][c]
    mine[String(consumer || "-")] = done
    w[token] = mine
    rt.imageWaits = w
    if (first || broken === true || e > (rt.sentEpoch[token] || 0)) {
      rt.sentEpoch[token] = e
      var f = { t: "image", token: token, epoch: e, prio: prio === "focus" || prio === "rest" ? prio : "visible" }
      if (broken === true) f.broken = true
      rt.send(f)
    }
  }

  // The guide's demand moved on (another view, or away from the app's
  // screen): a new epoch, told to the helper even with nothing to ask for,
  // so what an older one queued goes
  function newDemand() {
    rt.demand += 1
    rt.send({ t: "demand", epoch: rt.demand })
    return rt.demand
  }

  // The guide let go of these results (their views gone, or their answers
  // dropped): the helper may let the pictures only they held go
  function release(results) {
    var ids = (results || []).filter(function(x) { return typeof x === "number" && x > 0 && Math.floor(x) === x })
    if (ids.length) rt.send({ t: "drop", results: ids })
  }

  function signIn(flow, how, done) { return rt.call("signIn", { flow: flow, how: how === "password" ? "password" : "code" }, done) }
  // what you typed in the password box: to the helper on its stdin, never
  // kept here (the helper hands it to the app once, inside that flow)
  // a live view (api 4) on the screen, or not any more: it may update while it's on
  function viewOn(view) { return rt.send({ t: "viewOn", view: view }) }
  function viewOff(view) { return rt.send({ t: "viewOff", view: view }) }
  function sendPassword(flow, username, password) { return rt.send({ t: "signInPassword", flow: flow, username: username, password: password }) }
  // the server you chose while signing in: one of its addresses, or one you typed for it
  function chooseServer(flow, handle, url) { return rt.send({ t: "signInServer", flow: flow, handle: handle, url: url }) }
  function typedServer(flow, handle, address) { return rt.send({ t: "signInServer", flow: flow, handle: handle, typedAddress: address }) }
  function cancelSignIn(flow) { rt.send({ t: "signInCancel", flow: flow }) }
  // the guide took a sign-in as done and marked it: what it kept is the app's now
  function markSignedIn() { rt.send({ t: "signedIn" }) }
  function closeRelay(session) { rt.send({ t: "relayClose", session: session }) }

  function lease(name, on) {
    var l = {}
    for (var k in rt.leases) if (k !== name) l[k] = true
    if (on) l[name] = true
    rt.leases = l
    rt.lastUsed = Date.now()
  }

  // Ordered: the helper fails what's waiting, closes the app, then exits;
  // if it hasn't in 5 s, the unit is killed. forget: "signIn" (sign-out),
  // "server" (a new server), "data" (Clear its data)
  function stop(forget) {
    if (rt.phase === "queued") {   // never started: nothing to stop
      rt.phase = "stopped"
      rt.why = "normal"
      rt.leases = ({})
      rt.stopped("normal", "")
      return
    }
    if (rt.phase === "stopped" || rt.phase === "stopping") return
    rt.stopForget = forget || ""
    rt.stopAsked = true
    rt.phase = "stopping"
    // before its init is out, the stop goes right behind it (onStarted);
    // a process that's gone is killed, as before; 5 s at most either way
    if (!rt.send({ t: "stop", forget: rt.stopForget }) && !proc.running) rt.killUnit()
    stopWatch.restart()
  }

  function killUnit() {
    Quickshell.execDetached(["/usr/bin/systemctl", "--user", "kill", "--signal=KILL", rt.unit + ".scope"])
  }

  function onFrame(line) {
    var f
    try { f = JSON.parse(line) } catch (e) { return }
    if (!f || typeof f !== "object") return
    if (f.t === "state") {
      if (f.state === "ready" && rt.phase === "starting") {
        startWatch.stop()
        rt.phase = "ready"
        rt.store.cleaned(rt.record, rt.cleanup)   // the helper did them before it got here
        rt.readyNow()
      } else if (f.state === "stopped") {
        rt.why = String(f.why || "normal")
        rt.whyText = String(f.text || "")
      }
    } else if (f.t === "result") {
      var d = rt.pending[f.id]
      if (!d) {
        // an answer no one waits for any more (called off as it came): the
        // pictures it holds in the helper are let go
        if (f.kind === "screen" || f.kind === "detail" || f.kind === "rows") rt.release([f.id])
        return
      }
      rt.drop(f.id)
      d(String(f.kind), f.value)
    } else if (f.t === "image") {
      var path = typeof f.path === "string" && f.path.charAt(0) === "/" ? f.path : ""
      var code = path ? "" : ["unknown", "refused", "failed", "stale", "busy"].indexOf(f.code) >= 0 ? f.code : "failed"
      // a newer ask for it is out: the answer to that is the one that counts
      if (code === "stale" && (rt.sentEpoch[f.token] || 0) > (Number(f.epoch) || 0)) return
      var waits = rt.imageWaits[f.token] || {}
      var w = {}
      for (var k in rt.imageWaits) if (k !== f.token) w[k] = rt.imageWaits[k]
      rt.imageWaits = w
      delete rt.sentEpoch[f.token]   // answered: nothing of it kept here
      // its size, from its header: a whole number of pixels up to 4096, or 0
      var side = function(v) { return typeof v === "number" && v > 0 && v <= 4096 && Math.floor(v) === v ? v : 0 }
      var info = path ? { w: side(f.w), h: side(f.h) } : { code: code }
      for (var c in waits) waits[c](path, info)
    } else if (f.t === "signInCode") {
      rt.signInCode(String(f.flow), String(f.code), String(f.url || ""), Number(f.expires) || 600)
    } else if (f.t === "signInDone") {
      rt.signInDone(String(f.flow), f.ok === true, String(f.message || ""), typeof f.server === "string" ? f.server.slice(0, 500) : "")
    } else if (f.t === "signInServers") {
      // names, addresses and handles only (the helper checked each address)
      var list = Array.isArray(f.servers) ? f.servers.slice(0, 10) : []
      rt.signInServers(String(f.flow), list.filter(function(s) {
        return s && typeof s.handle === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(s.handle) && typeof s.label === "string"
               && Array.isArray(s.urls) && s.urls.length >= 1 && s.urls.every(function(u) { return typeof u === "string" && /^https?:\/\//.test(u) && u.length <= 500 })
      }).map(function(s) { return { handle: s.handle, label: s.label.slice(0, 80), urls: s.urls.slice(0, 8) } }))
    } else if (f.t === "signInServerRefused") {
      rt.signInServerRefused(String(f.flow), String(f.why || "").slice(0, 200))
    } else if (f.t === "update") {
      // checked by the helper (rows of the screen's own ids, within its caps)
      if (typeof f.view === "number" && (Array.isArray(f.rows) || Array.isArray(f.items)))
        rt.updated(f.view, Array.isArray(f.rows) ? f.rows : null, Array.isArray(f.items) ? f.items : null)
    } else if (f.t === "refused") {
      // a site's name as the helper checked it, or none
      var site = typeof f.site === "string" && /^[a-z0-9.\-\[\]:]{1,260}$/.test(f.site) ? f.site : ""
      rt.refused(site)
    }
  }

  function finish() {
    startWatch.stop()
    stopWatch.stop()
    var p = rt.pending
    rt.pending = ({})
    for (var k in p) p[k]("error", { code: "stopped", text: "the app stopped" })
    var w = rt.imageWaits
    rt.imageWaits = ({})
    rt.sentEpoch = ({})
    for (var t in w) for (var c in w[t]) w[t][c]("", { code: "stopped" })
    rt.leases = ({})
    if (!rt.why) rt.why = rt.stopAsked ? "normal" : "crash"
    rt.phase = "stopped"
    // the scope may outlive its first process: it's the unit that ends it
    Quickshell.execDetached(["/usr/bin/systemctl", "--user", "stop", rt.unit + ".scope"])
    rt.stopped(rt.why, rt.whyText)
  }

  Component.onDestruction: if (proc.running) { proc.stdinEnabled = false; rt.killUnit() }

  Timer {
    id: startWatch
    interval: 12000
    onTriggered: if (rt.phase === "starting") { rt.why = "start"; rt.whyText = "it didn't start in time"; rt.killUnit() }
  }

  Timer {
    id: stopWatch
    interval: 5000
    onTriggered: if (proc.running) rt.killUnit()
  }

  Process {
    id: proc
    stdinEnabled: true
    clearEnvironment: true
    onStarted: {
      // what the record says now (a queued one may start a while later):
      // the secrets marked set, signed in or not, and clean-ups not yet done
      var now = rt.store.record(rt.record.id)
      if (!now || now.source !== rt.record.source || now.version !== rt.record.version) now = rt.record
      var v = now.values || {}
      rt.cleanup = { forget: Array.isArray(v["@forget"]) ? v["@forget"] : [], clear: Array.isArray(v["@clear"]) ? v["@clear"] : [] }
      write(JSON.stringify({ t: "init", id: rt.record.id, source: rt.record.source, version: rt.record.version, gen: rt.gen,
                             settings: rt.settings, server: rt.server || null, pin: rt.record.pin || "",
                             secretsSet: (now.settings || []).filter(function(st) { return st.type === "secret" && v["@secret:" + st.key] === true }).map(function(st) { return st.key }),
                             signedIn: v["@signedIn"] === true, forget: rt.cleanup.forget, clear: rt.cleanup.clear,
                             locale: Qt.locale().name.replace("_", "-") }) + "\n")
      rt.introduced = true
      // a stop asked for while it was starting goes right behind its init
      if (rt.stopAsked) rt.send({ t: "stop", forget: rt.stopForget })
    }
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(data) { rt.onFrame(data) }
    }
    stderr: SplitParser {
      onRead: function(data) { if (data.length < 2000) console.log("om-pg app " + rt.record.id + ": " + data) }
    }
    onExited: function(code) {
      rt.introduced = false
      if (code !== 0 && !rt.why) {
        // systemd-run refusing (no user manager, no delegation) never got as far as the helper
        rt.why = rt.phase === "starting" ? "unavailable" : "crash"
        rt.whyText = rt.phase === "starting" ? "the system wouldn't start it (systemd-run exited " + code + ")" : ""
      }
      rt.finish()
    }
  }
}
