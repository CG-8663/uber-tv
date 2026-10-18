#!/usr/bin/python3
"""The phone remote's commands (bin/om-pg-remote), through its real request
handler with the request stood in: /usr/bin/python3 tests/remote.test.py

The channel lock's passcode, typed on the phone, comes as "code" with its
digits as text (a leading 0 counts), 4 to 8 of them, only from a paired
phone; anything else is refused before it reaches the guide."""

import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader("om_pg_remote", os.path.join(ROOT, "bin", "om-pg-remote"))
_spec = importlib.util.spec_from_loader("om_pg_remote", _loader)
remote = importlib.util.module_from_spec(_spec)
_loader.exec_module(remote)

# The import read the user's remotes.json. Point at a temp folder before
# anything saves, and don't touch that file.
_dir = pathlib.Path(tempfile.mkdtemp())
remote.CONFIG = _dir
remote.CACHE = _dir
remote.DEVICES = _dir / "remotes.json"
remote.devices = []
remote.pairing = {"on": False, "code": "", "link": "", "expires": 0, "tries": 0, "qr": ""}

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def post(body, paired=True):
    """One POST /api/cmd from a phone on the network: what it answered, and
    what reached the guide"""
    said, answered = [], []
    remote.say = said.append
    h = remote.Handler.__new__(remote.Handler)
    h.path = "/api/cmd"
    h.client_address = ("192.168.1.20", 50000)
    h.private = lambda: True
    h.from_here = lambda: False
    h.same_origin = lambda: True
    h.body = lambda: body
    h.device = lambda: {"id": "phone"} if paired else None
    h.json = lambda code, data, headers=None: answered.append((code, data))
    h.send = lambda code, *a, **k: answered.append((code, None))
    h.do_POST()
    return answered, said


answered, said = post({"cmd": "code", "digits": "0123"})
check("a paired phone's passcode reaches the guide as text, a leading 0 and all", said == [{"command": {"cmd": "code", "digits": "0123"}}] and answered == [(204, None)], (answered, said))
for bad in ["123", "123456789", "12a4", "", None, 1234, ["1234"], "１２３４"]:
    answered, said = post({"cmd": "code", "digits": bad})
    check("refused: %r" % (bad,), not said and answered and answered[0][0] == 400, (answered, said))
answered, said = post({"cmd": "code", "digits": "2468"}, paired=False)
check("an unpaired phone's passcode never reaches the guide", not said and answered and answered[0][0] == 401, (answered, said))
answered, said = post({"cmd": "tune", "number": 101})
check("the other commands are as they were (tune)", said == [{"command": {"cmd": "tune", "number": 101}}], said)

HERE = "Pair and press buttons from your phone, not from this computer."


def get(path, here=False, headers=None):
    """One GET, with private, from_here and the answer stood in"""
    answered = []
    h = remote.Handler.__new__(remote.Handler)
    h.path = path
    h.client_address = ("192.168.1.20", 50000)
    h.private = lambda: True
    h.from_here = lambda: here
    h.headers = headers or {}
    h.json = lambda code, data, headers=None: answered.append((code, data))
    h.send = lambda code, *a, **k: answered.append((code, None))
    h.do_GET()
    return answered


remote.say = lambda message: None
link = "phone-link"
remote.devices = []
remote.pairing.update(on=True, code="111111", link=link, expires=time.time() + 120, tries=0, qr="")
answered = get("/?pair=" + link, here=True)
check("a QR link opened on this computer is refused, and the link stays valid",
      answered == [(403, {"error": HERE})] and remote.devices == [] and remote.pairing["link"] == link,
      (answered, remote.pairing["link"], remote.devices))

remote.devices = []
remote.pairing.update(on=True, code="222222", link=link, expires=time.time() + 120, tries=0, qr="")
answered = get("/?pair=" + link, here=False)
check("a QR link opened on a phone pairs it, and the link is used once",
      answered == [(303, None)] and len(remote.devices) == 1 and remote.pairing["link"] != link,
      (answered, len(remote.devices)))

token = "stolen-token"
seen = 1
remote.devices = [{"id": "abcd1234", "hash": remote.digest(token), "name": "Phone", "added": 1, "seen": seen}]
answered = get("/api/state", here=True, headers={"Cookie": "omt=" + token})
check("a page on this computer can't use a paired phone's token",
      answered == [(403, {"error": HERE})] and remote.devices[0]["seen"] == seen,
      (answered, remote.devices[0]["seen"]))

answered = get("/", here=True)
check("the remote page still opens on this computer", answered == [(200, None)], answered)

saves = []
real_save = remote.save_devices


def wrapped_save():
    assert remote.lock._is_owned() is True
    saves.append(True)
    real_save()


remote.save_devices = wrapped_save
remote.add_device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit Safari")
check("add_device saves the list while it holds the lock", saves == [True], saves)

saves.clear()
remote.devices = [{"id": "abcd1234", "hash": remote.digest("tok"), "name": "Phone", "added": 1, "seen": 0}]
h = remote.Handler.__new__(remote.Handler)
h.headers = {"Cookie": "omt=tok"}
h.device()
check("a phone seen again is saved while the lock is held", saves == [True] and remote.devices[0]["seen"] != 0, saves)

mode = os.stat(remote.DEVICES).st_mode & 0o777
parts = [n for n in os.listdir(remote.CONFIG) if n.endswith(".part")]
check("remotes.json is readable by you alone and no partial file remains",
      mode == 0o600 and parts == [], (oct(mode), parts))

remote.network = {}
remote.pairing["on"] = True
remote.new_code()
qr = remote.pairing["qr"]
qr_mode = os.stat(qr).st_mode & 0o777 if qr else 0
check("the pairing QR code is readable by you alone",
      bool(qr) and os.path.dirname(qr) == str(remote.CACHE) and qr_mode == 0o600,
      (qr, oct(qr_mode) if qr else None))

print("\n" + ("remote: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
