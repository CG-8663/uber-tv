#!/usr/bin/python3
"""The recorder (bin/om-pg-dvr, lib/dvrproxy.py): /usr/bin/python3 tests/dvr.test.py

File names cleaned (no slashes, control or FAT-unsafe characters, no
leading dot, capped, numbered on a clash). The mount table read, the
longest mount winning and the later of two at one place. A place refused
when it's relative, missing, hidden, Uber TV's or your settings' own, the
system's or in memory, or can't be written; a kept place found again only
on the same filesystem, mounted where it was, the folder really a folder
with its marker: an unplugged drive that leaves its empty folder behind,
another drive at the same place, a link instead of the folder, all "drive".
The relay: a master cut to one picture (the biggest up to the height, H.264
first) and its sound; every address in a playlist pointed back at it,
resolved against where the playlist came from; file:, data:, concat:,
unix: and the like dead; keys capped; only its own tokens under its secret;
a redirect away from the web refused; media streamed through. With real
ffmpeg, through the relay, a hostile playlist's local file never reaches
the recording and the upstream address never reaches ffmpeg's command
line. The state: one at a time under its lock, the most at once, back to
back on one channel joining one recording, a video saved once, stop, a new
stop time within the limits, removing a recording's files and nothing
else, and a worker that died settled from what's on disk. A recording made
end to end by the worker, stopped on request, its file and details in
place. Nothing goes to the network: every server is on 127.0.0.1."""

