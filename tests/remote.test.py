#!/usr/bin/python3
"""The phone remote's commands (bin/om-pg-remote), through its real request
handler with the request stood in: /usr/bin/python3 tests/remote.test.py

The channel lock's passcode, typed on the phone, comes as "code" with its
digits as text (a leading 0 counts), 4 to 8 of them, only from a paired
phone; anything else is refused before it reaches the guide."""

import importlib.machinery
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader("om_pg_remote", os.path.join(ROOT, "bin", "om-pg-remote"))
_spec = importlib.util.spec_from_loader("om_pg_remote", _loader)
remote = importlib.util.module_from_spec(_spec)
_loader.exec_module(remote)

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

print("\n" + ("remote: all good" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
