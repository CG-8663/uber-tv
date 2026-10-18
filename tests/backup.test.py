#!/usr/bin/python3
"""Backups, restore and reset (bin/om-pg-backup): /usr/bin/python3 tests/backup.test.py

Everything here runs in a throwaway home folder (HOME and the XDG folders
pointed into it, checked before anything is reset): never on yours.

A backup holds your channels, settings, My List, Continue watching, themes
and picked pictures, and never paired phones, the channel lock, app
sign-ins or apps; it's readable by you alone. Restore puts a backup's parts
back, keeps the phone remote's settings as they are, and refuses anything a
backup wouldn't hold (a path out of the folder, a link, another file, JSON
that doesn't read, too big) with nothing changed; a step that fails partway
puts back what was swapped. Reset leaves Uber TV's folders empty (an app's
read-only files included) and the backups where they are."""

import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-backup")
_loader = importlib.machinery.SourceFileLoader("om_pg_backup", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_backup", _loader)
bk = importlib.util.module_from_spec(_spec)
_loader.exec_module(bk)

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def write(path, data, mode=0o600):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    os.chmod(path, mode)


def read(path):
    with open(path, "rb") as f:
        return f.read()


HEX = "0123456789abcdef0123456789abcdef"

with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home")
    env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
               XDG_DATA_HOME=os.path.join(home, ".local", "share"), XDG_CACHE_HOME=os.path.join(home, ".cache"))
    os.environ.update({k: env[k] for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")})
    r = bk.roots()
    inside = all(p.startswith(home + "/") for p in r.values()) and bk.backups_folder().startswith(home + "/")
    check("everything here is in the throwaway home folder", inside, r)
    if not inside:
        sys.exit(1)
    config, data, cache = r["config"], r["data"], r["cache"]

    def helper(*args):
        out = subprocess.run(["/usr/bin/python3", HELPER] + list(args), env=env, stdout=subprocess.PIPE, timeout=120).stdout
        return json.loads(out.decode() or "null")

    # ---- what's there ----
    write(os.path.join(config, "channels.json"), json.dumps({"channels": ["one", "two"]}))
    write(os.path.join(config, "settings.json"), json.dumps({"logos": True, "remote": {"enabled": False, "port": 24750}}))
    write(os.path.join(config, "library.json"), json.dumps({"version": 1, "items": [], "myList": ["a"]}))
    write(os.path.join(config, "history.json"), json.dumps({"a": 30}))
    write(os.path.join(config, "lock.json"), json.dumps({"passcode": "secret"}))
    write(os.path.join(config, "remotes.json"), json.dumps({"phones": ["p"]}))
    write(os.path.join(config, "apps.json"), json.dumps({"on": True, "developer": True}))
    write(os.path.join(config, "app-secrets", "x", "y.json"), "{}")
    write(os.path.join(config, "themes", "mine", "theme.json"), json.dumps({"name": "Mine"}))
    write(os.path.join(config, "themes", "mine", "background.png"), b"\x89PNG....")
    write(os.path.join(config, "themes", "other.json"), json.dumps({"name": "Other"}))
    write(os.path.join(config, "themes", ".hidden.json"), "{}")
    os.symlink(os.path.join(config, "lock.json"), os.path.join(config, "themes", "link.json"))
    write(os.path.join(config, "app-pictures", HEX + ".png"), b"\x89PNG.")
    write(os.path.join(config, "app-pictures", "notes.txt"), "no")

    got = helper("backup", "0.1.0-beta")
    check("backup: made", got.get("ok") is True and got.get("file", "").startswith(bk.backups_folder() + "/"), got)
    file = got.get("file", "")
    check("backup: readable by you alone, in a folder only you can open",
          stat.S_IMODE(os.stat(file).st_mode) == 0o600 and stat.S_IMODE(os.stat(bk.backups_folder()).st_mode) == 0o700)
    with tarfile.open(file, "r:gz") as t:
        names = sorted(t.getnames())
    want = sorted(["uber-tv-backup.json", "config/channels.json", "config/settings.json", "config/library.json", "config/history.json",
                   "config/themes/mine/theme.json", "config/themes/mine/background.png", "config/themes/other.json",
                   "config/app-pictures/" + HEX + ".png"])
    check("backup: channels, settings, My List, Continue watching, themes, pictures; never phones, the lock, sign-ins, apps or links",
          names == want, names)
    got = helper("list")
    check("list: the backup, with when it was made", got.get("ok") and [b["file"] for b in got["backups"]] == [os.path.basename(file)]
          and got["backups"][0]["made"] > 0 and got["backups"][0]["size"] > 0, got)

    # ---- restore ----
    write(os.path.join(config, "channels.json"), json.dumps({"channels": ["changed"]}))
    os.unlink(os.path.join(config, "history.json"))
    write(os.path.join(config, "settings.json"), json.dumps({"logos": False, "remote": {"enabled": True, "port": 4321}}))
    write(os.path.join(config, "lock.json"), json.dumps({"passcode": "new"}))
    got = helper("restore", os.path.basename(file))
    check("restore: done", got == {"ok": True}, got)
    check("restore: the channels and Continue watching are the backup's",
          json.loads(read(os.path.join(config, "channels.json"))) == {"channels": ["one", "two"]}
          and json.loads(read(os.path.join(config, "history.json"))) == {"a": 30})
    s = json.loads(read(os.path.join(config, "settings.json")))
    check("restore: settings are the backup's, the phone remote's stay as they are here",
          s.get("logos") is True and s.get("remote") == {"enabled": True, "port": 4321}, s)
    check("restore: the channel lock and paired phones aren't touched",
          json.loads(read(os.path.join(config, "lock.json"))) == {"passcode": "new"} and os.path.exists(os.path.join(config, "remotes.json")))
    check("restore: nothing left beside the settings folder",
          not [n for n in os.listdir(os.path.dirname(config)) if n.startswith(".om-pg-restore")])

    # ---- restore refuses what a backup wouldn't hold, changing nothing ----
    def crafted(name, members, manifest=True, raw=None):
        path = os.path.join(bk.backups_folder(), name)
        if raw is not None:
            write(path, raw)
            return name
        with tarfile.open(path, "w:gz") as t:
            if manifest:
                m = json.dumps({"format": 1}).encode()
                i = tarfile.TarInfo("uber-tv-backup.json")
                i.size = len(m)
                t.addfile(i, io.BytesIO(m))
            for n, body, kind in members:
                i = tarfile.TarInfo(n)
                if kind == "link":
                    i.type, i.linkname = tarfile.SYMTYPE, "/etc/passwd"
                    t.addfile(i)
                else:
                    i.size = len(body)
                    t.addfile(i, io.BytesIO(body))
        return name

    before = {n: read(os.path.join(config, n)) for n in ("channels.json", "settings.json", "history.json")}
    good = json.dumps({"channels": ["evil"]}).encode()
    cases = [
        ("a path out of the folder", crafted("uber-tv-backup-2001-01-01-000001.tar.gz", [("config/../escaped.json", good, "file")])),
        ("an absolute path", crafted("uber-tv-backup-2001-01-01-000002.tar.gz", [("/tmp/abs.json", good, "file")])),
        ("a link", crafted("uber-tv-backup-2001-01-01-000003.tar.gz", [("config/channels.json", b"", "link")])),
        ("the channel lock", crafted("uber-tv-backup-2001-01-01-000004.tar.gz", [("config/lock.json", b"{}", "file")])),
        ("no manifest", crafted("uber-tv-backup-2001-01-01-000005.tar.gz", [("config/channels.json", good, "file")], manifest=False)),
        ("JSON that doesn't read", crafted("uber-tv-backup-2001-01-01-000006.tar.gz", [("config/channels.json", b"{nope", "file")])),
        ("too big a settings file", crafted("uber-tv-backup-2001-01-01-000007.tar.gz", [("config/settings.json", b" " * ((1 << 20) + 1), "file")])),
        ("not a backup at all", crafted("uber-tv-backup-2001-01-01-000008.tar.gz", [], raw=b"not gzip at all")),
        ("a file twice", crafted("uber-tv-backup-2001-01-01-000009.tar.gz", [("config/channels.json", good, "file"), ("config/channels.json", good, "file")])),
    ]
    for what, name in cases:
        got = helper("restore", name)
        check("restore refuses " + what, got.get("ok") is False and got.get("error"), got)
    got = helper("restore", "../" + os.path.basename(file))
    check("restore refuses a name that isn't a backup's", got.get("ok") is False, got)
    after = {n: read(os.path.join(config, n)) for n in ("channels.json", "settings.json", "history.json")}
    check("and nothing changed", before == after and not os.path.exists(os.path.join(os.path.dirname(config), "escaped.json"))
          and not os.path.exists("/tmp/abs.json"))
    check("nothing left beside the settings folder after the refusals",
          not [n for n in os.listdir(os.path.dirname(config)) if n.startswith(".om-pg-restore")])

    # ---- a step that fails partway puts back what was swapped ----
    real_rename = os.rename
    calls = {"n": 0}

    def failing(src, dst):
        # the backup's library.json going in fails (the rollback's moves don't)
        if os.path.basename(src) == "library.json" and ".om-pg-restore-" in src and ".om-pg-restore-was-" not in src:
            raise OSError(5, "Input/output error", src)
        return real_rename(src, dst)

    write(os.path.join(config, "channels.json"), json.dumps({"channels": ["before the failed restore"]}))
    before = {n: read(os.path.join(config, n)) for n in ("channels.json", "settings.json", "library.json", "history.json")}
    bk.os.rename = failing
    try:
        try:
            bk.restore(os.path.basename(file))
            check("a failing restore says so", False)
        except OSError:
            check("a failing restore says so", True)
    finally:
        bk.os.rename = real_rename
    after = {n: read(os.path.join(config, n)) for n in ("channels.json", "settings.json", "library.json", "history.json")}
    check("and what was swapped before the failure went back", before == after, [n for n in before if before[n] != after.get(n)])
    check("with nothing left beside the settings folder",
          not [n for n in os.listdir(os.path.dirname(config)) if n.startswith(".om-pg-restore")])

    # ---- and if putting one back fails too, your files are kept, and where is said ----
    def failing_twice(src, dst):
        if os.path.basename(src) == "library.json" and ".om-pg-restore-" in src:
            raise OSError(5, "Input/output error", src)
        return real_rename(src, dst)

    bk.os.rename = failing_twice
    try:
        try:
            bk.restore(os.path.basename(file))
            check("a restore that can't put everything back says where your files are", False)
        except bk.Refused as e:
            where = str(e).split("they're in ")[-1]
            check("a restore that can't put everything back says where your files are",
                  os.path.isdir(where) and os.path.exists(os.path.join(where, "library.json")), e)
    finally:
        bk.os.rename = real_rename
    if os.path.isdir(where):
        real_rename(os.path.join(where, "library.json"), os.path.join(config, "library.json"))
        os.rmdir(where)

    # ---- a backup refuses a file that's too big ----
    write(os.path.join(config, "settings.json"), b" " * ((1 << 20) + 1))
    got = helper("backup", "0.1.0-beta")
    check("backup refuses a settings file too big to restore", got.get("ok") is False and "too big" in got.get("error", ""), got)
    write(os.path.join(config, "settings.json"), json.dumps({"logos": True}))

    # ---- reset ----
    app = os.path.join(data, "apps", "tv.uber.scores", "1")
    write(os.path.join(app, "main.py"), "print()", mode=0o444)
    os.chmod(app, 0o555)
    write(os.path.join(cache, "epg.json"), "{}")
    kept = sorted(os.listdir(bk.backups_folder()))
    got = helper("reset")
    check("reset: done, nothing left over", got == {"ok": True, "left": []}, got)
    check("reset: Uber TV's folders are there, empty and yours alone",
          all(os.listdir(p) == [] and stat.S_IMODE(os.stat(p).st_mode) == 0o700 for p in (config, data, cache)))
    check("reset: nothing moved aside is left", not [n for p in (config, data, cache) for n in os.listdir(os.path.dirname(p)) if ".reset-" in n])
    check("reset: the backups are still there", sorted(os.listdir(bk.backups_folder())) == kept)
    os.rmdir(cache)
    os.symlink(tmp, cache)
    got = helper("reset")
    check("reset refuses a folder that's a link", got.get("ok") is False and "link" in got.get("error", ""), got)
    os.unlink(cache)

print("\n%d failed" % failures if failures else "\nall good")
sys.exit(1 if failures else 0)
