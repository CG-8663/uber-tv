// node tests/remotepage.test.mjs
// The phone remote's page (remote/index.html), its script run with the page
// stood in: a channel number goes after a moment, or on GO or OK (the big
// button in the middle); while the TV asks for the channel lock's passcode,
// the pad types that instead (dots, never sent by itself), and GO or OK sends
// it as text, a leading 0 and all
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"

const html = readFileSync(new URL("../remote/index.html", import.meta.url), "utf8")
const src = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].pop()[1]

function page() {
  const sent = []
  const els = {}
  const el = (id) => els[id] || (els[id] = { id, textContent: "", hidden: false, style: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
    append(...k) { this.textContent += k.map(x => x.textContent ?? x).join("|") }, appendChild() {}, addEventListener(t, f) { this["on" + t] = f },
    focus() {}, getAttribute() { return null }, setAttribute() {} })
  const digits = [..."0123456789"].map(d => Object.assign(el("digit" + d), { dataset: { digit: d } }))
  const cmds = ["power", "mute", "up", "down", "left", "right", "ok", "back", "guide", "full", "mini", "chup", "chdown", "options"].map(c => Object.assign(el("cmd" + c), { dataset: { cmd: c } }))
  const timers = []
  const env = {
    document: {
      querySelector: (s) => el(s.replace(/^#/, "")),
      querySelectorAll: (s) => s === "[data-digit]" ? digits : s === "[data-cmd]" ? cmds : [],
      createElement: () => ({ textContent: "", style: {}, classList: { toggle() {} }, append() {}, addEventListener() {} }),
      createTextNode: (t) => ({ textContent: t }),
    },
    navigator: {},
    EventSource: class { close() {} },
    // a press is a POST; the page's own start (GET /api/state) is told to pair,
    // so the state each test gives is the one it has
    fetch: async (path, opts) => {
      if (opts && opts.body) { sent.push(JSON.parse(opts.body)); return { ok: true, status: 204, json: async () => ({}) } }
      return { ok: false, status: 401, json: async () => ({}) }
    },
    setTimeout: (f) => { timers.push(f); return timers.length },
    clearTimeout: (i) => { if (i) timers[i - 1] = null },
  }
  const names = Object.keys(env)
  const run = new Function(...names, src + "\n;return { render }")
  const p = run(...names.map(n => env[n]))
  return {
    render: (s) => p.render(s),
    press: (keys) => { for (const k of keys) els["digit" + k].onclick() },
    cmd: (c) => els["cmd" + c].onclick(),
    go: () => els.enter.onclick(),
    wait: () => { const due = timers.splice(0); due.forEach(f => f && f()) },
    shown: () => els.typed.textContent,
    sent: async () => { await new Promise(r => setImmediate(r)); return sent.splice(0) },
  }
}

// a channel number
let p = page()
p.render({ on: true, channels: [] })
p.press("101")
assert.equal(p.shown(), "CHANNEL|101")
p.wait()
assert.deepEqual(await p.sent(), [{ cmd: "tune", number: 101 }], "it goes after a moment")
p.press("102"); p.go()
assert.deepEqual(await p.sent(), [{ cmd: "tune", number: 102 }], "or on GO")
p.press("103"); p.cmd("ok")
assert.deepEqual(await p.sent(), [{ cmd: "tune", number: 103 }], "or on OK, the big button in the middle (not an OK as well)")
p.cmd("ok")
assert.deepEqual(await p.sent(), [{ cmd: "ok" }], "with nothing typed, OK is OK")

// the channel lock's passcode
p = page()
p.render({ on: true, channels: [], passcode: true })
p.press("0246")
assert.equal(p.shown(), "PASSCODE|••••", "dots, never the digits")
p.wait()
assert.deepEqual(await p.sent(), [], "never sent by itself")
p.go()
assert.deepEqual(await p.sent(), [{ cmd: "code", digits: "0246" }], "GO sends it as text, a leading 0 and all")
p.press("13579"); p.cmd("ok")
assert.deepEqual(await p.sent(), [{ cmd: "code", digits: "13579" }], "and so does OK")
p.press("12"); p.go()
assert.deepEqual(await p.sent(), [], "fewer than 4 digits: nothing")
p.press("12345678"); p.press("9"); p.go()
assert.deepEqual(await p.sent(), [{ cmd: "code", digits: "12345678" }], "at most 8")
p.press("55")
p.render({ on: true, channels: [], passcode: false })
assert.equal(p.shown(), "", "the TV stops asking: what was typed goes")
console.log("remote page: all good")
