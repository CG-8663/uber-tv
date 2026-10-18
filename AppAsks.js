.pragma library

// What an app asks for, in plain words, and the review laid out for the
// couch: its lines, their groups, the one-line
// summary, what's new in an update, and where the review's cursor starts.
// Kept apart from the QML so it can be tested on its own
// (tests/appasks.test.mjs); Apps.qml calls it, and Commands.qml for what
// agents are told of where an app is from.

// Each line: key (stable: what's new in an update is told by it), group
// (where the review puts it) and text (a phrase: "Connect to api.example
// to get things"). A site it may change things on is a line a method, so
// a method added later is new. settings: an app's settings (each secret
// one asks for something)
var writeMethods = ["POST", "PUT", "PATCH", "DELETE"]
function asks(perms, settings) {
  var out = []
  var web = (perms && perms.web) || []
  for (var i = 0; i < web.length; i++) out.push({ key: "web:" + web[i], group: "web", host: web[i], text: "Open " + web[i] + ", full screen" })
  var writes = (perms && perms.netWrite) || {}
  var wh = Object.keys(writes).sort()
  for (var w = 0; w < wh.length; w++)
    for (var m = 0; m < (writes[wh[w]] || []).length; m++)
      out.push({ key: "write:" + wh[w] + ":" + writes[wh[w]][m], group: "write", host: wh[w], method: writes[wh[w]][m],
                 text: "Send data to " + wh[w] + " and change or delete things there (" + writes[wh[w]][m] + ")" })
  if (perms && perms.server) out.push({ key: "server", group: "server", text: "Read, change and delete what's on the server you choose, under its address" })
  var net = (perms && perms.net) || []
  for (var j = 0; j < net.length; j++) out.push({ key: "net:" + net[j], group: "net", host: net[j], text: "Connect to " + net[j] + " to get things" })
  if (perms && perms.play) out.push({ key: "play", group: "play", text: perms.server ? "Play video and audio from your server" + (net.length ? " and those sites" : "") : "Play video and audio from those sites" })
  // how it signs in: "code", "password" or "code+password" (each its own line,
  // so a way added later is new; a code keeps its key from before)
  var ways = String((perms && perms.signIn) || "").split("+")
  if (ways.indexOf("code") >= 0) out.push({ key: "signIn", group: "signIn", text: "Sign in to your account with a code" })
  if (ways.indexOf("password") >= 0) out.push({ key: "signIn:password", group: "signIn", text: "Sign in with your username and password: Uber TV keeps only what the service gives back" })
  if (perms && perms.storage) out.push({ key: "storage", group: "keeps", text: "Keep up to 4 MB of its own data" })
  var st = settings || []
  for (var k = 0; k < st.length; k++) if (st[k].type === "secret") out.push({ key: "secret:" + st[k].key, group: "keeps", text: "Ask you for: " + st[k].label })
  return out
}

