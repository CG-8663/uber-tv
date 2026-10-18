#!/usr/bin/python3
"""The screen saver's pictures (bin/om-pg-apps saver-pictures and
saver-folder), in scratch folders standing in for your
home folder and Omarchy's: /usr/bin/python3 tests/saver.test.py

Your folder's pictures are checked before they're shown: plain files only,
never through a link (to a file or a folder), PNG, JPEG or WebP by their first
bytes, within the size limits, two folders deep, hidden names left out, at
most 500. Omarchy's backgrounds come from its themes' backgrounds folders,
your own themes' and the backgrounds you've added, never a theme's other
pictures. Your folder is made only inside your home folder."""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-apps")

failures = 0


def re_copy(name):
    import re
    return re.match(r"^[0-9a-f]{32}\.(?:png|jpg|webp)\Z", name)


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\x00" * 16


def jpeg(w, h, app_bytes=0):
    """A JPEG header; app_bytes of APP1 segments before its size (as big EXIF
    or color profiles put it further in)"""
    out = b"\xff\xd8"
    while app_bytes > 0:
        n = min(app_bytes, 65000)
        out += b"\xff\xe1" + struct.pack(">H", n + 2) + b"\x00" * n
        app_bytes -= n
    return out + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x00" * 12


def webp(w, h):
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


work = tempfile.mkdtemp(prefix="om-pg-saver-test-")
home = os.path.join(work, "home")
omarchy = os.path.join(work, "omarchy")
env = dict(os.environ, HOME=home, OMARCHY_PATH=omarchy)


def call(cmd, req):
    raw = req if isinstance(req, bytes) else json.dumps(req).encode()
    out = subprocess.run(["/usr/bin/python3", HELPER, cmd], input=raw, capture_output=True, env=env, timeout=60)
    return json.loads(out.stdout.decode().strip().splitlines()[-1])


