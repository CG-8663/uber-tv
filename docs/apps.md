# Apps

Apps add to the guide: websites it opens, and apps with code that it runs in a sandbox and draws itself. How they're installed, checked, run and written.

## Apps

Apps bring services like Netflix, Hulu and Pluto TV into the guide, each
opening full screen, as on a TV. They're **off until you turn them on**:
Settings → Apps → Apps asks first ("Not now" is picked to begin with), and
turning apps off stops every app at once (they stay installed, off). With apps
on, an **Apps** item joins the nav rail and **Your apps** joins Home.

**Getting one.** **Get apps** lists the Uber TV catalog: Uber TV's own apps
(it takes no submissions). Pick an app and the guide checks it before
showing you anything: the catalog's signature (checked again, not taken from
the copy it keeps), the package's SHA-256, a safe unpack, its `app.json`. Then
you see who made it, where it's from, and what it asks for, in plain words
("Open netflix.com, full screen"), with **Install** and **Cancel**. Nothing is
installed until you say so, and what installs is exactly what you were shown.

**Your apps.** On the Apps screen (the rail) or Home, **Enter** (or a click)
opens one full screen (with the guide in a window, maximized under the bar
instead), with no browser bar, and the guide makes way. **Super +
W** closes it and brings the guide back where you were; the guide's own key
(or **Back** on the phone remote) brings the guide back over it while it stays
on, marked **ON NOW** on the Apps screen, where **Enter** goes back to it and
**X** closes it. One app is on at a time: opening another closes it. While one
is opening, **Esc** calls it off (so does putting the guide away, turning the
app off or opening another), and if its window turns up anyway in the next few
seconds, it's closed. The guide takes charge only of the window it starts: a
window for that app's website that wasn't open before, and opens within
seconds of the guide starting it (a YouTube TV window you already had open
stays as it is). It comes back by itself only if you were in the app when it
closed, so it never takes the keyboard while you're working in something else.
**I** (or Enter in Settings) shows its details: where it's from, what it's
allowed, its switch, Open it, Remove (Enter twice; its files go). Turning an
app off closes it, if the guide opened it.

**Updates.** The guide looks at the catalog about twice a day, and with Check
for updates. An update that asks for nothing new installs by itself, in the
background, never while you're installing one; one that asks for more waits in
the app's details until you agree. If the catalog pulls a bad app, it's turned
off and you're told why, and a pulled version is never offered or installed.

**Third-party apps** (Settings → Apps, off) is for a signed `.tvapp` file you
downloaded yourself. Turning it on asks for the computer's password and adds
**Install a third-party app**. Its picker stays inside your home folder. The review
shows the developer's key fingerprint, version and everything the app asks
for; **Install** asks for the computer's password again. Picking and installing
the file contacts nothing. A file with the same app id but another key is a
different developer's app: the review says it replaces yours as a new app and
keeps none of its saved data, sign-in, server, pictures or Activity.

If the signed file names an update address, Uber TV fetches only its small
signed release note about twice a day while the Third-party apps switch is on. A newer
version appears as **Update available** in the app's details. **Update** shows
the exact package address, version, size, developer key and permissions, with
new asks highlighted; only **Agree** fetches the package. A version withdrawn
by its developer turns off and says why. Turning off Third-party apps stops
these apps and all update checks; they stay installed. Each start verifies the
installed package, signed release and pinned key without contacting anything.
Uber TV doesn't make or check these apps: the signature identifies their
developer, not whether anyone reviewed the code. To publish one, see
[App files from outside Uber TV](sources.md).

**Developer mode** is hidden until you ask for it: press Enter (or click) 7
times on the Uber TV row in Settings → About, as its Developer mode line
says (from the third press it counts down; a pause of 3 seconds starts
over). Settings then shows a Developer part, off, and
turning it on asks first, then for the computer's password. Switched off
again, its row goes (until the next 7 presses). It adds
**Install an unsigned app**: a package (`.tar.gz`) or an app's folder (pick its `app.json`), for
people making apps. The picker searches your home folder as you type, or
**Tab** browses a folder at a time. The review says in red that Uber TV didn't
make it; an app from a file shows a small page on its tile, on Home and on
its band, and opens only while Developer mode is on.

