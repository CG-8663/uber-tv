// node tests/awake.test.mjs
// Awake.js: when the screen is kept awake (no Omarchy screen saver, no lock):
// never when off; while a video plays and shows; while the guide is on screen
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const A = new Function(readFileSync(new URL("../Awake.js", import.meta.url), "utf8").replace(".pragma library", "") +
  "; return { MODES, DEFAULT, checked, next, label, holding, videoPlays, windowSeen, SAVER_CLASS, address, saverEvent, focusTarget }")()

assert.deepEqual(A.MODES, ["off", "playing", "open"])
assert.equal(A.DEFAULT, "playing", "a playing video keeps it awake unless you say otherwise")
assert.equal(A.checked("open"), "open")
assert.equal(A.checked("always"), "playing", "an unknown one is the default")
assert.equal(A.checked(undefined), "playing", "none saved yet")
assert.equal(A.next("off"), "playing")
assert.equal(A.next("playing"), "open")
assert.equal(A.next("open"), "off", "Enter goes round")
assert.equal(A.label("open"), "While Uber TV is on")

const now = (shown, mini, playing) => ({ shown, mini, playing })
const cases = [
  // mode, shown, mini, playing, held
  ["off", true, false, true, false, "off: never, even playing on screen"],
  ["off", false, true, true, false, "off: never, in the mini player either"],
  ["playing", true, false, true, true, "a video playing in the guide"],
  ["playing", false, true, true, true, "a video playing in the mini player"],
  ["playing", true, false, false, false, "the guide on screen, nothing playing (or paused)"],
  ["playing", false, false, true, false, "playing where it can't be seen (the window on another desktop)"],
  ["open", true, false, false, true, "the guide on screen, nothing playing"],
  ["open", false, true, true, true, "the guide closed, the mini player playing"],
  ["open", false, true, false, false, "the guide closed, the mini player paused: you're working"],
  ["open", false, false, false, false, "nothing on screen"],
  ["bogus", true, false, true, true, "an unknown mode acts as the default"],
]
for (const [mode, shown, mini, playing, held, why] of cases)
  assert.equal(A.holding(mode, now(shown, mini, playing)), held, why)
// the screen saver on: held while Uber TV shows, whatever Keep the screen awake says
assert.equal(A.holding("off", { shown: true, mini: false, playing: false, saver: true }), true, "screen saver on, Uber TV on screen")
assert.equal(A.holding("playing", { shown: true, mini: false, playing: false, saver: true }), true, "the same with the default")
assert.equal(A.holding("off", { shown: false, mini: true, playing: false, saver: true }), false, "not for the mini player alone")
assert.equal(A.holding("off", { shown: false, mini: false, playing: false, saver: true }), false, "nor with nothing on screen")

// The guide's player: playing only while the guide has it on
const plays = (playing, stalled, reception) => A.videoPlays({ playing, stalled, reception })
assert.equal(plays(true, false, "on"), true, "on and playing")
assert.equal(plays(true, false, "lost"), false, "a dead stream or an error: lost, though the player still says playing")
assert.equal(plays(true, false, "tuning"), false, "still tuning (a stuck one turns lost after 20 s)")
assert.equal(plays(true, false, "off"), false, "turned off")
assert.equal(plays(true, true, "on"), false, "stalled, waiting for data")
assert.equal(plays(false, false, "on"), false, "paused")

// The guide's window shows on a screen
const PID = 4242, TITLE = "Uber TV"
const top = (title, pid, ws, active, monitor = "eDP-1") => ({ title, pid, monitor, workspace: { name: ws, active } })
const seen = (tops, specials = { "eDP-1": "" }) => A.windowSeen(tops, TITLE, PID, specials)
assert.equal(seen([top(TITLE, PID, "1", true)]), true, "on the desktop that shows")
assert.equal(seen([top(TITLE, PID, "9", false)]), false, "on a desktop that doesn't show")
assert.equal(seen([top(TITLE, PID, "special:tv", false)], { "eDP-1": "special:tv" }), true, "on the special workspace shown on its screen")
assert.equal(seen([top(TITLE, PID, "special:tv", false)]), false, "on a special workspace that's hidden")
assert.equal(seen([top(TITLE, PID, "special:tv", false, "HDMI-A-1")], { "eDP-1": "special:tv", "HDMI-A-1": "" }), false, "a special workspace shown on another screen isn't its own")
assert.equal(seen([top(TITLE, 999, "9", false), top(TITLE, PID, "1", true)]), true, "another app's window with its title, on a hidden desktop, doesn't count")
assert.equal(seen([top(TITLE, 999, "1", true), top(TITLE, PID, "9", false)]), false, "nor does one that shows, while the guide's doesn't")
assert.equal(seen([top(TITLE, undefined, "1", true)]), true, "its process not known yet: maybe the guide's")
assert.equal(seen([top("Something else", PID, "1", true)]), true, "not found yet (just appearing): yes")
assert.equal(seen([]), true, "no windows listed yet: yes")

// Omarchy's own screen saver, from Hyprland's window events
assert.equal(A.SAVER_CLASS, "org.omarchy.screensaver")
assert.equal(A.address("55C3ce1b"), "0x55c3ce1b", "Hyprland's events give it without 0x")
assert.equal(A.address("0x55c3ce1b"), "0x55c3ce1b")
assert.equal(A.address(""), "", "none")
assert.equal(A.address("0x55; rm"), "", "anything but hex isn't an address (it goes into a dispatcher)")
assert.deepEqual(A.saverEvent("openwindow", ["55c3ce1b", "1", "org.omarchy.screensaver", "foot"]), { open: "0x55c3ce1b" }, "one of its windows opens")
assert.equal(A.saverEvent("openwindow", ["55c3ce1b", "1", "foot", "org.omarchy.screensaver"]), null, "another window, whatever its title")
assert.equal(A.saverEvent("openwindow", ["55c3ce1b", "1"]), null, "too few fields")
assert.deepEqual(A.saverEvent("closewindow", ["55c3ce1b"]), { close: "0x55c3ce1b" }, "any window closing (it's checked against the ones open)")
assert.equal(A.saverEvent("activewindow", ["foot", "x"]), null, "other events")

// Which saver to focus: never one on another screen
const sv = (address, monitor) => ({ address, monitor })
assert.equal(A.focusTarget([sv("0xa", "eDP-1")], "0xb", "eDP-1"), "0xa", "the saver on the screen with focus, when it isn't active")
assert.equal(A.focusTarget([sv("0xa", "eDP-1")], "0xa", "eDP-1"), "", "it's the active window already")
assert.equal(A.focusTarget([sv("0xa", "DP-1"), sv("0xb", "eDP-1")], "0xa", "eDP-1"), "", "a saver is active (one per screen is enough for Omarchy)")
assert.equal(A.focusTarget([sv("0xa", "DP-1")], "0xc", "eDP-1"), "",
  "Omarchy moved focus to the next screen and its saver isn't there yet: don't pull focus back to the first")
assert.equal(A.focusTarget([sv("0xa", "DP-1"), sv("0xb", "eDP-1")], "0xc", "eDP-1"), "0xb", "the second screen's saver arrived: that one")
assert.equal(A.focusTarget([sv("0xa", "")], "0xc", "eDP-1"), "", "its screen not known yet: wait for the next try")
assert.equal(A.focusTarget([], "0xc", "eDP-1"), "", "none open")
console.log("awake: all good")