// The review's rows, from asks()'s lines: one a
// group, in a fixed order, each with its icon, its lines (a site each, or
// a phrase) and a note. Changing things comes first. A site it may change
// things on isn't listed again under Connects to (its note would say it
// can't). home: the app's Home rows (not an ask: they're off until you
// add them)
var groupOrder = ["how", "web", "write", "net", "server", "play", "signIn", "keeps", "home"]
function groupsOf(items, perms, home) {
  var by = {}
  for (var i = 0; i < items.length; i++) {
    // newAsks' own lines: a change of kind or api (all it asks then counts as new)
    var gk = items[i].group || (items[i].key === "kind" || items[i].key === "api" ? "how" : "")
    if (gk) (by[gk] = by[gk] || []).push(items[i])
  }
  var writes = (perms && perms.netWrite) || {}
  var out = []
  var add = function(key, title, icon, lines, note) { if (lines.length) out.push({ key: key, title: title, icon: icon, lines: lines, note: note || "", strong: key === "write" }) }
  for (var g = 0; g < groupOrder.length; g++) {
    var key = groupOrder[g], list = by[key] || []
    if (key === "how") add(key, "How it runs", "info", list.map(function(x) { return x.text }), "So everything it asks for counts as new.")
    else if (key === "web") add(key, "Opens", "globe", list.map(function(x) { return x.host + ", full screen" }), "Your browser handles everything else.")
    else if (key === "write") {
      var hosts = [], methods = {}
      list.forEach(function(x) { if (!methods[x.host]) { methods[x.host] = []; hosts.push(x.host) } methods[x.host].push(x.method) })
      add(key, "Can change things on", "pencil", hosts.map(function(h) { return h + " (" + methods[h].join(", ") + ")" }), "It can send data there, and change or delete things.")
    } else if (key === "net")
      add(key, "Connects to", "globe", list.filter(function(x) { return !writes[x.host] }).map(function(x) { return x.host }),
          "To get things. What it asks for can carry information, but it can't post, change or delete things there.")
    else if (key === "server") add(key, "Your server", "tv", list.length ? ["Read, change and delete what's on the server you choose, under its address"] : [])
    else if (key === "play") add(key, "Plays media from", "play", list.length ? [perms && perms.server ? ((perms.net || []).length ? "your server and the sites it connects to" : "your server") : "the sites it connects to"] : [])
    else if (key === "signIn") add(key, "Signs in", "lock", list.map(function(x) { return x.key === "signIn" ? "with a code" : "with your username and password" }),
                                   list.some(function(x) { return x.key === "signIn:password" }) ? "What you type goes to the app once, to sign in; Uber TV keeps only what the service gives back." : "")
    else if (key === "keeps") add(key, "Keeps on this computer", "folder", list.map(function(x) { return x.key === "storage" ? "up to 4 MB of its own data" : "a secret you give it: " + x.text.replace(/^Ask you for: /, "") }))
    else if (key === "home") add(key, "Shows on Home", "home", (home || []).map(function(h) { return h.label }), "Off until you add them (Customize Home, C).")
  }
  return out
}

// The review's one line before the rows: what it can do, in verbs that
// say so (never "reads from": what it asks a site for can carry
// information)
function summary(perms, kind) {
  var p = perms || {}
  if (kind !== "app") {
    var web = p.web || []
    return web.length ? "It opens " + web[0] + (web.length > 1 ? " and " + (web.length - 1) + " more" : "") + " in your browser." : ""
  }
  var nw = Object.keys(p.netWrite || {}).length, nn = (p.net || []).length
  var parts = []
  if (nn) parts.push("connects to " + nn + (nn === 1 ? " site" : " sites") + (nw ? " and can change things on " + (nw === nn ? (nw === 1 ? "it" : "all of them") : nw) : ""))
  if (p.server) parts.push("can read, change and delete things on your server")
  if (p.signIn) parts.push("keeps your sign-in")
  if (!parts.length) return "It doesn't connect to anything."
  var last = parts.pop()
  return "It " + (parts.length ? parts.join(", ") + (parts.length > 1 ? "," : "") + " and " : "") + last + "."
}

// An update that adds a way to change things: a site or a method there it
// may change things on, or a server (read, change and delete). From the
// permissions themselves, never from what's drawn; one taken away isn't one
function hasNewWrite(a, b) {
  var wa = (a && a.netWrite) || {}, wb = (b && b.netWrite) || {}
  for (var h in wb)
    for (var i = 0; i < (wb[h] || []).length; i++)
      if ((wa[h] || []).indexOf(wb[h][i]) < 0) return true
  return !!(b && b.server) && !(a && a.server)
}

// Where the review's cursor starts: on Cancel for anyone else's code, a
// replace, and an update that adds a way to change things, so a stray OK
// from the couch never installs it; on Install for Uber TV's own
function cancelFirst(r) {
  if (!r) return true
  if (r.from !== "bundled" && r.from !== "catalog") return true
  if (r.replaces) return true
  return !!r.have && hasNewWrite(r.have.permissions, r.manifest.permissions)
}

