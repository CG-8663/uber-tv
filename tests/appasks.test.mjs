// node tests/appasks.test.mjs
// What an app asks for and the review laid out for the couch (AppAsks.js):
// lines and their keys, the groups in order, the
// summary's verbs, what's new in an update, and where the cursor starts.
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const src = readFileSync(new URL("../AppAsks.js", import.meta.url), "utf8").replace(".pragma library", "")
const A = new Function(src + "; return { asks, groupsOf, summary, hasNewWrite, cancelFirst, reviewFolds, hadBefore, originLine, pulledBy, checkedHow, newAsks, times, sizeWords, activityFolds }")()

const perms = (o = {}) => ({ net: [], netWrite: {}, server: null, play: false, signIn: "", storage: false, ...o })
const app = (api, p, settings = [], home = []) => ({ kind: "app", api, permissions: perms(p), settings, home })
const keys = l => l.map(x => x.key).join(",")

// ---- lines: a write is a line a method, so one added later is new ----------
const trakt = perms({ net: ["api.trakt.tv", "img.example.com"], netWrite: { "api.trakt.tv": ["POST", "DELETE"] } })
assert.equal(keys(A.asks(trakt)), "write:api.trakt.tv:POST,write:api.trakt.tv:DELETE,net:api.trakt.tv,net:img.example.com")
assert.equal(keys(A.newAsks(app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }),
                            app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST", "DELETE"] } }))),
             "write:a.example.com:DELETE", "a method added to a site it could already change things on is new")
assert.equal(keys(A.newAsks(app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST", "DELETE"] } }),
                            app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }))),
             "", "one taken away is nothing new")
assert.equal(keys(A.newAsks(app(4, { net: ["a.example.com"] }), app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["PUT"] } }))),
             "write:a.example.com:PUT")
assert.match(keys(A.newAsks(app(3, {}), app(4, {}))), /^api/, "3 to 4 is reviewed, as any change of api but 2 to 3")
assert.equal(keys(A.newAsks(app(2, { net: ["a.example.com"] }), app(3, { net: ["a.example.com"] }))), "", "2 to 3 alone stays quiet")

// ---- groups: in order, changing things first, a write site not listed again under Connects to
const g = A.groupsOf(A.asks(perms({ net: ["api.trakt.tv", "img.example.com"], netWrite: { "api.trakt.tv": ["POST", "DELETE"] },
                                    server: { label: "S" }, play: true, signIn: "code", storage: true }),
                            [{ key: "apiKey", type: "secret", label: "API key" }]),
                     perms({ net: ["api.trakt.tv", "img.example.com"], netWrite: { "api.trakt.tv": ["POST", "DELETE"] }, server: { label: "S" } }),
                     [{ key: "now", label: "Now playing" }])
assert.deepEqual(g.map(x => x.key), ["write", "net", "server", "play", "signIn", "keeps", "home"])
assert.deepEqual(g.map(x => x.icon), ["pencil", "globe", "tv", "play", "lock", "folder", "home"])
assert.deepEqual(g[0].lines, ["api.trakt.tv (POST, DELETE)"])
assert.equal(g[0].strong, true, "changing things stands out")
assert.equal(g[0].title, "Can change things on")
assert.deepEqual(g[1].lines, ["img.example.com"], "a site it may change things on isn't under Connects to, whose note says it can't")
assert.match(g[1].note, /can carry information, but it can't post, change or delete/)
assert.deepEqual(g[2].lines, ["Read, change and delete what's on the server you choose, under its address"])
assert.deepEqual(g[3].lines, ["your server and the sites it connects to"])
assert.deepEqual(g[5].lines, ["up to 4 MB of its own data", "a secret you give it: API key"])
assert.deepEqual(g[6].lines, ["Now playing"])
assert.ok(g.slice(1).every(x => !x.strong))
// a launcher
const w = A.groupsOf(A.asks({ web: ["netflix.com"] }), { web: ["netflix.com"] }, [])
assert.deepEqual(w.map(x => [x.key, x.lines]), [["web", ["netflix.com, full screen"]]])

// ---- signing in: a line a way, so a way added later is new -----------------
assert.equal(keys(A.asks(perms({ server: { label: "S" }, signIn: "code" }))), "server,signIn", "a code keeps its key from before")
assert.equal(keys(A.asks(perms({ server: { label: "S" }, signIn: "code+password" }))), "server,signIn,signIn:password")
assert.equal(keys(A.newAsks(app(4, { server: { label: "S" }, signIn: "code" }), app(4, { server: { label: "S" }, signIn: "code+password" }))),
             "signIn:password", "a password added later is new")
const si = A.groupsOf(A.asks(perms({ server: { label: "S" }, signIn: "code+password" })), perms({ server: { label: "S" } }), []).filter(x => x.key === "signIn")[0]
assert.deepEqual(si.lines, ["with a code", "with your username and password"])
assert.match(si.note, /keeps only what the service gives back/)

// ---- the summary: verbs that say what it can do, never "reads from" ---------
const sum = p => A.summary(perms(p), "app")
assert.equal(sum({ net: ["a.example.com", "b.example.com"], netWrite: { "a.example.com": ["POST"] } }), "It connects to 2 sites and can change things on 1.")
assert.equal(sum({ net: ["a.example.com"] }), "It connects to 1 site.")
assert.equal(sum({ net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }), "It connects to 1 site and can change things on it.")
assert.equal(sum({ server: { label: "S" }, signIn: "code" }), "It can read, change and delete things on your server and keeps your sign-in.")
assert.equal(sum({ net: ["a.example.com"], server: { label: "S" }, signIn: "code" }),
             "It connects to 1 site, can read, change and delete things on your server, and keeps your sign-in.")
assert.equal(sum({}), "It doesn't connect to anything.")
for (const p of [{ net: ["a.example.com"] }, { server: { label: "S" } }, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }])
  assert.doesNotMatch(sum(p), /read(s)? from|only read|read only|read-only/i, "nothing implies it only receives")
