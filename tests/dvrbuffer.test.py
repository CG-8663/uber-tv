#!/usr/bin/python3
"""Pause and rewind's buffer (bin/om-pg-dvr buffer, lib/dvrbuffer.py):
/usr/bin/python3 tests/dvrbuffer.test.py

The published playlist: only names the writer makes, each segment's start
in the session's time summed from their lengths, the newest N minutes by
summed length, never none, a longer single segment kept whole, marked EVENT,
from the seq asked for (or its head, once that's gone), a discontinuity
where the writer started again. A file deleted only once neither of the
last two published lists names it (a big drop too: a smaller window).
Live: the start of the second-newest; ready once there are two. The server:
only under its secret, only the playlist, the status (the lease) and the
segments still kept, by exact name, never following a link; nothing else.
The helper: what it refuses to start (an address off the web, a length it
doesn't offer, a drive that's gone or read-only, too little space); a
session as its own systemd service by its id only, answering once it
serves. End to end with real ffmpeg, through the relay: segments in a
private folder, served as published, the upstream address never on
ffmpeg's command line; a new address (the old one closed first, a
discontinuity); writes that follow the folder's descriptor when the path
is swapped (a drive replaced under it never gets them); too little space:
the writer stops at once, the status says why; the guide gone (no status
asked): the session stops and deletes its folder; stop: gone, folder and
control file too; sessions left behind cleaned, nothing else touched.
Nothing goes to the network: every server is on 127.0.0.1."""