// The review's rows that fold, each a row the cursor stops on before
// Install and Cancel: a group of more than 3 sites, an update's "what it
// had before", and Can't (an app with code)
function reviewFolds(r) {
  if (!r) return []
  var update = r.newAsks.length > 0
  var out = groupsOf(update ? r.newAsks : r.asks, r.manifest.permissions, update ? [] : r.manifest.home)
                .filter(function(g) { return g.lines.length > 3 }).map(function(g) { return { type: "fold", key: g.key, label: g.title } })
  if (update && hadBefore(r).length) out.push({ type: "fold", key: "before", label: "And what it had before" })
  if (r.manifest.kind === "app") out.push({ type: "fold", key: "cant", label: "Can't" })
  return out
}

// The details box's Activity rows that fold (more than 6 sites it
// contacted, more than 4 refused sites whose names were kept): each a row the
// cursor stops on before the box's own
var activityShown = { sites: 6, refused: 4 }
function activityFolds(act) {
  if (!act || act.failed) return []
  var out = []
  if ((act.sites || []).length > activityShown.sites) out.push({ type: "fold", key: "sites", label: "Sites it contacted" })
  if ((act.refused || []).length > activityShown.refused) out.push({ type: "fold", key: "refused", label: "Sites it was refused" })
  return out
}

// An update's lines it had before (what's new is shown on its own)
function hadBefore(r) {
  if (!r || !r.newAsks.length) return []
  var fresh = r.newAsks.map(function(x) { return x.key })
  return r.asks.filter(function(x) { return fresh.indexOf(x.key) < 0 })
}

// Where it's from, in one plain line (the review and its details)
function originLine(from, name, fingerprint) {
  return from === "bundled" ? "From Uber TV: it comes with the guide"
       : from === "catalog" ? "From Uber TV's catalog" + (name && !/^(the )?uber tv/i.test(name) ? " (" + name + ")" : "") + ": checked, and signed with its key"
       : from === "appFile" ? "From a signed app file you installed" + (fingerprint ? " (developer key " + fingerprint + ")" : "") + ". A signature shows who published it, not that anyone checked it."
       : "From a file on this computer. Uber TV didn't make this app."
}

// Who withdrew it, in a few words (the refusals, and agents).
function pulledBy(from) { return from === "appFile" ? "its developer withdrew it" : "the catalog pulled it" }

// How an installed app was checked (by its install, and at each start), in
// a few words for agents (Commands.qml's apps). One from a source is traced
// back to its source's signed list, with the key that signed what's
// installed: who published it, not that anyone checked it. Only the
// catalog's is Uber TV's signed catalog; anything else claims no more than
// a file
function checkedHow(from, name, fingerprint) {
  return from === "bundled" ? "against the copy Uber TV comes with"
       : from === "catalog" ? "traced back to the signed catalog"
       : from === "appFile" ? "traced back to its signed app file" + (fingerprint ? " (developer key " + fingerprint + ")" : "")
                              + ": a signature shows who published it, not that anyone checked it"
       : "against what was installed (an unsigned app from a file)"
}

// asked for by b, not by a (a and b: records or manifests). A change of
// kind or api is all new, except an app going from api 2 to 3 exactly:
// that alone asks for nothing
// more, so with no new ask it's quiet. The update path and review share
// this; each also checks the source is the same (sourceFor).
function newAsks(a, b) {
  var pa = a && a.permissions !== undefined ? a : { permissions: a }
  var pb = b && b.permissions !== undefined ? b : { permissions: b }
  var all = asks(pb.permissions, pb.settings)
  if ((pa.kind || "launcher") !== (pb.kind || "launcher"))
    return [{ key: "kind", text: (pb.kind === "app" ? "Now run code in a sandbox on this computer" : "Now be a website opened full screen") }].concat(all)
  var apiA = pa.api || 1, apiB = pb.api || 1
  if (apiA !== apiB && !(pb.kind === "app" && apiA === 2 && apiB === 3))
    return [{ key: "api", text: "Now use version " + apiB + " of the guide's app protocol, where it used version " + apiA }].concat(all)
  var had = asks(pa.permissions, pa.settings).map(function(x) { return x.key })
  return all.filter(function(x) { return had.indexOf(x.key) < 0 })
}

function times(n) { return n === 1 ? "once" : n === 2 ? "twice" : n + " times" }
function sizeWords(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " bytes" }