assert.equal(A.summary({ web: ["netflix.com"] }, "launcher"), "It opens netflix.com in your browser.")

// ---- a new way to change things: from the permissions, never the rows ------
const nw = (a, b) => A.hasNewWrite(perms(a), perms(b))
assert.equal(nw({ net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST", "DELETE"] } }), true, "POST to POST and DELETE")
assert.equal(nw({ net: ["a.example.com"] }, { net: ["a.example.com", "b.example.com"], netWrite: { "b.example.com": ["POST"] } }), true, "a new write site")
assert.equal(nw({}, { server: { label: "S" } }), true, "a new server: read, change and delete")
assert.equal(nw({ net: ["a.example.com"], netWrite: { "a.example.com": ["POST", "DELETE"] } }, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } }), false, "only taken away")
assert.equal(nw({ server: { label: "S" } }, { server: { label: "S" } }), false)
assert.equal(nw({ net: ["a.example.com"] }, { net: ["a.example.com", "b.example.com"] }), false, "a site to connect to is new, but no way to change things")

// ---- where the review's cursor starts --------------------------------------
const review = (from, have, m, replaces = "") => {
  const r = { from, have, manifest: m, replaces, asks: A.asks(m.permissions, m.settings) }
  r.newAsks = have && !replaces ? A.newAsks(have, m) : []
  return r
}
const plain = app(4, { net: ["a.example.com"] })
const writer = app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST"] } })
const deleter = app(4, { net: ["a.example.com"], netWrite: { "a.example.com": ["POST", "DELETE"] } })
assert.equal(A.cancelFirst(review("bundled", null, writer)), false, "Uber TV's own, new: Install first")
assert.equal(A.cancelFirst(review("catalog", null, { kind: "launcher", api: 1, permissions: { web: ["netflix.com"] } })), false)
assert.equal(A.cancelFirst(review("file", null, plain)), true, "a file's: Cancel first")
assert.equal(A.cancelFirst(review("bundled", app(4, { net: ["a.example.com"] }), plain, "file")), true, "a replace: Cancel first")
assert.equal(A.cancelFirst(review("bundled", writer, deleter)), true, "an update adding DELETE: Cancel first")
assert.equal(A.cancelFirst(review("bundled", plain, writer)), true, "an update adding a write site")
assert.equal(A.cancelFirst(review("bundled", plain, app(4, { net: ["a.example.com"], server: { label: "S" } }))), true, "an update adding a server")
assert.equal(A.cancelFirst(review("bundled", deleter, writer)), false, "one only taking away: Update first")
assert.equal(A.cancelFirst(review("bundled", plain, app(4, { net: ["a.example.com", "b.example.com"] }))), false, "a new site to connect to: Update first")

// ---- what folds, and an update's old lines ---------------------------------
const many = app(4, { net: ["a.example.com", "b.example.com", "c.example.com", "d.example.com", "e.example.com"] })
assert.deepEqual(A.reviewFolds(review("file", null, many)).map(x => x.key), ["net", "cant"], "more than 3 sites fold, and Can't")
assert.deepEqual(A.reviewFolds(review("bundled", plain, writer)).map(x => x.key), ["before", "cant"], "an update folds what it had before")
assert.deepEqual(A.reviewFolds(review("catalog", null, { kind: "launcher", api: 1, permissions: { web: ["netflix.com"] } })).map(x => x.key), [], "a launcher folds nothing")
assert.equal(keys(A.hadBefore(review("bundled", plain, writer))), "net:a.example.com")
// a change of api: everything counts as new, and says why; nothing "before" to fold
const up = review("bundled", app(3, { net: ["a.example.com"] }), app(4, { net: ["a.example.com"] }))
const ug = A.groupsOf(up.newAsks, up.manifest.permissions, [])
assert.equal(ug[0].key, "how", "how it runs comes first")
assert.match(ug[0].lines[0], /version 4 of the guide's app protocol/)
assert.deepEqual(ug.map(x => x.key), ["how", "net"])
assert.deepEqual(A.reviewFolds(up).map(x => x.key), ["cant"], "nothing it had before to fold")

// ---- where it's from -------------------------------------------------------
assert.equal(A.originLine("bundled"), "From Uber TV: it comes with the guide")
assert.equal(A.originLine("catalog", "the Uber TV catalog"), "From Uber TV's catalog: checked, and signed with its key")
assert.equal(A.originLine("catalog", "My apps"), "From Uber TV's catalog (My apps): checked, and signed with its key")
assert.equal(A.originLine("file"), "From a file on this computer. Uber TV didn't make this app.")
assert.equal(A.originLine("appFile", "", "SHA256:abc"), "From a signed app file you installed (developer key SHA256:abc). A signature shows who published it, not that anyone checked it.")
// who pulled it, and how it was checked (the refusals, and agents)
assert.equal(A.pulledBy("appFile"), "its developer withdrew it")
assert.equal(A.pulledBy("catalog"), "the catalog pulled it")
const fp = "SHA256:" + "k".repeat(43)
assert.equal(A.checkedHow("appFile", "", fp), "traced back to its signed app file (developer key " + fp + "): a signature shows who published it, not that anyone checked it")
assert.equal(A.checkedHow("catalog", "the Uber TV catalog"), "traced back to the signed catalog")
assert.equal(A.checkedHow("bundled"), "against the copy Uber TV comes with")
assert.equal(A.checkedHow("file"), "against what was installed (an unsigned app from a file)")
assert.equal(A.checkedHow(""), A.checkedHow("file"), "anything else claims no more than a file")
// Commands.qml's apps, run as it is (it loads only in the shell): what agents
// are told of each installed app. A signed app file is traced back to its
// pinned developer key, and a withdrawal is attributed to that developer:
// never Uber TV's signed catalog.
{
  const commandsSrc = readFileSync(new URL("../Commands.qml", import.meta.url), "utf8")
  const start = commandsSrc.indexOf("    function apps(): string {")
  assert.ok(start >= 0, "Commands.qml's apps")
  const appsCommand = new Function("guide", "commands", "Qt", "Asks", commandsSrc.slice(commandsSrc.indexOf("{", start) + 1, commandsSrc.indexOf("\n    }\n", start)))
  const rec = (id, from, more) => Object.assign({ id, name: "Scores", version: "1.0.0", author: "Uber TV", kind: "launcher", enabled: true, broken: "", revoked: "", update: null, from,
                                                  source: { appFile: "app:0123456789abcdef", catalog: "catalog:uber", bundled: "bundled", file: "file:0123456789abcdef" }[from],
                                                  catalogName: from === "catalog" ? "the Uber TV catalog" : "", keyFingerprint: from === "appFile" ? fp : "",
                                                  permissions: { web: ["scores.example.com"] }, settings: [] }, more)
  const store = { on: true, developer: true, unknownSources: true, catalog: { name: "Uber TV apps", apps: [], updated: 0 }, catalogError: "", runtime: () => null, asks: A.asks,
                  installed: [rec("tv.alex.scores", "appFile"), rec("tv.uber.flix", "catalog"), rec("tv.uber.scores", "bundled"), rec("dev.me.scores", "file"),
                              rec("tv.alex.films", "appFile", { revoked: "Malware found.", enabled: false }), rec("tv.uber.pulled", "catalog", { revoked: "It was broken.", enabled: false })] }
  store.checkedIds = Object.fromEntries(store.installed.map(x => [x.id, true]))
  const said = () => {
    const out = JSON.parse(appsCommand({ apps: store, appUp: "", codeApp: "" }, { okReply: o => JSON.stringify(Object.assign({ ok: true }, o)) }, { formatDateTime: () => "" }, A))
    return id => out.installed.find(x => x.id === id)
  }
  const by = said()
  assert.equal(by("tv.alex.scores").checked, "traced back to its signed app file (developer key " + fp + "): a signature shows who published it, not that anyone checked it",
               "its signed file and pinned developer key")
  assert.equal(by("tv.alex.scores").problem, "")
  assert.equal(by("tv.alex.films").problem, "its developer withdrew it: Malware found.", "its developer withdrew it, not the catalog")
  assert.equal(by("tv.alex.films").checked, by("tv.alex.scores").checked)
  for (const id of ["tv.alex.scores", "tv.alex.films"]) assert.doesNotMatch(by(id).checked + " " + by(id).problem, /catalog/, id)
  assert.equal(by("tv.uber.flix").checked, "traced back to the signed catalog", "the catalog's are")
  assert.equal(by("tv.uber.pulled").problem, "the catalog pulled it: It was broken.")
  assert.equal(by("tv.uber.scores").checked, "against the copy Uber TV comes with")
  assert.equal(by("dev.me.scores").checked, "against what was installed (an unsigned app from a file)")
  store.checkedIds = {}
  const unchecked = said()
  for (const x of store.installed) assert.equal(unchecked(x.id).checked, "not yet", "not checked yet: " + x.id)
}
// Apps.qml's refusals, run as they are: opening a withdrawn signed app file,
// or turning it on, says its developer withdrew it; one the catalog pulled,
// the catalog.
{
  const appsSrc = readFileSync(new URL("../Apps.qml", import.meta.url), "utf8")
  const fnOf = (opener, params) => {
    const start = appsSrc.indexOf(opener)
    assert.ok(start >= 0, "Apps.qml: " + opener)
    return new Function("apps", "Asks", ...params, appsSrc.slice(appsSrc.indexOf("{", start) + 1, appsSrc.indexOf("\n  }\n", start)))
  }
  const cannotOpen = fnOf("  function cannotOpen(id) {", ["id"])
  const setEnabled = fnOf("  function setEnabled(id, on) {", ["id", "on"])
  const recs = { "tv.alex.films": { id: "tv.alex.films", kind: "launcher", from: "appFile", enabled: false, broken: "", revoked: "Malware found." },
                 "tv.uber.pulled": { id: "tv.uber.pulled", kind: "launcher", from: "catalog", enabled: false, broken: "", revoked: "It was broken." } }
  const apps = { on: true, developer: true, unknownSources: true, migrating: false, canRun: true, checkedIds: { "tv.alex.films": true, "tv.uber.pulled": true },
                 record: id => recs[id] || null, linkOk: () => true, withRecord() { assert.fail("a pulled app isn't turned on") }, stopRuntime() {}, save: () => true }
  assert.equal(cannotOpen(apps, A, "tv.alex.films"), "its developer withdrew it")
  assert.equal(setEnabled(apps, A, "tv.alex.films", true), "its developer withdrew it: Malware found.")
  assert.equal(cannotOpen(apps, A, "tv.uber.pulled"), "the catalog pulled it")
  assert.equal(setEnabled(apps, A, "tv.uber.pulled", true), "the catalog pulled it: It was broken.")

  // A valid signed update folder survives Apps.qml's state-file check at
  // the same 2,048-character bound the helper accepts. Otherwise a restart
  // would silently stop both updates and developer withdrawal notices.
  const checkedRecord = fnOf("  function checkedRecord(a) {", ["a"])
  const longUpdate = "https://updates.example.com/" + "a".repeat(2019) + "/"
  assert.equal(longUpdate.length, 2048)
  const loader = {
    writeMethods: A.writeMethods,
    checkedServer: x => x,
    checkedLayout: () => null,
    fromOf: source => /^app:/.test(source) ? "appFile" : "catalog",
    owed: () => ({}),
    linkOk: () => true
  }
  const loaded = checkedRecord(loader, A, {
    id: "tv.alex.clock", name: "Clock", version: "1.0.0", author: "Alex",
    kind: "launcher", source: "app:0123456789abcdef", sourceDir: "0123456789abcdef",
    permissions: { web: ["example.com"] }, launch: { web: "https://example.com/" },
    updateAddress: longUpdate
  })
  assert.equal(loaded.updateAddress, longUpdate, "a valid long update address is kept across restart")
  assert.equal(checkedRecord(loader, A, Object.assign({}, loaded, { updateAddress: "https://updates.example.com/" + "a".repeat(2020) + "/" })).updateAddress, "",
               "an update address beyond the helper's bound is still refused")
}
// Guide.qml's Home card for an app, run as it is: it carries where the app is
// from, for Home's badge (tests/qml/tst_homebadge.qml draws it)
{
  const guideSrc = readFileSync(new URL("../Guide.qml", import.meta.url), "utf8")
  const m = /\} else if \(sec\.type === "apps"\) \{\n *(cards = [^\n]+)\n/.exec(guideSrc)
  assert.ok(m, "Guide.qml's Home cards for apps")
  const cardsOf = new Function("appsStore", "var cards; " + m[1] + "; return cards")
  const ready = ["bundled", "catalog", "appFile", "file"].map(from => ({ id: "tv.example." + from, name: "Scores", author: "Uber TV", color: "#d62828", icon: "/x/icon.png", used: 1, from }))
  assert.deepEqual(cardsOf({ ready }).map(c => [c.kind, c.appId, c.from]), ready.map(a => ["app", a.id, a.from]))
}

// the details box's Activity: past 6 sites and 4 refused names, a row each that opens
const site = n => ({ site: "s" + n + ".example.com" })
assert.deepEqual(A.activityFolds({ sites: [1, 2, 3, 4, 5, 6].map(site), refused: [1, 2, 3, 4].map(site), refusedMore: 9 }), [])
assert.deepEqual(A.activityFolds({ sites: [1, 2, 3, 4, 5, 6, 7].map(site), refused: [1, 2, 3, 4, 5].map(site), refusedMore: 0 }).map(x => x.key), ["sites", "refused"])
assert.deepEqual(A.activityFolds(null), [])
assert.deepEqual(A.activityFolds({ failed: true, sites: [], refused: [] }), [])
// Guide.qml's openAppInfo, run as it is: only the read of the opening that's
// still on the screen moves the cursor, whatever order the reads come back in
{
  const guideSrc = readFileSync(new URL("../Guide.qml", import.meta.url), "utf8")
  const start = guideSrc.indexOf("  function openAppInfo(id, by) {")
  const body = guideSrc.slice(guideSrc.indexOf("{", start) + 1, guideSrc.indexOf("\n  }\n", start))
  const openAppInfo = new Function("root", "appsStore", "keys", "id", "by", body)
  const reads = []
  const appsStore = { record: id => ({ id }), activity: (id, done) => reads.push(done), activityFolds: A.activityFolds,
                      withKey: (m, k, v) => Object.assign({}, m, { [k]: v }) }
  const root = { byUser: {}, dialog: "", appInfoId: "", appsCursor: 0, appsArmed: "", appActivity: null, reviewOpen: {}, appActivityGen: 0 }
  const keys = { forceActiveFocus() {} }
  const act = { sites: [1, 2, 3, 4, 5, 6, 7].map(site), refused: [1, 2, 3, 4, 5].map(site), refusedMore: 0 }   // two folded rows
  openAppInfo(root, appsStore, keys, "tv.example.a", root.byUser)
  root.dialog = ""                                   // closed before its read came back
  openAppInfo(root, appsStore, keys, "tv.example.a", root.byUser)   // and opened again
  assert.equal(reads.length, 2)
  reads[1](true, act)                                // this opening's read
  assert.equal(root.appsCursor, 2, "past its two folded rows, on On")
  reads[0](true, act)                                // the first opening's, late
  assert.equal(root.appsCursor, 2, "an earlier opening's read moves nothing")
  assert.equal(root.appActivity, act)
  // the other order: the old read first does nothing, the new one counts once
  openAppInfo(root, appsStore, keys, "tv.example.a", root.byUser)
  const n = reads.length
  root.dialog = ""
  openAppInfo(root, appsStore, keys, "tv.example.a", root.byUser)
  reads[n - 1](true, { sites: [], refused: [], refusedMore: 0 })
  assert.equal(root.appsCursor, 0)
  assert.equal(root.appActivity, null, "nothing applied from the old read")
  reads[n](true, act)
  assert.equal(root.appsCursor, 2)
  // a read that fails says so, and moves nothing
  openAppInfo(root, appsStore, keys, "tv.example.a", root.byUser)
  reads[reads.length - 1](false, null)
  assert.equal(root.appActivity.failed, true)
  assert.equal(root.appsCursor, 0)
}

assert.equal(A.times(1), "once")
assert.equal(A.times(3), "3 times")
assert.equal(A.sizeWords(2048), "2 KB")
console.log("appasks: all passed")
