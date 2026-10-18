// node tests/shortcut.test.mjs
// Shortcut.js: the guide's own binding never counts as taken, whether it was
// registered under its name now (Uber TV) or its name before (Program Guide)
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const S = new Function(readFileSync(new URL("../Shortcut.js", import.meta.url), "utf8").replace(".pragma library", "") +
  "; return { takenBy, SUFFIX, parse }")()

const bind = description => ({ modmask: 72, key: "T", description, dispatcher: "event" })
assert.equal(S.SUFFIX, " (Uber TV)")
assert.equal(S.takenBy("SUPER + ALT + T", [bind("Open the guide (Uber TV)")]), "", "its own, under its name now")
assert.equal(S.takenBy("SUPER + ALT + T", [bind("Open the guide (Program Guide)")]), "", "its own, registered before the rename")
assert.equal(S.takenBy("SUPER + ALT + T", [bind("Screenshot")]), "Screenshot", "someone else's is taken")
assert.equal(S.takenBy("SUPER + ALT + V", [bind("Screenshot")]), "", "another key is free")
console.log("shortcut: all good")