import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-dvr")
_loader = importlib.machinery.SourceFileLoader("om_pg_dvr", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_dvr", _loader)
dvr = importlib.util.module_from_spec(_spec)
_loader.exec_module(dvr)
bufmod = dvr.buffer_module()

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def wait_for(test, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if test():
            return True
        time.sleep(0.2)
    return test()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError:
        return 0, b""


TMP = tempfile.mkdtemp(prefix="dvrbuffer-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
dvr.TEMPORARY = ("/proc", "/sys", "/dev")   # the test's own folders live in /tmp: treat it as a disk here
DISK = os.path.join(TMP, "disk")
os.makedirs(DISK)
TABLE = ("22 1 0:20 / / rw,relatime - btrfs /dev/mapper/root rw\n"
         "40 22 0:30 / %s rw,relatime - ext4 /dev/sdz1 rw\n" % DISK)
real_mounts = dvr.mounts
dvr.mounts = lambda text=None: real_mounts(TABLE if text is None else text)
dvr.volume_of = lambda m, by_uuid=None: "uuid:test-" + m["source"]
dvr.check_place = (lambda real: lambda folder, table=None, home=None, own=None: real(folder, table, home or TMP, own if own is not None else []))(dvr.check_place)
dvr.drive_facts = lambda m: ("TESTDRIVE", True)
place = dvr.prepare(DISK)["place"]
rec_root = os.path.join(DISK, dvr.ROOT_NAME)

# ---- the published playlist ----
check("only names the writer makes", bufmod.parse("#EXT-X-MEDIA-SEQUENCE:7\n#EXTINF:2.0,\ns000000007.ts\n#EXTINF:2.0,\n../etc/passwd\n#EXTINF:x,\ns000000009.ts\n")
      == [(7, 2000, "s000000007.ts")])

UNIT = os.path.join(TMP, "unit")
os.makedirs(UNIT)
ufd = os.open(UNIT, os.O_RDONLY | os.O_DIRECTORY)
clock = [100.0]
b = bufmod.Buffer(ufd, 0.2, lambda: clock[0])      # a 12 s window
lines = ["#EXTM3U", "#EXT-X-MEDIA-SEQUENCE:0"]


def write_seg(seq, secs):
    with open(os.path.join(UNIT, "s%09d.ts" % seq), "wb") as f:
        f.write(b"x" * 188 * (seq + 1))
    lines.extend(["#EXTINF:%.3f," % secs, "s%09d.ts" % seq])


def producer():
    return "\n".join(lines) + "\n"


write_seg(0, 6)
lines.extend(["#EXTINF:2.0,", "s000000001.ts"])     # listed before its file is in place
check("a segment listed before it's in place waits", b.ingest(producer()) == 1 and b.status()["count"] == 1 and not b.status()["ready"])
check("one isn't ready: Live is its start", b.status()["live"] == 0 and b.playlist(0) is not None)
lines[-2:] = []
write_seg(1, 2)
write_seg(2, 4)
clock[0] = 105.5
check("finished ones come, in the session's time", b.ingest(producer()) == 2 and [s["start"] for s in b.segments] == [0, 6000, 8000] and b.edge == 12000)
st = b.status()
check("ready with two; Live at the second-newest's start", st["ready"] and st["live"] == 6000 and st["oldest"] == 0 and st["edge"] == 12000
      and st["newest"] == 4000 and st["completedAgo"] == 0, st)
pl = b.playlist(0).decode()
check("marked EVENT, its media sequence, its segments", "#EXT-X-PLAYLIST-TYPE:EVENT" in pl and "#EXT-X-MEDIA-SEQUENCE:0" in pl
      and pl.count("#EXTINF:") == 3 and "#EXT-X-TARGETDURATION:6" in pl, pl)
write_seg(3, 3)
b.ingest(producer())
check("the newest 12 s by summed length (2 + 4 + 3 and the 6 s one doesn't fit)", b.status()["headSeq"] == 1 and b.status()["oldest"] == 6000, b.status())
check("its file kept while the previous list still names it", os.path.exists(os.path.join(UNIT, "s000000000.ts")))
write_seg(4, 2)
b.ingest(producer())
check("deleted once neither of the last two lists names it", not os.path.exists(os.path.join(UNIT, "s000000000.ts"))
      and os.path.exists(os.path.join(UNIT, "s000000001.ts")))
check("from a seq that's gone: the head", "#EXT-X-MEDIA-SEQUENCE:%d" % b.status()["headSeq"] in b.playlist(0).decode())
check("from a seq still listed: there", "#EXT-X-MEDIA-SEQUENCE:3" in b.playlist(3).decode())
b.restarted()
write_seg(5, 2)
b.ingest(producer())
check("from a seq older than the head but still kept (what the guide measured from): there",
      b.status()["headSeq"] == 2 and "#EXT-X-MEDIA-SEQUENCE:1" in b.playlist(1).decode(), b.status())
pl = b.playlist(0).decode()
check("a restarted writer: a discontinuity before its first segment", pl.index("#EXT-X-DISCONTINUITY") < pl.index("s000000005.ts")
      and pl.index("#EXT-X-DISCONTINUITY") > pl.index("s000000004.ts"), pl)
write_seg(6, 20)
b.ingest(producer())
check("one segment longer than the window: kept, never none", b.status()["count"] == 1 and b.status()["oldest"] == b.segments[-1]["start"])
check("a big drop (the head jumps four): every file the previous list named stays",
      all(os.path.exists(os.path.join(UNIT, "s%09d.ts" % n)) for n in (2, 3, 4, 5)))
write_seg(7, 2)
b.ingest(producer())
check("then they go, once neither of the last two names them", not any(os.path.exists(os.path.join(UNIT, "s%09d.ts" % n)) for n in (2, 3, 4, 5))
      and os.path.exists(os.path.join(UNIT, "s000000006.ts")))
write_seg(8, 2)
b.ingest(producer())
check("a kept segment opens", b.open_segment("s000000007.ts") is not None)
check("one deleted doesn't", b.open_segment("s000000002.ts") is None)
check("a name it didn't make doesn't", b.open_segment("../unit/s000000007.ts") is None and b.open_segment("p1.m3u8") is None)
os.unlink(os.path.join(UNIT, "s000000008.ts"))
os.symlink("/etc/passwd", os.path.join(UNIT, "s000000008.ts"))
check("a link in its place doesn't (never followed)", b.open_segment("s000000008.ts") is None)

# ---- the server ----
asked = []
srv = bufmod.Server(b, "SeCrEt-123", lambda: {"state": "ready", "reason": ""}, lambda: clock[0]).start()
base = "http://127.0.0.1:%d/SeCrEt-123" % srv.port
lease = srv.asked
clock[0] = 200.0
code, body = get(base + "/status")
check("the status, under its secret, and it's the lease", code == 200 and json.loads(body)["state"] == "ready" and srv.asked == 200.0, (code, body))
code, body = get(base + "/live.m3u8?open=3&from=0")
check("the playlist, not cached", code == 200 and body.startswith(b"#EXTM3U"))
code, body = get(base + "/s000000007.ts")
check("a kept segment, its bytes", code == 200 and body == open(os.path.join(UNIT, "s000000007.ts"), "rb").read())
check("another secret: nothing", get("http://127.0.0.1:%d/wrong/status" % srv.port)[0] == 404)
check("no listing", get(base + "/")[0] == 404 and get(base)[0] == 404)
check("no way out of the folder", get(base + "/..%2Fetc%2Fpasswd")[0] == 404 and get(base + "/../unit/s000000007.ts")[0] == 404)
check("a link named like a segment: nothing", get(base + "/s000000008.ts")[0] == 404)
srv.stop()
empty = bufmod.Server(bufmod.Buffer(ufd, 5), "s", lambda: {}).start()
check("nothing yet: the playlist isn't there", get("http://127.0.0.1:%d/s/live.m3u8" % empty.port)[0] == 503)
empty.stop()
os.close(ufd)

# ---- the helper ----
dvr.SYSTEMD_RUN = "/usr/bin/true"
dvr.SYSTEMCTL = "/usr/bin/true"
real_run = subprocess.run
started, workers = [], {}
holding = [False]                  # systemd not carrying out a stop


def fake_run(argv, *a, **kw):
    if argv and argv[0] == "/usr/bin/true":
        started.append(argv)
        if "buffer-run" in argv:   # systemd starting the session's service
            w = dvr.BufferWorker(argv[-1], signals=False)
            w.free = lambda fd: free[0]
            t = threading.Thread(target=w.run, daemon=True)
            workers[argv[-1]] = (w, t)
            t.start()
        elif len(argv) > 3 and argv[2] == "stop":   # systemctl --user stop: it ends before this answers
            w, t = workers.get(argv[3][len(dvr.BUF_UNIT):], (None, None))
            if w and not holding[0]:
                w.stopping = True
                t.join(30)
    return real_run(argv, *a, **kw)


# what systemd says about a session: active, inactive (stopped, failed, not there), or unknown (not answering)
FAKE = os.path.join(TMP, "systemctl")
def systemd_says(script):
    with open(FAKE, "w") as f:
        f.write("#!/bin/sh\n" + script + "\n")
    os.chmod(FAKE, 0o700)
real_systemctl = dvr.SYSTEMCTL
dvr.SYSTEMCTL = FAKE
dvr.BUF_PROBE_TIMEOUT = 1
for script, want in [("echo active", "active"), ("echo deactivating", "active"), ("echo inactive", "inactive"), ("echo failed", "inactive"),
                     ("echo; exit 0", "unknown"), ("echo 'Failed to connect to bus' >&2; exit 1", "unknown"), ("sleep 3; echo inactive", "unknown")]:
    systemd_says(script)
    check("systemd says %r: %s" % (script, want), dvr.buffer_state("0123456789abcdef") == want, dvr.buffer_state("0123456789abcdef"))
dvr.SYSTEMCTL = os.path.join(TMP, "no-such-systemctl")
check("systemctl not there: unknown, never taken as stopped", dvr.buffer_state("0123456789abcdef") == "unknown" and dvr.buffer_running("0123456789abcdef"))
# not known to have stopped: stop isn't ok, and nothing's cleaned
os.makedirs(os.path.join(rec_root, dvr.BUF_DIR, "0123456789abcdef"), exist_ok=True)
open(os.path.join(rec_root, dvr.BUF_DIR, "0123456789abcdef", "s000000001.ts"), "wb").close()
dvr.write_control("0123456789abcdef", {"session": "0123456789abcdef", "place": place})
systemd_says("echo 'Failed to connect to bus' >&2; exit 1")
dvr.SYSTEMCTL = FAKE
t0 = time.time()
check("systemd not answering: stop not ok", dvr.buffer_stop("0123456789abcdef") == {"ok": False, "error": "running"} and time.time() - t0 < 30)
dvr.clean_buffers(rec_root)
check("and nothing cleaned, by stop or the next start", dvr.read_control("0123456789abcdef") is not None
      and os.path.exists(os.path.join(rec_root, dvr.BUF_DIR, "0123456789abcdef", "s000000001.ts")))
systemd_says("echo inactive")
check("once systemd says it's stopped: ok, and cleaned", dvr.buffer_stop("0123456789abcdef") == {"ok": True} and dvr.read_control("0123456789abcdef") is None
      and not os.path.exists(os.path.join(rec_root, dvr.BUF_DIR, "0123456789abcdef")))
dvr.SYSTEMCTL = real_systemctl

dvr.subprocess.run = fake_run
dvr.buffer_running = lambda session: session in workers and workers[session][1].is_alive()
free = [500 * dvr.GiB]
dvr.free_of = lambda path: free[0]
dvr.BUF_MINUTES = (0.2, 5, 30)


def startjob(**kw):
    j = {"url": UP + "/src.ts", "minutes": 5, "place": place, "keepFree": dvr.GiB}
    j.update(kw)
    return j


# a channel: 40 s of a moving picture, a keyframe every second, sent four times faster than it plays
SRC = os.path.join(TMP, "src.ts")
subprocess.run(["nice", "-n", "19", "/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "40", "-c:v", "mpeg2video", "-g", "10", "-c:a", "mp2",
                "-f", "mpegts", SRC], check=True, timeout=120)
source = open(SRC, "rb").read()
seen = []


class Up(http.server.ThreadingHTTPServer):
    daemon_threads = True


class UpHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        seen.append(self.path)
        if self.path.split("?")[0] not in ("/src.ts", "/src-new.ts"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.end_headers()
        step = len(source) // 100
        try:
            for i in range(0, len(source), step):
                self.wfile.write(source[i:i + step])
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass


up = Up(("127.0.0.1", 0), UpHandler)
threading.Thread(target=up.serve_forever, daemon=True).start()
UP = "http://127.0.0.1:%d" % up.server_address[1]

check("an address off the web refused", dvr.buffer_start(startjob(url="file:///etc/passwd")).get("error") == "url")
check("a length it doesn't offer refused", dvr.buffer_start(startjob(minutes=7)).get("error") == "minutes")
check("a drive that's gone refused", dvr.buffer_start(startjob(place=dict(place, volume="uuid:other"))).get("error") == "drive")
free[0] = dvr.GiB
check("too little space refused", dvr.buffer_start(startjob()).get("error") == "space")
free[0] = 500 * dvr.GiB
check("nothing started for those", not started)

res = dvr.buffer_start(startjob())
check("a session starts, answering once it serves", res.get("ok") and dvr.ID_RE.match(res.get("session", "")) and res["base"].startswith("http://127.0.0.1:"), res)
s1 = res["session"]
check("as its own systemd service, by its id only", ("--unit=uber-tv-buf-" + s1) in started[0] and started[0][-1] == s1
      and not any(UP in a for a in started[0]), started[0])
ctl = os.path.join(os.environ["XDG_CONFIG_HOME"], "om-pg", "dvr", "buffers", s1 + ".json")
check("its address kept privately while it runs", oct(os.stat(ctl).st_mode & 0o777) == "0o600" and json.load(open(ctl))["url"].startswith(UP))
w1, t1 = workers[s1]
check("ready once two segments are in", wait_for(lambda: json.loads(get(res["base"] + "/status")[1] or b"{}").get("state") == "ready", 30))
sdir = os.path.join(rec_root, dvr.BUF_DIR, s1)
check("its folder at the recordings place, private", oct(os.stat(sdir).st_mode & 0o777) == "0o700"
      and oct(os.stat(os.path.dirname(sdir)).st_mode & 0o777) == "0o700")
segs = sorted(n for n in os.listdir(sdir) if n.endswith(".ts"))
check("its segments private", segs and all(oct(os.stat(os.path.join(sdir, n)).st_mode & 0o777) == "0o600" for n in segs), segs)
check("the upstream address never on ffmpeg's command line", w1.proc and not any(UP in a for a in w1.proc.args)
      and any(a.startswith("/proc/self/fd/") for a in w1.proc.args), w1.proc and w1.proc.args)
code, pl = get(res["base"] + "/live.m3u8?open=1&from=0")
first = [l for l in pl.decode().splitlines() if l.endswith(".ts")][0]
code2, data = get(res["base"] + "/" + first)
check("served as published", code == 200 and code2 == 200 and data == open(os.path.join(sdir, first), "rb").read() and len(data) > 1000)

# a new address: the old one closed first, then a discontinuity
before = len([p for p in seen if p.startswith("/src.ts")])
check("a new address taken", dvr.buffer_follow(s1, {"url": UP + "/src-new.ts"}).get("gen") == 1)
check("the same address again: nothing to do", dvr.buffer_follow(s1, {"url": UP + "/src-new.ts"}).get("ok"))
check("read from the new one", wait_for(lambda: any(p.startswith("/src-new.ts") for p in seen), 15))
check("and the old one not again", len([p for p in seen if p.startswith("/src.ts")]) == before)
check("a discontinuity where it went on", wait_for(lambda: b"#EXT-X-DISCONTINUITY" in get(res["base"] + "/live.m3u8?open=2")[1], 20))

# too little space while it writes: the writer stops at once, the status says why
reads = len(seen)
free[0] = int(1.2 * dvr.GiB)
check("too little space: failed, saying so", wait_for(lambda: json.loads(get(res["base"] + "/status")[1] or b"{}").get("reason") == "space", 10))
check("its writer gone at once", w1.proc is None)
time.sleep(1)
check("nothing more read from the provider", len(seen) == reads)
free[0] = 500 * dvr.GiB

# a stop systemd didn't carry out: not ok, nothing deleted; then it is
running = dvr.buffer_running
dvr.buffer_running = lambda session: True
holding[0] = True
t0 = time.time()
held = dvr.buffer_stop(s1)
holding[0] = False
dvr.buffer_running = running
check("still running after the stop and a kill: not ok, saying so", held == {"ok": False, "error": "running"} and time.time() - t0 < 20, held)
check("and nothing deleted (it's still writing there)", os.path.exists(ctl) and os.path.exists(sdir))
check("the kill was asked for", any(len(a) > 3 and a[2] == "kill" and a[3] == "--signal=SIGKILL" for a in started))

# stop: gone before it answers, its folder and control file too
check("stopped", dvr.buffer_stop(s1).get("ok") and not t1.is_alive())
check("its folder deleted", not os.path.exists(sdir))
check("its control file (the address) deleted", not os.path.exists(ctl))

# the guide gone: no status for its lease, the session stops by itself
dvr.BUF_FIRST_LEASE, dvr.BUF_LEASE = 3, 2
res = dvr.buffer_start(startjob())
s2 = res["session"]
w2, t2 = workers[s2]
t2.join(15)
check("never asked for its status: it stops by itself", not t2.is_alive())
check("its folder and control file deleted", not os.path.exists(os.path.join(rec_root, dvr.BUF_DIR, s2))
      and not os.path.exists(os.path.join(os.path.dirname(ctl), s2 + ".json")))
dvr.BUF_FIRST_LEASE, dvr.BUF_LEASE = 60, 20

# the folder swapped under it (a drive replaced at the same path): writes follow the descriptor
res = dvr.buffer_start(startjob())
s3 = res["session"]
w3, t3 = workers[s3]
check("ready", wait_for(lambda: json.loads(get(res["base"] + "/status")[1] or b"{}").get("state") == "ready", 30))
d3 = os.path.join(rec_root, dvr.BUF_DIR, s3)
aside = d3 + "-aside"
os.rename(d3, aside)
os.mkdir(d3, 0o700)
n_aside = len(os.listdir(aside))
time.sleep(4)
check("new segments land where the descriptor points", len(os.listdir(aside)) > n_aside, (n_aside, len(os.listdir(aside))))
check("nothing in what's now at its path", os.listdir(d3) == [], os.listdir(d3))
dvr.buffer_stop(s3)
shutil.rmtree(aside, ignore_errors=True)

# sessions left behind: cleaned, nothing else touched
bdir = os.path.join(rec_root, dvr.BUF_DIR)
old = os.path.join(bdir, "0123456789abcdef")
os.makedirs(old)
open(os.path.join(old, "s000000001.ts"), "wb").close()
odd = os.path.join(bdir, "fedcba9876543210")
os.makedirs(odd)
open(os.path.join(odd, "s000000001.ts"), "wb").close()
open(os.path.join(odd, "yours.txt"), "wb").close()
dvr.buffer_running = lambda session: False
open(os.path.join(os.path.dirname(ctl), "aaaaaaaaaaaaaaaa.json"), "w").write("{}")
dvr.clean_buffers(rec_root)
check("a session left behind: its folder gone", not os.path.exists(old))
check("one with a file it didn't make: that file stays", os.path.exists(os.path.join(odd, "yours.txt"))
      and not os.path.exists(os.path.join(odd, "s000000001.ts")))
check("a control file whose writer isn't running: gone", not os.path.exists(os.path.join(os.path.dirname(ctl), "aaaaaaaaaaaaaaaa.json")))

# stop after the writer was killed: its folder and control file cleaned by stop
res = dvr.buffer_start(startjob())
s4 = res["session"]
w4, t4 = workers.pop(s4)
w4.stopping = True
t4.join(30)
dvr.write_control(s4, {"session": s4, "place": place})
os.makedirs(os.path.join(bdir, s4), exist_ok=True)
open(os.path.join(bdir, s4, "s000000003.ts"), "wb").close()
dvr.buffer_stop(s4)
check("stop cleans up after a writer that didn't", not os.path.exists(os.path.join(bdir, s4)) and not os.path.exists(os.path.join(os.path.dirname(ctl), s4 + ".json")))

up.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
if failures:
    print("%d failed" % failures)
    sys.exit(1)
print("dvrbuffer: all good")
