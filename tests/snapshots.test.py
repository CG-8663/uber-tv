#!/usr/bin/python3
"""Snapshots.qml's files: its move script, taken from the file as the guide
runs it (/usr/bin/sh -c), in a scratch folder:
/usr/bin/python3 tests/snapshots.test.py

It checks that a picture goes into place whole and readable by you alone,
never over anything already at its name (a file, a link, a folder); that
this start's newest five snapshots are kept and its older ones and
leftovers taken away; that the guide's other files (other starts', and
the versions before's) are left alone until they're an hour old (another
start may still be running), then taken away, and nothing else ever is;
and that a failed move leaves nothing behind. Then that the guard's list
of text fields (Snapshots.textField) still names every text field in the
guide's files."""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "Snapshots.qml")).read()
SCRIPT = json.loads(re.search(r'readonly property string moveScript: ("(?:[^"\\]|\\.)*")', SRC).group(1))
fails = 0


def check(cond, what):
    global fails
    if not cond:
        fails += 1
    print(("ok   " if cond else "FAIL ") + what)


RUN = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"   # a start's run: 128 bits, 32 hex digits
OTHER = "ffee0011ffee0011ffee0011ffee0011"


def move(d, n, keep=5, run=RUN):
    return subprocess.run(["/usr/bin/sh", "-c", SCRIPT, "sh", d, run, str(n), os.path.join(d, part(n, run)), os.path.join(d, final(n, run)), str(keep)],
                          capture_output=True, text=True, env={}).returncode


def final(n, run=RUN):
    return "snapshot-%s-%d.png" % (run, n)


def part(n, run=RUN):
    return ".snapshot-%s-%d.part.png" % (run, n)


def aged(path, hours=2):
    """made that long ago (a link's own time, not what it points at)"""
    t = time.time() - hours * 3600
    os.utime(path, (t, t), follow_symlinks=False)


def put(path, data=b"x", mode=0o644):
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


