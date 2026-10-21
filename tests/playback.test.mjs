// The players and the screen under them, from the guide's own code: every
// player's sound follows the system's sound output now (MediaDevices), so a
// sound server that restarts doesn't leave Uber TV silent until the shell
// restarts; Home is made only while it's on screen, not under the splash, a
// channel full screen, an app's media or a closed guide.
//   node tests/playback.test.mjs
import assert from "node:assert/strict"
import { readFileSync, readdirSync } from "node:fs"

const read = f => readFileSync(new URL("../" + f, import.meta.url), "utf8")
const files = [".", "ui"].flatMap(d => readdirSync(new URL("../" + d + "/", import.meta.url))
  .filter(f => f.endsWith(".qml")).map(f => d === "." ? f : d + "/" + f))
// an object's body: from its opening brace to the brace that closes it
const body = (text, open) => {
  let depth = 0
  for (let i = open; i < text.length; i++) {
    if (text[i] === "{") depth++
    else if (text[i] === "}" && --depth === 0) return text.slice(open + 1, i)
  }
  assert.fail("unclosed object")
}

// ---- every AudioOutput follows the default output ----
{
  let outputs = 0
  for (const f of files) {
    const src = read(f)
    for (const m of src.matchAll(/\bAudioOutput\s*\{/g)) {
      outputs++
      const device = body(src, m.index + m[0].length - 1).match(/\bdevice:\s*(\w+)\.defaultAudioOutput\b/)
      assert.ok(device, f + ": an AudioOutput without device: <MediaDevices>.defaultAudioOutput")
      assert.match(src, new RegExp("MediaDevices\\s*\\{\\s*id:\\s*" + device[1] + "\\s*\\}"), f + ": no MediaDevices " + device[1])
    }
  }
  assert.ok(outputs >= 3, "the TV's, the apps' and Multiview's outputs: found " + outputs)
}

// ---- Home only while it's on screen: its loader, and its rows and cards ----
{
  const src = read("Guide.qml")
  // the guide's own expressions, run over a stand-in (with: as QML's scope)
  const binding = name => {
    const m = src.match(new RegExp("readonly property \\w+ " + name + ": "))
    assert.ok(m, "missing: " + name)
    const from = m.index + m[0].length
    return src[from] === "{" ? body(src, from) : "return " + src.slice(from, src.indexOf("\n", from))
  }
  const run = (name, scope) => new Function("scope", "with (scope) { " + binding(name) + " }")(scope)
  const on = { screen: "home", opened: true, watching: false, appPlaying: false, pip: false, splashItem: { running: false } }
  const with_ = o => Object.assign({}, on, o)
  assert.equal(run("homeOnScreen", on), true, "Home in the guide")
  assert.equal(run("homeOnScreen", with_({ pip: true })), true, "Home beside the mini player")
  assert.equal(run("homeOnScreen", with_({ watching: true })), false, "a channel full screen")
  assert.equal(run("homeOnScreen", with_({ appPlaying: true })), false, "an app's media full screen")
  assert.equal(run("homeOnScreen", with_({ opened: false })), false, "the guide closed")
  assert.equal(run("homeOnScreen", with_({ screen: "library" })), false, "another screen")
  assert.equal(run("homeOnScreen", with_({ splashItem: { running: true } })), false, "under the splash")

  const at = src.indexOf("HomeScreen { guide: root }")
  assert.ok(at > 0, "Home's loader")
  assert.match(src.slice(src.lastIndexOf("Loader {", at), at), /\n\s*active: root\.homeOnScreen\n/, "Home's loader goes by homeOnScreen")

  // hidden, homeView reads nothing else (the clock, the channels and a
  // listing then don't work it out again); on screen, it goes through the sections
  const reads = []
  // (what the binding writes, its own variables under with, it reads back)
  const scope = homeOnScreen => new Proxy({}, {
    has: () => true,
    set: (t, k, v) => { t[k] = v; return true },
    get: (t, k) => {
      if (typeof k !== "string") return undefined
      if (k in t) return t[k]
      reads.push(k)
      return k === "homeOnScreen" ? homeOnScreen : k === "homeSections" ? [] : undefined
    }
  })
  assert.deepEqual(run("homeView", scope(false)), [], "hidden: no rows")
  assert.deepEqual(reads, ["homeOnScreen"], "hidden: read only homeOnScreen, read " + reads.join(", "))
  reads.length = 0
  assert.deepEqual(run("homeView", scope(true)), [], "on screen, no sections: no rows")
  assert.ok(reads.includes("homeSections"), "on screen: goes through the sections")

  // openHome measures the cursor only against rows that are there
  const open = src.slice(src.indexOf("function openHome() {"), src.indexOf("function moveHome("))
  assert.match(open, /if \(root\.homeOnScreen\) root\.homeRow = /, "openHome clamps only with Home on screen")
}

console.log("playback: ok")
