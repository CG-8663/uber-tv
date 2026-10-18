#!/usr/bin/python3
"""The channel lock's passcode and file (bin/om-pg-apps lock-read, lock-check,
lock-passcode, lock-save, lock-reset), in a scratch
folder: /usr/bin/python3 tests/lock.test.py

The passcode is kept only as a salted scrypt hash, in a file readable by you
alone; changing it needs the one now; wrong tries slow down (5 in a row, then
a minute, doubled for each miss after, refused unchecked meanwhile, and kept
across restarts); a hash that isn't a sound one counts as none; the locked
channels and options are checked; a reset clears the passcode and the list."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-apps")

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


work = tempfile.mkdtemp(prefix="om-pg-lock-test-")
path = os.path.join(work, "om-pg", "lock.json")


def call(cmd, req, file=None):
    req = dict(req, file=file or path)
    out = subprocess.run(["/usr/bin/python3", HELPER, cmd], input=json.dumps(req).encode(), capture_output=True, timeout=60)
    return json.loads(out.stdout.decode().strip().splitlines()[-1])


def kept():
    with open(path) as f:
        return json.load(f)


try:
    res = call("lock-read", {})
    check("to begin with: no passcode, off, nothing locked, unlocks last until the TV is off, titles hidden",
          res == {"ok": True, "set": False, "on": False, "channels": [], "unlockFor": "tv", "titles": False, "wait": 0}, res)
    check("checking with no passcode yet is refused", not call("lock-check", {"code": "1234"}).get("ok"))
    check("the lock can't be turned on without a passcode", not call("lock-save", {"on": True}).get("ok"))

    # ---- setting it ----------------------------------------------------------------------------
    check("a passcode is 4 to 8 digits", all(not call("lock-passcode", {"code": c}).get("ok") for c in ("123", "123456789", "12a4", "", "١٢٣٤")))
    res = call("lock-passcode", {"code": "0123"})
    check("a passcode set (a leading 0 counts)", res.get("ok") and res.get("set") is True, res)
    raw = open(path).read()
    check("  kept only as a salted scrypt hash, never the passcode", "0123" not in raw and kept()["hash"]["n"] == 2 ** 14
          and len(kept()["hash"]["salt"]) == 32 and len(kept()["hash"]["key"]) == 64, raw[:200])
    check("  in a file readable by you alone, in a 0700 folder", (os.stat(path).st_mode & 0o777, os.stat(os.path.dirname(path)).st_mode & 0o777) == (0o600, 0o700))
    check("  and the guide never gets the hash", "hash" not in call("lock-read", {}) and "key" not in json.dumps(call("lock-read", {})))
    check("the right passcode passes", call("lock-check", {"code": "0123"}) == {"ok": True})
    check("  and 123 isn't 0123", not call("lock-check", {"code": "1230"}).get("ok"))
    salt1 = kept()["hash"]["salt"]
    call("lock-passcode", {"code": "4444", "old": "0123"})
    check("changing it needs the one now, and gives a new salt", kept()["hash"]["salt"] != salt1 and call("lock-check", {"code": "4444"}) == {"ok": True})
    check("  without it, refused", not call("lock-passcode", {"code": "5555"}).get("ok") and call("lock-check", {"code": "4444"}) == {"ok": True})
    res = call("lock-passcode", {"code": "5555", "old": "0000"})
    check("  with a wrong one, refused (and counted)", not res.get("ok") and res.get("wrong") and kept()["misses"] == 1, res)
    call("lock-check", {"code": "4444"})
    check("a right one starts the misses over", kept()["misses"] == 0)

    # ---- wrong tries slow down -----------------------------------------------------------------
    for i in range(4):
        res = call("lock-check", {"code": "0000"})
    check("four wrong in a row: no wait yet", res.get("wait") == 0 and kept()["misses"] == 4, res)
    res = call("lock-check", {"code": "0000"})
    check("the fifth: a minute's wait", 55 <= res.get("wait", 0) <= 60 and "wait" in res.get("error", ""), res)
    res = call("lock-check", {"code": "4444"})
    check("  meanwhile even the right one is refused, unchecked (no miss counted)", not res.get("ok") and kept()["misses"] == 5, res)
    check("  and reading says how long", 55 <= call("lock-read", {}).get("wait", 0) <= 60)
    d = kept()
    d["waitUntil"] = time.time() - 1
    open(path, "w").write(json.dumps(d))
    res = call("lock-check", {"code": "0000"})
    check("once it's over, another miss waits twice as long", 115 <= res.get("wait", 0) <= 120, res)
    d = kept()
    d["waitUntil"] = time.time() - 1
    d["misses"] = 40
    open(path, "w").write(json.dumps(d))
    res = call("lock-check", {"code": "0000"})
    check("  at most an hour", 3590 <= res.get("wait", 0) <= 3600, res)
    d = kept()
    d["waitUntil"] = time.time() - 1
    open(path, "w").write(json.dumps(d))
    check("and the right one after the wait passes", call("lock-check", {"code": "4444"}) == {"ok": True} and kept()["misses"] == 0)

    # ---- channels and options ------------------------------------------------------------------
    res = call("lock-save", {"on": True, "unlockFor": 60, "titles": True,
                             "channels": [{"url": "https://a/1", "name": "One"}, {"url": "https://a/1", "name": "Again"},
                                          {"url": "", "name": "x"}, {"name": "no url"}, "nope", {"url": "https://b/2", "name": 5}]})
    check("locked channels are kept once each by address, each checked", res.get("channels") == [{"url": "https://a/1", "name": "One"}, {"url": "https://b/2", "name": ""}], res)
    check("  with the options", res.get("on") is True and res.get("unlockFor") == 60 and res.get("titles") is True, res)
    check("an unlock lasts tv, 60 or 240, nothing else", not call("lock-save", {"unlockFor": 30}).get("ok") and not call("lock-save", {"unlockFor": "1h"}).get("ok"))
    check("on and titles are true or false", not call("lock-save", {"on": "yes"}).get("ok"))
    many = [{"url": "https://c/%d" % i, "name": "c"} for i in range(5100)]
    check("at most 5000 locked channels", len(call("lock-save", {"channels": many}).get("channels", [])) == 5000)
    call("lock-save", {"channels": [{"url": "https://a/1", "name": "One"}]})

    # ---- a file that isn't sound ---------------------------------------------------------------
    d = kept()
    d["hash"]["n"] = 2 ** 30
    open(path, "w").write(json.dumps(d))
    check("a hash with other costs (one that could make a check run forever) counts as none", call("lock-read", {}).get("set") is False)
    open(path, "w").write("not json")
    check("a file that isn't readable is said so", not call("lock-read", {}).get("ok"))
    os.unlink(path)
    os.symlink(os.path.join(work, "elsewhere.json"), path)
    check("a link in its place isn't followed", not call("lock-read", {}).get("ok"))
    os.unlink(path)
    check("only the guide's lock file", not call("lock-read", {}, file=os.path.join(work, "om-pg", "settings.json")).get("ok")
          and not call("lock-read", {}, file="relative/lock.json").get("ok"))

    # ---- forgotten: a reset --------------------------------------------------------------------
    call("lock-passcode", {"code": "2468"})
    call("lock-save", {"on": True, "channels": [{"url": "https://a/1", "name": "One"}]})
    res = call("lock-reset", {})
    check("a reset clears the passcode and the locked channels, and turns it off", res.get("set") is False and res.get("on") is False and res.get("channels") == [], res)
    check("  and nothing of the old hash stays", kept()["hash"] is None)
    open(path, "w").write("not json at all")
    res = call("lock-reset", {})
    check("a reset also works over a file that can't be read (the way back from one)", res.get("ok") and res.get("set") is False
          and call("lock-read", {}).get("ok"), res)
finally:
    shutil.rmtree(work, ignore_errors=True)

print("\n" + ("lock: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