work = tempfile.mkdtemp(prefix="om-pg-snapshots-test-")
try:
    N = 1

    # into place, whole and yours alone
    d = os.path.join(work, "a")
    os.makedirs(d)
    put(os.path.join(d, part(N)), b"\x89PNG picture")
    check(move(d, N) == 0, "it moves")
    name = os.path.join(d, final(N))
    check(open(name, "rb").read() == b"\x89PNG picture", "the same bytes, under its name")
    check(stat.S_IMODE(os.stat(name).st_mode) == 0o600, "readable by you alone")
    check(not os.path.exists(os.path.join(d, part(N))), "nothing left at the temporary name")

    # this start's newest five kept, its older ones and leftovers taken away;
    # the guide's other files left alone until they're an hour old, then
    # taken away; nothing named otherwise, however old
    d = os.path.join(work, "b")
    os.makedirs(d)
    n = 10
    for k in range(n - 7, n):
        put(os.path.join(d, final(k)))
    put(os.path.join(d, part(n - 3)))                            # this start's leftover
    others = [final(3, OTHER), final(50, OTHER), part(2, OTHER),   # another start's (it may be running)
              final(7, "deadbeef"), part(8, "deadbeef"),           # the version before's (8 hex digits)
              "snapshot-4.png", "snapshot-1760000000123.png", ".snapshot-12.part.png"]   # and before that
    for k in others:
        put(os.path.join(d, k))
        aged(os.path.join(d, k), 0.5)                            # half an hour: newer than an hour
    old_others = ["snapshot-%s-%d.png" % (OTHER, k) for k in (60, 61)] + [part(70, OTHER), final(9, "deadbeef"), "snapshot-5.png", ".snapshot-13.part.png"]
    for k in old_others:
        put(os.path.join(d, k))
        aged(os.path.join(d, k))
    keepers = ["snapshot-abc.png", "snapshot-1x.png", "snapshot-.png", "snapshot-1 2.png", "notes.txt", "listings.json", "snapshot-cafe.png",
               "snapshot-12.png.bak", "snapshot-\n5.png", "snapshot-%s-.png" % RUN, "snapshot-%s-1x.png" % RUN, "snapshot-%s-4.png" % RUN.upper(),
               "snapshot-0a1b2c3-4.png", "snapshot-%s0-4.png" % RUN]     # (runs of neither 8 nor 32 hex digits)
    for k in keepers:
        put(os.path.join(d, k))
        aged(os.path.join(d, k))
    os.remove(os.path.join(d, final(n - 6)))
    os.makedirs(os.path.join(d, final(n - 6)))   # a folder by an old one's name
    put(os.path.join(d, part(n)), b"new")
    check(move(d, n) == 0, "it moves among others")
    left = sorted(os.listdir(d))
    want = sorted([final(k) for k in range(n - 4, n + 1)] + others + keepers + [final(n - 6)])
    check(left == want, "this start's newest five, another start's newer than an hour, and what isn't the guide's stay: %r" % [x for x in left if x not in want] + " %r" % [x for x in want if x not in left])
    check(os.path.isdir(os.path.join(d, final(n - 6))), "a folder isn't taken away")

    # never over anything at its name: a folder, a link, a file; what was
    # begun is taken away
    d = os.path.join(work, "c")
    os.makedirs(os.path.join(d, final(N)))
    put(os.path.join(d, part(N)))
    check(move(d, N) != 0, "a folder at its name: it fails")
    check(os.listdir(os.path.join(d, final(N))) == [], "and puts nothing in the folder")
    check(not os.path.exists(os.path.join(d, part(N))), "and takes away what was begun")
    d = os.path.join(work, "e")
    os.makedirs(d)
    outside = os.path.join(work, "outside.png")
    put(outside, b"yours")
    os.symlink(outside, os.path.join(d, final(N)))
    put(os.path.join(d, part(N)), b"new")
    check(move(d, N) != 0, "a link at its name: it fails")
    check(os.path.islink(os.path.join(d, final(N))) and open(outside, "rb").read() == b"yours", "the link, and what it points at, are untouched")
    check(not os.path.exists(os.path.join(d, part(N))), "and what was begun is taken away")
    d = os.path.join(work, "g")
    os.makedirs(d)
    put(os.path.join(d, part(N)), b"the first")
    check(move(d, N) == 0, "a picture")
    put(os.path.join(d, part(N)), b"again")
    check(move(d, N) != 0, "the same name again: refused")
    check(open(os.path.join(d, final(N)), "rb").read() == b"the first", "the picture already at that name is untouched")
    check(not os.path.exists(os.path.join(d, part(N))), "and the second is taken away")
    d = os.path.join(work, "h")
    os.makedirs(d)
    os.symlink(outside, os.path.join(d, final(4, OTHER)))
    aged(os.path.join(d, final(4, OTHER)))
    os.symlink(outside, os.path.join(d, final(5, OTHER)))
    put(os.path.join(d, part(N)), b"new")
    check(move(d, N) == 0 and not os.path.lexists(os.path.join(d, final(4, OTHER))), "another start's old one that's a link: the link goes")
    check(os.path.lexists(os.path.join(d, final(5, OTHER))), "a newer one stays")
    check(open(outside, "rb").read() == b"yours", "and what they point at is untouched")

    # nothing to move: it fails
    d = os.path.join(work, "f")
    os.makedirs(d)
    check(move(d, N) != 0, "no picture: it fails")
    check(os.listdir(d) == [], "and leaves nothing")

    # the guard knows every text field the guide draws
    FIELDS = {
        "ui/AppCustomize.qml": 1,   # a row's name in Customize: appPanel.renaming
        "ui/AppScreen.qml": 4,      # an app's own: appView.editing; its sign-in's (a username, a password, a server's address): appView.signIn
        "ui/ColorPicker.qml": 1,    # a color: styleEditing
        "ui/DialogBox.qml": 5,      # rename, category, pick, add, listings while adding
        "ui/HomeScreen.qml": 1,     # a Home row's name: homeRenaming
        "ui/StylePanel.qml": 1,     # a theme's name: styleNaming
    }
    found = {}
    for sub in ("", "ui"):
        for f in sorted(os.listdir(os.path.join(ROOT, sub))):
            if f.endswith(".qml"):
                text = open(os.path.join(ROOT, sub, f)).read()
                k = len(re.findall(r"\b(?:TextInput|TextEdit|TextField|TextArea)\s*\{", text))
                if k:
                    found[os.path.join(sub, f) if sub else f] = k
    check(found == FIELDS, "the text fields are the ones the guard knows: %r" % found)
    guard = SRC[SRC.index("function textField()"):SRC.index("readonly property string moveScript")]
    for name in ('"rename"', '"category"', '"pick"', '"add"', "listingsAdding", "styleNaming", "styleEditing", "homeRenaming",
                 "appPanel.renaming", "appView.editing"):
        check(name in guard, "the guard names " + name)
finally:
    shutil.rmtree(work)

print("snapshots: " + ("all good" if not fails else "%d failed" % fails))
raise SystemExit(1 if fails else 0)
