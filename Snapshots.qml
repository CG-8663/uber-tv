import QtQuick

// Pictures of the guide for agents (snapshot "" and appSnapshot):
// snapshot-<run>-<n>.png in the cache folder,
// where run is 128 bits (32 hex digits) from the kernel's random source,
// new each time the guide starts, and n counts from 1, whatever the clock
// does: two starts' names differ unless they drew the same 128 bits, which
// is negligible. Each is grabbed to a temporary name of this start's, made
// readable by you alone, and put in place with a link that never replaces
// anything (a file of that name there: refused, and the file stays). A
// file with that name is complete; this start's newest five are kept, and
// another start's files are left alone for an hour (it may still be
// running: two logins, say). The name is answered at once, and state's
// snapshot (report) says how it went: { name, outcome: pending, written or
// refused, why in the guide's own words }. One is taken at a time.
//
// Checked when asked (an error answer) and again when the picture is
// grabbed (refused, and no file is written): never while a sensitive screen
// is up (the phone remote's box, which shows the pairing code; an app's
// sign-in, its settings or a certificate to pin; a text field), and one
// that came up in between, even for a moment, drops the picture too. The
// one asking adds its own check (appSnapshot: nothing over the app's screen,
// and the same view).
Item {
  id: snaps

  required property var guide
  property Item target: null          // what's grabbed: the guide's screen
  property string folder: ""          // the cache folder
  property real dpr: 1
  // moves the picture into place: mover(argv, done(ok)) (the guide runs it;
  // tests stand in for it, and for the grab: grab(item, done(result), size))
  property var mover: null
  property var grab: null
  readonly property int keep: 5
  property int waitMs: 10000          // for the grab: a window that isn't drawn never gives one
  property string run: ""             // 32 hex digits, this start's (the guide's kernel random)
  readonly property string runPart: /^[0-9a-f]{32}$/.test(snaps.run) ? snaps.run : ""
  property int seq: 0
  property var report: ({ name: "", outcome: "", why: "" })
  property double live: 0             // the number being taken (0: none)

  // A sensitive screen now ("" if none), and how often one has come up
  readonly property string sensitiveNow: snaps.sensitive()
  property int sensitiveSeen: 0
  property string sensitiveLast: ""
  onSensitiveNowChanged: if (snaps.sensitiveNow !== "") { snaps.sensitiveSeen += 1; snaps.sensitiveLast = snaps.sensitiveNow }

  function sensitive() {
    var g = snaps.guide
    if (g.dialog === "remote") return "the phone remote's box is open (it shows the pairing code)"
    if (g.nativeSaver && g.nativeSaver.up) return "Omarchy's screen saver is up, and the guide is out of its way"
    if (g.channelLock && g.channelLock.boxUp) return "the channel lock's box is open"
    if (g.screen === "app" && g.appView) {
      var v = g.appView
      if (v.signIn !== null) return "an app's sign-in is on the screen"
      if (v.settingsOpen) return "an app's settings are on the screen"
      if (v.certOffer !== null) return "a certificate to pin is on the screen"
    }
    if (snaps.textField()) return "a text field is on the screen"
    return ""
  }
  // Every text field the guide draws, by what shows it (tests/snapshots.test.py
  // holds this list to the fields in its files): the boxes that rename a
  // channel, file one under a category, pick a file, add channels or a
  // listings link; the style panel's color and its name for a theme; a Home
  // row's name; a row's name in Customize; an app's own (and its password
  // box's two, which come with its sign-in: refused as that, above); a
  // source's link (Unknown sources' add box)
  function textField() {
    var g = snaps.guide
    return ["rename", "category", "pick", "add"].indexOf(g.dialog) >= 0 || (g.dialog === "listings" && !!g.listingsAdding)
           || !!g.styleNaming || (!!g.styleEditing && g.styleEditing !== "") || !!g.homeRenaming
           || (!!g.appPanel && !!g.appPanel.open && !!g.appPanel.renaming)
           || (g.screen === "app" && !!g.appView && g.appView.editing !== null)
  }

  // Puts the picture in place (readable by you alone, linked whole under its
  // name, never over anything already there: a file, a link or a folder),
  // then keeps this start's newest five and takes away its older ones and
  // leftovers; the guide's other files (other starts', snapshot-<32 hex>-<n>,
  // the versions before's, snapshot-<8 hex>-<n> and snapshot-<n>, and their
  // temporary ones) only once they're an hour old; nothing named otherwise.
  // $1 the folder, $2 this start's run, $3 its number, $4 the temporary
  // file, $5 its name, $6 how many are kept
  readonly property string moveScript: "PATH=/usr/bin\nd=$1; run=$2; n=$3; part=$4; name=$5; keep=$6\nchmod 600 -- \"$part\" && ln -T -- \"$part\" \"$name\" || { rm -f -- \"$part\"; exit 1; }\nrm -f -- \"$part\"\nold() { [ -n \"$(find \"$1\" -maxdepth 0 -mmin +60 -print 2>/dev/null)\" ]; }\nfor f in \"$d\"/snapshot-*.png \"$d\"/.snapshot-*.part.png; do\n  b=${f##*/}\n  case $b in .snapshot-*.part.png) m=${b#.snapshot-}; m=${m%.part.png}; final=;; *) m=${b#snapshot-}; m=${m%.png}; final=1;; esac\n  case $m in\n    *-*) r=${m%%-*}; k=${m#*-};;\n    *) r=; k=$m;;\n  esac\n  case $r in *[!0-9a-f]*) continue;; esac\n  [ -z \"$r\" ] || [ ${#r} -eq 32 ] || [ ${#r} -eq 8 ] || continue\n  case $k in ''|*[!0-9]*) continue;; esac\n  if [ \"$r\" = \"$run\" ]; then\n    [ -n \"$final\" ] && [ \"$k\" -le \"$n\" ] && [ \"$k\" -gt $((n - keep)) ] && continue\n  else\n    old \"$f\" || continue\n  fi\n  rm -f -- \"$f\"\ndone\nexit 0"

  // Takes one: check(atGrab) says why not ("" goes ahead). Answers
  // { path, width, height } (the picture is 1600 wide at most), or { error }.
  function take(check) {
    if (!snaps.guide.opened) return { error: "the guide isn't open: open it first (open, or watch a channel)" }
    if (snaps.live) return { error: "a snapshot is being taken: wait until state's snapshot isn't pending" }
    var why = snaps.sensitiveNow || (check ? check(false) : "")
    if (why) return { error: why + ", so no snapshot now" }
    var item = snaps.target
    if (!item || item.width <= 0 || item.height <= 0 || !snaps.mover || !snaps.runPart) return { error: "the guide's screen can't be grabbed now" }
    var dpr = Math.max(1, snaps.dpr)
    var w = Math.round(Math.min(1600, item.width * dpr))
    var h = Math.round(item.height * w / item.width)
    var n = snaps.seq + 1
    var name = snaps.folder + "/snapshot-" + snaps.runPart + "-" + n + ".png"
    var part = snaps.folder + "/.snapshot-" + snaps.runPart + "-" + n + ".part.png"
    var seen = snaps.sensitiveSeen
    // the picture comes out at the screen's scale: ask for less on a HiDPI one
    var grabber = snaps.grab || function(it, done, size) { return it.grabToImage(done, size) }
    var asked = grabber(item, function(result) {
      if (snaps.live !== n) return          // given up on: no file
      grabTimer.stop()
      var no = !snaps.guide.opened ? "the guide closed"
             : snaps.sensitiveSeen !== seen ? snaps.sensitiveLast + " (it came up while the picture was taken)"
             : (check ? check(true) : "")
      if (no) { snaps.finish(n, "refused", no); return }
      if (!result.saveToFile(part)) { snaps.mover(["/usr/bin/rm", "-f", "--", part], function() {}); snaps.finish(n, "refused", "it couldn't be written"); return }
      snaps.mover(["/usr/bin/sh", "-c", snaps.moveScript, "sh", snaps.folder, snaps.runPart, String(n), part, name, String(snaps.keep)], function(ok) {
        snaps.finish(n, ok ? "written" : "refused", ok ? "" : "it couldn't be written")
      })
    }, Qt.size(Math.round(w / dpr), Math.round(h / dpr)))
    if (!asked) return { error: "the guide's screen can't be grabbed now" }
    snaps.seq = n
    snaps.live = n
    snaps.report = { name: name, outcome: "pending", why: "" }
    grabTimer.restart()
    return { path: name, width: w, height: h }
  }
  function finish(n, outcome, why) {
    if (snaps.live !== n) return
    snaps.live = 0
    grabTimer.stop()
    snaps.report = { name: snaps.report.name, outcome: outcome, why: why }
  }
  Timer {
    id: grabTimer
    interval: snaps.waitMs
    onTriggered: if (snaps.live) snaps.finish(snaps.live, "refused", "the guide's screen wasn't drawn in time (its window may be on another workspace)")
  }

  // snapshot "": the guide as it is on screen
  function snapshot(path) {
    if (String(path || "").trim()) return { error: "snapshots go to " + snaps.folder + " as snapshot-<run>-<n>.png: give \"\"" }
    return snaps.take(null)
  }
}
