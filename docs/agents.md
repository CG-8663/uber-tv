# AI agents

An AI agent (Claude Code and others) can work the guide through its commands, once you turn the agent skill on.

## AI agents

The guide can be customized by an AI agent such as Claude Code or Codex. You
ask in your own words, for example:

- "Make Uber TV look like an 80s arcade"
- "Theme the guide to match my Omarchy theme"
- "Round the guide's cells, use Adwaita Sans and put the clock in the info panel"
- "Make the lower third a floating pill on the left"
- "Add this playlist to the guide: https://…/playlist_usa.m3u8"
- "Put the news channels in one category and show only those"
- "Make the timeline green, then save this as a theme called Sunday"
- "Use ~/Pictures/banner.png for the lower third and my logo instead of the title"
- "Make Jellyfin look like Netflix", "posters for my movies, hide Recently added"
- "Load the demo channels"
- "Put 101, 501 and 801 on Multiview, featured, sound from 501"
- "Record channel 132 for the next two hours", "record every episode of Bake Off", "save my recordings to the USB drive"

The agent does it through the guide's own commands, so nothing is edited
behind its back. It can make themes of any style and add them to the style
panel, change colors, fonts, shapes, sizes and the layout, the background
picture, the banner and the card, take a snapshot of the guide to check what
it made looks right, add M3U/M3U8
playlists, YouTube channels and channel lists, sort channels into
categories, rename them, choose what's shown, and open the guide on a
channel, and load the [demo channels](manual.md#demo-channels) when you say
so. It removes channels or themes only when you ask. **It can't turn on
the phone remote or touch the firewall:** there's no command for that.

**Apps' screens.** Agents can change how an app with code looks, as you
can with **C** on its screen: `appScreen` says how it looks and what's on
it, `setAppScreen` changes the choices (one app's, or every app's), and
`resetAppScreen` puts one back (only when you ask). Rows and items are named
by handles the guide makes, never by the app's own ids or words, so nothing
an app sends ever reaches an agent. `openApp` opens an app that comes with
the guide (refused while a box is open, something plays or the app has
stopped working; it never plays anything or presses an app's buttons), and
`appSnapshot` takes a picture of its screen only while nothing of the guide's
is over it. Each change is saved as a confirmed write, and `state` says when
it's on disk.

Agents can also arrange Home (`home`, `setHome`: its sections, tiles and
background) and the nav rail (`rail`, `setRail`), show the guide full screen
or in a window (`display`), turn My Videos on or off or
point it at another folder (`videos`, `setVideos`), add program listings
(`listings`, `addListings`, `removeListings`), and play from the library
or your videos (`library`, `videos`, `play`), and search everything
(`search`), and run Multiview: `multiview "101,501,801"` opens it with up
to four channels (never a locked one), then `multiviewAdd`,
`multiviewRemove`, `multiviewLayout`, `multiviewSound` and `multiviewClose`;
`state` says what's on it, and `multiviewBackground` sets what's behind the
tiles.

**Recordings.** They start off: until you turn them on (a strip asks you
once, or Settings → Recordings), the recording commands say so, and an agent
turns them on only when you ask. `record 132 "2h"` records a channel from now (`""`: to its
show's end plus the end-late minutes, or an hour without listings), `recordShow 132 21:00` schedules
a later show (IPTV with listings; `shows "" "bake off"` finds one, with the
day and time to give it), `recordSeries 132 now` records every
episode of a show, `cancelRecording` cancels a scheduled one or a series
(only when you ask), `recordUntil` changes when one stops, `stopRecording`
stops it, `recordings` lists them (the first 300; scheduled ones and series too) with their
state and why one didn't go as planned, `playRecording` plays one (`startOver` from the start, a movie or video too), and
`removeRecording` deletes one (only when you ask). `recordingSettings` and
`setRecordingSettings` are Settings → Recordings: where recordings go (your
Videos folder, a folder, or a USB drive that's already opened:
`recordingDrives` lists them), the space kept free, YouTube's quality and
the padding and how many record at once, and pause and rewind (5 or 30
minutes, or off); turning Recordings off while one records or is scheduled needs you to say so.
With pause and rewind on, `pauseLive` pauses the live channel on the TV (or
resumes it), `seekLive -60` goes back a minute (forward with a positive
number, as far as its buffer goes), and `goLive` goes back to live; each
answers whether it's paused, live, and how far behind. They refuse while
it's off (an agent never turns it on unasked), when no live channel is on,
or while its buffer can't run, saying why.
A locked channel is never recorded or played by an agent, and its
recordings say only *Locked recording* to it. The Recordings parts (the REC
badge, the Record choice, the cards) are theme parts like the rest
(`elements`, `setStyle`), Recordings can be a Home row (`setHome`) and a rail
item (`setRail`), and `libraryTabs` / `setLibraryTabs` order the library's
tabs.

**Turning it on.** The skill that teaches agents those commands
(`skills/program-guide/SKILL.md`) is off until you turn it on in Settings
(**,** → *AI agent skill*). The first time the guide opens it asks you. Until
you turn it on, or say no, a strip at the top of the guide offers it; ✕
dismisses the strip. On, the guide links the skill into the folders agents
read skills from, wherever they exist and nothing else is called
`program-guide` there: `~/.claude/skills`, `~/.codex/skills` (or
`$CODEX_HOME/skills`), `~/.agents/skills`, `~/.hermes/skills` and
`~/.pi/agent/skills`. Off takes those links out again, and only those. If
you remove the plugin while the skill is on, turn it off first, or delete the
`program-guide` links yourself.

**Any other assistant.** Settings → General → *Save the agent skill* saves a
copy of the skill as one Markdown file, `Uber TV agent skill.md`, in your
Downloads folder, to give to the AI assistant you use. Assistants that run
commands on this computer can use it as it is; a web chat can read it and
tell you what to run. Save it again after an update.

**The commands** work whether the skill is on or not, for scripts too. Each
answers with JSON. `omarchy-shell om-pg help` lists them all:

```bash
omarchy-shell om-pg state                         # the guide at a glance
omarchy-shell om-pg addChannels "https://example.com/playlist.m3u8"
omarchy-shell om-pg status                        # how that import is going
omarchy-shell om-pg demoChannels                  # the demo lineup: what's in it, how many you don't have
omarchy-shell om-pg loadDemoChannels              # adds those (nothing is removed)
omarchy-shell om-pg addTheme "$(cat my-theme.json)"
omarchy-shell om-pg saveTheme "Sunday" ""           # the look on screen, as a theme
omarchy-shell om-pg setImage lt ~/Pictures/banner.png frame 0.95
omarchy-shell om-pg elements programCell          # one part: what it takes, how it's styled
omarchy-shell om-pg setStyle programCell '{"radius": 0.4}'
omarchy-shell om-pg setStyle layout '{"clock": "info", "upNext": 2}'
omarchy-shell om-pg setStyle fonts '{"body": "Adwaita Sans"}'
omarchy-shell om-pg snapshot ""                   # a PNG of the guide on screen (state's snapshot: when it's written)
omarchy-shell om-pg setAppScreen tv.uber.jellyfin '{"look": "cinematic"}'
omarchy-shell om-pg openApp tv.uber.jellyfin ""   # answers the view it asked for
omarchy-shell om-pg themes
omarchy-shell om-pg theme retro
omarchy-shell om-pg reset original                # back to how the guide came
omarchy-shell om-pg reset undo                    # changed your mind
omarchy-shell om-pg watch 101
omarchy-shell om-pg multiview "101,501,801"       # Multiview, the first with the sound
omarchy-shell om-pg multiviewLayout grid
omarchy-shell om-pg record 132 "90"               # 90 minutes from now; "" to the show's end plus the end-late minutes
omarchy-shell om-pg recordShow 132 21:00          # the show on at 9 PM, scheduled
omarchy-shell om-pg recordings                    # their state, and why one didn't go as planned
```

**Claude Code** asks before running each command unless you allow them, in
`~/.claude/settings.json`:

```json
{ "permissions": { "allow": ["Bash(omarchy-shell om-pg:*)"] } }
```