try:
    # ---- your folder ---------------------------------------------------------------------------
    folder = os.path.join(home, "Pictures", "Screen Saver")
    good = [put(os.path.join(folder, "a.png"), png(1920, 1080)),
            put(os.path.join(folder, "b.JPG"), jpeg(3840, 2160)),
            put(os.path.join(folder, "c.webp"), webp(800, 600)),
            put(os.path.join(folder, "trips", "d.jpeg"), jpeg(1000, 800)),
            put(os.path.join(folder, "trips", "2026", "e.png"), png(10, 10)),
            put(os.path.join(folder, "far.jpg"), jpeg(1200, 900, app_bytes=300 * 1024))]
    put(os.path.join(folder, "trips", "2026", "deep", "f.png"), png(10, 10))     # three folders down
    put(os.path.join(folder, ".hidden.png"), png(10, 10))
    put(os.path.join(folder, ".private", "g.png"), png(10, 10))
    put(os.path.join(folder, "notes.txt"), b"hello")
    put(os.path.join(folder, "fake.jpg"), b"not a picture at all")
    put(os.path.join(folder, "wide.png"), png(9000, 100))                        # over 8192 a side
    put(os.path.join(folder, "huge.png"), png(8000, 6000))                       # over 40 MP
    put(os.path.join(folder, "toofar.jpg"), jpeg(100, 100, app_bytes=2 * 1024 * 1024))   # its size past what's read
    outside = put(os.path.join(work, "outside", "secret.png"), png(10, 10))
    os.symlink(outside, os.path.join(folder, "link.png"))
    os.symlink(os.path.dirname(outside), os.path.join(folder, "linked-folder"))
    os.mkfifo(os.path.join(folder, "pipe.png"))
    with open(os.path.join(folder, "heavy.png"), "wb") as f:   # a good header, but over 40 MB (sparse)
        f.write(png(100, 100))
        f.truncate(41 * 1024 * 1024)

    res = call("saver-pictures", {"folder": folder})
    got = sorted(res.get("folder", []))
    check("your folder's pictures: PNG, JPEG (any case) and WebP, two folders deep", res.get("ok") and got == sorted(good), (got, res))
    check("  hidden names, links (to a file or a folder) and special files are left out",
          not any(n in p for p in got for n in (".hidden", ".private", "link", "secret", "pipe")), got)
    check("  a fake picture, ones too big (sides, pixels, over 40 MB) and a special file are skipped (and counted)", res.get("skipped") == 6, res.get("skipped"))
    check("  a JPEG whose size is far in is still read (up to 1 MB)", any(p.endswith("far.jpg") for p in got))
    check("  Omarchy's aren't listed unless asked", res.get("omarchy") == [], res.get("omarchy"))
    check("  and the folder is there", res.get("folderMissing") is False)

    res = call("saver-pictures", {"folder": os.path.join(home, "Pictures", "Nope")})
    check("a folder that isn't there: said so, and no pictures", res.get("ok") and res.get("folderMissing") is True and res.get("folder") == [], res)
    check("a folder must be a full path", not call("saver-pictures", {"folder": "Pictures/Screen Saver"}).get("ok"))
    check("  without a NUL", not call("saver-pictures", {"folder": "/tmp/a\u0000b"}).get("ok"))
    check("a request that isn't one is refused", not call("saver-pictures", b"[1, 2]").get("ok") and not call("saver-pictures", b"not json").get("ok"))

    # ---- a picture ready to show: the file checked is the file copied --------------------------
    cache = os.path.join(home, ".cache", "om-pg", "saver")
    res = call("saver-pictures", {"folder": folder})
    root = res.get("folderRoot")
    ids = res.get("ids", {})
    check("the listing says the folder it read (links on the way to it resolved)", root == os.path.realpath(folder), root)
    check("  and each picture's identity, from the file it checked", all(ids.get(p) == "%d:%d" % (os.stat(p).st_dev, os.stat(p).st_ino) for p in res.get("folder", []))
          and len(ids) == len(res.get("folder", [])), ids)
    take = lambda rel, r=root, i=None: call("saver-take", {"root": r, "from": rel, "into": cache,
                                                         "id": i if i is not None else ids.get(os.path.join(r, rel), "")})
    res = take("trips/d.jpeg")
    check("a listed picture is copied into the cache, and only the copy is shown", res.get("ok") and os.path.dirname(res["path"]) == cache
          and open(res["path"], "rb").read() == open(os.path.join(folder, "trips", "d.jpeg"), "rb").read(), res)
    check("  as <32 hex>.<ext>, yours alone, in a 0700 folder", bool(re_copy(os.path.basename(res.get("path", ""))))
          and (os.stat(res["path"]).st_mode & 0o777, os.stat(cache).st_mode & 0o777) == (0o600, 0o700), res)
    # the name replaced after it was listed: by a link to a private picture elsewhere
    os.unlink(os.path.join(folder, "a.png"))
    os.symlink(outside, os.path.join(folder, "a.png"))
    check("a name swapped for a link after it was listed is refused", not take("a.png").get("ok"))
    # a folder on the way replaced by a link to another folder with the same names
    elsewhere = os.path.join(work, "elsewhere-trips")
    put(os.path.join(elsewhere, "d.jpeg"), jpeg(1000, 800))
    shutil.move(os.path.join(folder, "trips"), os.path.join(work, "trips-moved"))
    os.symlink(elsewhere, os.path.join(folder, "trips"))
    check("  and so is one whose folder was swapped for a link", not take("trips/d.jpeg").get("ok"))
    # the picture replaced by something that isn't one
    put(os.path.join(folder, "c.webp"), b"no longer a picture")
    check("  and a picture replaced by something that isn't one", not take("c.webp").get("ok"))
    check("  and one that's gone", not take("gone.png").get("ok"))
    climb = os.path.relpath(outside, root)   # ../../../outside/secret.png: a real way out
    check("never outside the folder", climb.startswith("..") and not take(climb).get("ok") and not take("/etc/passwd").get("ok")
          and not take("trips-moved/../b.JPG").get("ok"), climb)
    check("only into the guide's screen saver cache", not call("saver-take", {"root": root, "from": "b.JPG", "into": os.path.join(home, "elsewhere"),
                                                                              "id": ids.get(os.path.join(root, "b.JPG"), "")}).get("ok"))
    check("only with the identity it was listed with", not take("b.JPG", i="").get("ok") and not take("b.JPG", i="1:2").get("ok")
          and not take("b.JPG", i="x").get("ok"))
    # a picture replaced by another real picture under the same name: another file
    os.unlink(os.path.join(folder, "far.jpg"))
    put(os.path.join(folder, "far.jpg"), jpeg(1200, 900))
    check("a picture replaced by another one since the listing is refused (shown once listed again)", not take("far.jpg").get("ok"))
    # the cache keeps the newest few, and is emptied on request (only its own copies)
    put(os.path.join(cache, "notes.txt"), b"not ours")
    for _ in range(15):
        take("b.JPG")
    ours = [n for n in os.listdir(cache) if re_copy(n)]
    check("the cache keeps the newest 12 copies", len(ours) == 12, len(ours))
    check("  and empties on request, leaving what isn't its own", call("saver-take", {"clear": True, "into": cache}).get("ok")
          and os.listdir(cache) == ["notes.txt"], os.listdir(cache))

    # the listed folder itself swapped for a link to a folder with the same names
    swap_home = os.path.join(work, "swap", "Pictures", "Saver")
    put(os.path.join(swap_home, "same.png"), png(10, 10))
    res = call("saver-pictures", {"folder": swap_home})
    sroot, sids = res.get("folderRoot"), res.get("ids", {})
    staken = lambda: call("saver-take", {"root": sroot, "from": "same.png", "into": cache, "id": sids.get(os.path.join(sroot, "same.png"), "")})
    check("a listed picture of another folder is taken", staken().get("ok"), sroot)
    decoy = os.path.join(work, "decoy", "Saver")
    put(os.path.join(decoy, "same.png"), png(10, 10) + b"PRIVATE")
    os.rename(swap_home, swap_home + "-moved")
    os.symlink(decoy, swap_home)
    check("  refused once the folder itself is swapped for a link", not staken().get("ok"))
    os.unlink(swap_home)
    os.rename(swap_home + "-moved", swap_home)
    check("  (taken again once it's back)", staken().get("ok"))
    # a folder above it swapped for a link to one laid out the same way
    above = os.path.join(work, "swap", "Pictures")
    os.rename(above, above + "-moved")
    os.symlink(os.path.join(work, "decoy"), above)
    check("  and refused when a folder above it is swapped", not staken().get("ok"))

    # ---- Omarchy's backgrounds -----------------------------------------------------------------
    theirs = [put(os.path.join(omarchy, "themes", "nord", "backgrounds", "1.png"), png(3840, 2160)),
              put(os.path.join(omarchy, "themes", "nord", "backgrounds", "2.jpg"), jpeg(3840, 2160)),
              put(os.path.join(omarchy, "themes", "osaka", "backgrounds", "1.webp"), webp(1920, 1080)),
              put(os.path.join(home, ".config", "omarchy", "themes", "mine", "backgrounds", "x.png"), png(100, 100)),
              put(os.path.join(home, ".config", "omarchy", "backgrounds", "nord", "added.jpg"), jpeg(100, 100))]
    put(os.path.join(omarchy, "themes", "nord", "preview.png"), png(100, 100))       # a theme's other picture
    put(os.path.join(omarchy, "themes", "nord", "backgrounds", "omarchy.png"), png(3840, 2160))   # its logo wallpaper
    put(os.path.join(omarchy, "themes", "nord", "backgrounds", "sub", "deeper.png"), png(10, 10))
    linked = put(os.path.join(work, "elsewhere-bgs", "x.png"), png(10, 10))
    os.makedirs(os.path.join(home, ".config", "omarchy", "backgrounds"), exist_ok=True)
    os.symlink(os.path.dirname(linked), os.path.join(home, ".config", "omarchy", "backgrounds", "linked"))
    res = call("saver-pictures", {"omarchy": True})
    check("Omarchy's backgrounds: its themes', your themes' and the ones you've added", res.get("ok") and sorted(res.get("omarchy", [])) == sorted(theirs),
          (res.get("omarchy"), res))
    check("  never a theme's other pictures, its logo wallpaper, folders inside backgrounds, or a linked backgrounds folder",
          not any(n in p for p in res.get("omarchy", []) for n in ("preview", "omarchy.png", "deeper", "elsewhere")))

    # ---- at most 500 ---------------------------------------------------------------------------
    many = os.path.join(home, "Many")
    for i in range(505):
        put(os.path.join(many, "p%03d.png" % i), png(10, 10))
    res = call("saver-pictures", {"folder": many, "omarchy": True})
    check("at most 500 pictures in all, and it says there were more", len(res.get("folder", [])) == 500 and res.get("omarchy") == [] and res.get("more") is True,
          (len(res.get("folder", [])), len(res.get("omarchy", [])), res.get("more")))

    # ---- your folder, made when it's first needed ----------------------------------------------
    new = os.path.join(home, "Pictures", "New Saver")
    res = call("saver-folder", {"folder": new})
    check("your folder is made when it isn't there", res.get("ok") and os.path.isdir(new) and res.get("folder") == new, res)
    check("  one that's there is fine", call("saver-folder", {"folder": new}).get("ok"))
    check("  only inside your home folder", not call("saver-folder", {"folder": os.path.join(work, "elsewhere", "Saver")}).get("ok")
          and not os.path.exists(os.path.join(work, "elsewhere")))
    check("  not through .. out of it", not call("saver-folder", {"folder": os.path.join(home, "..", "escaped")}).get("ok")
          and not os.path.exists(os.path.join(work, "escaped")))
    put(os.path.join(home, "Pictures", "AFile"), b"x")
    check("  refused when a file has its name", not call("saver-folder", {"folder": os.path.join(home, "Pictures", "AFile")}).get("ok"))
    check("  a full path only", not call("saver-folder", {"folder": "Pictures/X"}).get("ok"))
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("saver: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
