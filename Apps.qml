import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "ui"
import "AppBudget.js" as Budget
import "AppAsks.js" as Asks

// Apps: Uber TV's apps for the guide, installed with care. Off until you
// turn them on (Settings → Apps, which asks first), each app with its own
// switch. They come from the Uber TV catalog, signed with its key
// (apps/catalog-signers), from a signed .tvapp the user picked while Unknown
// sources is on, or, in Developer mode, from an unsigned file (and open only
// while Developer mode is on). Before anything is installed, bin/om-pg-apps
// checks it (the catalog's signature, again, not the copy kept here; the
// package's SHA-256; a safe unpack; its app.json) and you see who made it
// and what it asks for; what installs is exactly what you saw. An update
// asking for more waits for you; a catalog can pull a bad app, which turns
// it off and is never installed. Installed apps are read-only, and checked
// each time the guide starts: one from the catalog is traced back to the
// signed catalog it came from, and what it shows and opens comes from its
// own app.json as checked, not from apps.json. None opens until it's been
// checked. A signed app file is pinned to its developer's key; only its small
// signed release note is checked in the background, and its update package is
// fetched only after consent. A launcher is a website the guide opens full screen in your
// browser's app window (signed in as you are there), nothing run on this
// computer. An app with code runs in a sandbox
// (AppRuntime.qml, bin/om-pg-apprun) and the guide draws its screens; v1's
// come with the guide itself ("bundled", part of the plugin's reviewed
// commit) or, in Developer mode, from a file. Every install has a source
// (catalog:uber, bundled, app:<key> or file:<lineage>) and everything of an app is kept
// by (source, id). What's installed is in apps.json.
Scope {
  id: apps

  required property var guide

  property bool loaded: false
  property bool on: false
  property bool developer: false
  property bool developerShown: false   // Developer mode's row, once you asked for it (Settings → About, OK 7 times): until it's switched off, or the guide starts again
  property bool unknownSources: false   // signed app files the user picked: on only with the computer's password
  // [{ id, name, version, author, description, api, kind, color, icon, launch,
  //    permissions, source, sourceDir, from: "catalog"|"bundled"|"file", file,
  //    sha256, files, installed, updated, used, enabled, broken, revoked,
  //    update, main, settings, home, values, server, pin }]
  property var installed: []
  property real catalogSeen: 0          // the newest catalog seen, so an older one is refused
  property string catalogSource: ""     // a catalog of your own (apps.json only), still checked with the guide's key
  property var catalog: null            // { name, updated, fetched, apps, revoked }
  property string catalogError: ""
  property bool fetching: false
  property real checked: 0              // the last look for updates
  property var review: null             // an app waiting for Install or Cancel
  property bool inspecting: false
  property bool installing: false       // yours: the boxes wait for it
  property bool preparing: false        // a consented signed update package getting ready (Cancel still works)
  property var prepareRun: null         // its Run while it gets ready: Cancel, or apps or Unknown sources turned off, stops it
  property bool updating: false         // a quiet update, in the background
  property string status: ""            // the last thing worth saying
  property var updateQueue: []          // apps updating quietly (they ask for nothing new): [{ id, install }], each for the install it was queued for
  property var checkedIds: ({})         // checked since the guide started: id -> true
  property var unproven: ({})           // from the catalog before it kept proof: installed again (id -> that install)
  property bool checkingAppFiles: false // signed release notes, one at a time
  property var appCheckRun: null        // cancelled immediately when Unknown sources goes off
  property var appCheckQueue: []        // [{ id, install }], identities fixed before each check
  property var appCheckDone: null
  property bool appCheckForced: false
  property string appFileError: ""
  property bool fetchedNow: false       // the catalog read since the guide started (its signed copy is fresh)
  property var bundled: []              // the apps the guide comes with: [{ id, manifest, tree }]
  property bool canRun: true            // bubblewrap and systemd-run are there (apps with code can run)
  property bool migrating: false
  property var runtimes: ({})           // id -> AppRuntime, at most 3
  property var faults: ({})             // id -> [when] (crashes, violations, timeouts in 5 minutes)
  property var faulted: ({})            // id -> why (3 of those: stopped until you open it)
  property var unavailable: ({})        // id -> why (the system can't run it; not a fault)
  property int gens: Math.floor(Date.now() / 1000) % 1000000 * 100
  readonly property int budget: 3

  readonly property string defaultCatalog: "https://raw.githubusercontent.com/marcho78/uber-tv-apps/main/catalog.json"
  readonly property string catalogUrl: catalogSource || defaultCatalog
  readonly property string statePath: guide.configDir + "/apps.json"
  readonly property string dataHome: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/om-pg"
  readonly property string appsDir: dataHome + "/apps"
  readonly property string dataDir: dataHome + "/app-data"
  readonly property string stagingDir: guide.cacheDir + "/app-staging"
  readonly property string catalogCache: guide.cacheDir + "/apps-catalog.json"
  readonly property string signers: guide.pluginDir + "/apps/catalog-signers"
  readonly property string helper: guide.pluginDir + "/bin/om-pg-apps"
  readonly property string stateHome: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/om-pg"
  readonly property string storeDir: dataHome + "/app-store"
  readonly property string secretsDir: guide.configDir + "/app-secrets"
  readonly property string logsDir: stateHome + "/app-logs"
  readonly property string imagesDir: guide.cacheDir + "/app-img"
  readonly property string activityDir: stateHome + "/app-activity"
  readonly property string journal: dataHome + "/apps-migration.json"
  // the apps you can open now (an unsigned file only in Developer mode; a
  // signed app file only while Unknown sources is on)
  readonly property var ready: on && !migrating ? installed.filter(function(a) { return a.enabled && !a.broken && !a.revoked && (a.from !== "file" || developer) && (a.from !== "appFile" || unknownSources) }) : []
  // what Get apps offers: the guide's own apps, then the catalog's
  readonly property var offered: bundled.filter(function(b) { return b.manifest }).map(function(b) {
    var m = b.manifest
    return { id: m.id, name: m.name, version: m.version, author: m.author, description: m.description, kind: m.kind, color: m.color,
             permissions: m.permissions, settings: m.settings, bundled: true, iconFile: m.icon ? guide.pluginDir + "/apps/first-party/" + m.id + "/" + m.icon : "" }
  }).concat(catalog ? catalog.apps || [] : [])
  readonly property var updates: installed.filter(function(a) { return !!a.update })
  readonly property bool busy: fetching || inspecting || installing || preparing || updating || updateQueue.length > 0

  function record(id) {
    for (var i = 0; i < apps.installed.length; i++) if (apps.installed[i].id === id) return apps.installed[i]
    return null
  }

  // The record a row of Get apps (Guide.qml appsBoxRows) is about: the one
  // installed from that row's own origin (the guide's own or the catalog),
  // else null. The same id from somewhere else isn't
  // the row's: choosing the row opens the replace review
  function rowRecord(r) {
    var origin = !r || r.type !== "app" ? "" : r.entry && r.entry.bundled ? "bundled" : "catalog:uber"
    var a = origin ? apps.record(r.id) : null
    return a && a.source === origin ? a : null
  }

  function catalogEntry(id) {
    var list = apps.catalog ? apps.catalog.apps || [] : []
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]
    return null
  }

  function withRecord(id, change) {
    apps.installed = apps.installed.map(function(a) {
      if (a.id !== id) return a
      var copy = {}
      for (var k in a) copy[k] = a[k]
      change(copy)
      return copy
    })
  }

  // ---- what an app asks for, in plain words (AppAsks.js) --------------------
  readonly property var writeMethods: Asks.writeMethods
  function asks(perms, settings) { return Asks.asks(perms, settings) }
  function groupsOf(items, perms, home) { return Asks.groupsOf(items, perms, home) }
  function summary(perms, kind) { return Asks.summary(perms, kind) }
  function hasNewWrite(a, b) { return Asks.hasNewWrite(a, b) }
  function cancelFirst(r) { return Asks.cancelFirst(r) }
  function reviewFolds(r) { return Asks.reviewFolds(r) }
  function activityFolds(act) { return Asks.activityFolds(act) }
  readonly property var activityShown: Asks.activityShown
  function hadBefore(r) { return Asks.hadBefore(r) }
  function originLine(from, name, fingerprint) { return Asks.originLine(from, name, fingerprint) }
  function newAsks(a, b) { return Asks.newAsks(a, b) }
  function times(n) { return Asks.times(n) }
  function sizeWords(n) { return Asks.sizeWords(n) }

  // An app's Activity (lib/appactivity.py), read by the helper: done(ok, { sites, refused, refusedMore })
  function activity(id, done) {
    var a = apps.record(id)
    if (!a || !a.source || a.kind !== "app") { done(false, null); return }
    apps.run(["activity", id, a.source, apps.roots()], function(res) { done(res.ok === true, res.ok ? res : null) }, 30)
  }

  // Wrong passwords: after 5 in a row an app's password box waits 30
  // seconds before it takes another try (this guide session)
  property var passwordFails: ({})       // id -> { n, until }
  // a live view's update (api 4), for whoever shows that result: an app's
  // screen (AppView) or a Home row (AppHome)
  signal liveUpdated(string id, var rt, int view, var rows, var items)
  function passwordWait(id) {
    var f = apps.passwordFails[id]
    return f && f.until > Date.now() ? Math.ceil((f.until - Date.now()) / 1000) : 0
  }
  function passwordFailed(id) {
    var f = apps.passwordFails[id] || { n: 0, until: 0 }
    var n = f.n + 1
    apps.passwordFails = apps.withKey(apps.passwordFails, id, n >= 5 ? { n: 0, until: Date.now() + 30000 } : { n: n, until: f.until })
  }
  function passwordWorked(id) { apps.passwordFails = apps.without(apps.passwordFails, id) }

  // A refused request, told by its runtime the first time in a run: said
  // once a guide session an app
  property var refusedSaid: ({})
  function sayRefused(id) {
    if (apps.refusedSaid[id]) return false
    apps.refusedSaid = apps.withKey(apps.refusedSaid, id, true)
    return true
  }

  function fromOf(source) { return /^file:/.test(source) ? "file" : /^app:/.test(source) ? "appFile" : /^source:/.test(source) ? "legacySource" : source === "bundled" ? "bundled" : "catalog" }

  function newer(a, b) {
    var x = String(a).split(".").map(Number)
    var y = String(b).split(".").map(Number)
    for (var i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0)
    return false
  }

  // A launcher's link, checked again here: plain https on one of its
  // websites (bin/om-pg-apps checked it at install)
  function linkOk(url, perms) {
    var u = String(url || "")
    if (!/^https:\/\/[A-Za-z0-9\-._~:\/?#\[\]@!&()*+,;=%]{4,492}$/.test(u)) return false
    var host = u.slice(8).split(/[\/?#]/)[0].toLowerCase()
    if (host.indexOf("@") >= 0 || host.indexOf(":") >= 0) return false
    var web = (perms && perms.web) || []
    return web.some(function(d) { return host === d || host.slice(-d.length - 1) === "." + d })
  }

  // ---- the helper ----------------------------------------------------------
  // bin/om-pg-apps through the bounded runner (ui/Run.qml): its own process
  // group, a deadline (one that's stuck doesn't keep everything waiting) and
  // 8 MB of output at most; it answers with one JSON line, ok or not
  Component { id: job; Run { maxBytes: 8 * 1024 * 1024; okCodes: [0, 1]; splitMarker: "\n" } }

  function run(args, done, seconds) {
    var r = job.createObject(apps, { timeoutMs: (seconds || 120) * 1000 })
    r.finished.connect(function(ok, output) {
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, error: ok ? "the app helper failed" : String(output).slice(0, 200) } }
      if (done) done(res)
      Qt.callLater(function() { r.destroy() })
    })
    r.start(["/usr/bin/python3", apps.helper].concat(args))
  }

  // ---- an app's settings (only from its settings page, by you) ----------
  function setValue(id, key, value) {
    apps.withRecord(id, function(a) {
      var v = {}
      for (var k in a.values || {}) v[k] = a.values[k]
      v[key] = value
      a.values = v
    })
    apps.save()
  }

  // A secret you typed: kept by bin/om-pg-apps (on its stdin, never on a
  // command line) in the app's secrets file
  Component { id: stdinJob; Run { timeoutMs: 30000; maxBytes: 8192 } }
  function setSecret(id, name, value, done) {
    var a = apps.record(id)
    if (!a || !a.sourceDir) { done(false, "it isn't installed"); return }
    if (apps.changing[id]) { done(false, "it's being changed; try again in a moment"); return }
    if (value === "") { apps.clearSecret(id, name, done); return }   // nothing typed: cleared
    // a start not done with its clean-ups may yet clear this name (it was
    // told to before you typed it): not until it's done them
    var rt = apps.runtimes[id]
    if (apps.pending(a, "@clear").indexOf(name) >= 0 && rt && rt.phase !== "ready" && rt.phase !== "stopped") { done(false, "it's starting; try again in a moment"); return }
    var mine = apps.installOf(a)
    apps.setChanging(id, true)   // no install, update or removal while its secrets file is written
    var job = stdinJob.createObject(apps)
    job.finished.connect(function(ok, output) {
      apps.setChanging(id, false)
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, error: ok ? "no answer" : output } }
      var same = apps.installOf(apps.record(id)) === mine
      if (res.ok && same) { apps.unpend(id, "@clear", [name]); apps.setValue(id, "@secret:" + name, true); apps.authChanged(id) }
      done(res.ok === true && same, same ? res.error || "" : "it was replaced meanwhile")
      Qt.callLater(function() { job.destroy() })
    })
    job.start(["/usr/bin/python3", apps.helper, "secret-set", apps.secretsDir + "/" + a.sourceDir + "/" + id + ".json", name], value + "\n")
  }

  function clearSecret(id, name, done) {
    var a = apps.record(id)
    if (!a || !a.sourceDir) { if (done) done(false, "it isn't installed"); return }
    if (apps.changing[id]) { if (done) done(false, "it's being changed; try again in a moment"); return }
    var mine = apps.installOf(a)
    apps.setChanging(id, true)
    apps.run(["secret-clear", apps.secretsDir + "/" + a.sourceDir + "/" + id + ".json", name], function(res) {
      apps.setChanging(id, false)
      var same = apps.installOf(apps.record(id)) === mine
      if (res.ok && same) { apps.dropValue(id, "@secret:" + name); apps.authChanged(id) }
      if (done) done(res.ok === true && same, same ? res.error || "" : "it was replaced meanwhile")
    }, 30)
  }

  function dropValue(id, key) {
    apps.withRecord(id, function(a) {
      var v = {}
      for (var k in a.values || {}) if (k !== key) v[k] = a.values[k]
      a.values = v
    })
    apps.save()
  }

  // What a sign-out, a new server or Clear its data takes away, done by the
  // guide once the app has stopped, whatever the app said (bin/om-pg-apps
  // forget): signIn and server: the sign-in's secrets, storage marked
  // server, pictures; data: all its storage
  // The caller holds the app (changing) while this runs, so no runtime reads
  // what's being forgotten, and bumps its auth generation once it's done.
  function forget(id, what, done) {
    var a = apps.record(id)
    if (!a || !a.source) { if (done) done(false, "it isn't installed"); return }
    apps.run(["forget", what, id, a.source, apps.roots()], function(res) {
      if (res.ok) apps.unpend(id, "@forget", [what])   // otherwise the next start does it first
      if (done) done(res.ok === true, res.error || "")
    }, 60)
  }

  // The server an app talks to, made canonical first. A new server forgets
  // what the old one gave (its sign-in, its server-scoped data, pictures).
  function setServer(id, text, done) {
    var a0 = apps.record(id)
    if (!a0) { done(false, "it isn't installed"); return }
    if (apps.changing[id]) { done(false, "it's being changed; try again in a moment"); return }
    var mine = apps.installOf(a0)
    apps.setChanging(id, true)
    apps.run(["server", String(text)], function(res) {
      apps.setChanging(id, false)
      if (!res.ok) { done(false, res.error, true); return }
      if (apps.installOf(apps.record(id)) !== mine) { done(false, "it was replaced meanwhile"); return }
      var saved = apps.commit(id, function(a) {
        a.server = res.server
        a.pin = ""             // a pin belongs to the server it was made for
        var v = {}
        for (var k in a.values || {}) if (k !== "@signedIn") v[k] = a.values[k]
        // what the old server gave is owed from this same write (the
        // restart that follows forgets it)
        var f = apps.pending(a, "@forget")
        if (f.indexOf("server") < 0) v["@forget"] = f.concat(["server"])
        a.values = v
      })
      if (!saved) { done(false, "your list of apps couldn't be saved (" + apps.saveError + ")"); return }
      apps.authChanged(id)
      done(true, "")
    }, 30)
  }

  // The server chosen while signing in (an account that lists your
  // servers), kept with the sign-in in one write: only when the install is
  // the one the sign-in began on, and the app has no server yet or this
  // same one (another server goes through setServer first, which forgets
  // what the old one gave). Not through setServer: that clears the sign-in
  // and owes the forget. { ok, why }
  function signedInWith(id, server, install) {
    var a = apps.record(id)
    if (!a) return { ok: false, why: "it isn't installed" }
    if (apps.installOf(a) !== install) return { ok: false, why: "it was replaced meanwhile" }
    if (!/^https?:\/\//.test(String(server || ""))) return { ok: false, why: "no server was chosen" }
    if (a.server && a.server !== server) return { ok: false, why: "it has another server" }
    var same = a.server === server
    var saved = apps.commit(id, function(r) {
      r.server = server
      if (!same) r.pin = ""   // a pin belongs to the server it was made for
      var v = {}
      for (var k in r.values || {}) if (k !== "@forget" && k !== "@clear") v[k] = r.values[k]
      // what it kept now is the sign-in: none of these is owed any more
      var f = apps.pending(r, "@forget").filter(function(x) { return x !== "signIn" && x !== "server" })
      var c = apps.pending(r, "@clear").filter(function(x) { return x !== "signIn" })
      if (f.length) v["@forget"] = f
      if (c.length) v["@clear"] = c
      v["@signedIn"] = true
      r.values = v
    })
    return saved ? { ok: true, why: "" } : { ok: false, why: "your list of apps couldn't be saved (" + apps.saveError + ")" }
  }

  // An address you typed, made canonical by the helper as a server's is:
  // done(ok, server, why)
  function canonicalServer(text, done) {
    apps.run(["server", String(text)], function(res) { done(res.ok === true, res.ok ? res.server : "", res.error || "") }, 30)
  }

  function setPin(id, sha) {
    apps.withRecord(id, function(a) { a.pin = /^[0-9a-f]{64}$/.test(sha || "") ? sha : "" })
    apps.authChanged(id)
    apps.save()
  }

  // The server's certificate, as it is now: { sha256, verified }
  function certOf(id, done) {
    var a = apps.record(id)
    if (!a || !a.server) { done(false, "it has no server"); return }
    apps.run(["cert", a.server], function(res) { if (res.ok) done(true, { sha256: res.sha256, verified: res.verified === true }); else done(false, res.error) }, 30)
  }

  // Sign-in, sign-out, a new server or pin, an update, another source: what
  // Home rows had cached for it is no longer good (milestone 6)
  property var authGens: ({})
  function authChanged(id) { apps.authGens = apps.withKey(apps.authGens, id, (apps.authGens[id] || 0) + 1) }

  // Clean-ups not done yet, kept in the record until they are: "@forget"
  // (signIn, server, data) and "@clear" (secrets' names, or signIn). Each
  // runtime's start does them first (bin/om-pg-apprun) and won't run the
  // app if they fail, so what a failed or cut-off clean-up left is never
  // the app's, and it's tried again at every start.
  function pending(a, key) { return a && a.values && Array.isArray(a.values[key]) ? a.values[key] : [] }
  function pend(id, key, items) {
    var cur = apps.pending(apps.record(id), key)
    var more = items.filter(function(x) { return cur.indexOf(x) < 0 })
    if (apps.record(id) && more.length) apps.setValue(id, key, cur.concat(more))
  }
  function unpend(id, key, items) {
    var a = apps.record(id)
    if (!a || !a.values || a.values[key] === undefined) return
    var left = apps.pending(a, key).filter(function(x) { return items.indexOf(x) < 0 })
    if (left.length) apps.setValue(id, key, left)
    else apps.dropValue(id, key)
  }
  // a runtime of rec got to ready: what it was asked to clear first is
  // cleared (not while something holds the app: that may have asked for the
  // same again, and the next start does it once more, which does no harm)
  function cleaned(rec, c) {
    if (!c || apps.changing[rec.id] || apps.installOf(apps.record(rec.id)) !== apps.installOf(rec)) return
    if (c.forget.length) apps.unpend(rec.id, "@forget", c.forget)
    if (c.clear.length) apps.unpend(rec.id, "@clear", c.clear)
  }

  // Which install a record is (its source, version and package): a job
  // started for one acts only if it's still that one when it's done
  function installOf(a) { return a ? [a.source, a.version, a.sha256, a.updated].join("|") : "" }

  // Where everything of an app is kept, for remove to delete
  function roots() {
    return JSON.stringify({ apps: apps.appsDir, data: apps.dataDir, store: apps.storeDir, secrets: apps.secretsDir, logs: apps.logsDir, images: apps.imagesDir,
                            activity: apps.activityDir })
  }

  // ---- turning things on and off -----------------------------------------
  // Turning apps on or Developer mode on asks you first (guide.askApps,
  // guide.askDeveloper: Developer mode, and Unknown sources, with the
  // computer's password); these do it once you've said yes.
  function setOn(on) {
    apps.on = on === true
    if (!apps.on) {
      apps.developer = false
      apps.developerShown = false
      apps.unknownSources = false
      apps.updateQueue = []
      apps.stopAll()
      apps.dropAppFileReview()
      apps.stopAppChecks()
    }
    apps.save()
    if (apps.on) { apps.verify(); apps.freshen(); apps.listBundled() }
  }

  function setDeveloper(on) {
    apps.developer = on === true && apps.on
    if (!apps.developer) apps.developerShown = false   // off: its row goes again (7 presses bring it back)
    apps.save()
  }

  // Off: every signed app-file app stops for now (it stays installed), a
  // review/package preparation goes, and no update address remains in use.
  function setUnknownSources(on) {
    apps.unknownSources = on === true && apps.on
    if (!apps.unknownSources) {
      apps.stopAppChecks()
      apps.installed.forEach(function(a) { if (a.from === "appFile") apps.stopRuntime(a.id, "", "appsOff") })
      apps.dropAppFileReview()
    }
    apps.save()
    if (apps.unknownSources) apps.freshen()
  }

  // Apps or Unknown sources turned off: a signed app file in review goes, as
  // Cancel does. One already in install finishes (install contacts nothing).
  function dropAppFileReview() {
    apps.stopPreparing()
    if (apps.review && apps.review.from === "appFile") apps.cancel()
  }

  function showDeveloper() {
    apps.developerShown = true
  }

  function setEnabled(id, on) {
    var r = apps.record(id)
    if (!r) return "not installed"
    if (on && r.revoked) return Asks.pulledBy(r.from) + ": " + (r.revoked || "")
    if (on && r.broken) return r.broken + ": remove it and install it again"
    apps.withRecord(id, function(a) { a.enabled = on === true })
    if (!on) apps.stopRuntime(id, "", "appsOff")
    apps.save()
    return "ok"
  }

  // ---- the catalog ---------------------------------------------------------
  property var afterFetch: []
  function fetchCatalog(then) {
    if (then) apps.afterFetch = apps.afterFetch.concat([then])
    if (apps.fetching) return
    apps.fetching = true
    apps.run(["catalog", apps.catalogUrl, apps.signers, String(apps.catalogSeen), guide.cacheDir], function(res) {
      apps.fetching = false
      if (res.ok) {
        apps.catalog = res.catalog
        apps.catalogError = ""
        apps.catalogSeen = Math.max(apps.catalogSeen, res.catalog.updated || 0)
        apps.checked = Date.now() / 1000   // a failed look tries again within the hour
        apps.fetchedNow = true
        apps.applyCatalog()
      } else {
        apps.catalogError = res.error || "the catalog couldn't be read"
      }
      apps.save()
      var calls = apps.afterFetch
      apps.afterFetch = []
      for (var i = 0; i < calls.length; i++) calls[i](res)
    }, 300)
  }

  // An app from the catalog, for bin/om-pg-apps to check the catalog's
  // signature again (not the copy kept here)
  function catalogRequest(id) {
    return { type: "catalog", id: id, cache: guide.cacheDir, signers: apps.signers, seen: apps.catalogSeen }
  }

  // Why the catalog pulled this app at this version ("" if it didn't)
  function pulledReason(id, version) {
    var pulled = apps.catalog ? apps.catalog.revoked || [] : []
    for (var i = 0; i < pulled.length; i++)
      if (pulled[i].id === id && (pulled[i].version === "*" || pulled[i].version === version)) return pulled[i].reason || "The catalog pulled it."
    return ""
  }

  // Pulled apps turn off; updates asking for nothing new install quietly,
  // the others wait for you. A pulled version is never offered: the helper
  // leaves it out of the catalog.
  function applyCatalog() {
    if (!apps.catalog) return
    var quiet = []
    var said = []
    apps.installed = apps.installed.map(function(a) {
      var copy = {}
      for (var k in a) copy[k] = a[k]
      if (copy.from !== "catalog") return copy
      var bad = apps.pulledReason(copy.id, copy.version)
      if (bad && !copy.revoked) {
        copy.revoked = bad
        copy.enabled = false
        said.push(copy.name + " was turned off: the catalog pulled it. " + bad)
      } else if (!bad && copy.revoked) copy.revoked = ""   // put back
      var e = apps.catalogEntry(copy.id)
      copy.update = null
      if (e && apps.newer(e.version, copy.version) && !copy.revoked) {
        var more = apps.newAsks(copy.permissions, e.permissions)
        if (more.length) copy.update = { version: e.version, asks: more.map(function(x) { return x.text }) }
        else quiet.push(apps.queued(copy))
      }
      return copy
    })
    if (said.length) apps.status = said.join(" ")
    if (quiet.length && apps.on) apps.queueUpdates(quiet)
  }

  // An app queued as the install it is now (queueUpdates): an update queued
  // for one install never acts on another that took its place
  function queued(a) { return { id: a.id, install: apps.installOf(a) } }

  function queueUpdates(items) {
    apps.updateQueue = apps.updateQueue.concat(items.filter(function(q) { return !apps.updateQueue.some(function(x) { return x.id === q.id && x.install === q.install }) }))
    apps.nextUpdate()
  }

  // One quiet update at a time, and never while something of yours is going
  // on (a review, an install). What asks for more than the app has waits for
  // you, whatever the catalog said.
  function nextUpdate() {
    if (!apps.updateQueue.length || !apps.on || apps.migrating || apps.updating || apps.installing || apps.preparing || apps.inspecting || apps.review) return
    var q = apps.updateQueue[0]
    var id = q.id
    var rec = apps.record(id)
    // queued for one install of the catalog's or the guide's own: gone since,
    // or another in its place (from a signed app file, say: these never
    // update quietly), it isn't this update's to touch
    if (!rec || apps.installOf(rec) !== q.install || (rec.from !== "catalog" && rec.from !== "bundled")) {
      apps.updateQueue = apps.updateQueue.slice(1)
      if (apps.unproven[id] === q.install) apps.unproven = apps.without(apps.unproven, id)
      Qt.callLater(apps.nextUpdate)
      return
    }
    if (apps.changing[id]) {
      // being removed or changed already: this update waits for the next look
      apps.updateQueue = apps.updateQueue.slice(1)
      Qt.callLater(apps.nextUpdate)
      return
    }
    var name = rec.name || id
    var proving = apps.unproven[id] === q.install
    // held from here to the end, whatever happens: nothing else changes it,
    // and no runtime starts, until next() lets go (lost: what's said of what
    // it withdrew and couldn't give back)
    apps.setChanging(id, true)
    var next = function(problem, lost, retry) {
      apps.setChanging(id, false)
      apps.updating = false
      apps.updateQueue = apps.updateQueue.filter(function(x) { return x.id !== id })
      if (problem && proving && apps.installOf(apps.record(id)) === q.install) apps.withRecord(id, function(a) { a.broken = "It can't be traced back to the catalog (" + problem + ")" })
      if (retry) console.warn("om-pg: updating " + id + ": " + problem)
      if (problem && (!proving || lost)) apps.status = retry ? "Couldn't update " + name + ". Try again." + (lost || "")
                                                             : "Couldn't update " + name + ": " + (lost ? apps.sentence(problem) + lost : problem)
      if (apps.unproven[id] === q.install) apps.unproven = apps.without(apps.unproven, id)
      apps.nextUpdate()
    }
    apps.updating = true
    var request = rec.source === "bundled" ? apps.bundledRequest(id) : apps.catalogRequest(id)
    apps.run(["inspect", JSON.stringify(request), apps.stagingDir], function(res) {
      if (!res.ok) { next(res.error); return }
      var have = apps.record(id)
      // quiet only from where it came from (the manifest carries no source:
      // the record's against this one's, as review checks it), and only for
      // the install it was queued for (held since, but checked): otherwise
      // nothing is said of it
      if (!have || apps.installOf(have) !== q.install || have.source !== apps.sourceFor({ from: res.source, have: have })) {
        apps.run(["discard", res.staging, apps.stagingDir], function() {}, 60)
        next("")
        return
      }
      var more = apps.newAsks(have, res.manifest)
      if (more.length) {
        apps.run(["discard", res.staging, apps.stagingDir], function() {}, 60)
        apps.withRecord(id, function(a) {
          a.update = { version: res.manifest.version, asks: more.map(function(x) { return x.text }) }
          if (proving) a.broken = "It needs updating before it can be checked"
        })
        next("")
        return
      }
      // its runtime gone first (playback finalized, the helper exited), then the files
      apps.stopThen(id, "replaced", function() {
        var was = apps.record(id)   // what withdraw takes from, given back if install changes nothing
        if (!apps.withdraw(id, res.manifest)) {
          apps.run(["discard", res.staging, apps.stagingDir], function() {}, 60)
          next("your list of apps couldn't be saved (" + apps.saveError + ")")
          return
        }
        apps.run(["install", res.staging, apps.appsDir, apps.dataDir, res.tree, have.source], function(done) {
          if (!done.ok) { next(done.error, apps.giveBack(id, was, res.manifest, done), done.retry === true); return }
          var again = done.manifest.version === have.version
          apps.keep(done, have.source, res.sourceName, res.sha256, function(warning) {
            if (warning) apps.status = warning
            else if (!again) apps.status = done.manifest.name + " updated to " + done.manifest.version + "."
            if (done.warning) apps.status = (apps.status ? apps.status + " " : "") + done.warning   // installed; something old left to tidy
            next("")
          })
        }, 120)
      })
    }, 300)
  }

  // The catalog and signed app-file release notes, about twice a day. A
  // signed app's own clock is kept with it: a catalog look while Unknown
  // sources is off can never delay its first look when that switch comes on.
  function freshen() {
    if (!apps.on || apps.migrating) return
    var catalogAt = apps.catalog ? Number(apps.catalog.fetched) || 0 : apps.checked
    if (!apps.fetching && Date.now() / 1000 - catalogAt > 12 * 3600) apps.fetchCatalog()
    if (apps.unknownSources) apps.checkAppFiles(false)
  }

  function checkUpdates(force) {
    if (!apps.on || apps.migrating) return false
    if (!apps.fetching) apps.fetchCatalog()
    if (apps.unknownSources) apps.checkAppFiles(force === true)
    return true
  }

  Component { id: appCheckJob; Run { timeoutMs: 120000; maxBytes: 4 * 1024 * 1024; okCodes: [0, 1]; splitMarker: "\n" } }

  // Checks one or all signed app files. Only their signed release notes are
  // fetched. Each answer belongs to the exact install queued for it; removal,
  // replacement or an Unknown-sources-off in between makes it a no-op.
  function checkAppFiles(force, done, only) {
    if (!apps.on || !apps.unknownSources || apps.migrating) { if (done) done(false); return false }
    if (apps.checkingAppFiles) {
      apps.appFileError = "An app-file update check is already in progress."
      if (done) done(false)
      return false
    }
    var now = Date.now() / 1000
    var list = apps.installed.filter(function(a) {
      return a.from === "appFile" && a.updateAddress && (!only || a.id === only)
             && (force || now - (Number(a.updateChecked) || 0) > 12 * 3600)
    }).map(apps.queued)
    if (!list.length) { if (done) done(true); return true }
    apps.appCheckQueue = list
    apps.appCheckDone = done || null
    apps.appCheckForced = force === true
    apps.checkingAppFiles = true
    apps.appFileError = ""
    apps.nextAppCheck()
    return true
  }

  function stopAppChecks() {
    var r = apps.appCheckRun
    apps.appCheckRun = null
    apps.appCheckQueue = []
    apps.checkingAppFiles = false
    var done = apps.appCheckDone
    apps.appCheckDone = null
    if (r) { r.cancel(); r.destroy() }
    if (done) done(false)
  }

  function finishAppChecks(ok) {
    apps.appCheckRun = null
    apps.appCheckQueue = []
    apps.checkingAppFiles = false
    var done = apps.appCheckDone
    apps.appCheckDone = null
    if (done) done(ok)
  }

  function nextAppCheck() {
    if (!apps.on || !apps.unknownSources) { apps.stopAppChecks(); return }
    if (!apps.appCheckQueue.length) { apps.finishAppChecks(true); return }
    var q = apps.appCheckQueue[0]
    apps.appCheckQueue = apps.appCheckQueue.slice(1)
    var rec = apps.record(q.id)
    if (!rec || rec.from !== "appFile" || apps.installOf(rec) !== q.install || !rec.updateAddress) { apps.nextAppCheck(); return }
    var j = appCheckJob.createObject(apps)
    apps.appCheckRun = j
    j.finished.connect(function(ok, output) {
      if (apps.appCheckRun !== j) return
      apps.appCheckRun = null
      Qt.callLater(function() { j.destroy() })
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, error: "the app helper failed" } }
      var have = apps.record(q.id)
      if (apps.on && apps.unknownSources && have && have.from === "appFile" && apps.installOf(have) === q.install) {
        if (!res.ok) {
          apps.appFileError = String(res.error || "its signed release note couldn't be checked")
          if (apps.appCheckForced) apps.status = "Couldn't check " + have.name + " for an update: " + apps.appFileError + "."
        } else {
          var pulled = res.revoked && res.revoked.reason ? String(res.revoked.reason) : ""
          var entry = res.update || null
          var review = entry && res.review ? res.review : null
          apps.withRecord(have.id, function(a) {
            a.updateChecked = Number(res.checked) || Math.floor(Date.now() / 1000)
            a.keyFingerprint = res.review && res.review.fingerprint ? String(res.review.fingerprint) : a.keyFingerprint
            a.revoked = pulled
            if (pulled) {
              a.enabled = false
              a.update = null
            } else if (entry && apps.newer(entry.version, a.version)) {
              var m = apps.entryManifest(entry)
              a.update = { version: entry.version, asks: apps.newAsks(a, m).map(function(x) { return x.text }), review: review }
            } else a.update = null
          })
          if (pulled) {
            apps.stopRuntime(have.id, "", "appsOff")
            apps.status = have.name + " was turned off: its developer withdrew this version. " + pulled
          } else if (res.warning) apps.status = String(res.warning)
          apps.checked = Math.max(apps.checked, Number(res.checked) || 0)
          apps.save()
        }
      }
      apps.nextAppCheck()
    })
    j.start(["/usr/bin/python3", apps.helper, "app-update-check", apps.appsDir, rec.source, rec.id])
  }

  function without(map, key) {
    var out = {}
    for (var k in map) if (k !== key) out[k] = map[k]
    return out
  }

  // ---- installing ----------------------------------------------------------
  // inspect: checked and unpacked, waiting in review for you to say yes
  function inspect(source, done) {
    if (apps.inspecting || apps.installing || apps.preparing) return false
    if (apps.updating) { apps.status = "Your apps are updating. Try again in a moment."; return false }
    apps.inspecting = true
    apps.status = ""
    apps.run(["inspect", JSON.stringify(source), apps.stagingDir], function(res) {
      apps.inspecting = false
      if (!res.ok) {
        apps.status = "Not installed: " + res.error.charAt(0).toUpperCase() + res.error.slice(1) + "."
        if (done) done(false)
        apps.nextUpdate()
        return
      }
      apps.review = apps.reviewOf(res)
      if (done) done(true)
    }, 300)
    return true
  }

  function bundledRequest(id) { return { type: "bundled", id: id, plugin: guide.pluginDir } }
  function isBundled(id) { return apps.bundled.some(function(b) { return b.id === id && b.manifest }) }
  function get(id, done) { return apps.inspect(apps.isBundled(id) ? apps.bundledRequest(id) : apps.catalogRequest(id), done) }
  function getFile(path, done) { return apps.developer && apps.inspect({ type: "file", path: String(path) }, done) }

  // A signed .tvapp picked by the user. The helper reads it no-follow and
  // contacts nothing; its returned sourceId is the pinned developer key.
  function getAppFile(path, done) {
    if (!apps.on || !apps.unknownSources || apps.inspecting || apps.installing || apps.preparing) return false
    if (apps.updating) { apps.status = "Your apps are updating. Try again in a moment."; return false }
    apps.inspecting = true
    apps.status = ""
    apps.run(["app-inspect", String(path), apps.stagingDir, apps.appsDir], function(res) {
      apps.inspecting = false
      if (!apps.on || !apps.unknownSources) {
        if (res.ok) apps.run(["discard", res.staging, apps.stagingDir], function() {}, 60)
        if (done) done(false)
        return
      }
      if (!res.ok) {
        var t = String(res.error || "it couldn't be checked")
        apps.status = "Not installed: " + t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".")
        if (done) done(false)
        return
      }
      apps.review = apps.reviewOf(res)
      if (done) done(true)
    }, 300)
    return true
  }

  function reviewOf(res) {
    var have = apps.record(res.manifest.id)
    var r = { staging: res.staging, tree: res.tree, manifest: res.manifest, sha256: res.sha256, from: res.source, file: res.sourceName,
              fingerprint: res.keyFingerprint || "", releaseUpdated: Number(res.updated) || 0, updateAddress: res.updates || "", have: have,
              asks: apps.asks(res.manifest.permissions, res.manifest.settings) }
    r.source = res.sourceId || apps.sourceFor(r)
    r.replaces = have && have.source !== r.source ? have.from : ""
    r.newAsks = have && !r.replaces ? apps.newAsks(have, res.manifest) : []
    return r
  }

  // The guide's own apps (apps/first-party in the plugin), and whether apps
  // with code can run here
  function listBundled() {
    apps.run(["bundled", guide.pluginDir], function(res) {
      if (!res.ok) return
      apps.bundled = res.apps || []
      apps.canRun = res.canRun !== false
    }, 60)
  }

  // The source an install from review gets: a file over a file keeps its
  // lineage; anything else from a file starts one
  function sourceFor(r) {
    if (r.from === "catalog") return "catalog:uber"
    if (r.from === "bundled") return "bundled"
    if (r.from === "appFile" && /^app:[0-9a-f]{16}$/.test(r.source || "")) return r.source
    if (r.have && /^file:[0-9a-f]{16}$/.test(r.have.source || "")) return r.have.source
    var hex = ""
    for (var i = 0; i < 16; i++) hex += "0123456789abcdef".charAt(Math.floor(Math.random() * 16))
    return "file:" + hex
  }

  // Yes to what's in review: exactly what you saw, or nothing
  function confirm(done) {
    var r = apps.review
    if (!r || apps.installing || apps.preparing) return
    if (r.from === "appFile" && r.updateConsent && !r.staging) { apps.prepareAppUpdate(r, done); return }
    if (apps.changing[r.manifest.id]) { apps.status = "It's being changed. Try again in a moment."; if (done) done(false); return }
    apps.installing = true
    var id = r.manifest.id
    var removed = ""   // a change of source: the name of the one removed first
    var install = function() {
      // (r.have is gone by now if it came from somewhere else)
      var was = apps.record(id)   // what withdraw takes from, given back if install changes nothing
      if (!apps.withdraw(id, r.manifest)) {
        apps.run(["discard", r.staging, apps.stagingDir], function() {}, 60)
        apps.setChanging(id, false)
        apps.installing = false
        apps.review = null
        apps.status = "Not installed: your list of apps couldn't be saved (" + apps.saveError + ")."
        if (done) done(false)
        apps.nextUpdate()
        return
      }
      apps.run(["install", r.staging, apps.appsDir, apps.dataDir, r.tree, r.source], function(res) {
        var over = function() {
          apps.setChanging(id, false)
          apps.installing = false
          apps.review = null
          if (done) done(res.ok)
          apps.nextUpdate()
        }
        if (!res.ok) {
          // what install's words don't tell: what withdraw took and couldn't
          // give back, or the one it takes the place of, removed first (gone
          // from apps.json too: saved again, in case that failed then)
          var lost = apps.giveBack(id, was, r.manifest, res)
                     + (!removed ? "" : " The " + removed + " it was to take the place of was removed first."
                                        + (apps.save() ? "" : " Your list of apps couldn't be saved (" + apps.saveError + ")."))
          if (res.retry === true) {
            // a copy that couldn't be made or didn't check out: try again (the words, for the log)
            console.warn("om-pg: installing " + id + ": " + res.error)
            apps.status = "Couldn't " + (r.have && !r.replaces ? "update " : "install ") + r.manifest.name + ". Try again." + lost
          } else apps.status = "Not installed: " + (lost ? apps.sentence(res.error) + lost : res.error)
          over()
          return
        }
        apps.keep(res, r.source, r.file, r.sha256, function(warning) {
          apps.status = (warning || res.manifest.name + (r.have && !r.replaces ? " updated to " + res.manifest.version + "." : " is installed."))
                        + (res.warning ? " " + res.warning : "")   // installed; something old left to tidy
          over()
        })
      }, 120)
    }
    apps.setChanging(id, true)
    // A signed app file is still bound to the exact signed state reviewed,
    // before anything you have is stopped or removed; install checks again.
    if (r.from === "appFile" && !r.checkedNow) {
      apps.run(["app-current", r.staging, apps.stagingDir, apps.appsDir], function(still) {
        if (apps.review !== r) { apps.setChanging(id, false); apps.installing = false; if (done) done(false); return }
        if (!still.ok) {
          apps.run(["discard", r.staging, apps.stagingDir], function() {}, 60)
          apps.setChanging(id, false)
          apps.installing = false
          apps.review = null
          var t = String(still.error || "its signed release changed")
          apps.status = "Not installed: " + t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".")
          if (done) done(false)
          apps.nextUpdate()
          return
        }
        apps.setChanging(id, false)
        apps.installing = false
        r.checkedNow = true
        apps.confirm(done)
      }, 60)
      return
    }
    r.checkedNow = false
    // what's there stops first, in order (playback finalized, the helper exited)
    apps.stopThen(id, "replaced", function() {
      if (r.replaces && r.from === "appFile") { apps.replaceSigned(r, done); return }
      if (!r.replaces) { install(); return }
      // a change of source: the old one's files, storage, secrets, log and pictures go first
      apps.run(["remove", r.have.id, r.have.source, apps.roots()], function(gone) {
        if (!gone.ok) {
          apps.setChanging(id, false)
          apps.installing = false
          apps.status = "Not installed: the one you have couldn't be removed first (" + gone.error + ")"
          if (done) done(false)
          return
        }
        apps.installed = apps.installed.filter(function(a) { return a.id !== r.have.id })
        apps.dequeue(id)      // nothing queued for the old one (a quiet update) acts on the new
        apps.clearFault(id)   // the old source's faults aren't the new one's
        apps.save()           // gone from apps.json at once, as from your disk (if this fails, the install's end saves again)
        removed = r.have.name || id
        r.have = null
        install()
      }, 60)
    })
  }

  // A signed app file taking the place of the same id from somewhere else:
  // installed first, in its own key's folder beside the old one (the helper
  // checks the signed state
  // and puts it in place as one step); only once its record is saved do the
  // old one's files, storage, secrets, log and pictures go. If the install
  // fails, or its record can't be saved (keep saves it before anything
  // changes in memory), the old one is as it was (only stopped); what the
  // new one put in its key's folder is tidied by its next
  // install of it. The app is held, and its old runtime stopped, before this.
  function replaceSigned(r, done) {
    var id = r.manifest.id
    var old = r.have
    var over = function(ok) {
      apps.setChanging(id, false)
      apps.installing = false
      apps.review = null
      if (done) done(ok)
      apps.nextUpdate()
    }
    apps.run(["install", r.staging, apps.appsDir, apps.dataDir, r.tree, r.source], function(res) {
      if (!res.ok) {
        var t = String(res.error || "it couldn't be installed")
        if (res.retry === true) console.warn("om-pg: installing " + id + ": " + t)
        apps.status = res.retry === true ? "Couldn't install " + r.manifest.name + ". Try again."
                    : "Not installed: " + t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".") + " The one you have is as it was."
        over(false)
        return
      }
      // its record in the old one's place, on disk before anything changes in memory (keep)
      apps.keep(res, r.source, r.file, r.sha256, function(warning, saved) {
        if (!saved) {
          apps.status = "Not installed: your list of apps couldn't be saved (" + apps.saveError + "). The one you have is as it was."
          over(false)
          return
        }
        apps.dequeue(id)      // nothing queued for the old one (a quiet update) acts on the new
        apps.clearFault(id)   // the old source's faults aren't the new one's
        apps.run(["remove", old.id, old.source, apps.roots()], function(gone) {
          apps.status = (warning || res.manifest.name + " is installed.") + (res.warning ? " " + res.warning : "")
                        + (gone.ok ? "" : " What was left of the " + old.name + " it replaced couldn't be removed (" + gone.error + ").")
          over(true)
        }, 60)
      }, true)
    }, 120)
  }

  // ---- signed app files ---------------------
  // A signed release entry as the review sees it, before its package exists.
  function entryManifest(entry) {
    return { id: entry.id, name: entry.name, version: entry.version, author: entry.author, description: entry.description || "",
             kind: entry.kind, api: entry.api || 1, permissions: entry.permissions, settings: [], home: [], color: entry.color || "" }
  }

  // Opens the exact consent returned by app-update-check. If the guide was
  // restarted and only the authenticated update entry is known, check the
  // signed note again first; still no package is fetched.
  function reviewAppUpdate(id, done) {
    var a = apps.record(id)
    if (!a || a.from !== "appFile" || !apps.on || !apps.unknownSources || !a.update) { if (done) done(false); return false }
    var open = function() {
      var have = apps.record(id)
      var u = have && have.update ? have.update.review : null
      if (!have || have.from !== "appFile" || !u || !u.entry || u.source !== have.source || u.id !== have.id || u.installed !== have.version) {
        if (done) done(false)
        return
      }
      var m = apps.entryManifest(u.entry)
      apps.review = { staging: "", tree: "", manifest: m, sha256: u.entry.sha256, from: "appFile", file: "Signed app file",
                      fingerprint: u.fingerprint, source: have.source, have: have, replaces: "", updateConsent: true,
                      updateReview: u, updateAddress: have.updateAddress, releaseUpdated: Number(u.updated) || 0,
                      fetchAddress: u.url, fetchSize: Number(u.size) || 0,
                      asks: apps.asks(m.permissions, m.settings), newAsks: apps.newAsks(have, m) }
      apps.status = ""
      if (done) done(true)
    }
    if (a.update.review) { open(); return true }
    return apps.checkAppFiles(true, function() { open() }, id)
  }

  // Agree to a signed update: only now is the exact package named by the
  // consent downloaded. If app.json adds an ask the signed entry could not
  // describe (a secret setting), it is staged but shown for another Agree;
  // it is never installed on the first consent.
  Component { id: prepareJob; Run { timeoutMs: 300000; maxBytes: 4 * 1024 * 1024; okCodes: [0, 1]; splitMarker: "\n" } }
  function prepareAppUpdate(r, done) {
    if (!apps.on || !apps.unknownSources || !r.updateReview) { if (done) done(false); return }
    apps.preparing = true
    apps.status = ""
    var j = prepareJob.createObject(apps)
    apps.prepareRun = j
    j.finished.connect(function(ok, output) {
      Qt.callLater(function() { j.destroy() })
      apps.prepareRun = null
      apps.preparing = false
      var res
      try { res = JSON.parse(String(output).trim().split("\n").pop()) } catch (e) { res = { ok: false, error: "the app helper failed" } }
      if (apps.review !== r || !apps.on || !apps.unknownSources) { if (res.ok) apps.run(["discard", res.staging, apps.stagingDir], function() {}, 60); apps.nextUpdate(); return }
      if (!res.ok) {
        var t = String(res.error || "it couldn't be got ready")
        apps.status = "Not installed: " + t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".")
        if (done) done(false)
        apps.nextUpdate()
        return
      }
      var asks = apps.asks(res.manifest.permissions, res.manifest.settings)
      var ready = Object.assign({}, r, { staging: res.staging, tree: res.tree, manifest: res.manifest, asks: asks,
                                        sha256: res.sha256, fingerprint: res.keyFingerprint || r.fingerprint,
                                        releaseUpdated: Number(res.updated) || r.releaseUpdated, updateAddress: res.updates || r.updateAddress,
                                        newAsks: apps.newAsks(r.have, res.manifest) })
      apps.review = ready
      if (JSON.stringify(asks) !== JSON.stringify(r.asks)) {
        apps.status = "Its package asks for more than its signed release note showed: look again, then Agree."
        if (done) done("again")
        return
      }
      apps.confirm(done)
    })
    j.start(["/usr/bin/python3", apps.helper, "app-update-prepare", apps.appsDir, r.source, r.manifest.id, apps.stagingDir], JSON.stringify(r.updateReview))
  }

  // A signed update getting ready, stopped: its process killed (Run.cancel:
  // no answer comes, and what it half staged goes with staging's
  // leftovers), so nothing more is fetched for it and nothing waits on it
  function stopPreparing() {
    var j = apps.prepareRun
    if (!j) return
    apps.prepareRun = null
    apps.preparing = false
    j.cancel()
    j.destroy()
  }

  // No to what's in review (not while it's installing: that's said and done)
  function cancel() {
    if (apps.installing) return false
    apps.stopPreparing()   // a source's app still getting ready: stopped
    if (apps.review && apps.review.staging) apps.run(["discard", apps.review.staging, apps.stagingDir], function() {}, 60)
    apps.review = null
    apps.nextUpdate()
    return true
  }

  // What version m takes away from the one installed: the secrets of the
  // secret settings it dropped, and "signIn" if it no longer signs in
  function dropsOf(have, m) {
    if (!have) return []
    var out = (have.settings || []).filter(function(st) {
      return st.type === "secret" && !(m.settings || []).some(function(n) { return n.type === "secret" && n.key === st.key })
    }).map(function(st) { return st.key })
    if (have.permissions && have.permissions.signIn && !(m.permissions && m.permissions.signIn)) out.push("signIn")
    return out
  }

  // Before an update's package goes in (bin/om-pg-apps install deletes the
  // one there), what it takes away is withdrawn from the record (no longer
  // marked set or signed in) and owed as a clean-up, on disk. Whatever
  // happens after (a save or a clear that fails, the guide cut off), the
  // record on disk never again marks what the new version dropped, so no
  // later version is handed those bytes. False (nothing is installed) if
  // that couldn't be saved. The caller holds the app.
  function withdraw(id, m) {
    var drop = apps.dropsOf(apps.record(id), m)
    if (!drop.length) return true
    return apps.commit(id, function(a) {
      var v = {}
      for (var k in a.values || {}) v[k] = a.values[k]
      drop.forEach(function(x) { delete v[x === "signIn" ? "@signedIn" : "@secret:" + x] })
      var owed = apps.pending(a, "@clear")
      v["@clear"] = owed.concat(drop.filter(function(x) { return owed.indexOf(x) < 0 }))
      a.values = v
    })
  }

  // The helper's words ending a sentence, followed by what the guide itself
  // did first (what withdraw took and couldn't give back, the one it takes
  // the place of removed): a trailing ; or , dropped, and so is install's
  // "so nothing changed" (true of install alone, it isn't of the whole)
  function sentence(t) { var s = String(t || "").replace(/,?\s*so nothing changed[.!]?\s*$/, "").replace(/[;,\s]+$/, ""); return s + (/[.!?]$/.test(s) ? "" : ".") }

  // What withdraw took, given back when install says nothing on disk
  // changed (res.unchanged) and the record is still the install it took
  // from (was: that record, just before; another in its place has nothing
  // of it): the marks it removed put back and the names it added no longer
  // owed, in the order the record had them, anything else changed meanwhile
  // kept. The caller still holds the app, so nothing runs it in between.
  // Otherwise (any other failure, or a save that fails) it stays withdrawn,
  // as is safe: what's said then of the secrets and sign-in it had ("" if
  // nothing).
  function giveBack(id, was, m, res) {
    var drop = apps.dropsOf(was, m)
    if (!drop.length || apps.installOf(apps.record(id)) !== apps.installOf(was)) return ""
    var marks = drop.map(function(x) { return x === "signIn" ? "@signedIn" : "@secret:" + x })
    var had = was.values || {}
    var owed = apps.pending(was, "@clear")
    if (res.unchanged === true && apps.commit(id, function(a) {
      var now = a.values || {}
      var clear = apps.pending(a, "@clear").filter(function(x) { return drop.indexOf(x) < 0 || owed.indexOf(x) >= 0 })
      var v = {}
      var put = function(k) {
        if (k in v) return
        if (k === "@clear") { if (clear.length) v[k] = clear }
        else if (marks.indexOf(k) >= 0 && had[k] !== undefined) v[k] = had[k]
        else if (now[k] !== undefined) v[k] = now[k]
      }
      for (var k in had) put(k)
      for (var k2 in now) put(k2)
      a.values = v
    })) return ""
    var lost = drop.filter(function(x, i) { return had[marks[i]] === true }).map(function(x) {
      var st = (was.settings || []).filter(function(s) { return s.key === x })[0]
      return x === "signIn" ? "sign-in" : st && st.label ? st.label : x
    })
    if (!lost.length) return ""
    return " Its " + (lost.length === 1 ? lost[0] + " is" : lost.slice(0, -1).join(", ") + " and " + lost[lost.length - 1] + " are")
           + " cleared before it next starts: set " + (lost.length === 1 ? "it" : "them") + " again then."
  }

  // What install says, kept: a new app on, an update as it was (its
  // settings, server and sign-in kept, settings that went away dropped).
  // then(warning, saved): saved, whether its record reached apps.json with
  // keep's own save (before anything is cleared). replaces: it takes the
  // place of the same id from somewhere else (replaceSigned), saved
  // before anything changes in memory; if it can't be, nothing has
  // (then("", false))
  function keep(res, source, file, sha, then, replaces) {
    var m = res.manifest
    var have = apps.record(m.id)
    if (have && have.source !== source) have = null
    var from = apps.fromOf(source)
    var now = Math.floor(Date.now() / 1000)
    // A catalog withdrawal that arrived while it installed still wins. A
    // signed app-file install itself is refused by the helper if withdrawn.
    var pulled = from === "catalog" ? apps.pulledReason(m.id, m.version) : ""
    var said = !pulled ? "" : m.name + " was turned off: the catalog pulled it. " + pulled
    var told = !said ? then : function(w, ok) { then(said + (String(w || "").trim() ? " " + String(w).trim() : ""), ok) }
    // The reviewed signed release owns this value, including an explicit
    // "no update address". Falling back on the old record for an empty value
    // would keep scheduling failed update checks after the developer removed it.
    var reviewedUpdate = from === "appFile" && apps.review && apps.review.from === "appFile"
                         && apps.review.manifest && apps.review.manifest.id === m.id
                         ? String(apps.review.updateAddress || "") : String(have && have.updateAddress || "")
    var values = {}
    var old = have && have.values ? have.values : {}
    ;(m.settings || []).forEach(function(st) {
      if (st.type !== "secret" && old[st.key] !== undefined) values[st.key] = old[st.key]
      if (st.type === "secret" && old["@secret:" + st.key]) values["@secret:" + st.key] = true   // still declared: still set
    })
    // clean-ups not done yet stay with it
    if (apps.pending(have, "@forget").length) values["@forget"] = apps.pending(have, "@forget")
    if (apps.pending(have, "@clear").length) values["@clear"] = apps.pending(have, "@clear")
    // signed in stays signed in while it still signs in to a server
    if (have && old["@signedIn"] && m.permissions.server && m.permissions.signIn && have.permissions && have.permissions.signIn) values["@signedIn"] = true
    // what this version no longer asks for goes: secrets of settings it
    // dropped, and what a sign-in kept if it no longer signs in (withdraw
    // owed them before the package went in). Owed with the record itself,
    // so if clearing them below fails or is cut off, the next start does
    var clears = apps.dropsOf(have, m)
    if (clears.length) values["@clear"] = (values["@clear"] || []).concat(clears.filter(function(k) { return (values["@clear"] || []).indexOf(k) < 0 }))
    var rec = { id: m.id, name: m.name, version: m.version, author: m.author, description: m.description, api: m.api || 1, kind: m.kind, layout: m.api >= 3 ? apps.checkedLayout(m.layout) : null,
                color: m.color, icon: m.icon ? res.path + "/" + m.icon : "", launch: m.launch || null, permissions: m.permissions,
                source: source, sourceDir: res.sourceDir, from: from, file: from === "file" ? String(file) : "",
                catalogName: from === "catalog" ? String(file || "") : "",
                keyFingerprint: from === "appFile" ? String(res.keyFingerprint || "") : "",
                updateAddress: from === "appFile" ? reviewedUpdate : "",
                updateChecked: from === "appFile" && have ? Number(have.updateChecked) || 0 : 0,
                releaseUpdated: from === "appFile" ? Number((apps.review && apps.review.releaseUpdated) || 0) : 0,
                sha256: sha, files: res.files, installed: have ? have.installed : now, updated: now, used: have ? have.used || 0 : 0,
                enabled: !pulled && (have ? have.enabled !== false : true), broken: "", revoked: pulled,
                update: null,
                main: m.main || "", settings: m.settings || [], home: m.home || [], values: values,
                server: have && m.permissions.server ? have.server || "" : "", pin: have && m.permissions.server ? have.pin || "" : "",
                // an update keeps its incarnation; a first install, a reinstall after a
                // removal or a change of source (have is null then) gets a new one
                incarnation: have && have.incarnation ? have.incarnation : apps.newIncarnation() }
    var list = have ? apps.installed.map(function(a) { return a.id === m.id ? rec : a })
                    : apps.installed.filter(function(a) { return !replaces || a.id !== m.id }).concat([rec])
    if (replaces) {
      if (!apps.save(list)) { then("", false); return }
      apps.installed = list.filter(function(a) { return a.id !== m.id })   // the old one gone, as any removal, then the new one in
    }
    apps.installed = list
    apps.setChecked(m.id, true)   // just checked, by the install itself
    // on disk before anything is cleared (save() returns once it's written),
    // so a guide cut off from here on still owes what this records
    var saved = replaces || apps.save()
    var unsaved = saved ? "" : " Your list of apps couldn't be saved (" + apps.saveError + ")."
    apps.authChanged(m.id)        // an update or reinstall: Home's cached rows aren't its own
    // a launcher never starts a runtime to do what it owes first: all of it
    // is done here, and at the guide's next start if this fails (settle)
    if (rec.kind === "launcher") {
      apps.settle(m.id, function(why) { told((why ? "Couldn't clear what " + m.name + " no longer uses (" + why + "). It's tried again when the guide next starts." : "") + unsaved, saved) })
      return
    }
    // cleared in one write (bin/om-pg-apps secret-clear), and the update
    // isn't over (the app still held: nothing runs it) until that's done
    var secrets = apps.secretsDir + "/" + res.sourceDir + "/" + m.id + ".json"
    if (!clears.length) { told(unsaved.trim(), saved); return }
    apps.run(["secret-clear", secrets].concat(clears), function(r) {
      if (r.ok) apps.unpend(m.id, "@clear", clears)
      told((r.ok ? "" : "Couldn't clear the secrets " + m.name + " no longer uses (" + r.error + "). It can't read them, and they're cleared before it next starts.") + unsaved, saved)
    }, 30)
  }

  // What a launcher still owes from when it was an app with code (an update
  // that changed its kind): it never starts a runtime to do it first, so
  // the guide does, at that update and at each start of the guide until
  // it's done. The caller holds it (changing). then(why it failed, or "").
  function settle(id, then) {
    var a = apps.record(id)
    if (!a || a.kind !== "launcher" || !a.source || !a.sourceDir) { then(""); return }
    var forget = apps.pending(a, "@forget"), clear = apps.pending(a, "@clear")
    var next = function(i) {
      if (i < forget.length) { apps.forget(id, forget[i], function(ok, why) { if (ok) next(i + 1); else then(why) }); return }
      if (!clear.length) { then(""); return }
      apps.run(["secret-clear", apps.secretsDir + "/" + a.sourceDir + "/" + id + ".json"].concat(clear), function(r) {
        if (r.ok) apps.unpend(id, "@clear", clear)
        then(r.ok ? "" : r.error)
      }, 30)
    }
    next(0)
  }
  function settleAll() {
    apps.installed.forEach(function(a) {
      if (a.kind !== "launcher" || apps.changing[a.id] || !(apps.pending(a, "@forget").length || apps.pending(a, "@clear").length)) return
      apps.setChanging(a.id, true)
      apps.settle(a.id, function(why) {
        apps.setChanging(a.id, false)
        if (why) apps.status = "Couldn't clear what " + a.name + " no longer uses (" + why + "). It's tried again when the guide next starts."
      })
    })
  }

  function setChecked(id, ok) {
    var out = {}
    for (var k in apps.checkedIds) out[k] = apps.checkedIds[k]
    if (ok) out[id] = true
    else delete out[id]
    apps.checkedIds = out
  }

  // Why nothing more can be done to an app now (removing it, say): something
  // being installed, or this one being updated or changed ("" if it can)
  function busyWith(id) {
    if (apps.installing || (apps.updating && apps.updateQueue.length && apps.updateQueue[0].id === id)) return "It's being installed. Try again in a moment."
    if (apps.changing[id]) return "It's being changed. Try again in a moment."
    return ""
  }

  // An app's record gone, or another in its place: no quiet update waits
  // for it, and nothing's owed from before proof was kept
  function dequeue(id) {
    apps.updateQueue = apps.updateQueue.filter(function(x) { return x.id !== id })
    apps.unproven = apps.without(apps.unproven, id)
  }

  // An app and everything of it removed. install (installOf): only if it's
  // still that install, refused at once if another has taken its place
  // (removed and installed again, from here or elsewhere). False if
  // refused at once.
  function remove(id, done, install) {
    var a = apps.record(id)
    if (!a || (install !== undefined && apps.installOf(a) !== install)) return false
    var busy = apps.busyWith(id)
    if (busy) { apps.status = busy; return false }
    var mine = apps.installOf(a)
    var source = a.source || "catalog:uber"
    apps.setChanging(id, true)
    // its runtime gone first (playback reported removed and finalized, the
    // helper exited, so nothing of it writes again), then everything of it
    apps.stopThen(id, "removed", function() { apps.run(["remove", id, source, apps.roots()], function(res) {
      apps.setChanging(id, false)
      if (res.ok) {
        apps.clearFault(id)
        var name = (apps.record(id) || {}).name || id
        if (apps.installOf(apps.record(id)) === mine) {   // (held all along, so it is: checked all the same)
          apps.installed = apps.installed.filter(function(x) { return x.id !== id })
          apps.dequeue(id)
          apps.setChecked(id, false)
        }
        apps.status = name + " was removed."
        apps.save()
      } else apps.status = "Couldn't remove it: " + res.error
      if (done) done(res.ok)
    }, 60) })
    return true
  }

  function sameFiles(a, b) {
    var ka = Object.keys(a || {}), kb = Object.keys(b || {})
    return ka.length === kb.length && ka.every(function(k) { return a[k] === b[k] })
  }

  // Each installed app as it is on disk: catalog proof, signed app-file proof
  // and pinned key, bundled copy, or an unsigned Developer-mode file. What it
  // shows and opens comes only from that checked app.json. A failure turns it
  // off; none opens until this check has passed.
  function verify() {
    if (!apps.installed.length || apps.migrating) return
    var started = Math.floor(Date.now() / 1000)
    apps.run(["verify", apps.appsDir, apps.signers, guide.pluginDir], function(res) {
      if (!res.ok) {
        apps.status = "Couldn't check your apps (" + res.error + "), so they won't open until they can be."
        return
      }
      if (res.apps.some(function(x) { return x.legacy })) { apps.migrate(); return }
      var found = {}
      for (var i = 0; i < res.apps.length; i++) found[res.apps[i].sourceDir + "/" + res.apps[i].id + "@" + res.apps[i].version] = res.apps[i]
      var bundledAgain = []
      var said = []
      var ok = {}
      var again = []
      for (var k in apps.checkedIds) ok[k] = apps.checkedIds[k]
      apps.installed = apps.installed.map(function(a) {
        if (a.updated >= started) return a   // installed while this ran: checked by its install
        var copy = {}
        for (var key in a) copy[key] = a[key]
        var f = found[a.sourceDir + "/" + a.id + "@" + a.version]
        var why = !f ? "its files are gone" : f.problem
        var withdrawn = a.from === "appFile" && why && /^the developer withdrew this version:\s*/i.test(why)
                        ? why.replace(/^the developer withdrew this version:\s*/i, "") : ""
        if (withdrawn) {
          delete ok[a.id]
          if (!a.revoked) said.push(a.name + " was turned off: its developer withdrew this version. " + withdrawn)
          copy.enabled = false
          copy.broken = ""
          copy.revoked = withdrawn
          copy.update = null
          return copy
        }
        if (!why && a.from === "file" && !apps.sameFiles(f.files, a.files)) why = "its files were changed after it was installed"
        if (!why && a.from === "appFile" && f.proof !== "appFile") why = "it can't be traced back to its signed app file"
        if (!why && a.from === "appFile") {
          copy.keyFingerprint = f.keyFingerprint || ""
          copy.revoked = ""
          copy.update = f.update && apps.newer(f.update.version, a.version)
                        ? { version: f.update.version, asks: apps.newAsks(a, apps.entryManifest(f.update)).map(function(x) { return x.text }) }
                        : null
        }
        if (!why && a.from === "bundled" && f.proof === "bundledChanged") {
          // the guide was updated and its copy changed: installed again from it
          if (apps.isBundled(a.id) || !apps.bundled.length) { bundledAgain.push(apps.queued(copy)); delete ok[a.id]; return copy }
          why = "Uber TV doesn't come with it any more"
        }
        delete ok[a.id]
        if (!why && a.from === "catalog" && f.proof !== "catalog") {
          // installed before the guide kept proof: installed again from the catalog
          again.push(apps.queued(copy))
          return copy
        }
        if (why) {
          if (!a.broken) { copy.enabled = false; said.push(a.name + " was turned off: " + why + ".") }
          copy.broken = why.charAt(0).toUpperCase() + why.slice(1)
          return copy
        }
        var m = f.manifest
        copy.broken = ""
        copy.name = m.name
        copy.author = m.author
        copy.description = m.description
        copy.color = m.color
        copy.launch = m.launch || null
        copy.permissions = m.permissions
        copy.kind = m.kind
        copy.api = m.api || 1
        copy.layout = m.api >= 3 ? apps.checkedLayout(m.layout) : null
        copy.main = m.main || ""
        copy.settings = m.settings || []
        copy.home = m.home || []
        copy.icon = m.icon ? apps.appsDir + "/" + a.sourceDir + "/" + a.id + "/" + a.version + "/" + m.icon : ""
        if (m.kind === "launcher" && !apps.linkOk(copy.launch.web, copy.permissions)) { copy.broken = "Its link isn't right"; return copy }
        ok[a.id] = true
        return copy
      })
      apps.checkedIds = ok
      if (said.length) apps.status = said.join(" ")
      apps.save()
      if (bundledAgain.length && apps.on) apps.queueUpdates(bundledAgain)
      if (again.length) {
        var u = {}
        for (var x in apps.unproven) u[x] = apps.unproven[x]
        again.forEach(function(q) { u[q.id] = q.install })
        apps.unproven = u
        // the catalog first (its signed copy is what they're installed from);
        // only what's still the install it was then (one put in its place
        // meanwhile isn't the catalog's)
        if (apps.on) apps.fetchCatalog(function(r) {
          if (r.ok) { apps.queueUpdates(again); return }
          again.forEach(function(q) {
            if (apps.installOf(apps.record(q.id)) === q.install) apps.withRecord(q.id, function(a) { a.broken = "It can't be traced back to the catalog (" + r.error + ")" })
          })
          apps.unproven = ({})
        })
      }
    }, 300)
  }

  // ---- opening one ---------------------------------------------------------
  // Why it can't open now ("" when it can)
  function cannotOpen(id) {
    var a = apps.record(id)
    if (!a) return "not installed"
    if (!apps.on) return "apps are off"
    if (a.revoked) return Asks.pulledBy(a.from)
    if (a.broken) return a.broken
    if (!a.enabled) return "it's off"
    if (a.from === "file" && !apps.developer) return "it's from a file, and Developer mode is off"
    if (a.from === "appFile" && !apps.unknownSources) return "it's a third-party app, and third-party apps are off"
    if (apps.migrating || !apps.checkedIds[id]) return "it's still being checked"
    if (a.kind === "app") {
      if (!apps.canRun) return "apps with code can't run on this system (they need bubblewrap, /usr/bin/bwrap)"
      return ""
    }
    if (!apps.linkOk(a.launch ? a.launch.web : "", a.permissions)) return "its link isn't right"
    return ""
  }

  // Whether a window is this app's: a web app's is
  // "<browser>-<host>__<path>-<profile>" (Chromium and its kin), its host
  // exactly ("xtv.youtube.com" isn't tv.youtube.com)
  function isWindowOf(id, t) {
    var a = apps.record(id)
    var url = a && a.launch ? String(a.launch.web || "") : ""
    if (!t || !/^https:\/\//.test(url)) return false
    var host = url.slice(8).split(/[\/?#]/)[0].toLowerCase()
    var appId = String(t.appId || "").toLowerCase()
    var dash = appId.indexOf("-")
    return dash > 0 && /^[a-z0-9]+$/.test(appId.slice(0, dash)) && appId.slice(dash + 1, dash + 3 + host.length) === host + "__"
  }

  // The windows open now
  function windows() {
    var list = ToplevelManager.toplevels ? ToplevelManager.toplevels.values : []
    var out = []
    for (var i = 0; i < list.length; i++) out.push(list[i])
    return out
  }

  // Starts it: omarchy-launch-webapp, which quotes the link (never through a
  // shell), in your browser, so you're signed in as you are there
  function start(id) {
    if (apps.cannotOpen(id) || apps.record(id).kind !== "launcher") return
    Quickshell.execDetached(["/usr/share/omarchy/bin/omarchy-launch-webapp", apps.record(id).launch.web])
  }

  // ---- apps with code: their runtimes ------------------------------------
  // At most 3 at once. Asked for one more, the least recently used with no
  // lease and no call out (nothing on the screen, nothing playing) stops;
  // failing that, one that only holds Home rows makes room. An app being
  // changed (a sign-out, a new secret or server, an update) is never stopped
  // to make room (AppBudget.js). Off, removed, apps off and Developer mode
  // off (a file's app) stop it first.
  Component { id: runtimeKind; AppRuntime {} }

  function runtime(id) { return apps.runtimes[id] || null }

  // A running (or starting) runtime for id, holding lease; null and why
  // when it can't have one now
  // Runtimes that count toward the budget: starting, running or stopping
  function live() {
    var n = 0
    for (var k in apps.runtimes) if (["starting", "ready", "stopping"].indexOf(apps.runtimes[k].phase) >= 0) n++
    return n
  }

  // Queued ones start as slots free up, the oldest first
  function startQueued() {
    var q = Object.keys(apps.runtimes).filter(function(k) { return apps.runtimes[k].phase === "queued" })
                  .sort(function(x, y) { return apps.runtimes[x].gen - apps.runtimes[y].gen })
    for (var i = 0; i < q.length && apps.live() < apps.budget; i++) apps.runtimes[q[i]].start()
  }

  // Apps being changed (installed, updated, removed): no runtime meanwhile
  // and anything else that changes one while it runs (a secret, its server,
  // a restart with what goes with it): one at a time, each checking first
  property var changing: ({})
  function setChanging(id, on) { apps.changing = on ? apps.withKey(apps.changing, id, true) : apps.without(apps.changing, id) }

  // Its runtime stopped, in order (its playback finalized, then the helper
  // stopped and exited, so nothing of it writes again), then then()
  function stopThen(id, reason, then) {
    var rt = apps.runtimes[id]
    if (!rt || rt.phase === "stopped" || rt.phase === "queued") { if (rt) rt.stop(""); then(); return }
    var done = false
    var fin = function() { if (done) return; done = true; then() }
    rt.stopped.connect(fin)
    guide.finishAppPlayback(id, reason || "runtime", function() { if (rt.phase === "stopped") fin(); else rt.stop("") })
  }

  function ensure(id, lease) {
    var why = apps.cannotOpen(id)
    if (!why && apps.changing[id]) why = "it's being changed; try again in a moment"
    var a = apps.record(id)
    if (!why && (!a || a.kind !== "app")) why = "it isn't an app with code"
    if (!why && apps.unavailable[id]) why = apps.unavailable[id]
    if (!why && apps.faulted[id] && lease !== "foreground") why = "it stopped working: " + apps.faulted[id]
    if (why) return { rt: null, why: why }
    var rt = apps.runtimes[id]
    if (rt && rt.phase === "stopped") {
      // finished, whoever heard it stop first: a new one takes its place
      var left = {}
      for (var r in apps.runtimes) if (r !== id) left[r] = apps.runtimes[r]
      apps.runtimes = left
      rt = null
    }
    if (rt && rt.phase === "stopping") return { rt: null, why: "it's stopping; try again in a moment" }
    if (!rt) {
      // at the budget (starting, running and stopping ones all count): the
      // least recently used one with nothing on the screen stops, and this
      // one waits, queued, until a slot is really free
      var wait = apps.live() >= apps.budget
      if (wait) {
        var now = {}
        for (var x in apps.runtimes) {
          var o = apps.runtimes[x]
          now[x] = { phase: o.phase, leases: o.leases, busy: o.busy, lastUsed: o.lastUsed }
        }
        var room = Budget.makeRoom(now, apps.changing, lease)
        if (room.refuse) return { rt: null, why: "three apps are busy" }
        if (room.stop) apps.stopRuntime(room.stop, "", "runtime")
      }
      apps.gens += 1
      rt = runtimeKind.createObject(apps, { store: apps, record: a, gen: apps.gens, settings: apps.valuesOf(a), server: a.server || "", phase: "queued" })
      rt.stopped.connect(function(w, text) { apps.runtimeStopped(id, rt, w, text) })
      rt.updated.connect(function(v, rows, items) { apps.liveUpdated(id, rt, v, rows, items) })
      var m = {}
      for (var k in apps.runtimes) m[k] = apps.runtimes[k]
      m[id] = rt
      apps.runtimes = m
      if (!wait) rt.start()
    }
    if (lease) rt.lease(lease, true)
    return { rt: rt, why: "" }
  }

  // The non-secret settings an app starts with
  function valuesOf(a) {
    var out = {}
    ;(a.settings || []).forEach(function(st) { if (st.type !== "secret" && a.values && a.values[st.key] !== undefined) out[st.key] = a.values[st.key] })
    return out
  }

  // Ordered: if it's playing, playback ends first (its last report goes out
  // while the app still runs), then the app stops
  function stopRuntime(id, forget, reason) {
    var rt = apps.runtimes[id]
    if (!rt) return
    guide.finishAppPlayback(id, reason || "runtime", function() { rt.stop(forget || "") })
  }

  function stopAll() { for (var id in apps.runtimes) apps.stopRuntime(id, "", "appsOff") }

  function runtimeStopped(id, rt, why, text) {
    if (apps.runtimes[id] === rt) {
      var m = {}
      for (var k in apps.runtimes) if (k !== id) m[k] = apps.runtimes[k]
      apps.runtimes = m
    }
    Qt.callLater(function() { rt.destroy() })
    Qt.callLater(apps.startQueued)   // a slot is free
    guide.appPlayback.runtimeGone(id)   // playing when it stopped on its own: the media stops, and it's said
    if (why === "unavailable") {
      apps.unavailable = apps.withKey(apps.unavailable, id, text || "the system can't run it")
      return
    }
    if (["crash", "violation", "timeout", "start"].indexOf(why) < 0) return
    var now = Date.now()
    var list = (apps.faults[id] || []).filter(function(t) { return now - t < 5 * 60 * 1000 }).concat([now])
    apps.faults = apps.withKey(apps.faults, id, list)
    if (list.length >= 3) apps.faulted = apps.withKey(apps.faulted, id, text || why)
  }

  // You opened it: a fault or "can't run" is tried again
  function clearFault(id) {
    apps.faults = apps.without(apps.faults, id)
    apps.faulted = apps.without(apps.faulted, id)
    apps.unavailable = apps.without(apps.unavailable, id)
  }

  function withKey(map, key, value) {
    var out = {}
    for (var k in map) out[k] = map[k]
    out[key] = value
    return out
  }

  // Off is off: a runtime whose app can't open any more stops
  onReadyChanged: {
    for (var id in apps.runtimes) if (!apps.ready.some(function(a) { return a.id === id })) apps.stopRuntime(id, "", apps.record(id) ? "appsOff" : "removed")
  }

  // Idle: no lease and nothing waiting for 3 minutes
  Timer {
    interval: 30000
    repeat: true
    running: Object.keys(apps.runtimes).length > 0
    onTriggered: {
      var now = Date.now()
      for (var id in apps.runtimes) {
        var rt = apps.runtimes[id]
        if (!rt.leased && !rt.busy && now - rt.lastUsed > 180000) apps.stopRuntime(id, "", "runtime")
      }
    }
  }

  // Scopes a guide before this one left behind (a crash): only ones named
  // exactly om-pg-app-<source>-<id>-<gen>
  Run {
    id: leftovers
    timeoutMs: 8000
    maxBytes: 256 * 1024
    onFinished: function(ok, output) {
      if (!ok) return
      var names = output.split("\n").map(function(l) { return l.trim().split(/\s+/)[0] })
                        .filter(function(n) { return /^om-pg-app-[0-9a-f]{16}-[0-9a-f]{12}-[0-9]+\.scope$/.test(n || "") })
      var mine = []
      for (var id in apps.runtimes) mine.push(apps.runtimes[id].unit + ".scope")
      names = names.filter(function(n) { return mine.indexOf(n) < 0 })
      if (names.length) Quickshell.execDetached(["/usr/bin/systemctl", "--user", "stop"].concat(names))
    }
  }
  property bool sweep: true   // (false: a test's own Apps leaves the guide's apps running)
  Component.onCompleted: if (apps.sweep) leftovers.start(["/usr/bin/systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "--type=scope", "om-pg-app-*"])

  // ---- moving apps from before sources ------------------------------------
  // Apps installed before sources (<apps>/<id>/<version>) move into the
  // (source, id) layout, once: one from the catalog stays the catalog's
  // (if its proof is missing or untrusted, verify installs it again from the
  // catalog), one from a file gets a lineage of its own. bin/om-pg-apps keeps
  // a journal, so an interrupted move finishes with the same decisions.
  function migrate() {
    if (apps.migrating) return
    apps.migrating = true
    var legacy = apps.installed.filter(function(a) { return !a.source }).map(function(a) { return { id: a.id, from: a.from } })
    apps.run(["migrate", apps.appsDir, apps.journal, JSON.stringify(legacy)], function(res) {
      apps.migrating = false
      if (!res.ok) { apps.status = "Couldn't move your apps to the new layout (" + res.error + "), so they won't open until they can be."; return }
      apps.installed = apps.installed.map(function(a) {
        var mv = res.moved[a.id]
        if (!mv) return a
        var copy = {}
        for (var k in a) copy[k] = a[k]
        copy.source = mv.source
        copy.sourceDir = mv.sourceDir
        copy.from = apps.fromOf(mv.source)
        if (copy.icon && copy.icon.indexOf(apps.appsDir + "/" + a.id + "/") === 0)
          copy.icon = apps.appsDir + "/" + mv.sourceDir + "/" + copy.icon.slice(apps.appsDir.length + 1)
        return copy
      })
      apps.save()
      apps.verify()
      apps.freshen()   // the catalog only once every app has its source
    }, 120)
  }

  function used(id) {
    apps.withRecord(id, function(x) { x.used = Math.floor(Date.now() / 1000) })
    apps.save()
  }

  // ---- apps.json -----------------------------------------------------------
  // Written before save() returns (blockWrites; a new file put in place of
  // the old, so one cut off leaves the old whole), by a FileView made for
  // this save alone, then read back from disk: Quickshell 0.3.1 reports a
  // replace that failed as saved, and a FileView whose write failed keeps
  // what it tried as if it were written (the same text again isn't
  // written at all). True only if what's on disk is what was saved;
  // otherwise false, and saveError says why. installed: the list to save in
  // place of the one in memory (giveIncarnations: one that's in memory only
  // once it's on disk).
  property string saveError: ""
  Component { id: stateWriter; FileView { blockWrites: true; preload: false; printErrors: false } }
  Component { id: stateReader; FileView { blockLoading: true; printErrors: false } }
  property Component writerKind: stateWriter   // (tests/appstate.test.py swaps in one that writes nothing)
  function save(installed) {
    if (!apps.loaded || apps.guide.wiping) return false
    var text = JSON.stringify({ on: apps.on, developer: apps.developer,
                                unknownSources: apps.unknownSources, catalogSeen: apps.catalogSeen, checked: apps.checked,
                                catalog: apps.catalogSource || undefined, installed: installed || apps.installed }, null, 2) + "\n"
    var failed = ""
    var w = apps.writerKind.createObject(apps, { path: apps.statePath })
    w.saveFailed.connect(function(error) { failed = FileViewError.toString(error) || "it couldn't be written" })
    w.setText(text)
    w.destroy()
    if (!failed) {
      var r = stateReader.createObject(apps, { path: apps.statePath })
      if (r.text() !== text) failed = "what's on disk isn't what was written"
      r.destroy()
    }
    apps.saveError = failed
    if (!failed) privateState.running = true   // what you installed, yours alone
    return !failed
  }

  // A change that must be on disk before anything acts on it: made, saved,
  // and taken back if it couldn't be (false; saveError says why). change
  // gets a shallow copy: it replaces fields (a new values), never changes
  // one in place, or the record taken back would be changed too.
  function commit(id, change) {
    var was = apps.record(id)
    if (!was) { apps.saveError = "it isn't installed"; return false }
    apps.withRecord(id, change)
    if (apps.save()) return true
    var why = apps.saveError
    apps.installed = apps.installed.map(function(a) { return a.id === id ? was : a })
    apps.saveError = why
    return false
  }

  function checkedServer(sv, str) {
    var out = { label: str(sv.label, 40), defaultPort: Number(sv.defaultPort) || 0 }
    if (sv.fromSignIn === true) out.fromSignIn = true
    return out
  }

  function checkedRecord(a) {
    if (!a || typeof a !== "object" || typeof a.id !== "string" || !/^[a-z][a-z0-9.-]{2,190}$/.test(a.id)) return null
    if (typeof a.version !== "string" || !/^\d+\.\d+\.\d+$/.test(a.version)) return null
    var str = function(v, n) { return typeof v === "string" ? v.slice(0, n) : "" }
    var code = a.kind === "app"
    var p = a.permissions && typeof a.permissions === "object" ? a.permissions : {}
    var hosts = function(list) { return (Array.isArray(list) ? list : []).filter(function(d) { return typeof d === "string" && /^[a-z0-9.-]{4,253}$/.test(d) }) }
    var net = hosts(p.net)
    var writes = {}
    if (code && p.netWrite && typeof p.netWrite === "object")
      for (var wh in p.netWrite)
        if (net.indexOf(wh) >= 0 && Array.isArray(p.netWrite[wh])) {
          var ms = apps.writeMethods.filter(function(x) { return p.netWrite[wh].indexOf(x) >= 0 })
          if (ms.length) writes[wh] = ms
        }
    var perms = code ? { net: net, netWrite: writes, server: p.server && typeof p.server === "object" ? apps.checkedServer(p.server, str) : null,
                         play: p.play === true, signIn: ["code", "password", "code+password"].indexOf(p.signIn) >= 0 ? p.signIn : "", storage: p.storage === true }
                     : { web: hosts(p.web) }
    // a record from before sources has none: migrate() gives it one
    var source = typeof a.source === "string" && /^(catalog:uber|bundled|file:[0-9a-f]{16}|app:[0-9a-f]{16}|source:[0-9a-f]{16})$/.test(a.source) ? a.source : ""
    var rec = { id: a.id, name: str(a.name, 40) || a.id, version: a.version, author: str(a.author, 60), description: str(a.description, 300),
                api: code ? (a.api === 3 || a.api === 4 ? a.api : 2) : 1, kind: code ? "app" : "launcher", color: /^#[0-9a-f]{6}$/.test(a.color) ? a.color : "", icon: str(a.icon, 400),
                layout: code && a.api >= 3 ? apps.checkedLayout(a.layout) : null,
                launch: code ? null : { web: a.launch && typeof a.launch.web === "string" ? a.launch.web : "" }, permissions: perms,
                source: source, sourceDir: source && /^[0-9a-f]{16}$/.test(a.sourceDir || "") ? a.sourceDir : "",
                from: source ? apps.fromOf(source) : a.from === "file" ? "file" : "catalog", file: str(a.file, 1000), catalogName: str(a.catalogName, 60), sha256: str(a.sha256, 64),
                keyFingerprint: /^SHA256:[A-Za-z0-9+\/]{43}$/.test(a.keyFingerprint || "") ? a.keyFingerprint : "",
                // lib/appfiles.py accepts a canonical update folder up to
                // 2,048 characters. Keep that same bound here: silently
                // dropping a longer valid one on restart would also stop
                // its signed withdrawal notices.
                updateAddress: typeof a.updateAddress === "string" && a.updateAddress.length <= 2048
                               && /^https:\/\/[^\s]+\/$/.test(a.updateAddress) ? a.updateAddress : "",
                updateChecked: Number(a.updateChecked) || 0, releaseUpdated: Number(a.releaseUpdated) || 0,
                files: a.files && typeof a.files === "object" ? a.files : {}, installed: Number(a.installed) || 0, updated: Number(a.updated) || 0,
                used: Number(a.used) || 0, enabled: a.enabled !== false, broken: str(a.broken, 200), revoked: str(a.revoked, 200),
                update: a.update && typeof a.update.version === "string" ? { version: a.update.version, asks: Array.isArray(a.update.asks) ? a.update.asks.map(String) : [] } : null,
                main: code ? str(a.main, 64) : "", settings: code && Array.isArray(a.settings) ? a.settings : [], home: code && Array.isArray(a.home) ? a.home : [],
                values: code && a.values && typeof a.values === "object" ? a.values : apps.owed(a.values), server: code ? str(a.server, 500) : "",
                pin: code && /^[0-9a-f]{64}$/.test(a.pin || "") ? a.pin : "",
                // which install this is: kept through updates and restarts, new after a
                // removal and reinstall or a change of source (one that isn't 16 hex
                // digits is replaced on load, which drops its screen's customization)
                incarnation: /^[0-9a-f]{16}$/.test(a.incarnation || "") ? a.incarnation : "" }
    if (!code && !apps.linkOk(rec.launch.web, rec.permissions)) rec.broken = "Its link isn't right"   // until it's checked
    return rec
  }

  // Random hex digits from the kernel's random source: version-4 UUIDs read
  // from /proc/sys/kernel/random/uuid, their fixed version and variant digits
  // left out (120 random bits each). "" if there's no such source.
  Component { id: kernelUuid; FileView { path: "/proc/sys/kernel/random/uuid"; blockLoading: true; printErrors: false } }
  function randomHex(n) {
    var out = ""
    while (out.length < n) {
      var f = kernelUuid.createObject(apps)
      var u = String(f.text()).trim().replace(/-/g, "")
      f.destroy()
      if (!/^[0-9a-f]{32}$/.test(u)) return ""
      out += u.slice(0, 12) + u.slice(13, 16) + u.slice(17)
    }
    return out.slice(0, n)
  }
  function newIncarnation() { return apps.randomHex(16) }

  // A record without an incarnation (from before them, or with one that
  // wasn't one) gets a new one, kept from now on. Your choices for its
  // screen are kept under it, so it's in memory only once it's on disk: if
  // it can't be saved, the app has none for now (nothing is customized for
  // it: the panel and agents say it isn't ready, and incarnationProblem
  // why), and it's tried again.
  property string incarnationProblem: ""
  property int incarnationRetryMs: 30000
  function giveIncarnations() {
    var made = false
    var next = apps.installed.map(function(a) {
      if (a.incarnation) return a
      var b = {}
      for (var k in a) b[k] = a[k]
      b.incarnation = apps.newIncarnation()
      made = made || b.incarnation !== ""
      return b
    })
    if (!made) return
    if (!apps.save(next)) {
      apps.incarnationProblem = apps.saveError || "apps.json couldn't be saved"
      incarnationRetry.restart()
      return
    }
    apps.incarnationProblem = ""
    apps.installed = next
  }
  Timer { id: incarnationRetry; interval: apps.incarnationRetryMs; onTriggered: apps.giveIncarnations() }

  // An api 3 app's layout (app.json's, checked by bin/om-pg-apps at install),
  // checked again as it's loaded: the look it suggests, and at most 40 rows'
  // defaults, each by its row id
  function checkedLayout(l) {
    var out = { look: "", rows: [] }
    if (!l || typeof l !== "object") return out
    if (["classic", "posters", "cinematic", "wall", "compact"].indexOf(l.look) >= 0) out.look = l.look
    var seen = Object.create(null)
    ;(Array.isArray(l.rows) ? l.rows : []).slice(0, 40).forEach(function(r) {
      if (!r || typeof r.id !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(r.id) || seen[r.id]) return
      seen[r.id] = true
      // at most 40 characters, counted as bin/om-pg-apps counts them (code
      // points, never a pair of UTF-16 halves split; for...of goes by code
      // point here, where Array.from on a string doesn't)
      var label = []
      if (typeof r.label === "string") for (var ch of r.label) { if (label.length === 40) break; label.push(ch) }
      var row = { id: r.id, label: label.length ? label.join("") : r.id }
      if (["poster", "wide", "square", "logo", "circle"].indexOf(r.shape) >= 0) row.shape = r.shape
      if (["small", "medium", "large"].indexOf(r.size) >= 0) row.size = r.size
      if (["row", "grid", "list", "hero"].indexOf(r.layout) >= 0) row.layout = r.layout
      out.rows.push(row)
    })
    return out
  }

  // Of a launcher's values, only the clean-ups it still owes (settle)
  function owed(v) {
    var out = {}
    if (!v || typeof v !== "object") return out
    var f = (Array.isArray(v["@forget"]) ? v["@forget"] : []).filter(function(x) { return x === "signIn" || x === "server" || x === "data" })
    var c = (Array.isArray(v["@clear"]) ? v["@clear"] : []).filter(function(x) { return typeof x === "string" && /^[A-Za-z][A-Za-z0-9_.:-]{0,63}$/.test(x) }).slice(0, 32)
    if (f.length) out["@forget"] = f
    if (c.length) out["@clear"] = c
    return out
  }

  Process {
    id: privateState
    command: ["/usr/bin/chmod", "600", apps.statePath]
  }

  FileView {
    id: stateFile
    path: apps.statePath
    printErrors: false
    onLoaded: {
      try {
        var d = JSON.parse(text())
        apps.on = d.on === true
        apps.developer = apps.on && d.developer === true
        apps.unknownSources = apps.on && d.unknownSources === true
        apps.catalogSeen = Number(d.catalogSeen) || 0
        apps.checked = Number(d.checked) || 0
        apps.catalogSource = typeof d.catalog === "string" && (/^https:\/\/\S+$/.test(d.catalog) || /^\/\S+$/.test(d.catalog)) ? d.catalog : ""
        apps.installed = (Array.isArray(d.installed) ? d.installed : []).map(apps.checkedRecord).filter(function(a) { return a })
      } catch (e) {}
      apps.loaded = true
      apps.giveIncarnations()
      apps.settleAll()
      if (apps.installed.some(function(a) { return !a.source })) apps.migrate()
      else if (apps.installed.length) apps.verify()
      apps.freshen()
      if (apps.on) apps.listBundled()
    }
    onLoadFailed: apps.loaded = true
  }

  // The catalog as last read (bin/om-pg-apps checked it before keeping it)
  FileView {
    path: apps.catalogCache
    printErrors: false
    onLoaded: {
      if (apps.catalog) return
      try {
        var c = JSON.parse(text())
        if (c && Array.isArray(c.apps)) apps.catalog = c
      } catch (e) {}
    }
  }

  Timer {
    interval: 60 * 60 * 1000
    repeat: true
    running: apps.on
    onTriggered: apps.freshen()
  }
}