import contextlib
import hashlib
import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-dvr")
_loader = importlib.machinery.SourceFileLoader("om_pg_dvr", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_dvr", _loader)
dvr = importlib.util.module_from_spec(_spec)
_loader.exec_module(dvr)
relaymod = dvr.relay_module()

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


TMP = tempfile.mkdtemp(prefix="dvr-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
# the test's own folders live in /tmp: treat it as a disk here
dvr.TEMPORARY = ("/proc", "/sys", "/dev")
DISK = os.path.join(TMP, "disk")
os.makedirs(DISK)
TABLE = ("22 1 0:20 / / rw,relatime - btrfs /dev/mapper/root rw\n"
         "40 22 0:30 / %s rw,relatime - ext4 /dev/sdz1 rw\n" % DISK)
real_mounts = dvr.mounts
dvr.mounts = lambda text=None: real_mounts(TABLE if text is None else text)
dvr.volume_of = lambda m, by_uuid=None: "uuid:test-" + m["source"]

# ---- names ----
check("slashes, control and FAT-unsafe characters go", dvr.clean('a/b\\c:d*e?f"g<h>i|j\x01k') == "a b c d e f g h i j k")
check("no leading dot", dvr.clean("..hidden") == "hidden")
check("capped", len(dvr.clean("x" * 500)) <= 90)
taken = {"News – BBC – 2026-10-19 21.00.ts"}
name = dvr.file_name("News", "BBC", time.mktime((2026, 10, 19, 21, 0, 0, 0, 0, -1)), ".ts", lambda n: n in taken)
check("numbered on a clash", name == "News – BBC – 2026-10-19 21.00 (2).ts", name)
check("the title once when it's the channel", dvr.file_name("BBC", "BBC", 0, ".ts", lambda n: False).startswith("BBC – 19"))
check("a part file's name", dvr.part_name("a.ts") == "a.part.ts")
check("safe names only", not dvr.safe_name("../x") and not dvr.safe_name(".x") and dvr.safe_name("a b.ts"))

# ---- the mount table ----
mi = ("1 0 0:1 / / rw - btrfs /dev/root rw\n"
      "2 1 0:2 / /run/media/me/My\\040Drive rw,nosuid - vfat /dev/sdb1 rw\n"
      "3 1 0:3 / /tmp rw - tmpfs tmpfs rw\n"
      "4 1 0:4 / /mnt ro - ext4 /dev/sdc1 ro\n"
      "5 1 0:5 / /mnt rw - ext4 /dev/sdd1 rw\n")
t = real_mounts(mi)
check("escapes in mount points read", t[1]["mount"] == "/run/media/me/My Drive")
check("the longest mount wins", dvr.mount_of("/run/media/me/My Drive/x", t)["source"] == "/dev/sdb1")
check("the later of two at one place wins", dvr.mount_of("/mnt/x", t)["source"] == "/dev/sdd1")
check("a prefix that isn't a folder doesn't count", dvr.mount_of("/tmpfoo", t)["mount"] == "/")

# ---- the place check ----
home = os.path.join(TMP, "home")
os.makedirs(os.path.join(home, ".hidden"))
os.makedirs(os.path.join(home, ".config"))
own = [os.path.join(home, ".config")]
check("relative refused", dvr.check_place("Videos", home=home, own=own).get("error") == "relative")
check("missing refused", dvr.check_place(os.path.join(home, "nope"), home=home, own=own).get("error") == "missing")
check("hidden refused", dvr.check_place(os.path.join(home, ".hidden"), home=home, own=own).get("error") == "hidden")
os.makedirs(os.path.join(TMP, "conf"))
check("settings' own refused", dvr.check_place(os.path.join(TMP, "conf"), home=home, own=[os.path.join(TMP, "conf")]).get("error") == "own")
check("system refused", dvr.check_place("/etc", home=home, own=own).get("error") == "system")
check("/dev refused as temporary", dvr.check_place("/dev", home=home, own=own).get("error") == "temporary")
memory = "1 0 0:1 / / rw - tmpfs tmpfs rw\n"
check("a memory filesystem refused", dvr.check_place(DISK, table=real_mounts(memory), home=home, own=own).get("error") == "temporary")
readonly = "1 0 0:1 / / ro - ext4 /dev/sda1 ro\n"
check("read-only refused", dvr.check_place(DISK, table=real_mounts(readonly), home=home, own=own).get("error") == "readonly")
os.symlink(os.path.join(home, ".hidden"), os.path.join(home, "sneaky"))
check("a link into a hidden folder refused (its real path)", dvr.check_place(os.path.join(home, "sneaky"), home=home, own=own).get("error") == "hidden")
ok = dvr.check_place(DISK, home=home, own=own)
check("a disk accepted, with its filesystem", ok.get("volume") == "uuid:test-/dev/sdz1" and ok.get("mount") == DISK, ok)
check("another disk isn't the system disk", ok.get("system") is False, ok)
check("your home folder's disk is", dvr.check_place(home, home=home, own=own).get("system") is True)

# ---- prepare and verify ----
dvr.check_place = (lambda real: lambda folder, table=None, home=None, own=None: real(folder, table, home or TMP, own if own is not None else []))(dvr.check_place)
dvr.drive_facts = lambda m: ("TESTDRIVE", True)
p = dvr.prepare(DISK)
check("prepare makes the folder and its marker", p.get("ok") and os.path.isfile(os.path.join(DISK, dvr.ROOT_NAME, dvr.MARKER)), p)
place = p["place"]
check("the place is its filesystem and folder", place["volume"] == "uuid:test-/dev/sdz1" and place["rel"] == dvr.ROOT_NAME and place["label"] == "TESTDRIVE")
check("the folder is private", p.get("private") is True and oct(os.stat(os.path.join(DISK, dvr.ROOT_NAME)).st_mode & 0o777) == "0o700")
check("prepare again is fine", dvr.prepare(DISK).get("ok"))
root, problem = dvr.verify(place)
check("found again", root == os.path.join(DISK, dvr.ROOT_NAME) and problem == "", (root, problem))
unplugged = "22 1 0:20 / / rw - btrfs /dev/mapper/root rw\n"
check("unplugged, its empty folder left behind: drive", dvr.verify(place, real_mounts(unplugged)) == (None, "drive"))
other = "22 1 0:20 / / rw - btrfs /dev/mapper/root rw\n40 22 0:31 / %s rw - ext4 /dev/sdy1 rw\n" % DISK
check("another drive at the same place: drive", dvr.verify(place, real_mounts(other)) == (None, "drive"))
check("a place that climbs out: drive", dvr.verify(dict(place, rel="../../etc"))[1] == "drive")
check("a made-up place: drive", dvr.verify({"volume": 1})[1] == "drive")
os.makedirs(os.path.join(DISK, "elsewhere"))
os.rename(os.path.join(DISK, dvr.ROOT_NAME), os.path.join(DISK, "moved"))
os.symlink(os.path.join(DISK, "moved"), os.path.join(DISK, dvr.ROOT_NAME))
check("a link instead of the folder: drive", dvr.verify(place)[1] == "drive")
os.unlink(os.path.join(DISK, dvr.ROOT_NAME))
os.rename(os.path.join(DISK, "moved"), os.path.join(DISK, dvr.ROOT_NAME))
os.unlink(os.path.join(DISK, dvr.ROOT_NAME, dvr.MARKER))
check("no marker: drive", dvr.verify(place)[1] == "drive")
dvr.prepare(DISK)
check("the marker back: found", dvr.verify(place)[1] == "")


# ---- the relay ----
class Upstream(http.server.ThreadingHTTPServer):
    daemon_threads = True


routes = {}
seen_paths = []


class UpHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        seen_paths.append(self.path)
        r = routes.get(self.path.split("?")[0])
        if r is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if callable(r):
            return r(self)
        code, ctype, body, extra = r if len(r) == 4 else r + ({},)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


up = Upstream(("127.0.0.1", 0), UpHandler)
threading.Thread(target=up.serve_forever, daemon=True).start()
UP = "http://127.0.0.1:%d" % up.server_address[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


master = "\n".join([
    "#EXTM3U",
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="en",DEFAULT=YES,URI="audio/en.m3u8"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="other",NAME="x",URI="audio/x.m3u8"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="en",URI="subs.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2",AUDIO="aud"', "v360.m3u8",
    '#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080,CODECS="hvc1.1,mp4a.40.2",AUDIO="aud",SUBTITLES="subs"', "v1080hevc.m3u8",
    '#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="aud",SUBTITLES="subs"', "v1080.m3u8",
    '#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=3840x2160,CODECS="avc1.640033,mp4a.40.2",AUDIO="aud"', "v2160.m3u8", ""])
routes["/live/master.m3u8"] = (200, "application/vnd.apple.mpegurl", master.encode())
relay = relaymod.Relay(UP + "/live/master.m3u8", 1080).start()
code, body = get(relay.url)
text = body.decode()
lines = [l for l in text.splitlines() if l]
infs = [l for l in lines if l.startswith("#EXT-X-STREAM-INF")]
check("a master cut to one picture", len(infs) == 1, text)
check("the biggest up to 1080, H.264 first", "avc1.640028" in infs[0] and "SUBTITLES" not in infs[0], infs)
check("its sound kept, the other group and subtitles gone", any('GROUP-ID="aud"' in l for l in lines)
      and not any('GROUP-ID="other"' in l for l in lines) and not any("SUBTITLES" in l and "TYPE=" in l for l in lines), text)
check("no upstream address left in it", "127.0.0.1:%d" % up.server_address[1] not in text and "v1080.m3u8" not in text, text)
check("every address points back at the relay", all(("http://127.0.0.1:%d/%s/" % (relay.port, relay.secret)) in l
                                                   for l in lines if not l.startswith("#") or 'URI="' in l))
relay.stop()
hevc = "\n".join([
    "#EXTM3U",
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="English",LANGUAGE="en",DEFAULT=YES,URI="en.m3u8"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Spanish",LANGUAGE="es",URI="es.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2",AUDIO="a"', "v720.m3u8",
    '#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080,CODECS="hvc1.1.6.L120,mp4a.40.2",AUDIO="a"', "v1080hevc.m3u8", ""])
routes["/live/hevc.m3u8"] = (200, "application/vnd.apple.mpegurl", hevc.encode())
r3 = relaymod.Relay(UP + "/live/hevc.m3u8", 1080).start()
code, body = get(r3.url)
text = body.decode()
check("720p H.264 beats 1080p HEVC (H.264 first, as the streamer picks)", "RESOLUTION=1280x720" in text and "hvc1" not in text, text)
check("one sound: the default of the group", text.count("TYPE=AUDIO") == 1 and 'NAME="English"' in text, text)
r3.stop()
small = relaymod.Relay(UP + "/live/master.m3u8", 480).start()
code, body = get(small.url)
check("nothing small enough: the smallest", "640x360" in body.decode(), body)
small.stop()

secret_file = os.path.join(TMP, "secret.ts")
with open(secret_file, "wb") as f:
    f.write(b"SECRETMARKER" * 100)
media = "\n".join([
    "#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2",
    '#EXT-X-KEY:METHOD=AES-128,URI="file:///etc/passwd"',
    '#EXT-X-KEY:METHOD=AES-128,URI="keys/k1.key"',
    "#EXTINF:1,", "seg1.ts",
    "#EXTINF:1,", UP + "/elsewhere/seg2.ts",
    "#EXTINF:1,", "//127.0.0.1:%d/proto/seg3.ts" % up.server_address[1],
    "#EXTINF:1,", "file://" + secret_file,
    "#EXTINF:1,", "data:video/mp2t;base64,AAAA",
    "#EXTINF:1,", "concat:" + secret_file + "|" + secret_file,
    "#EXTINF:1,", "unix:/run/user/1000/bus",
    "#EXTINF:1,", "subfile,,start,0,end,0,,:" + secret_file,
    "#EXTINF:1,", "seg.php?token=abc", ""])
routes["/live/media.m3u8"] = (200, "application/x-mpegURL", media.encode())
routes["/live/keys/k1.key"] = (200, "application/octet-stream", b"0123456789abcdef")
routes["/live/big.key"] = (200, "application/octet-stream", b"k" * (relaymod.KEY_MAX + 10))
relay = relaymod.Relay(UP + "/live/media.m3u8").start()
code, body = get(relay.url)
out = [l for l in body.decode().splitlines() if l]
uris = [l for l in out if not l.startswith("#")]
keys = [l for l in out if l.startswith("#EXT-X-KEY")]
dead = relay.address(relay.dead)
check("file: key dead", dead in keys[0], keys)
check("a relative key relayed", relay.address("") in keys[1] and dead not in keys[1], keys)
check("relative, absolute and scheme-relative segments relayed", all(u.startswith(relay.address("")) and u != dead for u in uris[:3]), uris)
check("file:, data:, concat:, unix: segments dead", uris[3:7] == [dead] * 4, uris)
check("subfile (no scheme) stays on the web (relative to the playlist)", uris[7] != dead, uris)
check("a .php segment is called .ts for ffmpeg", uris[8].endswith(".ts"), uris)
st, kb = get(keys[1].split('URI="')[1].split('"')[0])
check("a key comes through", st == 200 and kb == b"0123456789abcdef", st)
st, _ = get(dead)
check("a dead token is a 404", st == 404)
st, _ = get("http://127.0.0.1:%d/%s/%s" % (relay.port, "wrong" + relay.secret[5:], relay.root))
check("the secret guards every path", st == 404)
st, _ = get("http://127.0.0.1:%d/%s/%s" % (relay.port, relay.secret, "http%3A%2F%2Fexample.com%2Fx.ts"))
check("no address taken from the request", st == 404)
bigkey = relay.token_for(UP + "/live/big.key", "key")
st, _ = get(relay.address(bigkey))
check("a key over the cap refused", st == 502, st)
routes["/redir.m3u8"] = (302, "text/plain", b"", {"Location": "file:///etc/passwd"})
r2 = relaymod.Relay(UP + "/redir.m3u8").start()
st, _ = get(r2.url)
check("a redirect away from the web refused", st == 502, st)
r2.stop()
routes["/live/missing.ts"] = None
st, _ = get(relay.address(relay.token_for(UP + "/live/missing.ts", "media")))
check("an upstream 404 passes through", st == 404, st)
relay.stop()
try:
    relaymod.Relay("file:///etc/passwd")
    check("a channel that isn't on the web refused", False)
except ValueError:
    check("a channel that isn't on the web refused", True)

# ---- with real ffmpeg ----
FIX = os.path.join(TMP, "fix")
os.makedirs(FIX)
subprocess.run(["nice", "-n", "19", "/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4", "-c:v", "mpeg2video", "-c:a", "mp2",
                "-f", "hls", "-hls_time", "1", "-hls_list_size", "0", "-hls_segment_filename", os.path.join(FIX, "s%d.ts"),
                os.path.join(FIX, "good.m3u8")], check=True, timeout=120)
segs = sorted(n for n in os.listdir(FIX) if n.endswith(".ts"))
for n in segs:
    with open(os.path.join(FIX, n), "rb") as f:
        routes["/fix/" + n] = (200, "video/mp2t", f.read())
good = open(os.path.join(FIX, "good.m3u8")).read()
routes["/fix/good.m3u8"] = (200, "application/vnd.apple.mpegurl", good.encode())
hostile = good.replace("s1.ts", "file://" + secret_file).replace("s2.ts", "concat:" + secret_file + "|" + secret_file)
routes["/fix/hostile.m3u8"] = (200, "application/vnd.apple.mpegurl", hostile.encode())


def record_through(path, seconds=30):
    rl = relaymod.Relay(UP + path).start()
    argv = dvr.ffmpeg_argv(rl.url)
    out_path = os.path.join(TMP, "out-%d.ts" % len(seen_paths))
    with open(out_path, "wb") as fo:
        p = subprocess.run(["nice", "-n", "19"] + argv, stdout=fo, stderr=subprocess.PIPE, timeout=seconds)
    rl.stop()
    with open(out_path, "rb") as f:
        return argv, f.read(), p


argv, data, p = record_through("/fix/good.m3u8")
check("recorded through the relay", len(data) > 10000, (len(data), p.stderr[-300:]))
check("ffmpeg may follow http and https only", argv[argv.index("-protocol_whitelist") + 1] == "http,https,tcp,tls,crypto")
check("ffmpeg copies one picture and one sound", argv[argv.index("-map") + 1] == "0:v:0?" and argv[argv.index("-map", argv.index("-map") + 1) + 1] == "0:a:0?", argv)
check("the upstream address isn't on ffmpeg's command line", not any(UP in a or "/fix/" in a for a in argv), argv)
argv, data, p = record_through("/fix/hostile.m3u8")
check("a hostile playlist's local file never reaches the recording", b"SECRETMARKER" not in data, len(data))
check("its good segments still recorded", len(data) > 5000, len(data))

# ---- the state ----
started = []
dvr.SYSTEMD_RUN = "/usr/bin/true"
dvr.SYSTEMCTL = "/usr/bin/true"
real_run = subprocess.run


def fake_run(argv, *a, **kw):
    if argv and argv[0] == "/usr/bin/true":
        started.append(argv)
    return real_run(argv, *a, **kw)


dvr.subprocess.run = fake_run
H1, H2, H3 = "a" * 64, "b" * 64, "c" * 64
now = int(time.time())


def job(**kw):
    j = {"kind": "iptv", "url": UP + "/fix/good.m3u8", "channel": {"name": "Test One", "number": 101, "hash": H1},
         "title": "The News", "end": now + 600, "place": place, "keepFree": dvr.GiB, "quality": 1080}
    j.update(kw)
    return j


dvr.free_of = lambda path: 500 * dvr.GiB
r1 = dvr.start(job())
check("a recording starts", r1.get("ok") and dvr.ID_RE.match(r1.get("id", "")), r1)
check("as its own systemd service, by its id only", started and ("--unit=uber-tv-rec-" + r1["id"]) in started[-1]
      and started[-1][-1] == r1["id"] and not any(UP in a for a in started[-1]), started[-1:])
st = dvr.load()["recordings"][r1["id"]]
check("starting until the worker says it's recording", st["state"] == "starting")
check("its stream's address is kept privately while it runs", st["source"]["url"].startswith(UP)
      and oct(os.stat(os.path.join(dvr.state_dir(), "state.json")).st_mode & 0o777) == "0o600")
j2 = dvr.start(job(title="The Weather", end=now + 1200))
check("back to back on one channel: the same recording, its stop later", j2.get("joined") and j2["id"] == r1["id"] and j2["end"] == now + 1200, j2)
check("the card names both shows", dvr.load()["recordings"][r1["id"]]["titles"] == ["The News", "The Weather"])
r2 = dvr.start(job(channel={"name": "Two", "number": 102, "hash": H2}))
check("a second recording", r2.get("ok") and r2["id"] != r1["id"])
r3 = dvr.start(job(channel={"name": "Three", "number": 103, "hash": H3}, title="Late"))
check("a third: refused, naming the two", r3.get("error") == "cap" and len(r3.get("recording", [])) == 2, r3)
listed = dvr.listing()
check("the list never has a stream's address", UP not in json.dumps(listed), listed)
check("refused: a bad job", dvr.start({"kind": "iptv", "url": "file:///etc/passwd", "end": now + 60})["error"] == "job")
check("refused: a stop more than 12 hours away", dvr.start(job(end=now + 13 * 3600))["error"] == "job")
check("a new stop time within the limits", dvr.until(r1["id"], now + 3600).get("end") == now + 3600)
check("not past 12 hours from its start", dvr.until(r1["id"], now + 13 * 3600).get("error") == "time")
check("stop asks the worker to stop", dvr.stop(r1["id"]).get("ok") and dvr.load()["recordings"][r1["id"]].get("stop") is True)
check("unknown ids", dvr.stop("0" * 16).get("error") == "unknown")

# a worker that died: settled from what's on disk
rec_root = os.path.join(DISK, dvr.ROOT_NAME)
s = dvr.load()
r = s["recordings"][r2["id"]]
with open(os.path.join(rec_root, dvr.part_name(r["file"])), "wb") as f:
    f.write(b"\x47" * 188 * 10)
r["beat"] = now - 600
dvr.save(s)
dvr.unit_active = lambda rid: False
listed = {x["id"]: x for x in dvr.listing()["recordings"]}
check("a dead worker's recording: incomplete, its file in place", listed[r2["id"]]["state"] == "incomplete"
      and os.path.isfile(os.path.join(rec_root, r["file"])) and listed[r2["id"]]["path"].endswith(r["file"]), listed[r2["id"]])
check("its stream's address forgotten", "source" not in dvr.load()["recordings"][r2["id"]])
with open(os.path.join(rec_root, "keep me.ts"), "wb") as f:
    f.write(b"x")
rm = dvr.remove(r2["id"])
check("remove deletes its file", rm.get("ok") and not os.path.exists(os.path.join(rec_root, r["file"])), rm)
check("and nothing else", os.path.exists(os.path.join(rec_root, "keep me.ts")))
s = dvr.load()
s["recordings"][r1["id"]]["state"] = "done"
s["recordings"][r1["id"]]["file"] = "gone.ts"
dvr.save(s)
dvr.verify = (lambda real: lambda pl, table=None: (None, "drive") if (pl or {}).get("volume") == "uuid:unplugged" else real(pl, table))(dvr.verify)
s = dvr.load()
s["recordings"][r1["id"]]["place"] = dict(place, volume="uuid:unplugged")
dvr.save(s)
listed = {x["id"]: x for x in dvr.listing()["recordings"]}
check("a recording on a missing drive: listed, not present", listed[r1["id"]]["present"] is False and listed[r1["id"]]["path"] == "")
check("removing it then forgets it (its file stays on the drive)", dvr.remove(r1["id"]).get("forgotten") is True)
v1 = dvr.start({"kind": "youtube-video", "video": "abcdefghijk", "channel": {"name": "Kurz", "hash": H3}, "title": "A video",
                "place": place, "keepFree": dvr.GiB})
v2 = dvr.start({"kind": "youtube-video", "video": "abcdefghijk", "channel": {"name": "Kurz", "hash": H3}, "title": "A video",
                "place": place, "keepFree": dvr.GiB})
check("a video saved once", v1.get("ok") and v2.get("already") and v2["id"] == v1["id"], (v1, v2))
dvr.free_of = lambda path: 2 * dvr.GiB
check("not enough free space: refused", dvr.start(job(channel={"name": "X", "hash": "d" * 64}, keepFree=5 * dvr.GiB)).get("error") == "space")
dvr.free_of = lambda path: 500 * dvr.GiB
for rid in list(dvr.load()["recordings"]):
    dvr.remove(rid)

# ---- scheduled: later shows, series, conflicts, claimed when due, missed ----
heard = []
real_say_note, real_unit_active = dvr.say_note, dvr.unit_active
dvr.say_note = lambda summary, body: heard.append((summary, body))
dvr.unit_active = lambda rid: True   # (the clock goes forward here: a recording's service is still running)
S1, S2, S3, S4 = "1" * 64, "2" * 64, "3" * 64, "4" * 64
T = now + 3600


def slot(**kw):
    s = {"kind": "iptv", "channel": {"name": "One", "number": 101, "hash": S1}, "title": "Bake Off", "sub": "", "ep": "",
         "showStart": T, "showEnd": T + 1800, "early": 60, "late": 120, "provider": "src:abcdefabcdef"}
    s.update(kw)
    return s


def scheduled(*slots, at=None):
    return dvr.schedule({"slots": list(slots)}, at)["slots"]


a = scheduled(slot())[0]
st = dvr.load()["recordings"].get(a.get("id", ""), {})
check("a later show: Scheduled, its window padded", a.get("state") == "scheduled" and st.get("start") == T - 60 and st.get("end") == T + 1800 + 120, (a, st))
check("no stream address kept with a schedule", "source" not in st and "url" not in json.dumps(st), st)
check("the same show again: not twice", scheduled(slot())[0].get("already") is True)
check("refused: not IPTV, no channel, gone by, more than 8 days ahead", [x.get("error") for x in scheduled(
    slot(kind="youtube-live"), slot(channel={"name": "X"}), slot(showStart=now - 7200, showEnd=now - 3600),
    slot(showStart=now + 9 * 86400, showEnd=now + 9 * 86400 + 1800))] == ["job"] * 4)
b = scheduled(slot(channel={"name": "Two", "number": 102, "hash": S2}, title="Quiz"))[0]
same = scheduled(slot(title="Bake Off Extra", showStart=T + 1800, showEnd=T + 3600))[0]
check("a second channel at the same time: Scheduled", b.get("state") == "scheduled", b)
check("back to back on one channel (the paddings overlapping): one stream, Scheduled", same.get("state") == "scheduled", same)
c = scheduled(slot(channel={"name": "Three", "number": 103, "hash": S3}, title="Film"))[0]
check("a third at once: a Conflict, the two by their ids", c.get("state") == "conflict" and sorted(c.get("others", [])) == sorted([a["id"], b["id"]]), c)
check("never their names in the state (a channel locked later would still be named)",
      "Quiz" not in json.dumps(dvr.load()["recordings"][c["id"]]) and "Bake Off" not in json.dumps(dvr.load()["recordings"][c["id"]].get("others")))
priv = scheduled(slot(channel={"name": "Four", "number": 104, "hash": S4}, title="Secret", private=True))[0]
check("a locked channel's names stay out of a conflict's", priv.get("state") == "conflict")
dvr.cancel(priv["id"])
check("cancel: gone", priv["id"] not in dvr.load()["recordings"])
dvr.cancel(b["id"])
check("one of the two cancelled: the conflict is Scheduled again", dvr.load()["recordings"][c["id"]]["state"] == "scheduled")
# how many at once: the user's setting (2 unless they say)
check("the limit: 1 to 4 only", dvr.limit(5).get("error") == "job" and dvr.limit(0).get("error") == "job")
b2 = scheduled(slot(channel={"name": "Two", "number": 102, "hash": S2}, title="Quiz again"))[0]
check("back to two others: the third is a Conflict", dvr.load()["recordings"][c["id"]]["state"] == "conflict" or b2.get("state") == "conflict")
check("three at once allowed: Scheduled", dvr.limit(3).get("atOnce") == 3 and all(dvr.load()["recordings"][x]["state"] == "scheduled" for x in (c["id"], b2["id"])))
dvr.limit(1)
st = dvr.load()["recordings"]
check("one at once: only the first scheduled keeps its place", st[a["id"]]["state"] == "scheduled" and st[same["id"]]["state"] == "scheduled"
      and st[b2["id"]]["state"] == "conflict" and st[c["id"]]["state"] == "conflict", {k: st[k]["state"] for k in (a["id"], same["id"], b2["id"], c["id"])})
dvr.limit(2)
dvr.cancel(b2["id"])
check("back to two, one cancelled: Scheduled again", dvr.load()["recordings"][c["id"]]["state"] == "scheduled")

# claimed when due
started.clear()
due = {"slot": a["id"], "url": UP + "/fix/good.m3u8", "place": place, "keepFree": dvr.GiB, "quality": 1080}
check("too early: not started", dvr.start(due, T - 600).get("error") == "early")
cl = dvr.start(due, T - 30)
st = dvr.load()["recordings"][a["id"]]
check("due: claimed, started as its own service by its id", cl.get("ok") and cl["id"] == a["id"] and st["state"] == "starting"
      and started and ("--unit=uber-tv-rec-" + a["id"]) in started[-1], (cl, started[-1:]))
check("its address kept only now, while it runs; its title the schedule's", st["source"]["url"].startswith(UP) and st["title"] == "Bake Off")
check("claimed once: asked again, not started twice", dvr.start(due, T - 20).get("error") == "notScheduled" and len(started) == 1)
j = dvr.start(dict(due, slot=same["id"]), T + 1790)
check("the next show on that channel joins it: one recording, its stop later, both named",
      j.get("joined") and j["id"] == a["id"] and same["id"] not in dvr.load()["recordings"]
      and dvr.load()["recordings"][a["id"]]["titles"] == ["Bake Off", "Bake Off Extra"] and dvr.load()["recordings"][a["id"]]["end"] == T + 3600 + 120, j)
dvr.limit(1)
check("one at once: a second recording now is refused", dvr.start(job(channel={"name": "Two", "number": 102, "hash": S2}, title="Now", end=T + 600), T).get("error") == "cap")
dvr.limit(2)
r2 = dvr.start(job(channel={"name": "Two", "number": 102, "hash": S2}, title="Now", end=T + 600), T)
heard.clear()
cap = dvr.start(dict(due, slot=c["id"], url=UP + "/fix/good.m3u8?three"), T)
check("due with two recording: a Conflict, not started, said", cap.get("error") == "cap" and dvr.load()["recordings"][c["id"]]["state"] == "conflict"
      and heard and heard[-1] == ("Recording didn't start", "Too many recordings at this time.") and "Film" not in json.dumps(heard), (cap, heard))
dvr.limit(1)
check("lowering it doesn't stop one that's recording", all(dvr.load()["recordings"][x]["state"] == "starting" for x in (a["id"], r2["id"])))
dvr.limit(2)
dvr.remove(r2["id"])
# one stream, whatever its address is called: a schedule made under the old hash joins by the address supplied now
rot = scheduled(slot(channel={"name": "One", "number": 101, "hash": "8" * 64}, title="Rotated", showStart=T + 3500, showEnd=T + 4100))[0]
jr = dvr.start(dict(due, slot=rot["id"]), T + 3450)
check("its address turned since: still one stream (joined, by the address now)", jr.get("joined") and jr["id"] == a["id"], jr)
# its address turned: the recording under the old one and the next show under the new one are one stream (by provider and name)
dvr.limit(1)
s = dvr.load()
s["recordings"][a["id"]]["provider"] = "src:abcdefabcdef"
dvr.save(s)
nx = scheduled(slot(channel={"name": "One", "number": 101, "hash": "d" * 63 + "e"}, title="Next under the new address", showStart=T + 3600, showEnd=T + 4800))[0]
check("one at once: the next show under the channel's new address isn't a conflict with itself", nx.get("state") == "scheduled", nx)
ox = scheduled(slot(channel={"name": "One", "number": 101, "hash": "e" * 63 + "d"}, title="Another provider's One", provider="src:000000000000",
                    showStart=T + 3600, showEnd=T + 4800))[0]
check("another provider's channel of that name is another stream", ox.get("state") == "conflict", ox)
jn = dvr.start(dict(due, slot=nx["id"], url=UP + "/fix/good.m3u8?new-address"), T + 3540)
check("one at once, due under the new address: joined to the one running (not refused as another stream)", jn.get("joined") and jn["id"] == a["id"], jn)
dvr.remove(ox["id"])
dvr.limit(2)
# a video save is a stream of its own, even from one channel
s = dvr.load()
s["recordings"][a["id"]]["state"] = "done"
dvr.save(s)
sv = [dvr.start({"kind": "youtube-video", "video": v, "channel": {"name": "Kurz", "hash": "9" * 64}, "title": v, "place": place, "keepFree": dvr.GiB}, T)
      for v in ("aaaaaaaaaa1", "aaaaaaaaaa2")]
check("two videos from one channel: both saving", all(x.get("ok") for x in sv), sv)
vs = scheduled(slot(channel={"name": "Ten", "number": 110, "hash": "0" * 64}, title="Beside two saves", showStart=now + 900, showEnd=now + 1500))[0]
check("two videos saving from one channel are two streams: a show beside them is a Conflict", vs.get("state") == "conflict", vs)
dvr.limit(3)
check("three at once: it fits", dvr.load()["recordings"][vs["id"]]["state"] == "scheduled")
dvr.limit(2)
for x in sv + [vs]:
    dvr.remove(x["id"])
g = scheduled(slot(channel={"name": "Five", "number": 105, "hash": "5" * 64}, title="Gone", showStart=T + 7200, showEnd=T + 9000))[0]
heard.clear()
dvr.start({"slot": g["id"], "gone": True}, T + 7200)
check("its channel gone from the list: Failed, saying why, not naming it", dvr.load()["recordings"][g["id"]]["state"] == "failed"
      and dvr.load()["recordings"][g["id"]]["reason"] == "gone" and heard and "isn't in your list" in heard[-1][1] and "Gone" not in json.dumps(heard), heard)
m = scheduled(slot(channel={"name": "Six", "number": 106, "hash": "6" * 64}, title="Missed one", showStart=now - 600, showEnd=now - 300), at=now - 900)[0]
heard.clear()
listed = {x["id"]: x for x in dvr.listing()["recordings"]}
check("never started by the time it was over: Missed, said, not named", listed[m["id"]]["state"] == "missed" and listed[m["id"]]["reason"] == "notRunning"
      and heard and heard[-1][0] == "Recording missed" and "Missed one" not in json.dumps(heard), (listed[m["id"]], heard))
check("the list has the schedule's show and window, and never an address", listed[c["id"]]["show"]["start"] == T and listed[c["id"]]["start"] == T - 60
      and UP not in json.dumps(dvr.listing()), listed[c["id"]])

# a series
ru = dvr.series_add({"channel": {"name": "Seven", "number": 107, "hash": "7" * 64}, "title": "Bake  Off", "provider": "src:abcdefabcdef"})
check("Record every episode: a rule", ru.get("ok") and dvr.ID_RE.match(ru.get("id", "")), ru)
check("the same channel and title (spacing and case aside): the same rule",
      dvr.series_add({"channel": {"name": "Seven", "hash": "7" * 64}, "title": "bake off"}).get("id") == ru["id"])
ep = lambda **kw: slot(channel={"name": "Seven", "number": 107, "hash": "7" * 64}, rule=ru["id"], **kw)
e1, e1again, e2 = scheduled(ep(ep="S2E5", showStart=T + 86400, showEnd=T + 88200), ep(ep="S2E5", showStart=T + 2 * 86400, showEnd=T + 2 * 86400 + 1800),
                            ep(sub="Bread Week", showStart=T + 3 * 86400, showEnd=T + 3 * 86400 + 1800))
check("its episodes scheduled; a rerun of one already scheduled isn't", e1.get("state") == "scheduled" and e1again.get("already") and e2.get("state") == "scheduled", (e1, e1again, e2))
dvr.cancel(e2["id"])
check("an episode cancelled isn't scheduled again", scheduled(ep(sub="bread week", showStart=T + 4 * 86400, showEnd=T + 4 * 86400 + 1800))[0].get("skipped") is True)
check("the list has the rule, not its skipped episodes", [x["title"] for x in dvr.listing()["rules"]] == ["Bake  Off"] and "skip" not in json.dumps(dvr.listing()["rules"]))
s = dvr.load()
s["recordings"][e1["id"]]["state"] = "done"
dvr.save(s)
e3 = scheduled(ep(ep="S2E6", showStart=T + 5 * 86400, showEnd=T + 5 * 86400 + 1800))[0]
# an episode recorded now, as one of the series': its rerun isn't recorded again
now_ep = dvr.start(job(channel={"name": "Seven", "number": 107, "hash": "7" * 64}, title="Bake Off", end=T + 1200, ep="S2E8", rule=ru["id"],
                       show={"start": T - 60, "end": T + 1080}), T)
check("recorded now with its episode and series", dvr.load()["recordings"][now_ep["id"]].get("rule") == ru["id"]
      and dvr.load()["recordings"][now_ep["id"]].get("ids") == ["ep:bake off|s2e8"], dvr.load()["recordings"][now_ep["id"]])
check("its rerun: already", scheduled(ep(ep="S2E8", showStart=T + 7 * 86400, showEnd=T + 7 * 86400 + 1800))[0].get("already") is True)
b2b = scheduled(ep(ep="S2E9", showStart=T + 1080, showEnd=T + 2880))[0]
jb = dvr.start(dict(due, slot=b2b["id"]), T + 1020)
check("the next episode joins it, its identity kept", jb.get("joined") and "ep:bake off|s2e9" in dvr.load()["recordings"][now_ep["id"]]["ids"], dvr.load()["recordings"][now_ep["id"]])
check("so its rerun isn't recorded either", scheduled(ep(ep="S2E9", showStart=T + 2 * 86400 + 7200, showEnd=T + 2 * 86400 + 9000))[0].get("already") is True)
# the channel's address turned: the same series, brought up to date, its episodes still known
same_rule = dvr.series_add({"channel": {"name": "Seven", "number": 107, "hash": "a" * 63 + "b"}, "title": "Bake Off", "provider": "src:abcdefabcdef"})
check("its address turned: the same series, its channel brought up to date", same_rule.get("id") == ru["id"] and dvr.load()["rules"][ru["id"]]["channel"]["hash"] == "a" * 63 + "b", same_rule)
check("an episode it recorded under the old address: already", scheduled(slot(channel={"name": "Seven", "number": 107, "hash": "a" * 63 + "b"}, rule=ru["id"], ep="S2E8",
                                                                              showStart=T + 2 * 86400 + 14400, showEnd=T + 2 * 86400 + 16200))[0].get("already") is True)
# every show a 12-hour recording can hold, and every series they're of
other = dvr.series_add({"channel": {"name": "Seven", "number": 107, "hash": "a" * 63 + "b"}, "title": "Quiz Night", "provider": "src:abcdefabcdef"})
s = dvr.load()
held = s["recordings"][now_ep["id"]]
for n in range(10, 24):
    dvr.merge_shows(held, {"title": "Bake Off", "ep": "S2E%d" % n, "rule": ru["id"]})
dvr.merge_shows(held, {"title": "Quiz Night", "ep": "S1E1", "rule": other["id"]})
dvr.save(s)
check("16 episodes and two series joined: none forgotten", len(dvr.load()["recordings"][now_ep["id"]]["ids"]) == 17
      and set(dvr.load()["recordings"][now_ep["id"]]["rules"]) == {ru["id"], other["id"]}, dvr.load()["recordings"][now_ep["id"]].get("rules"))
check("the 14th of them: already", scheduled(slot(channel={"name": "Seven", "number": 107, "hash": "a" * 63 + "b"}, rule=ru["id"], ep="S2E23",
                                                   showStart=T + 3 * 86400 + 600, showEnd=T + 3 * 86400 + 2400))[0].get("already") is True)
check("the second series' episode, under the channel's new address: already", scheduled(slot(channel={"name": "Seven", "number": 107, "hash": "a" * 63 + "b"},
      title="Quiz Night", rule=other["id"], ep="S1E1", showStart=T + 3 * 86400 + 4000, showEnd=T + 3 * 86400 + 5800))[0].get("already") is True)
check("another show's S2E10 on that channel isn't one of them", scheduled(slot(channel={"name": "Seven", "number": 107, "hash": "a" * 63 + "b"},
      title="Other Show", ep="S2E10", showStart=T + 3 * 86400 + 9000, showEnd=T + 3 * 86400 + 10800))[0].get("state") == "scheduled")
before_end = dvr.load()["recordings"][now_ep["id"]]["end"]
tg = dvr.tag({"id": now_ep["id"], "rule": other["id"], "title": "Quiz Night", "ep": "S1E9", "late": 120, "show": {"start": before_end - 60, "end": before_end + 1800}})
r_tg = dvr.load()["recordings"][now_ep["id"]]
check("Record every episode on a show recording already: joined to it, its stop moved to that show's end", tg.get("ok") and r_tg["end"] == before_end + 1800 + 120
      and "Quiz Night" in r_tg["titles"] and "ep:quiz night|s1e9" in r_tg["ids"] and other["id"] in r_tg["rules"], (tg, r_tg.get("end"), before_end))
check("tag: refused for an unknown recording or series, or a show under 5 minutes",
      dvr.tag({"id": "0" * 16, "show": {"start": T, "end": T + 600}}).get("error") == "unknown"
      and dvr.tag({"id": now_ep["id"], "rule": "1" * 16, "show": {"start": T, "end": T + 600}}).get("error") == "rule"
      and dvr.tag({"id": now_ep["id"], "show": {"start": T, "end": T + 200}}).get("error") == "job")
past = dvr.tag({"id": now_ep["id"], "show": {"start": T + 12 * 3600, "end": T + 13 * 3600}})
check("tag: one past its 12 hours goes to a continuation from its end", past.get("ok") and past.get("continued")
      and dvr.load()["recordings"][past["continued"]]["after"] == now_ep["id"], past)
dvr.remove(past["continued"])
s = dvr.load()
held = s["recordings"][now_ep["id"]]
for n in range(30):
    dvr.merge_shows(held, {"title": "Short %d" % n, "ep": "S1E1", "rule": "%016x" % (n + 1)})
dvr.save(s)
check("30 series in one recording: none forgotten", len(dvr.rules_of(dvr.load()["recordings"][now_ep["id"]])) >= 32)
check("a show under 5 minutes isn't scheduled", scheduled(slot(title="Short", showStart=T + 86400, showEnd=T + 86400 + 240))[0].get("error") == "job")
dvr.series_remove(other["id"])
check("another provider's channel of that name: another series", dvr.series_add({"channel": {"name": "Seven", "hash": "c" * 63 + "d"}, "title": "Bake Off",
                                                                                   "provider": "src:000000000000"}).get("id") != ru["id"])
dvr.stop(now_ep["id"])
s = dvr.load()
s["recordings"][now_ep["id"]]["state"] = "done"
dvr.save(s)
gone = dvr.series_remove(ru["id"])
s = dvr.load()
check("stopping the series: its rule and its shows not started go, what it recorded stays",
      gone.get("cancelled") == 1 and ru["id"] not in s["rules"] and e3["id"] not in s["recordings"] and e1["id"] in s["recordings"], gone)
check("a show of a stopped series isn't scheduled", scheduled(ep(ep="S2E7", showStart=T + 6 * 86400, showEnd=T + 6 * 86400 + 1800))[0].get("error") == "rule")
# past a recording's 12 hours: a continuation from its end, the show its own
near = dvr.start(job(channel={"name": "Marathon", "number": 120, "hash": "5" * 63 + "6"}, title="Hour 12", provider="src:abcdefabcdef",
                     end=T + 600), T - 12 * 3600 + 600)
latest = T + 600
cs = scheduled(slot(channel={"name": "Marathon", "number": 120, "hash": "5" * 63 + "6"}, title="Crossing", showStart=T + 500, showEnd=T + 2000))[0]
cl1 = dvr.start(dict(due, slot=cs["id"], url=UP + "/fix/good.m3u8?marathon"), T + 450)
st = dvr.load()["recordings"]
check("a show past the running one's 12 hours: not joined to it, a continuation from its end", cl1.get("error") == "early" and cl1.get("after") == near["id"]
      and st[cs["id"]]["start"] == latest and st[cs["id"]]["after"] == near["id"] and st[near["id"]].get("then") == cs["id"]
      and "Crossing" not in st[near["id"]].get("titles", []), (cl1, st[cs["id"]].get("start"), latest))
check("and the running one told the address now (its continuation starts from it)", st[near["id"]].get("handoff", {}).get("url", "").endswith("?marathon"), st[near["id"]].get("handoff"))
check("not before that recording has ended", dvr.start(dict(due, slot=cs["id"], url=UP + "/fix/good.m3u8?marathon"), T + 590).get("error") == "early")
s = dvr.load()
s["recordings"][near["id"]]["state"] = "done"
dvr.save(s)
cl2 = dvr.start(dict(due, slot=cs["id"], url=UP + "/fix/good.m3u8?marathon"), T + 605)
check("then it starts as its own recording", cl2.get("ok") and cl2["id"] == cs["id"] and not cl2.get("joined") and dvr.load()["recordings"][cs["id"]]["state"] == "starting", cl2)
dvr.remove(cs["id"])
near2 = dvr.start(job(channel={"name": "Marathon two", "number": 121, "hash": "6" * 63 + "5"}, title="Hour 12", end=T + 600), T - 12 * 3600 + 600)
tc = dvr.tag({"id": near2["id"], "rule": "", "title": "Crossing too", "ep": "S1E1", "late": 120, "show": {"start": T + 500, "end": T + 2000}}, T)
st = dvr.load()["recordings"]
cont = st.get(tc.get("continued") or "", {})
check("Record every episode past its 12 hours: it records to its end, a continuation holds the show", tc.get("ok") and st[near2["id"]]["end"] == T + 600
      and cont.get("state") == "scheduled" and cont.get("start") == T + 600 and cont.get("after") == near2["id"]
      and "ep:crossing too|s1e1" in cont.get("ids", []) and "ep:crossing too|s1e1" not in st[near2["id"]].get("ids", []), (tc, cont))
for x in (near["id"], near2["id"], tc.get("continued")):
    if x:
        dvr.remove(x)
# a recording started by hand joins the one running on that channel under its old address
by_hand_a = dvr.start(job(channel={"name": "Hand", "number": 130, "hash": "7" * 63 + "8"}, title="First", provider="src:abcdefabcdef", end=T + 900), T)
by_hand_b = dvr.start(job(channel={"name": "Hand", "number": 130, "hash": "8" * 63 + "7"}, title="Second", provider="src:abcdefabcdef", end=T + 1800), T + 60)
check("by hand, the channel's address turned: joined, not a second stream", by_hand_b.get("joined") and by_hand_b["id"] == by_hand_a["id"], by_hand_b)
dvr.remove(by_hand_a["id"])

# the 12 hours run from when a recording began, not from when it was scheduled
dvr.limit(4)
far = scheduled(slot(channel={"name": "Far", "number": 140, "hash": "9" * 63 + "a"}, title="Far ahead", showStart=T + 2 * 86400, showEnd=T + 2 * 86400 + 1800), at=T)[0]
air = T + 2 * 86400
cf = dvr.start(dict(due, slot=far["id"], url=UP + "/fix/good.m3u8?far"), air - 30)
tf = dvr.tag({"id": far["id"], "title": "After it", "ep": "S1E2", "late": 120, "show": {"start": air + 1800, "end": air + 5400}}, air)
r = dvr.load()["recordings"][far["id"]]
check("scheduled two days ahead, started at its time, tagged an hour on: the same recording, its stop later",
      cf.get("ok") and tf.get("ok") and not tf.get("continued") and r["end"] == air + 5400 + 120 and r["state"] == "starting", (cf, tf, r.get("end")))
check("its 12 hours run from when it began", dvr.until(far["id"], air - 30 + 12 * 3600 - 60, air).get("end") and dvr.until(far["id"], air + 13 * 3600, air).get("error") == "time")
tf2 = dvr.tag({"id": far["id"], "title": "Past its edge", "ep": "S1E9", "show": {"start": air + 11 * 3600, "end": air + 13 * 3600}}, air)
check("only past that edge: a continuation, from 12 hours after it began", tf2.get("continued") and dvr.load()["recordings"][tf2["continued"]]["start"] == air - 30 + 12 * 3600, tf2)
for x in (far["id"], tf2.get("continued")):
    if x:
        dvr.remove(x)
# by hand at the channel's new address: it moves there; past its 12 hours a continuation holds the show
h1 = dvr.start(job(url=UP + "/fix/good.m3u8?old", channel={"name": "Moving", "number": 150, "hash": "b" * 63 + "c"}, title="First", provider="src:abcdefabcdef", end=T + 900), T)
h2 = dvr.start(job(url=UP + "/fix/good.m3u8?new", channel={"name": "Moving", "number": 150, "hash": "c" * 63 + "b"}, title="Second", provider="src:abcdefabcdef", end=T + 1800), T + 60)
rr = dvr.load()["recordings"][h1["id"]]
check("by hand at the channel's new address: joined, and told to move there", h2.get("joined") and rr.get("handoff", {}).get("url", "").endswith("?new")
      and rr["channel"]["hash"] == hashlib.sha256((UP + "/fix/good.m3u8?new").encode()).hexdigest(), rr.get("handoff"))
h3 = dvr.start(job(url=UP + "/fix/good.m3u8?new", channel={"name": "Moving", "number": 150, "hash": "c" * 63 + "b"}, title="Long one", ep="S1E1", provider="src:abcdefabcdef",
                   end=T + 12 * 3600 + 100, show={"start": T + 11 * 3600, "end": T + 12 * 3600 + 60}), T + 120)
st = dvr.load()["recordings"]
check("by hand past its 12 hours: a continuation holds the show, not the one that can't", h3.get("continued") and st[h1["id"]]["end"] == T + 12 * 3600
      and "ep:long one|s1e1" in st[h3["continued"]]["ids"] and "ep:long one|s1e1" not in st[h1["id"]].get("ids", []), h3)
tg_url = dvr.tag({"id": h1["id"], "title": "Tagged", "url": UP + "/fix/good.m3u8?tagged", "show": {"start": T + 600, "end": T + 1500}}, T + 200)
check("Record every episode on it, with the channel's address now: told to move there", tg_url.get("ok") and dvr.load()["recordings"][h1["id"]]["handoff"]["url"].endswith("?tagged"))
fo = dvr.follow_cmd({"id": h1["id"], "url": UP + "/fix/good.m3u8?newest"})
check("follow: the newest address, for the guide's own notice", fo.get("ok") and dvr.load()["recordings"][h1["id"]]["handoff"]["url"].endswith("?newest")
      and dvr.follow_cmd({"id": h1["id"], "url": "file:///etc/passwd"}).get("error") == "job")
for x in (h1["id"], h3.get("continued")):
    if x:
        dvr.remove(x)
dvr.limit(2)

# Recordings off: every scheduled one off the list at once, the series and the running ones kept
keepr = dvr.series_add({"channel": {"name": "Eleven", "hash": "e" * 63 + "f"}, "title": "Kept"})
w1, w2 = scheduled(slot(title="Off one", showStart=T + 86400 * 2, showEnd=T + 86400 * 2 + 600), slot(title="Off two", showStart=T + 86400 * 3, showEnd=T + 86400 * 3 + 600))
run = dvr.start(job(channel={"name": "Twelve", "number": 112, "hash": "f" * 63 + "e"}, title="Running", end=T + 600), T)
cl = dvr.clear()
s = dvr.load()
check("clear: the scheduled ones gone at once, the series and the running one kept", cl.get("cleared", 0) >= 2 and w1["id"] not in s["recordings"]
      and w2["id"] not in s["recordings"] and keepr["id"] in s["rules"] and s["recordings"][run["id"]]["state"] == "starting", cl)
dvr.say_note, dvr.unit_active = real_say_note, real_unit_active
for rid in list(dvr.load()["recordings"]):
    dvr.remove(rid)

# ---- end to end: the worker records, then stops on request ----
with open(os.path.join(FIX, "s0.ts"), "rb") as f:
    chunk = f.read()


def slow_stream(h):
    h.send_response(200)
    h.send_header("Content-Type", "video/mp2t")
    h.end_headers()
    try:
        for _ in range(60):
            h.wfile.write(chunk)
            h.wfile.flush()
            time.sleep(0.5)
    except OSError:
        pass


routes["/fix/endless.ts"] = slow_stream
dvr.inhibit = lambda: None
notes = []
dvr.notify = lambda r: notes.append(r)
said = []
dvr.say_note = lambda summary, body: said.append((summary, body))
state_when_pictured = []
dvr.thumb_of = lambda path, rid: state_when_pictured.append(dvr.load()["recordings"][rid]["state"]) or ""
check("recordings' pictures in their own folder (My Videos clears its own)", dvr.thumbs_dir().endswith(os.path.join("om-pg", "recordings")))
res = dvr.start(job(url=UP + "/fix/endless.ts", channel={"name": "Endless", "number": 7, "hash": "e" * 64}, title="Loop"))
rid = res["id"]
w = dvr.Worker.__new__(dvr.Worker)
w.rid, w.stopping = rid, False
t = threading.Thread(target=w.run, daemon=True)
t.start()
deadline = time.time() + 30
while time.time() < deadline and dvr.load()["recordings"][rid]["state"] != "recording":
    time.sleep(0.5)
check("the worker says recording once data comes", dvr.load()["recordings"][rid]["state"] == "recording")
listed = {x["id"]: x for x in dvr.listing()["recordings"]}
check("no sleep protection: said while it records", listed[rid].get("sleepUnprotected") is True, listed[rid])
check("a notification when it starts, saying so", said and said[0][0] == "Recording" and "sleep protection is unavailable" in said[0][1], said)
time.sleep(3)
dvr.stop(rid)
t.join(40)
r = dvr.load()["recordings"][rid]
final = os.path.join(rec_root, r["file"])
check("stopped on request: done", r["state"] == "done", r)
check("its file in place, no part file left", os.path.getsize(final) > 1000 and not os.path.exists(os.path.join(rec_root, dvr.part_name(r["file"]))))
details = json.load(open(os.path.splitext(final)[0] + ".json"))
check("its details next to it, without the stream's address", details["title"] == "Loop" and details["channel"]["hash"] == "e" * 64
      and UP not in json.dumps(details))
check("its stream's address forgotten when it ends", "source" not in r)
check("its file is yours alone", oct(os.stat(final).st_mode & 0o777) == "0o600")
check("an Omarchy notification says so", notes and notes[-1]["state"] == "done")
said.clear()
real_notify = importlib.util.module_from_spec(_spec)
_loader.exec_module(real_notify)
real_notify.say_note = lambda summary, body: said.append((summary, body))
real_notify.notify(dict(r, state="done"))
real_notify.notify(dict(r, state="incomplete", reason="space"))
check("its notifications never name it (the lock may change while it records)", said and all("Loop" not in s + b and "Endless" not in s + b for s, b in said), said)
check("and say why it stopped", "The disk got too full" in said[1][1], said)
check("a length worked out", r.get("duration", 0) >= 1, r.get("duration"))
check("said done before its picture was made", state_when_pictured == ["done"], state_when_pictured)

# ---- its channel's address turned while it records: the same file goes on from the new one ----
routes["/fix/endless-new.ts"] = slow_stream
res = dvr.start(job(url=UP + "/fix/endless.ts", channel={"name": "Turning", "number": 8, "hash": "1" * 63 + "2"}, title="Turn", provider="src:abcdefabcdef"))
rid = res["id"]
w = dvr.Worker(rid)
t = threading.Thread(target=w.run, daemon=True)
t.start()
deadline = time.time() + 30
while time.time() < deadline and dvr.load()["recordings"][rid]["state"] != "recording":
    time.sleep(0.5)
# (told through Record now on the channel at its new address, as a user or agent would)
moved = dvr.start(job(url=UP + "/fix/endless-new.ts", channel={"name": "Turning", "number": 8, "hash": "2" * 63 + "1"}, title="Turn on", provider="src:abcdefabcdef"))
check("Record now at the channel's new address: joined", moved.get("joined") and moved["id"] == rid, moved)
old_route = routes.pop("/fix/endless.ts")
deadline = time.time() + 20
while time.time() < deadline and dvr.load()["recordings"][rid].get("source", {}).get("url", "").endswith("/fix/endless.ts"):
    time.sleep(0.5)
size_at_switch = dvr.load()["recordings"][rid].get("bytes", 0)
time.sleep(12)
r = dvr.load()["recordings"][rid]
check("moved to the new address", r.get("source", {}).get("url", "").endswith("/fix/endless-new.ts") and any(p.startswith("/fix/endless-new.ts") for p in seen_paths), r.get("source"))
check("the same file goes on growing from it, the old one gone", r["state"] == "recording" and r.get("bytes", 0) > size_at_switch, (r["state"], size_at_switch, r.get("bytes")))
dvr.stop(rid)
t.join(40)
r = dvr.load()["recordings"][rid]
check("then done, one file, no address kept", r["state"] == "done" and "source" not in r and "handoff" not in r, r.get("state"))
routes["/fix/endless.ts"] = old_route

# ---- a continuation: started by the recording before it, as that one ends ----
res = dvr.start(job(url=UP + "/fix/endless-new.ts", channel={"name": "Before", "number": 9, "hash": "3" * 63 + "4"}, title="Before", end=int(time.time()) + 6))
rid = res["id"]
cid = "c" * 16
with dvr.locked():
    s = dvr.load()
    s["recordings"][cid] = {"id": cid, "kind": "iptv", "state": "scheduled", "reason": "", "created": int(time.time()), "channel": {"name": "Before", "number": 9, "hash": "3" * 63 + "4"},
                            "provider": "", "title": "After", "titles": ["After"], "show": {"start": int(time.time()), "end": int(time.time()) + 900},
                            "start": int(time.time()) + 6, "end": int(time.time()) + 900, "rule": "", "ids": ["at:1"], "after": rid, "bytes": 0}
    s["recordings"][rid]["then"] = cid
    dvr.save(s)
started.clear()
w = dvr.Worker(rid)
t = threading.Thread(target=w.run, daemon=True)
t.start()
t.join(60)
check("the recording before it ended: the continuation started at once, from the same address",
      dvr.load()["recordings"][cid]["state"] == "starting" and any(("--unit=uber-tv-rec-" + cid) in a for a in started)
      and dvr.load()["recordings"][cid].get("source", {}).get("url", "").endswith("/fix/endless-new.ts"), dvr.load()["recordings"][cid].get("state"))
dvr.remove(cid)

# ---- at its 12-hour edge, a scheduled show at the channel's new address: it moves there, and its continuation starts from there ----
routes["/fix/endless-edge-new.ts"] = slow_stream
now0 = int(time.time())
edge = dvr.start(job(url=UP + "/fix/endless.ts", channel={"name": "Edge", "number": 10, "hash": "4" * 63 + "5"}, title="Hour 12", provider="src:abcdefabcdef",
                     end=now0 + 10), now0 - 12 * 3600 + 10)
erid = edge["id"]
w = dvr.Worker(erid)
t = threading.Thread(target=w.run, daemon=True)
t.start()
deadline = time.time() + 30
while time.time() < deadline and dvr.load()["recordings"][erid]["state"] != "recording":
    time.sleep(0.5)
nxt = scheduled(slot(channel={"name": "Edge", "number": 10, "hash": "5" * 63 + "4"}, title="Next hour", showStart=now0 + 5, showEnd=now0 + 900))[0]
cl = dvr.start(dict(due, slot=nxt["id"], url=UP + "/fix/endless-edge-new.ts"), int(time.time()))
check("at the edge: a continuation, and the running one told the new address", cl.get("error") == "early" and cl.get("after") == erid, cl)
started.clear()
t.join(60)
st = dvr.load()["recordings"]
check("the running one moved to it, then started its continuation from it", any(p.startswith("/fix/endless-edge-new.ts") for p in seen_paths)
      and st[nxt["id"]]["state"] == "starting" and st[nxt["id"]].get("source", {}).get("url", "").endswith("/fix/endless-edge-new.ts"), st[nxt["id"]].get("state"))
dvr.remove(nxt["id"])

# ---- My Videos leaves recordings out ----
VIDS = os.path.join(TMP, "vids")
os.makedirs(os.path.join(VIDS, dvr.ROOT_NAME))
os.makedirs(os.path.join(VIDS, "Holiday"))
for path in ("mine.mp4", "Holiday/beach.mp4", dvr.ROOT_NAME + "/News.ts"):
    with open(os.path.join(VIDS, path), "wb") as f:
        f.write(b"x" * 2048)
open(os.path.join(VIDS, dvr.ROOT_NAME, dvr.MARKER), "w").close()


def my_videos(folder):
    out = subprocess.run(["nice", "-n", "19", "/usr/bin/python3", "-I", os.path.join(ROOT, "bin", "om-pg-videos"), folder, os.path.join(TMP, "vcache")],
                         capture_output=True, text=True, timeout=120).stdout
    first = json.loads(out.splitlines()[0])
    return sorted(os.path.relpath(v["path"], folder) for v in first["videos"])


check("My Videos skips the recordings folder", my_videos(VIDS) == ["Holiday/beach.mp4", "mine.mp4"], my_videos(VIDS))
with open(os.path.join(VIDS, dvr.ROOT_NAME, "News.json"), "w") as f:
    f.write("{}")
with open(os.path.join(VIDS, dvr.ROOT_NAME, "dropped in.mp4"), "wb") as f:
    f.write(b"x" * 2048)
with open(os.path.join(VIDS, dvr.ROOT_NAME, "Show.part.ts"), "wb") as f:
    f.write(b"x" * 2048)
check("My Videos on the recordings folder itself: nothing (a recording still going, one without details, nothing)",
      my_videos(os.path.join(VIDS, dvr.ROOT_NAME)) == [], my_videos(os.path.join(VIDS, dvr.ROOT_NAME)))

# ---- a video save says Saving only once video has come ----
FAKE = os.path.join(TMP, "fake-yt-dlp")
with open(FAKE, "w") as f:
    f.write("""#!/bin/sh
out=""; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done
dir=$(dirname "$out")
sleep 3
echo note > "$dir/video.mkv.ytdl"
sleep 3
head -c 4096 /dev/zero > "$dir/video.mkv.part"
sleep 3
mv "$dir/video.mkv.part" "$dir/video.mkv"
""")
os.chmod(FAKE, 0o700)
dvr.YTDLP = FAKE
said.clear()
res = dvr.start({"kind": "youtube-video", "video": "fAkEvIdEo01", "channel": {"name": "Kurz", "hash": "f" * 64}, "title": "Fake",
                 "place": place, "keepFree": dvr.GiB})
vid = res["id"]
w = dvr.Worker.__new__(dvr.Worker)
w.rid, w.stopping, w.unprotected = vid, False, False
t = threading.Thread(target=w.run, daemon=True)
t.start()
time.sleep(5.5)
check("only yt-dlp's notes so far: still starting, nothing said", dvr.load()["recordings"][vid]["state"] == "starting" and not said, (dvr.load()["recordings"][vid]["state"], said))
time.sleep(3)
check("video bytes: Saving, said once", dvr.load()["recordings"][vid]["state"] == "recording" and len(said) == 1, (dvr.load()["recordings"][vid]["state"], said))
t.join(30)
check("then done", dvr.load()["recordings"][vid]["state"] == "done" and len(said) == 1, dvr.load()["recordings"][vid])
check("a recording keeps its provider (bounded, opaque)", dvr.job_from({"kind": "iptv", "url": "http://x/1", "end": int(time.time()) + 60, "provider": "src:abcdefabcdef"}, int(time.time()))[0]["provider"] == "src:abcdefabcdef"
      and dvr.job_from({"kind": "iptv", "url": "http://x/1", "end": int(time.time()) + 60, "provider": "http://evil/"}, int(time.time()))[0]["provider"] == "")

shutil.rmtree(TMP, ignore_errors=True)
up.shutdown()
if failures:
    print("%d failed" % failures)
    sys.exit(1)
print("dvr: all good")
