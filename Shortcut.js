.pragma library

// The guide's keyboard shortcut: registered with Hyprland at runtime by
// hypr/om-pg.lua (run with `hyprctl eval`), never written into your Hyprland
// config. These helpers turn the setting into that call, check it against the
// bindings Hyprland already has, and read the message the shortcut sends back.

var PREFIX = "marcho78.om-pg|"
var EVENTS = ["toggle"]
// Our own binding's description ends with this, so a re-registration doesn't
// count it as taken by someone else (one registered before the guide was
// called Uber TV ends with its old name)
var SUFFIX = " (Uber TV)"
var OWN = [SUFFIX, " (Program Guide)"]
// The choices Settings offers, in order; "" is none.
var CHOICES = ["SUPER + ALT + T", "SUPER + ALT + V", "ALT + G", ""]
var DEFAULT = "SUPER + ALT + T"

var MODS = { SUPER: 64, ALT: 8, CTRL: 4, CONTROL: 4, SHIFT: 1 }

// "SUPER + ALT + T" → { keys, key, modmask }, or null if it isn't a shortcut
function parse(text) {
  var parts = String(text || "").toUpperCase().split("+").map(function(p) { return p.trim() }).filter(function(p) { return p })
  if (!parts.length) return null
  var key = parts.pop()
  if (!/^[A-Z0-9]{1,12}$/.test(key) || MODS[key] !== undefined) return null
  var modmask = 0
  for (var i = 0; i < parts.length; i++) {
    if (MODS[parts[i]] === undefined) return null
    modmask |= MODS[parts[i]]
  }
  if (!modmask) return null   // a shortcut needs a modifier
  var names = ["SUPER", "CTRL", "ALT", "SHIFT"].filter(function(m) { return modmask & MODS[m] })
  return { keys: names.concat([key]).join(" + "), key: key, modmask: modmask }
}

// "SUPER + ALT + T" → "Super + Alt + T"
function label(text) {
  var s = parse(text)
  if (!s) return ""
  return s.keys.split(" + ").map(function(p) { return p.length > 1 ? p.charAt(0) + p.slice(1).toLowerCase() : p }).join(" + ")
}

// Who already uses this shortcut ("" if nobody), from `hyprctl -j binds`
function takenBy(shortcut, binds) {
  var s = parse(shortcut)
  if (!s || !Array.isArray(binds)) return ""
  for (var i = 0; i < binds.length; i++) {
    var b = binds[i]
    if (!b || b.mouse === true || String(b.submap || "") !== "") continue
    var description = String(b.description || "")
    if (OWN.some(function(x) { return description.slice(-x.length) === x })) continue
    if (Number(b.modmask) === s.modmask && String(b.key || "").toUpperCase() === s.key)
      return description || String(b.dispatcher || "another shortcut")
  }
  return ""
}

function luaString(text) {
  var out = "\""
  var value = String(text)
  for (var i = 0; i < value.length; i++) {
    var c = value.charAt(i)
    var code = value.charCodeAt(i)
    if (c === "\\" || c === "\"") out += "\\" + c
    else if (code >= 32 && code < 127) out += c
    else if (code < 128) out += "\\" + ("00" + code).slice(-3)
    else {
      var bytes = unescape(encodeURIComponent(c + (code >= 0xd800 && code < 0xdc00 ? value.charAt(++i) : "")))
      for (var j = 0; j < bytes.length; j++) out += "\\" + ("00" + bytes.charCodeAt(j)).slice(-3)
    }
  }
  return out + "\""
}

// The `hyprctl eval` expression: the shortcut registered, or (shortcut
// null) everything of ours taken back out
function registration(luaFile, shortcut) {
  var s = parse(shortcut)
  var options = s
    ? "{ binds = { { keys = " + luaString(s.keys) + ", event = \"toggle\", description = " + luaString("Open the guide" + SUFFIX) + " } } }"
    : "{ remove = true }"
  return "return dofile(" + luaString(luaFile) + ")(" + options + ")"
}

// What the shortcut sent ("toggle"), or "" for anything else
function parseEvent(data) {
  var text = String(data || "")
  if (text.length > 80 || text.indexOf(PREFIX) !== 0) return ""
  var command = text.slice(PREFIX.length)
  return EVENTS.indexOf(command) >= 0 ? command : ""
}
