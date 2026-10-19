#!/usr/bin/python3
"""Themes saved as one confirmed transaction, and pictures you pick
(bin/om-pg-apps theme-save, theme-tidy, theme-sweep, theme-remove,
picture-import), in scratch folders:
/usr/bin/python3 tests/themes.test.py

It checks the file layer's steps in their order with a failure injected at
each (a failure up to and including the rename changes nothing and leaves
nothing behind; only the last folder sync failing is unconfirmed), what a
power cut could bring back loading whole, the sweep after a crash (and that
it keeps everything when it can't sync or read), the old pictures going only
once the new theme.json names other ones, removal, and the checks on a
picture you pick: special files, links, renamed non-pictures, bad headers
and oversized dimensions."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-apps")
_loader = importlib.machinery.SourceFileLoader("om_pg_apps", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_apps", _loader)
apps = importlib.util.module_from_spec(_spec)
_loader.exec_module(apps)

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def png(w, h, extra=b"pixels"):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\x00" * 4 + extra


def jpeg(w, h):
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x00" * 12


def webp(w, h):
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


work = tempfile.mkdtemp(prefix="om-pg-themes-test-")


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def call(cmd, req):
    """the helper itself, its request on stdin"""
    w = subprocess.run([sys.executable, HELPER, cmd], input=json.dumps(req).encode(), capture_output=True)
    return json.loads(w.stdout.decode().strip().splitlines()[-1])


def loads_whole(folder):
    """theme.json there, and every picture it names a plain file beside it"""
    try:
        theme = json.load(open(os.path.join(folder, "theme.json")))
    except (OSError, ValueError):
        return False
    return all(os.path.isfile(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n)) for n in apps.named_in(theme))


def files(folder):
    return {n: open(os.path.join(folder, n), "rb").read() for n in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, n))}


class StepFS:
    """os, each step of a save named and recorded, and one made to fail"""
    def __init__(self, fail=None):
        self.fail, self.calls, self.dirfd = fail, [], {}

    def step(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise OSError("injected: " + name)

    def makedirs(self, *a, **k):
        return os.makedirs(*a, **k)

    def mkdir(self, path, mode=0o777):
        return os.mkdir(path, mode)

    def unlink(self, path):
        self.step("unlink:" + os.path.basename(path))
        return os.unlink(path)

    def open(self, path, flags, mode=0o777):
        base = os.path.basename(path)
        if flags & os.O_DIRECTORY:
            fd = os.open(path, flags, mode)
            self.dirfd[fd] = base
            return fd
        if flags & os.O_CREAT:
            self.step("create:" + ("tmp" if base.startswith(".theme-") else "copy"))
        elif base.startswith(".theme-"):
            self.step("readback")
        return os.open(path, flags, mode)

    def fsync(self, fd):
        if fd in self.dirfd:
            self.step("dirsync:" + self.dirfd[fd])
        else:
            self.step("sync")
        return os.fsync(fd)

    def replace(self, a, b):
        self.step("rename")
        return os.replace(a, b)


def with_fs(fs, fn, *a):
    apps._fs = fs
    try:
        return fn(*a)
    finally:
        apps._fs = os


try:
    pics = os.path.join(work, "pictures")
    p1 = put(os.path.join(pics, "one.png"), png(1920, 1080))
    p2 = put(os.path.join(pics, "two.jpg"), jpeg(3840, 2160))
    p3 = put(os.path.join(pics, "three.webp"), webp(5120, 1440))

    # ---- the pictures you pick ------------------------------------------------------
    for path, ext in ((p1, "png"), (p2, "jpg"), (p3, "webp")):
        data, got = apps.user_picture(path)
        check("a " + ext + " is taken, by its first bytes", got == ext and data == open(path, "rb").read())
    big = put(os.path.join(pics, "8k.png"), png(7680, 4320))
    check("an 8K wallpaper still saves", apps.user_picture(big)[1] == "png")

    def refused(path, what):
        try:
            apps.user_picture(path)
            check(what + ": refused", False)
        except apps.Bad as e:
            check(what + ": refused, said in the guide's words", "/" not in str(e), str(e))

    os.symlink(p1, os.path.join(pics, "link.png"))
    refused(os.path.join(pics, "link.png"), "a link (swapped in)")
    os.mkfifo(os.path.join(pics, "pipe.png"))
    refused(os.path.join(pics, "pipe.png"), "a pipe")
    refused(pics, "a folder")
    refused(put(os.path.join(pics, "notes.png"), b"just some text, renamed"), "a renamed non-picture")
    refused(put(os.path.join(pics, "cut.png"), b"\x89PNG\r\n\x1a\n\x00\x00"), "a bad header")
    refused(put(os.path.join(pics, "wide.png"), png(8193, 100)), "more than 8192 a side")
    refused(put(os.path.join(pics, "mega.png"), png(8000, 8000)), "more than 40 megapixels")
    huge = os.path.join(pics, "huge.png")
    with open(huge, "wb") as f:
        f.write(png(100, 100))
        f.truncate(40 * 1024 * 1024 + 1)
    refused(huge, "more than 40 MB")
    refused("relative/one.png", "a relative path")
    refused("qrc:/one.png", "a qrc: picture")
    refused("image://provider/one", "a provider's picture")
    refused("https://example.com/one.png", "a remote picture")

    # ---- a new theme, saved -----------------------------------------------------------
    themes = os.path.join(work, "themes")
    theme = {"name": "Neon", "colors": {"text": "#ffffff"}, "images": {"masthead": {"src": p1, "fit": "fit", "opacity": 1}},
             "background": {"mode": "image", "image": p2, "dim": 0.4}, "apps": {"look": "cinematic", "background": {"mode": "image", "image": p3, "dim": 0.5}}}
    fs = StepFS()
    res = with_fs(fs, apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": theme}).encode())
    folder = os.path.join(themes, "neon")
    check("a new theme: saved", res.get("outcome") == "saved", res)
    check("the steps in order: each copy synced, the new theme.json synced, the folder and the themes folder synced, read back, renamed, the folder synced",
          fs.calls == ["create:copy", "sync", "create:copy", "sync", "create:copy", "sync", "create:tmp", "sync",
                       "dirsync:neon", "dirsync:themes", "readback", "rename", "dirsync:neon"], fs.calls)
    names = sorted(n for n in os.listdir(folder) if n != "theme.json")
    check("its pictures copied in under new names, and nothing else", len(names) == 3 and all(apps.PIC_NAME.match(n) for n in names), names)
    saved = json.load(open(os.path.join(folder, "theme.json")))
    check("theme.json names its copies", saved["images"]["masthead"]["src"] in names and saved["background"]["image"] in names
          and saved["apps"]["background"]["image"] in names, saved)
    check("the copies are the pictures", open(os.path.join(folder, saved["background"]["image"]), "rb").read() == open(p2, "rb").read())
    check("readable by you alone", (os.stat(folder).st_mode & 0o777, os.stat(os.path.join(folder, names[0])).st_mode & 0o777) == (0o700, 0o600))
    check("the answer is the theme as written", res["theme"] == saved and res["old"] == [], res)
    check("and it loads whole", loads_whole(folder))

    # Multiview's background picture is copied in and named, as the others
    res = apps.do_theme_save(json.dumps({"dir": themes, "id": "mv", "theme": {"name": "MV", "colors": {"text": "#ffffff"},
                                                                            "multiview": {"background": {"mode": "image", "image": p2, "dim": 0.5}}}}).encode())
    mvf = os.path.join(themes, "mv")
    mvs = json.load(open(os.path.join(mvf, "theme.json"))) if res.get("outcome") == "saved" else {}
    mvpic = ((mvs.get("multiview") or {}).get("background") or {}).get("image", "")
    check("Multiview's picture: copied in, and theme.json names the copy", res.get("outcome") == "saved" and mvpic in os.listdir(mvf)
          and apps.PIC_NAME.match(mvpic) and open(os.path.join(mvf, mvpic), "rb").read() == open(p2, "rb").read(), (res, mvs))
    shutil.rmtree(mvf)

    # ---- a failure at each step changes nothing ---------------------------------------
    before = files(folder)
    steps = ["create:copy", "sync", "create:tmp", "dirsync:neon", "readback", "rename"]
    for step in steps:
        fs = StepFS(step)
        theme2 = dict(theme, name="Neon 2", background={"mode": "image", "image": p1, "dim": 0.4})
        res = with_fs(fs, apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": theme2}).encode())
        check("a failure at " + step + ": failed, the folder as it was, file by file", res.get("outcome") == "failed" and files(folder) == before, res)
        check("  said in the guide's words", "injected" not in json.dumps(res) and "/" not in res.get("why", ""), res)
    for step in ["create:copy", "dirsync:themes", "rename"]:
        res = with_fs(StepFS(step), apps.do_theme_save, json.dumps({"dir": themes, "id": "fresh", "theme": theme}).encode())
        check("a new theme failing at " + step + ": nothing of it left", res.get("outcome") == "failed" and not os.path.exists(os.path.join(themes, "fresh")), res)
    class Liar(StepFS):
        """the disk hands back other bytes than it was given"""
        def open(self, path, flags, mode=0o777):
            fd = super().open(path, flags, mode)
            if not flags & (os.O_CREAT | os.O_DIRECTORY) and os.path.basename(path).startswith(".theme-"):
                with open(path, "ab") as f:
                    f.write(b" ")
            return fd
    res = with_fs(Liar(), apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": dict(theme, name="Neon 2")}).encode())
    check("a read-back that differs: failed, the folder as it was", res.get("outcome") == "failed" and files(folder) == before, res)
    res = with_fs(StepFS(), apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": dict(theme, images={"masthead": {"src": os.path.join(pics, "notes.png")}})}).encode())
    check("a picture that won't do: failed, nothing changed", res.get("outcome") == "failed" and files(folder) == before and "PNG" in res.get("why", ""), res)

    # ---- replacing it: the old pictures go only once the new one names others -------------
    old_named = apps.named_in(saved)
    res = apps.do_theme_save(json.dumps({"dir": themes, "id": "neon", "theme": dict(theme, background={"mode": "image", "image": p1, "dim": 0.3})}).encode())
    check("saved over it", res.get("outcome") == "saved", res)
    check("the old pictures stay until the guide has put the new one on", old_named <= set(os.listdir(folder)))
    check("the answer names the ones only the old theme.json named", set(res["old"]) == old_named, res)
    tidy = apps.do_theme_tidy(json.dumps({"dir": themes, "id": "neon", "drop": res["old"] + ["theme.json", "../x", "/etc/passwd"]}).encode())
    check("tidy takes them, and only them", set(os.listdir(folder)) == apps.named_in(res["theme"]) | {"theme.json"} and tidy["removed"] == 3, (os.listdir(folder), tidy))
    check("and it loads whole", loads_whole(folder))
    keepme = put(os.path.join(folder, "notes.txt"), b"yours")
    tidy = apps.do_theme_tidy(json.dumps({"dir": themes, "id": "neon", "drop": sorted(apps.named_in(res["theme"]))}).encode())
    check("tidy never takes a picture theme.json still names", tidy["removed"] == 0 and loads_whole(folder), tidy)
    os.unlink(keepme)
    put(os.path.join(themes, "neon.json"), b'{"name": "Neon (old flat file)"}')
    apps.do_theme_tidy(json.dumps({"dir": themes, "id": "neon", "drop": []}).encode())
    check("tidy takes its old single file", not os.path.exists(os.path.join(themes, "neon.json")))

    # ---- unconfirmed: nothing that depends on it, and either theme.json loads whole -------------
    old_text = open(os.path.join(folder, "theme.json"), "rb").read()
    old_files = files(folder)
    res = with_fs(StepFS("dirsync:neon@2"), apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": dict(theme, name="Neon 3")}).encode())
    # (the first folder sync passes; only the one after the rename fails)
    class LastSync(StepFS):
        def step(self, name):
            self.calls.append(name)
            if name == "dirsync:neon" and "rename" in self.calls:
                raise OSError("injected: the last sync")
    res = with_fs(LastSync(), apps.do_theme_save, json.dumps({"dir": themes, "id": "neon", "theme": dict(theme, name="Neon 4")}).encode())
    check("only the folder sync after the rename failed: unconfirmed", res.get("outcome") == "unconfirmed" and res.get("old") == [], res)
    new_text = open(os.path.join(folder, "theme.json"), "rb").read()
    check("the new theme.json is in place, the old pictures kept", json.loads(new_text)["name"] == "Neon 4" and all(n in os.listdir(folder) for n in old_files))
    check("a power cut keeping the rename: the new one loads whole", loads_whole(folder))
    cut = tempfile.mkdtemp(dir=work)
    shutil.copytree(folder, os.path.join(cut, "neon"))
    put(os.path.join(cut, "neon", "theme.json"), old_text)
    check("a power cut losing it: the old one loads whole too", loads_whole(os.path.join(cut, "neon")))

    # ---- the sweep ---------------------------------------------------------------------------
    # after that unconfirmed save, a load whose sweep can't sync keeps everything
    class NoSync(StepFS):
        def step(self, name):
            self.calls.append(name)
            if name.startswith("dirsync"):
                raise OSError("injected")
    keep = sorted(os.listdir(folder))
    with_fs(NoSync(), apps.do_theme_sweep, json.dumps({"dir": themes}).encode())
    check("a sweep that can't sync removes nothing", sorted(os.listdir(folder)) == keep)
    shutil.rmtree(cut)
    cut = tempfile.mkdtemp(dir=work)
    shutil.copytree(folder, os.path.join(cut, "neon"))
    put(os.path.join(cut, "neon", "theme.json"), old_text)
    check("  and a power cut then bringing back the old theme.json: it loads whole", loads_whole(os.path.join(cut, "neon")))
    # one that syncs: the new theme.json is then the one that survives, and only copies it doesn't name go
    res = apps.do_theme_sweep(json.dumps({"dir": themes}).encode())
    check("a sweep that syncs takes the copies theme.json doesn't name", set(os.listdir(folder)) == apps.named_in(json.loads(new_text)) | {"theme.json"} and res["removed"] > 0,
          (os.listdir(folder), res))
    check("  and the theme that survives loads whole", loads_whole(folder))
    # a crash before the commit: the copies and the temporary file go, the theme stays
    put(os.path.join(folder, "pic-0123456789abcdef.png"), png(10, 10))
    put(os.path.join(folder, ".theme-0123456789abcdef.json.tmp"), b"{}")
    put(os.path.join(folder, ".theme.json.tmp"), b"{}")
    put(os.path.join(folder, "mine.png"), png(10, 10))
    os.symlink(p1, os.path.join(folder, "pic-fedcba9876543210.png"))
    apps.do_theme_sweep(json.dumps({"dir": themes}).encode())
    left = set(os.listdir(folder))
    check("a crash's leftovers are gone after the next load", "pic-0123456789abcdef.png" not in left and ".theme-0123456789abcdef.json.tmp" not in left
          and ".theme.json.tmp" not in left, left)
    check("  names not in a save's naming stay, and so does a link", "mine.png" in left and "pic-fedcba9876543210.png" in left, left)
    os.unlink(os.path.join(folder, "mine.png"))
    os.unlink(os.path.join(folder, "pic-fedcba9876543210.png"))
    check("  and the theme loads whole", loads_whole(folder))
    # a first save that never committed: no theme.json, so nothing's named; the empty folder goes
    first = os.path.join(themes, "never")
    put(os.path.join(first, "pic-00000000000000aa.jpg"), jpeg(10, 10))
    put(os.path.join(first, ".theme-00000000000000aa.json.tmp"), b"{}")
    apps.do_theme_sweep(json.dumps({"dir": themes}).encode())
    check("a new theme's crashed first save leaves nothing", not os.path.exists(first))
    # a theme.json that can't be read or checked: nothing removed
    broken = os.path.join(themes, "broken")
    put(os.path.join(broken, "theme.json"), b"{ not json")
    put(os.path.join(broken, "pic-00000000000000bb.png"), png(10, 10))
    apps.do_theme_sweep(json.dumps({"dir": themes}).encode())
    check("a theme.json that won't read: nothing removed", os.path.exists(os.path.join(broken, "pic-00000000000000bb.png")))
    shutil.rmtree(broken)

    # ---- removing a theme -------------------------------------------------------------------
    res = with_fs(StepFS("unlink:theme.json"), apps.do_theme_remove, json.dumps({"dir": themes, "id": "neon"}).encode())
    check("a removal that can't take theme.json: failed, nothing changed", res.get("outcome") == "failed" and loads_whole(folder), res)
    class RemoveSync(StepFS):
        def step(self, name):
            self.calls.append(name)
            if name == "dirsync:themes":
                raise OSError("injected")
    named = apps.named_in(json.load(open(os.path.join(folder, "theme.json"))))
    res = with_fs(RemoveSync(), apps.do_theme_remove, json.dumps({"dir": themes, "id": "neon"}).encode())
    check("a removal the disk hasn't confirmed: unconfirmed, its pictures kept", res.get("outcome") == "unconfirmed" and named <= set(os.listdir(folder)), res)
    put(os.path.join(folder, "theme.json"), new_text)   # (as a power cut could bring back)
    check("  so a theme.json a power cut brings back loads whole", loads_whole(folder))
    res = call("theme-remove", {"dir": themes, "id": "neon"})
    check("a removal: saved, its folder gone", res.get("outcome") == "saved" and not os.path.exists(folder), res)
    check("removing one that isn't there: failed", call("theme-remove", {"dir": themes, "id": "neon"}).get("outcome") == "failed")
    check("never retro, never a path", not call("theme-remove", {"dir": themes, "id": "retro"}).get("ok") and not call("theme-remove", {"dir": themes, "id": "../x"}).get("ok"))

    # ---- only what the guide wrote is ever deleted ------------------------------------------------
    mine = os.path.join(themes, "mine")
    put(os.path.join(mine, "theme.json"), json.dumps({"name": "Mine", "background": {"mode": "image", "image": "personal.png"},
                                                      "images": {"masthead": {"src": "masthead.png"}}}).encode())
    for n in ("personal.png", "masthead.png", "notes.txt", ".personal.tmp", ".notes.tmp", "pic.png", "pic-123.png"):
        put(os.path.join(mine, n), png(10, 10))
    put(os.path.join(mine, ".masthead.png.tmp"), b"old writer's leftover")
    put(os.path.join(mine, ".theme.json.tmp"), b"{}")
    apps.do_theme_sweep(json.dumps({"dir": themes}).encode())
    left = set(os.listdir(mine))
    check("the sweep keeps every name the guide didn't write", {"personal.png", "notes.txt", ".personal.tmp", ".notes.tmp", "pic.png", "pic-123.png"} <= left, left)
    check("  and takes the old writer's leftovers", ".masthead.png.tmp" not in left and ".theme.json.tmp" not in left, left)
    res = apps.do_theme_save(json.dumps({"dir": themes, "id": "mine", "theme": {"name": "Mine 2", "background": {"mode": "image", "image": p1}}}).encode())
    check("saving over a hand-made theme: only the guide's names count as old", res.get("old") == ["masthead.png"], res.get("old"))
    apps.do_theme_tidy(json.dumps({"dir": themes, "id": "mine", "drop": ["personal.png", "masthead.png", "notes.txt", "pic.png"]}).encode())
    left = set(os.listdir(mine))
    check("tidy never takes a name the guide didn't write, even when asked", {"personal.png", "notes.txt", "pic.png"} <= left and "masthead.png" not in left, left)
    res = apps.do_theme_remove(json.dumps({"dir": themes, "id": "mine"}).encode())
    left = set(os.listdir(mine)) if os.path.isdir(mine) else set()
    check("a removal takes the guide's files and theme.json, nothing else", res.get("outcome") == "saved" and "theme.json" not in left
          and {"personal.png", "notes.txt", ".personal.tmp", ".notes.tmp", "pic.png", "pic-123.png"} == left, left)
    shutil.rmtree(mine)

    # ---- the helper itself -------------------------------------------------------------------
    res = call("theme-save", {"dir": themes, "id": "cli", "theme": {"name": "CLI", "background": {"mode": "image", "image": p1, "dim": 0.5}}})
    check("theme-save through the helper: saved", res.get("outcome") == "saved" and loads_whole(os.path.join(themes, "cli")), res)
    check("a request that isn't one is refused", not call("theme-save", {"dir": "relative", "id": "x", "theme": {}}).get("ok")
          and not call("theme-save", {"dir": themes, "id": "Bad Id", "theme": {}}).get("ok"))
    w = subprocess.run([sys.executable, HELPER, "theme-save"], input=b"x" * (512 * 1024 + 1), capture_output=True)
    check("a request over 512 KiB is refused", not json.loads(w.stdout.decode().strip().splitlines()[-1]).get("ok"))

    # ---- picture-import ----------------------------------------------------------------------
    into = os.path.join(work, "config", "app-pictures")
    res = call("picture-import", {"into": into, "from": p3})
    check("a picture you pick is copied into the guide's folder", res.get("ok") and os.path.dirname(res["path"]) == into
          and open(res["path"], "rb").read() == open(p3, "rb").read(), res)
    check("  as <32 hex>.<ext>, yours alone, in a 0700 folder", bool(apps.re.match(r"^[0-9a-f]{32}\.webp\Z", os.path.basename(res["path"])))
          and (os.stat(res["path"]).st_mode & 0o777, os.stat(into).st_mode & 0o777) == (0o600, 0o700), res)
    check("  never anywhere else", not call("picture-import", {"into": os.path.join(work, "elsewhere"), "from": p3}).get("ok"))
    check("  and not a link", not call("picture-import", {"into": into, "from": os.path.join(pics, "link.png")}).get("ok"))
    # ---- picture-prune: the copies nothing names any more -----------------------------------
    named_copy = os.path.basename(res["path"])
    stale = put(os.path.join(into, "b" * 32 + ".png"), png(10, 10))
    fresh = put(os.path.join(into, "c" * 32 + ".png"), png(10, 10))
    other = put(os.path.join(into, "notes.txt"), b"not ours")
    os.symlink(p1, os.path.join(into, "d" * 32 + ".png"))
    for path in (os.path.join(into, named_copy), stale, other):
        os.utime(path, (1, 1))
    os.utime(os.path.join(into, "d" * 32 + ".png"), (1, 1), follow_symlinks=False)
    res = call("picture-prune", {"into": into, "keep": [named_copy]})
    left = set(os.listdir(into))
    check("a copy nothing names, and old, goes", os.path.basename(stale) not in left and res.get("removed") == 1, (left, res))
    check("  one still named stays, and so does a recent one (a pick on its way)", named_copy in left and os.path.basename(fresh) in left, left)
    check("  and what isn't its own copy stays, links too", "notes.txt" in left and "d" * 32 + ".png" in left, left)
    check("  only in the guide's own folder", not call("picture-prune", {"into": os.path.join(work, "elsewhere"), "keep": []}).get("ok"))
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("themes: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
