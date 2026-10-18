# The app protocol (API 2, 3 and 4)

An app with code talks to Uber TV's helper (`bin/om-pg-apprun`) over its stdin and stdout: UTF-8 JSON, one object a line, each with a `"t"` naming its type. The toolkit (`uber_tv.py`) speaks it for you; this page is for checking what it does, or for writing an app without it.

`examples/showcase/` is an offline app that uses every block below; `om-pg-apps try` on it prints each row's layout, shape and size and the picture each card shows.

An app says its API in `app.json` (`"api": 2`, `3` or `4`), and everything it sends is checked against that one. API 4 is API 3 plus the sites it may change things on (`netWrite`, below). API 3 adds a row's picture shape and size, hero rows, an item's pictures for each shape, its line, text and watched mark, and a details page's style, title logo, line and chips (the API 3 table below). An API 2 app that sends any of them is refused, like any unknown field. The toolkit leaves them out for an app running as API 2.

The rules below are enforced by `lib/appblocks.py` (frames and blocks) and `lib/appnet.py` (requests). Those two files are the normative definition: where this page and them disagree, they win. (The design called for JSON Schema files; one set of Python validators, shared by the installer, the helper, `check` and `try`, replaced them.)

## Framing and limits

- A line is at most 1 MiB. A longer one, invalid UTF-8 or JSON, a key twice, `NaN`/`Infinity`, nesting deeper than 12, an unknown type or field: a **protocol violation**, and the app is stopped.
- At most 30 frames a second (60 at once) and 4 MiB a second.
- `ready` within 5 seconds of `hello`; nothing but `log` before it.
- Bodies are base64; every byte limit is on the raw bytes.
- Stdout is for frames only. The toolkit moves `print` (and anything else written to fd 1) to stderr, which goes to the app's log (`~/.local/state/om-pg/app-logs/<source>/<id>.log`, its last 64 KB, secrets, `Authorization` values and link queries taken out).

## Guide → app

