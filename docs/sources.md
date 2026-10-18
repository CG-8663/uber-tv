# App files from outside Uber TV

Third-party apps means apps you downloaded yourself. Uber TV does not take a
catalog or source link. It opens one signed `.tvapp` file from this computer,
shows exactly what it is and what it may do, and installs it only after your
review and the computer-password confirmation in the guide.

Developer mode is separate. It still installs an unsigned app straight from
its folder or `.tar.gz` so its developer can test local work. Developer-mode
apps have no signed identity and no automatic updates.

## The `.tvapp` format

An app file is an uncompressed tar with exactly four plain-file members:

- `key.pub` — one canonical Ed25519 public key line;
- `release.json` — the app, version, permissions, package hash and size,
  optional HTTPS update folder, timestamp, and cumulative withdrawals;
- `release.json.sig` — an SSH signature over those exact release bytes in the
  `uber-tv-app` namespace;
- `package.tar.gz` — the normal checked Uber TV app package.

The outer file is opened without following links, must be a plain file and is
capped at 25 MB. The package is checked with the same limits as catalog and
Developer-mode packages: plain files and folders only, bounded compressed and
expanded size, member count and depth, and a strict `app.json`.

The signing key is the origin. A signed app is identified by its app id and
key together. An update signed by that key keeps the app's data. The same id
signed by another key is a different app and is reviewed as a replacement
with none of the old app's private data.

## Updates and withdrawals

While the Third-party apps switch is on, Uber TV may fetch `release.json` and
`release.json.sig` from the signed HTTPS update folder. This check fetches no
code. A note is accepted only when its signature is by the installed key and
its timestamp is later than the newest accepted note, or its bytes are exactly
the same. A different note at the same timestamp and every older note are
refused.

If a newer version exists, the guide shows the version, package address and
size, developer-key fingerprint, permissions, and anything newly requested.
Only Agree downloads the package. The package must be on the update folder's
host and match the signed size and SHA-256 before it is unpacked or installed.

Withdrawals only accumulate. Once a signed note withdraws a version (or every
version with `*`), a later note cannot silently restore it by leaving that
withdrawal out. A withdrawn installed version is disabled. Each start checks
the installed files, package, signed release, pinned key, monotonic state, and
cumulative withdrawals without contacting the network.

## Publisher commands

Run publisher commands in a terminal. The passphrase belongs to the developer
and is entered directly into `ssh-keygen`; Uber TV never receives it.

Initialize one permanent private workspace:

```sh
bin/om-pg-apps app-key /path/to/publisher-workspace
```

This creates an Ed25519 key under `~/.ssh/` and records its path and public key
in the workspace. Keep the whole workspace: its private bounded history is
what prevents an old release or a dropped withdrawal from becoming current.
An arbitrary empty folder is not treated as initialized publisher state.

Build and sign one new app version:

```sh
bin/om-pg-apps app-file /path/to/app /path/to/publisher-workspace
bin/om-pg-apps app-file /path/to/app /path/to/publisher-workspace https://updates.example.com/my-app/
```

The second form writes a release that can update. Each run creates a new
`<id>-<version>-<updated>` folder and never overwrites a release or file. The
folder contains the `.tvapp` plus the three files to upload:
`release.json`, `release.json.sig`, and `package.tar.gz`.

Withdraw a version (or every version):

```sh
bin/om-pg-apps app-revoke /path/to/publisher-workspace tv.example.app 1.2.0 "unsafe release"
bin/om-pg-apps app-revoke /path/to/publisher-workspace tv.example.app '*' "no longer supported"
```

A withdrawal makes a newer signed note and carries every earlier withdrawal.
There is deliberately no unrevoke command.

The workspace is opened without following links and locked for the whole run.
Before signing, the tool verifies the recorded release, signature and package.
A fully written release left by a stopped run is adopted only when it is newer,
valid, and contains every recorded withdrawal. Incomplete folders are ignored.
Only the one private history file is atomically replaced after the new release
has been written and verified.

## Helper interface used by the guide

- `app-inspect <file.tvapp> <staging> <apps>` authenticates and stages a picked
  file without network access.
- `app-update-check <apps> <origin> <id>` fetches and accepts only the signed
  note.
- `app-update-prepare <apps> <origin> <id> <staging>` reads the exact consent
  review on stdin and only then fetches and stages the named package.
- `app-current <staged> <staging> <apps>` confirms the accepted state has not
  changed before the guide stops or replaces anything.
- `install` commits app files, proof, and signed-note state together through the
  existing checked install transaction and undo.
- `verify` traces every installed signed app back to its key, signed release,
  package, state and on-disk files at startup.

The former link-source commands (`source-preview`, `source-add`,
`source-fetch`, `source-accept-key`, `source-remove`, `source-list`,
`source-current`, `source init`, `source build`, `source revoke`, and
`source unrevoke`) are not part of the helper interface.
