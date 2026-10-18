import QtQuick

// The computer's password, one prompt at a time:
// turning on Unknown sources or Developer mode, installing a signed app file,
// resetting the channel lock, and resetting Uber TV while a channel lock is
// set each ask for it through
// the system's own prompt (run by ChannelLock.qml's auth), which
// Uber TV can't fake.
//
// authorize(kind, payload, done, still): kind is what it's for, payload
// exactly what's approved (an address, two fingerprints), both kept while
// the prompt is up (asked). still(), if given, is checked when the prompt is
// answered: if the box it was asked from closed, or what it approves changed
// meanwhile, a yes does nothing. done(given, why): given only if the
// password was given and it's still what was asked; why is "busy" (another
// prompt is up), "changed", "unavailable" (no prompt can be shown: it fails
// closed) or "refused". While busy the guide lets go of the keyboard (so the
// prompt gets it) and refuses the phone remote and its boxes' actions.
QtObject {
  id: auth

  // ask(done(given, why)): the prompt itself (ChannelLock.qml's auth; the tests stand one in)
  property var ask: null
  property bool busy: false
  property var asked: null               // { kind, payload } while the prompt is up
  readonly property var kinds: ["unknownSourcesOn", "developerOn", "appFileInstall", "lockReset", "resetAll"]

  function authorize(kind, payload, done, still) {
    if (auth.kinds.indexOf(kind) < 0 || !auth.ask) { done(false, "unavailable"); return false }
    if (auth.busy) { done(false, "busy"); return false }
    auth.busy = true
    auth.asked = { kind: kind, payload: payload === undefined ? null : payload }
    var answered = false
    auth.ask(function(given, why) {
      if (answered) return
      answered = true
      auth.busy = false
      auth.asked = null
      if (given === true && still && !still()) { done(false, "changed"); return }
      done(given === true, given === true ? "" : why || "refused")
    })
    return true
  }

  // in words, for the box that asked ("" when it was given)
  function said(why) {
    return why === "busy" ? "The computer's password is being asked for already."
         : why === "changed" ? "Nothing changed: what you were asked about changed meanwhile."
         : why === "unavailable" ? "Nothing changed: the computer's password prompt can't be shown here."
         : why ? "Nothing changed: the computer's password wasn't given." : ""
  }
}
