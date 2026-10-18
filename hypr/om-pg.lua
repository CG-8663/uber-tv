-- Uber TV (marcho78.om-pg): its keyboard shortcut, the Hyprland half.
--
-- The guide runs this inside Hyprland with `hyprctl eval` when it starts,
-- after every Hyprland config reload, and when the shortcut setting changes:
--
--   return dofile("<plugin>/hypr/om-pg.lua")({ binds = { { keys = "SUPER + ALT + T", event = "toggle", description = "…" } } })
--   return dofile("<plugin>/hypr/om-pg.lua")({ remove = true })
--
-- The shortcut sends a message to the guide over Hyprland's event socket
-- (hl.dsp.event). Nothing here runs programs or reads or writes files, and
-- your Hyprland config is never edited: a config reload drops the shortcut,
-- and the guide registers it again. Anything that didn't register is raised
-- as an error, so the guide's Settings can say what went wrong.

local PREFIX = "marcho78.om-pg|"
local EVENTS = { toggle = true }
local STATE = "__marcho78_om_pg"

return function(options)
  options = type(options) == "table" and options or {}

  -- What earlier runs registered in this Lua state (a config reload starts a
  -- fresh one): replaced every time, so shortcuts never pile up.
  local state = rawget(_G, STATE)
  if type(state) ~= "table" then
    state = { binds = {} }
    rawset(_G, STATE, state)
  end
  for _, bind in ipairs(state.binds or {}) do pcall(function() bind:remove() end) end
  state.binds = {}

  if options.remove == true then return "ok" end

  local problems = {}
  local function problem(text)
    problems[#problems + 1] = tostring(text):gsub("[\r\n|;]", " ")
  end

  for _, bind in ipairs(type(options.binds) == "table" and options.binds or {}) do
    local keys = type(bind) == "table" and bind.keys or nil
    local event = type(bind) == "table" and bind.event or nil
    local description = type(bind) == "table" and bind.description or ""
    if type(keys) ~= "string" or #keys > 64 or not keys:match("^[%w_ %+]+$") then
      problem("skipped a shortcut with invalid keys")
    elseif not EVENTS[event] then
      problem("skipped " .. keys .. ": unknown action")
    else
      if type(description) ~= "string" or #description > 80 or not description:match("^[%w%p ]*$") then
        description = "Uber TV"
      end
      local done, handle = pcall(hl.bind, keys, hl.dsp.event(PREFIX .. event), { description = description })
      if done and handle then
        state.binds[#state.binds + 1] = handle
      else
        problem(keys .. ": " .. (done and "Hyprland didn't take it (is the key name right?)" or tostring(handle)))
      end
    end
  end

  if #problems == 0 then return "ok" end
  error(table.concat(problems, "; "), 0)
end
