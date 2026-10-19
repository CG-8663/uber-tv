#!/usr/bin/python3
"""The streamer's playlists (bin/om-pg-streamer): /usr/bin/python3 tests/streamer.test.py

A YouTube master trimmed to one H.264 picture at or under the height asked
for (1080 by default; 720, 480 or 360 for a Multiview tile), or the smallest
there is; the full master cached per video, so one quality never stands in
for another, asked in any order or at once; ?h= checked (only those
heights); the secret still guarding every path. Nothing goes to the network:
yt-dlp and the download are stood in for."""

import http.client
import importlib.machinery
import importlib.util
import io
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-streamer")
_loader = importlib.machinery.SourceFileLoader("om_pg_streamer", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_streamer", _loader)
st = importlib.util.module_from_spec(_spec)
_loader.exec_module(st)

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


def master(heights, vp9=()):
    lines = ["#EXTM3U",
             '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="original",DEFAULT=YES,URI="https://media.example/audio.m3u8"']
    for h in heights:
        lines += ['#EXT-X-STREAM-INF:BANDWIDTH=%d,CODECS="avc1.4d401f,mp4a.40.2",RESOLUTION=%dx%d,AUDIO="a"' % (h * 1000, h * 16 // 9, h),
                  "https://media.example/%d.m3u8" % h]
    for h in vp9:
        lines += ['#EXT-X-STREAM-INF:BANDWIDTH=%d,CODECS="vp09.00.40.08",RESOLUTION=%dx%d,AUDIO="a"' % (h * 1000, h * 16 // 9, h),
                  "https://media.example/vp9-%d.m3u8" % h]
    return "\n".join(lines) + "\n"


def picked(text):
    """The height of the one picture a trimmed master offers"""
    pics = [l for l in text.splitlines() if l.startswith("https://media.example/") and "audio" not in l]
    return pics[0].rsplit("/", 1)[1].replace(".m3u8", "") if len(pics) == 1 else pics


FULL = master([1080, 720, 480, 360, 240], vp9=[1440, 2160])

# ---- trimming ----
check("no height: the best H.264 up to 1080p", picked(st.trim(FULL)) == "1080")
check("720 asks for 720", picked(st.trim(FULL, 720)) == "720")
check("480 asks for 480", picked(st.trim(FULL, 480)) == "480")
check("360 asks for 360", picked(st.trim(FULL, 360)) == "360")
check("never VP9 above 1080p", "vp9" not in st.trim(FULL))
check("the original audio stays", "audio.m3u8" in st.trim(FULL, 480))
check("nothing small enough: the smallest there is, not the biggest", picked(st.trim(master([1080, 720]), 360)) == "720")

# ---- the cache: one fetch per video, trimmed per request ----
fetches = []


class FakeYDL:
    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return {"formats": [{"protocol": "m3u8_native", "manifest_url": "https://manifest.example/" + url[-11:]}]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_urlopen(url, timeout=0):
    fetches.append(url)
    return FakeResponse(FULL.encode())


st.yt_dlp.YoutubeDL = FakeYDL
st.urllib.request.urlopen = fake_urlopen
st.cache.clear()
order = [picked(st.playlist("aaaaaaaaaaa", h)) for h in (1080, 480, 360, 1080)]
check("the same video at 1080, 480, 360 then 1080: each its own", order == ["1080", "480", "360", "1080"], order)
check("fetched once for all four", len(fetches) == 1, fetches)
check("what's cached is the full master, not one trim", st.cache["aaaaaaaaaaa"][1] == FULL)

st.cache.clear()
fetches.clear()
st.playlist("bbbbbbbbbbb")   # warmed at the default, as the guide's preview does
results = {}


def ask(h):
    results[h] = picked(st.playlist("bbbbbbbbbbb", h))


threads = [threading.Thread(target=ask, args=(h,)) for h in (360, 480, 720, 1080) * 3]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("asked at once at four heights, after warming: each gets its own", results == {360: "360", 480: "480", 720: "720", 1080: "1080"}, results)

# ---- the request: ?h= checked, the secret still checked ----
asked = []
st.playlist = lambda vid, height=st.MAX_HEIGHT: (asked.append(height) or "#EXTM3U\n")
server = st.http.server.ThreadingHTTPServer(("127.0.0.1", 0), st.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()


def get(path):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


base = "/%s/play/ccccccccccc.m3u8" % st.SECRET
check("no ?h: 1080", get(base) == 200 and asked[-1] == 1080, asked)
check("?h=480: 480", get(base + "?h=480") == 200 and asked[-1] == 480, asked)
check("?h=360: 360", get(base + "?h=360") == 200 and asked[-1] == 360, asked)
n = len(asked)
check("?h=999 is refused", get(base + "?h=999") == 400 and len(asked) == n)
check("?h=4k is refused", get(base + "?h=4k") == 400 and len(asked) == n)
check("?h=-480 is refused", get(base + "?h=-480") == 400 and len(asked) == n)
check("the wrong secret is still a 404", get("/wrong/play/ccccccccccc.m3u8?h=480") == 404 and len(asked) == n)
server.shutdown()

print("\n%d failed" % failures if failures else "\nall passed")
sys.exit(1 if failures else 0)
