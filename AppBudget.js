.pragma library

// Which running app makes room when another needs a slot at the runtime
// budget (Apps.qml ensure). Kept apart from the QML so it can be tested on
// its own (tests/appbudget.test.mjs).
//
// runtimes: { id: { phase, leases: { name: true }, busy, lastUsed } }
// changing: { id: true } for apps being changed (a sign-out, a new secret or
// server, an update): their runtimes are never stopped to make room
// lease: the lease the new start asks for ("home:<key>", "foreground"…)
//
// Answers { stop, refuse }: stop is the id to stop ("" for none); refuse is
// true when nothing can make room and nothing is stopping already.
function makeRoom(runtimes, changing, lease) {
  var ids = Object.keys(runtimes).filter(function(x) { return runtimes[x].phase === "ready" && !changing[x] })
  // first, the least recently used one with nothing on the screen, nothing
  // playing, nothing loading and no call still out
  var free = ids.filter(function(x) { return !Object.keys(runtimes[x].leases).length && !runtimes[x].busy })
  // failing that, one that only holds Home rows' leases (at least one, every
  // one of them Home's) makes room, for any lease but a plain "home" (as in
  // v1; Home rows ask with "home:<key>", so they're included)
  if (!free.length && lease !== "home")
    free = ids.filter(function(x) {
      var l = Object.keys(runtimes[x].leases)
      return l.length > 0 && l.every(function(k) { return /^home:/.test(k) })
    })
  if (free.length) {
    free.sort(function(x, y) { return runtimes[x].lastUsed - runtimes[y].lastUsed })
    return { stop: free[0], refuse: false }
  }
  var stopping = Object.keys(runtimes).some(function(x) { return runtimes[x].phase === "stopping" })
  return { stop: "", refuse: !stopping }
}