**What an app is.** Most apps are *launchers*: a website the guide opens in
your browser's app window (`omarchy-launch-webapp`) and puts full screen (or
maximized, with the guide in a window), with nothing run on this computer. It's your browser because the big streaming
services only play there: they need its DRM (Widevine), which the shell's own
web engine doesn't have, and you stay signed in as you are in it. It can't see
your files, your channels or other apps, and you sign in on the website itself,
never in the guide. A few apps **run code in a sandbox**, and the guide draws
their screens: see [Apps with code](#apps-with-code).

### Apps with code

**Scores** (live, upcoming and final games from ESPN's public scoreboard) and
**Jellyfin** (your Jellyfin server's movies and shows) come with the guide: Get
apps lists them first, you see what they ask for, and they install from the
guide's own copy (part of the plugin, reviewed with it), and update with it.
In Developer mode, an app with code can also come unsigned from a folder or
package; a signed `.tvapp` instead uses Third-party apps and shows its
developer's key.

**What they look like.** They open in the guide, full screen, as on a TV: rows
of posters, grids, lists, an item's details with its picture and facts, and
their own media playing in the guide's player. The app never draws anything
and never sees a key: it sends what to show (plain text, pictures, what to
play), and the guide draws it. **Enter** does what an item says (opens it,
plays it, shows its details), **I** shows details, **/** searches the app,
**R** loads it again (a screen a button made isn't asked for again), **,**
opens its settings (its own settings, its server, signing in, clearing its
data), **Esc** goes back. Playing, **Space** pauses, **← →** skip 10 seconds,
**Esc** stops. Each row shows its pictures in their own shape (posters, wide
stills, squares, logos shown whole, people in circles), as the app says or as
the guide works out from the first pictures. A band across the top always says
which app it is (its icon, APP, its name, and a small file badge for one
installed from a file), and
nothing an app or a theme draws covers it.

**Richer screens** (API 4): an app can send a **table** (its columns' names,
then a line each item: standings, a schedule), a **ticker** (a line of short
news or scores moving across, which stops while it's selected, while the
screen saver is up and while a video plays), a **chart** (a line the guide
draws, in a list or table line and on a details page) and an **article page**
(a title and sections, which the arrows scroll). The guide draws them all,
in every look, from plain text and numbers. A screen can also be **live**:
while it's on the screen, the app updates its rows (Scores: a game in
progress changes on its own), and an API 4 app's Home rows update the same
way while Home is shown, every 5 seconds at most. Nothing updates once you've
moved on, and a row replaced again and again keeps only its own pictures.

**Looks.** An app's screen comes in five looks: **Classic** (as the app says,
titles under the cards, a details page's backdrop behind it), **Posters**
(posters wherever a row has them), **Cinematic** (wide pictures, large cards,
what's selected told large at the top, the selected item's picture blurred
behind the screen, and details pages with the backdrop across the screen and
the title logo), **Wall** (small posters, no titles, what's selected at the
top, its picture behind) and **Compact** (small cards on the theme's colors).
An app suggests one (Jellyfin: Posters), and a theme can set one for every app
(its `apps`), above the app's. A look never hides, reorders or re-lays-out an
app's rows.

**Customize** (**C** on an app's screen, or ⋯ Options on the phone remote)
opens "Customize Jellyfin" down the right, over the screen it changes: its
look, the top of the screen, the background (or a picture of yours), how dark
it is, the details page, titles under cards and card size, each also "As for
all apps". Then its rows: show or hide each, give it your own name, its
pictures (posters, wide, square, logos, round), size, layout and titles, and
move it up or down (a hidden row stays listed, so it can come back). Each
change shows at once and is saved as you make it ("Saving…", then "Saved");
"Follow all apps' settings" takes this app's off. **Settings → Apps → How apps
look** has the same look rows for every app, each "As the theme" where you
leave it, showing what the theme gives; an app's box in Settings → Apps has
"Customize its screen". **S** on an app's screen opens the style panel. Saving
the look as a theme keeps how every app looks (not one app's own choices). Rows the app makes featured show one big item at a time (← and →
change it). Cards mark what's watched with a ✓. However a theme styles them
(the APPS parts, which look like the library's until styled), the selected card
keeps the guide's focus ring and a readable title, and text never goes under
its 10-foot size. An app can offer rows for Home
(Continue watching, Scores now): they show only once you add them in Customize
Home (C), and stay up to date while Home is on the screen. On Home, every card
in a row is one height and as wide as its picture's shape, a poster narrower
than a wide picture, the guide's own rows too.

**Before it installs, you see what it can do**, laid
out to read from the couch: who made it and where it's from ("From Uber TV",
or "From a file on this computer · Uber TV didn't make this app"), one line on
what it can do ("It connects to 2 sites and can change things on 1"), then a
row for each kind of thing, each with its icon: **Can change things on** (the
sites it may send data to and change or delete things on, with how: POST,
PUT, PATCH, DELETE; first, and in the accent color), **Connects to** (the
sites it gets things from: what it asks for can carry information, so this
isn't "read only"), **Your server**, **Plays media from**, **Signs in**,
**Keeps on this computer** and **Shows on Home**. A row of more than three
sites shows three and folds the rest, and **Can't** (your files, channels,
history and other apps, sites it didn't list, your home network beyond your
server, running programs, more than its share) is one line; Enter opens
either, Esc folds it again. An update shows only what's new in it, with what it
had before folded. The cursor starts on **Install** for Uber TV's own apps, and
on **Cancel** for anyone else's, a replace, or an update that adds a way to
change things (a site, a method on a site, or a server), so a stray OK never
installs it.

**Activity.** An app's details box (Settings → Apps → the app) shows what it
actually contacted in the last 90 days: each site, whether it got things or
changed things there, how often, how much and when last (newest first), and
the sites it tried and was refused ("Tried to reach tracker.example: refused,
3 times"). The first refusal while it's on the screen also says so, once a
session. It's kept as daily totals per site
(`~/.local/state/om-pg/app-activity/`, readable by you alone, at most 1 MB an
app): never an address's path or query, a header or a body, which can hold a
secret. The names of refused sites have a small budget of their own, so an
app trying many or long addresses can't push out what it really did. Agents
can't read it. Removing the app, or clearing its data, removes it.

**Signing in** (Jellyfin) is with a code: choose Sign in in the app's
settings, and the guide shows the code big, with a QR code; enter it in
Jellyfin (its Quick Connect). An app can also offer **your username and
password** (Jellyfin does, for a server with Quick Connect off): choose "Sign in
with your username and password", and the guide's own box takes them, typed on
the keyboard only (the phone remote can't type there), the password as dots.
They go to the app once, to sign in; Uber TV keeps only what the service gives
back, never the password, and keeps them out of the app's log. Snapshots are
refused while the box is up, and agents can't open it. After 5 wrong passwords
in a row, the box waits 30 seconds.

**Choosing your server while signing in.** For a service whose online account
lists your servers (Plex, say), an app can have you choose the server as you
sign in, instead of typing it first: once you're signed in to the account,
the box lists your servers; you choose one, then one of its addresses or
**Type an address for this server**. The app keeps only that server's own
key, and Uber TV keeps the server with the sign-in, so it works the next time
without signing in again. If the app already has another server, it asks
first: "Switch to it? What it kept from the old one is cleared, and you sign
in again." Changing the server later from the app's settings works as it
always has (it signs you out). See `apps/sdk/examples/accounts`. Sign out forgets the sign-in, whatever the app
says. A server with a certificate this computer doesn't trust (a home server's
own) can have its certificate pinned there, on your say-so.

**The sandbox.** Each app runs in bubblewrap, with no network, no home folder,
nothing writable but 16 MB of scratch space that's gone when it stops, and only
the system's own programs read-only. A helper of the guide's
(`bin/om-pg-apprun`) speaks for it: it checks everything the app says, and does
everything the app may not do itself. Its requests go only to the exact hosts
it asked for (https; GET and HEAD, plus the methods it asked to change things
with on a site, API 4) or the server you chose, checked before any
lookup or connection (never your network's other machines, or a private
address a public name points at); its pictures are fetched and checked
(PNG, JPEG or WebP, 4096 by 4096 at most) before the guide decodes them; what
it plays reaches the player through a relay on 127.0.0.1 that checks the
media's format and rewrites playlists, so the player never gets a link the app
chose (an HLS playlist's links are http or https only: one that gives its key
as a `data:` link isn't played); its storage (4 MB) and its secrets (`~/.config/om-pg/app-secrets/`,
readable by you alone) are kept by the helper. At most 3 apps run at once, each
with 320 MB, half a core and 48 tasks; one with nothing on the screen stops
after 3 minutes, and one that keeps failing stops until you open it again.

**How apps with code are run and stopped.** The
guide runs each app with code in a systemd user scope of its own
(`systemd-run --user --scope`, named `om-pg-app-<source>-<app>-<run>`) and
stops it with `systemctl --user stop` or `kill` on that unit, so its memory,
CPU and task limits hold and nothing it starts outlives it; at start it also
stops any such scope a crashed guide left behind (only ones with exactly that
name). It doesn't install, enable or change any service, and it touches no
other unit.

**Where it's kept.** An app's files: `~/.local/share/om-pg/apps/<source>/<id>/<version>/`
(read-only); its storage: `~/.local/share/om-pg/app-store/`; its secrets:
`~/.config/om-pg/app-secrets/`; its log (the last 64 KB, secrets taken out):
`~/.local/state/om-pg/app-logs/`; its Activity: `~/.local/state/om-pg/app-activity/`;
its pictures: `~/.cache/om-pg/app-img/`. Removing an app removes all of it.

**Making one.** An app is a folder with an `app.json` and Python (the standard
library only, plus the guide's small toolkit, `apps/sdk/uber_tv.py`); see
`apps/sdk/PROTOCOL.md`, the two in `apps/first-party/`, and
`apps/sdk/examples/showcase`, an offline app that uses every block the guide
draws (start from it). An app says its
API in `app.json`: 4 adds the sites it may change things on (`netWrite`:
`{"api.example.com": ["POST"]}`, each one of its `net` sites, with the
methods); 3 adds a row's picture shape and size, an item's pictures for each
shape, a short line and text, and a details page's style, title logo and
chips; an app at 2 works as it always has. An update from 2 to 3 that asks for
nothing new installs quietly; anything else waits for you (an update to 4
too). `try` lets a write reach a site or the server only with
`--allow-write`. Check one, try it
in the same sandbox (offline, answering its requests from fixtures, unless
`--live`; it prints each row's layout, shape and size, where each came from,
and the picture each card shows, in the look the app suggests, before anyone's
choices), and pack it:

```bash
python3 bin/om-pg-apps check ~/my-app
python3 bin/om-pg-apps try apps/sdk/examples/showcase --call home   # every block, offline
python3 bin/om-pg-apps try ~/my-app --call home --fixtures fixtures.json
python3 bin/om-pg-apps try ~/my-app --live --call 'details:{"item":"42"}'
python3 bin/om-pg-apps pack ~/my-app my-app.tar.gz
```

### How an app is checked

- **The catalog** is `catalog.json` with a signature (`catalog.json.sig`), made
  with the catalog's key and checked with `ssh-keygen -Y verify` against the
  keys the guide ships with (`apps/catalog-signers`: the one it's signed with,
  and a spare kept offline in case that one's lost; only their public halves
  are here, which can check a signature but never make one). A catalog that isn't
  signed by it, or was changed after signing, is refused, and so is one older
  than one the guide has already seen, so an old one can't be replayed, and
  one whose revocations can't be read. The guide keeps the catalog as it came,
  with its signature, and checks that again for every install. The catalog's
  source is [uber-tv-apps](https://github.com/marcho78/uber-tv-apps) (`./build` packs and signs it);
  `apps.json` can name another (a link or a file), still checked with the same
  key.
- **A package** must match the SHA-256 and size the catalog lists, and its
  `app.json` must match its listing (id, version, permissions). It's read as a
  stream: plain files and folders only (no links, devices, absolute paths or
  `..`), no hidden files, 200 files, 400 files and folders, and 20 MB at most,
  four folders deep at most, no programs, and only `app.json`, pictures, `.md`
  and `.txt` files and a plain-text `LICENSE` or `COPYING` in a launcher.
- **`app.json`** is checked: an id like `tv.example.flix`, a version like
  `1.0.0`, an api this guide speaks, names without hidden or right-to-left
  characters (so one can't pass for another), only permissions this guide
  knows (a launcher may only ask to open websites), and its link: plain https
  (no quotes, spaces, `$` or backticks), on one of the websites it asks for,
  no name or password in it, no port, no IP address.
- **Installed** apps are kept read-only in `~/.local/share/om-pg/apps/<source>/<id>/<version>/`
  (the source is the catalog, the guide itself, a signed developer key or an
  unsigned Developer-mode file, kept apart: one origin never gets another's
  data).
  One from the catalog keeps its package and the signed catalog it came from
  beside it (`<version>.proof/`); a signed app file keeps its package,
  release note, signature, public key, cumulative withdrawals and newest
  accepted release state there too. Neither is ever installed without that
  proof. An
  install puts the new version and its proof in beside what's there and then
  swaps them in; if it stops partway (an error, a full disk, Ctrl-C), what
  was there is put back and checked, and the message says whether anything
  may be left in the app's folder to look at. Each time the guide starts it
  checks every app before it can open: one from the catalog is traced back
  to that signed catalog (the signature, the package's SHA-256, the
  package's files against the ones on disk), a signed app file to its pinned
  key and signed release the same way, and an unsigned Developer-mode file
  against what was installed,
  and what an app shows and opens comes from its own `app.json` as checked,
  not from `~/.config/om-pg/apps.json`. An app that fails is turned off; if the
  check can't run, none opens until it can.
- **Only you** turn apps or an app on, install, update and remove, and open
  the boxes that ask: from the keys, the mouse or your paired phone. A program
  calling the guide's functions (through `omarchy-shell shell call`) can't open
  one of those boxes, move in one, or answer one, and a box hidden behind the
  TV playing full screen never takes a key: it's closed.
- **AI agents** can see your apps (`apps`) and turn one off (`appOff`), and
  nothing more.

`bin/om-pg-apps` does the checking, unpacking, installing and removing;
`Apps.qml` keeps the list. `python3 tests/apps.test.py` tries it against
good apps and bad ones (links, `..`, programs, look-alike links, a changed or
replayed catalog, a swapped package, an edited copy of the catalog, a pulled
version, changed files on disk, a link where an app's folder goes). For apps
with code: `tests/apprun.test.py` (the sandbox and the helper: frames, deadlines,
requests trying to escape, the relay, sign-in, pinning, the real systemd scope
killed), `tests/appmedia.test.py` (media formats and playlists),
`tests/jellyfin.test.py` (the Jellyfin app against a fake Jellyfin server),
`tests/appplayback.test.py`, `tests/appstate.test.py` (`Apps.qml` in a Quickshell of
its own: what it saves, and the clean-ups it owes) and `qmltestrunner -input tests/qml`
(the guide's side).