| t | fields |
|---|---|
| `hello` | `api` (the app's own, from its `app.json`: 2, 3 or 4), `gen`, `locale`, `settings` (the non-secret settings), `server` (the base URL the user chose, or null) |
| `call` | `id`, `method`, `args`, `deadline` (ms) |
| `cancel` | `id` |
| `fetchReply` | `id`, `status`, `headers` (lowercase names, ≤ 16 KiB), `body` (base64); or `id`, `error` {`code`, `text`} |
| `storeReply` | `id`, one of `value` (base64, a list of keys for `storeList`, or null), `ok`, `error` |
| `secretReply` | `id`, one of `value` (text or null), `ok`, `error` |
| `credentials` | `flow`, `username`, `password`: what the user typed in the guide's own box, for a `password` sign-in (API 4), once, inside that flow only |
| `signInCancel` | `flow`: the sign-in was called off by the user, ran out of time, or a new one started (API 4; not sent for the app's own `signInDone`) |
| `viewOn` / `viewOff` | `view` (the result id of a live screen, or of a Home row), `method`, `args`: it's on the screen now, or not any more (API 4) |
| `streamData` | `id`, `line` (≤ 16 KiB): a line of the stream it asked for |
| `streamEnd` | `id`, `error`? {`code`, `text`}: the stream is over (its view went, it asked, the server ended it, or a limit) |
| `serverChosen` | `flow`, `handle`, `url`: the server the user chose while signing in (API 4, `server.fromSignIn`): one of its addresses, or one they typed for it, canonical; from now on the app's server |

## App → guide

| t | fields |
|---|---|
| `ready` | — |
| `result` | `id`, exactly one of `screen`, `detail`, `play`, `rows`, `message`, `page` (API 4), `ok` (true), `error` {`code`, `text`} |
| `fetch` | `id`, exactly one of `parent` (a call still waiting for its result) or `flow` (the sign-in going on), `url`, `method`, `headers`?, `body`? (base64, ≤ 256 KiB raw) |
| `storeGet` / `storeDel` | `id`, `parent` or `flow`, `key` (1–128 characters) |
| `storePut` | `id`, `parent` or `flow`, `key`, `value` (base64, ≤ 64 KiB raw), `server`? (true: forgotten on sign-out or a new server) |
| `storeList` | `id`, `parent` or `flow` |
| `secretGet` | `id`, `parent` or `flow`, `name` |
| `secretSet` | `id`, `flow`, `name`, `value` (≤ 4 KB; only during a sign-in) |
| `signInCode` | `flow`, `code` (≤ 16), `url` (on an origin the app may reach, or ""), `expires` (seconds) |
| `signInDone` | `flow`, `ok`, `message` (≤ 400) |
| `update` | `view`, and `rows` (a live screen's: each replacing the row of its id, never a new one) or `items` (a Home row's): only while the view is on, at most one a second (a Home row: every 5 s), ≤ 64 KiB; the merged screen within a screen's caps (API 4) |
| `stream` | `id`, `view`, `url`: a long `GET` to one of its `net` hosts answering `text/event-stream`, `text/plain` or `application/x-ndjson`, its lines sent back as they come, while its view is on (API 4) |
| `streamClose` | `id` |
| `signInServers` | `flow`, `servers`: up to 10 `{handle, label (≤ 80), urls (1 to 8 addresses)}`, the servers the account lists (API 4, `server.fromSignIn`); a handle is `[A-Za-z0-9_-]{1,64}`, each once, and stands for whatever the app keeps for that server (never send that) |
| `log` | `text` (≤ 8 KB) |

A fetch, storage or secret frame belongs to exactly one owner: a waiting call (it shares the call's deadline and is cancelled with it), the current sign-in flow, or (API 4) a live view that's on the screen (`view`: 30 s a request, cancelled when it goes). One whose owner is over gets an error reply (`cancelled`, `flow`); naming both, or neither, is a violation. At most 4 requests run at once with 16 waiting (more is a violation), 20 at once then 60 a minute.

## Methods

| method | args | answer |
|---|---|---|
| `home` | — | `screen` |
| `browse` | `item` | `screen` |
| `details` | `item` | `detail` |
| `search` | `query` | `screen` |
| `play` | `item` | `play` |
| `action` | `item`, `action` | `message`, `screen` or `detail` |
| `homeRow` | `key` | `rows` (the row's items) |
| `playback` | `session`, `seq`, `state` (`started`, `progress`, `paused`, `resumed`, `seeked`, `stopped`), `position`, `duration`, `reason`?, `context` | `ok` |
| `playbackFailed` | `session`, `reason`, `context` | `play` (one more try) or `message` |
| `signIn` | `flow`, `how` (`code`, or `password` at API 4: one of the ways `app.json` offers) | `ok` (then the flow goes on: `signInCode` or a `credentials` frame, `secretSet`, `signInDone`) |
| `signOut` | — | `ok` |

Every call has one deadline (10 s; `play` and `playbackFailed` 30 s; `signOut` 5 s), and the requests it makes share it. At the deadline the call is cancelled and its result dropped; 5 seconds past it, still unanswered, the app is stopped. At most 8 calls wait at once (the last playback report always has room). `context` is whatever the app put in its `play` result; the helper keeps it and hands it back with every playback call, the guide never sees it.

## Blocks

| block | fields |
|---|---|
| `screen` | `title` ≤ 80, `rows` ≤ 30, `refresh` 15–3600 s, `empty` ≤ 200; ≤ 200 items in all, ≤ 256 KiB |
| row | `id` ≤ 64 (unique), `title` ≤ 80, `layout` `row`/`grid`/`list`, `items` ≤ 50 |
| item | `id` ≤ 200 (unique in its row), `title` ≤ 120, `subtitle` ≤ 120, `image`, `badge` ≤ 12, `progress` 0–1, `kind` `open` (→ `browse`), `play` (→ `play`), `info` (→ `details`) |
| `detail` | `title` ≤ 120, `subtitle` ≤ 200, `text` ≤ 4,000 (≤ 60 lines), `image`, `backdrop`, `facts` ≤ 12 {`label` ≤ 40, `value` ≤ 120}, `actions` ≤ 6 {`id` ≤ 64, `label` ≤ 30, `kind` `action`/`play`}, `rows` ≤ 3 |
| `play` | `url`, `headers` (≤ 16; never Host, Cookie, hop-by-hop), `title` ≤ 120, `subtitle` ≤ 200, `startAt` ≥ 0, `live`, `context` (≤ 4 KB) |
| `message` | `text` ≤ 400 |

An image is `{"asset": "<a picture in the package>"}` or `{"url": "<a link on a net host, or under the server>"}`. Text is plain: no control characters (a newline only in `detail.text`, and in API 3 an item's `text`), no bidirectional overrides; markup is shown as it is, never interpreted. A result that breaks these is refused (the call fails with `invalid`); the app keeps running.

### API 3

| block | adds |
|---|---|
| row | `id` must match `^[a-z][a-z0-9_-]{0,63}$`, stay the same across versions and mean one thing; `layout` also `hero` (one big item at a time, at most 10 items, more is refused); `shape` `poster` (2:3), `wide` (16:9), `square`, `logo` (shown whole) or `circle`; `size` `small`, `medium` or `large`. A layout, shape or size left out is the app's `app.json` default for that row id, else the guide's (a row, a shape worked out from its first pictures, medium). |
| item | `images` `{ "poster", "wide", "square", "backdrop", "logo" }`, each an image, all optional (`image` stays the picture for its row's own shape); `meta` ≤ 80, one line; `text` ≤ 300, ≤ 4 lines; `watched` true or false |
| `detail` | `style` `classic` or `cinematic`; `logo` (an image of its title); `meta` ≤ 120; `chips` ≤ 8 labels of ≤ 24; `rows` ≤ 4 |

The new text counts toward the 256 KiB a result may be. `app.json` at API 3 may also have `layout`: `{ "look": "classic" | "posters" | "cinematic" | "wall" | "compact", "rows": [ { "id", "label" (≤ 40), "shape", "size", "layout" } ] }` (at most 40 rows: the defaults for the rows with those ids), and each `home` row may say its `shape`, `poster` or `wide`. Until the guide draws them, a hero row is drawn as a row, and `logo`, `chips`, `meta`, `text` and `style` are checked but not shown.

### API 4

| block | adds |
|---|---|
| row | `layout` also `table`: `columns` (1 to 8 `{label ≤ 24, align}`, align `start` or `end`), each item's `cells` (exactly one a column, ≤ 40 characters each), at most 50 items; and `ticker`: at most 30 items of `title` and `badge` (no pictures, no chart), moving across slowly, stopping while selected (and while the screen saver is up or a video plays full screen); Enter and I do nothing on it. Only the row itself makes either (not app.json's defaults), and nobody's choices change them. `columns` on any other row, or `cells` in its items, is refused. |
| item | `chart` `{points: 2 to 120 finite numbers, oldest first, low ≤ 24, high ≤ 24}`: drawn as a line by the guide (the app styles nothing), in a list or table line |
| `detail` | `chart`, the same, under its facts |
| `page` | a new result for `browse`, `details` and `action`: `title` ≤ 120, `sections` ≤ 30 `{heading ≤ 80, text ≤ 4,000, its own lines kept}`, 30,000 characters in all; the guide shows it whole, the arrows scroll it, Esc goes back |

Each counts toward the 256 KiB a result may be, and items toward a screen's 200.

## Requests

- `net` hosts: exactly those names (no subdomains), `https` on port 443, `GET` and `HEAD`, and only if every address the name resolves to is a public unicast one (checked before connecting, and the connection goes to the address checked).
- `netWrite` (API 4): `{ "<host>": ["POST", "PUT", "PATCH", "DELETE"] }`, each host one of its `net` hosts, each with a non-empty list of those methods. That host then also takes exactly those methods; nothing else changes (https, public addresses, the canonical path, the header rules, the 256 KiB body, the 512 KiB reply, the rates). The user sees each one under "Can change things on" before it installs, and an update adding a host or a method waits for them.
- `server`: the base URL the user chose (scheme, host, port, path prefix): `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, only under the prefix (on a segment boundary: `/jellyfin` holds `/jellyfin/x`, not `/jellyfin-other`). Private and local addresses are fine there.
- Paths are decoded once, with any encoded `%`, `.`, `/`, `\` or NUL, a backslash or a control character refused, and dot segments removed; the request sent is rebuilt from that canonical path. Queries pass as they are, minus control characters.
- Live updates (API 4): a screen with `"live": true` (and every Home row) is a live view while the guide shows it: `viewOn`, then `viewOff`. Meanwhile the app may send `update`s, and fetch for it (owner `view`). An update is checked as a result is; then, at once, the replaced rows' pictures are let go and the new ones held: pictures are held per (view, row), so a row replaced every second keeps only its own. An update for a view that's off is dropped. One `stream` an app at a time: lines ≤ 16 KiB, ≤ 20 a second, ≤ 256 KiB a minute (past any, it's closed with an error), an hour at most, closed when its view goes; a new one waits 5 seconds after the last ended, then longer (to 5 minutes) while they keep ending within a minute. It's counted in Activity (kind `stream`).
- Choosing the server while signing in (API 4, `"server": {"label", "fromSignIn": true}`, for an account that lists your servers): the sign-in starts with no server. Signed in to the account, the app sends `signInServers`; the helper checks each address as a server's (bad ones are dropped) and the guide shows the servers. The user chooses one, then one of its addresses or one they type for it; the helper checks the handle is this flow's and the address that server's (or a server address at all), sets it as the app's server for the flow and sends `serverChosen`. The app keeps only that server's credential (`secretSet`, kept with that server) and ends with `signInDone`; the guide keeps the server with the sign-in in one write. A sign-in that fails or is called off goes back to the server it had and forgets what it kept for the chosen one (its sign-in values and its storage marked `server`). A runtime that has a server takes only that one: another goes through the guide's "Switch servers?" (which forgets what the old one gave) and a new sign-in.
- Signing in with a password (API 4, `"signIn": "password"` or `["code", "password"]`): the guide shows its own box (Username, Password as dots, typed on the keyboard only) and gives what was typed to the helper on its stdin; the helper passes it to the app once, as `credentials`, inside that flow. The app signs in through `fetch` (the flow owns it), keeps what the service gives back with `secretSet`, and ends with `signInDone`. Nothing keeps the password. From the moment it's given, the username and password are taken out of the app's log for the rest of its run, at any length (a line holding one shorter than 4 characters is left out whole). After 5 failed attempts in a row the guide waits 30 seconds before the box takes another.
- Redirects: at most 5, each checked like the first with the method it will be sent with. A `301`, `302` or `303` becomes a `GET` without the body (a `HEAD` stays one). A `307` or `308` keeps the method and body, but a write (`POST`, `PUT`, `PATCH`, `DELETE`) is never carried to another origin: that redirect is the answer, and the app may make a new request, checked on its own. When the origin changes, **every header the app set is dropped** (a token in `X-Plex-Token` or `X-Api-Key` as much as in `Authorization`), and it stays dropped for the rest of the redirects.
- Activity: the helper counts what each request reached, as daily totals per site (the kind of request, read or changed, how many, bytes each way, answers by class) and the sites it tried and was refused, for the user's details box (`lib/appactivity.py`). Never a path, a query, a header or a body.
- Headers: token names, no CR/LF/NUL in values, never `Host`, `Content-Length`, `Transfer-Encoding`, `Connection`, `Cookie`, `Accept-Encoding` or the other hop-by-hop ones (the helper sets them).
- A reply is at most 512 KiB, its headers at most 16 KiB.

## The guide and the helper

The guide starts the helper in a systemd user scope (`om-pg-app-<source-dir>-<id-hash>-<gen>`, 320 MB, half a core, 48 tasks) and writes `{"t":"init","id","source","version","gen","settings","server","pin","locale"}`. Then `call`, `cancel`, `image` {`token`, `epoch`, `prio`}, `viewOn` and `viewOff` {`view`}, `signInPassword` {`flow`, `username` (≤ 256), `password` (≤ 1024), one line each}, `signInServer` {`flow`, `handle`, and `url` or `typedAddress`}, `drop` {`results`}, `signInCancel` {`flow`}, `relayClose` {`session`} and `stop` {`forget`: "", `signIn`, `server` or `data`}. The helper answers with `state` {`ready`; or `stopped` with `why`: `normal`, `guide`, `crash`, `violation`, `timeout`, `start`, `unavailable`}, `result` {`id`, `kind`, `value`}, `image` {`token`, `path`, `w`, `h`; or `token`, `code`, `error`}, `signInCode`, `signInServers` {`flow`, `servers`: names, addresses and handles}, `signInServerRefused` {`flow`, `why`}, `update` {`view`, `rows` or `items`, checked} and `signInDone` (with `server` for a `fromSignIn` app). A `play` result reaches the guide as a relay address on 127.0.0.1 and a session handle, never the app's link.

Pictures, between the guide and the helper:

- **A picture in the package** reaches the guide as `{path, w, h}`, its size read from its header. **A link** reaches it as a token: nothing is downloaded while a result is checked.
- **Tokens are held by results.** A result's tokens are made together, once it has passed its checks, and held by its result id (the call's) until the guide sends `drop` with it: when the view it made is popped, replaced or let go, or the answer isn't wanted. Past 4,000 tokens, only ones no result holds are let go, the least recently used first (a new result naming one, or an `image` asking for it, uses it).
- **The guide asks for a picture** with its demand `epoch` (it raises it on a change of view, focus or runtime) and its `prio`: `focus` (the selected card, a details page's pictures), `visible` (on the screen) or `rest`. The helper keeps at most 64 waiting, one fetch a token, the focus first, then visible, then the rest; work for an older epoch is dropped before it spends anything. One already fetched is read again through its descriptor (no link followed, a regular file, at most 2 MB, a picture's header); one that fails that is deleted and fetched again.
- **The answer** is `{token, path, w, h}` (`w` and `h` from its header, at most 4096), or `{token, code, error}`, the code saying what happened: `unknown` (no such token, or it was let go), `refused` (its link breaks the rules), `failed` (it couldn't be fetched, or isn't a picture), `stale` (asked for an older epoch; with that `epoch`), `busy` (64 were waiting).
