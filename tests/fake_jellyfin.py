#!/usr/bin/python3
"""A pretend Jellyfin server (10.9-10.11 API shapes) for testing the bundled
Jellyfin app without a real one. Stdlib only.

    /usr/bin/python3 tests/fake_jellyfin.py --port 0 --base /jellyfin --media DIR --log FILE
        [--quick-connect-off] [--approve-after 2] [--expire-token]

prints {"port": N} on its first line, then serves. As a module:

    fake = start(base="/jellyfin", media=dir, quick_connect=True, approve_after=2)
    fake.url        # "http://127.0.0.1:PORT/jellyfin"
    fake.events     # every POST/DELETE to /Sessions*, /Videos/ActiveEncodings,
                    # /LiveStreams/Close and PlaybackInfo: method, path, query, body, auth
    fake.requests   # every request: method, path, query, auth
    fake.expire_token()   # the tokens it gave answer 401 from now on
    fake.stop()

Everything is under the base path; anything outside it is 404. User
endpoints need a token (Authorization: MediaBrowser ..., Token="..."; or
X-Emby-Token, X-MediaBrowser-Token, api_key=); images don't. Media comes from
files made with /usr/bin/ffmpeg in the media folder (movie.mp4, an HLS stream:
master.m3u8 -> main.m3u8 -> seg0.ts...) and poster.png, served with ranges.
POST {base}/__test/expire does what expire_token() does (for the CLI)."""

import argparse
import copy
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import threading
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TICKS = 10_000_000
USER = {"Id": "u1", "Name": "tester"}
PASSWORD = "Pa55-w0rd!"   # the test account's password (AuthenticateByName)
SERVER_ID = "f00d"


# ---- media -------------------------------------------------------------------

def png(w, h, rgb=(40, 90, 160)):
    raw = b"".join(b"\0" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_media(media):
    os.makedirs(media, exist_ok=True)
    q = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    src = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "8",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "25", "-sc_threshold", "0",
           "-c:a", "aac", "-shortest"]
    if not os.path.exists(os.path.join(media, "movie.mp4")):
        subprocess.run(q + src + [os.path.join(media, "movie.mp4")], check=True)
    if not os.path.exists(os.path.join(media, "main.m3u8")):
        subprocess.run(q + src + ["-f", "hls", "-hls_time", "1", "-hls_list_size", "0", "-hls_segment_filename",
                                  os.path.join(media, "seg%d.ts"), os.path.join(media, "main.m3u8")], check=True)
    if not os.path.exists(os.path.join(media, "poster.png")):
        with open(os.path.join(media, "poster.png"), "wb") as f:
            f.write(png(200, 300))


# ---- the library -------------------------------------------------------------

PEOPLE = [{"Id": "p1", "Name": "Ann Actor", "Role": "Herself", "Type": "Actor", "PrimaryImageTag": "pt1"},
          {"Id": "p2", "Name": "Bob Actor", "Role": "The Neighbour", "Type": "Actor"},
          {"Id": "p3", "Name": "Cee Director", "Type": "Director", "PrimaryImageTag": "pt3"}]


def movie(n):
    item = {"Id": "m%d" % n, "Name": "Movie %d" % n, "Type": "Movie", "MediaType": "Video", "IsFolder": False,
            "ProductionYear": 1990 + n % 30, "RunTimeTicks": 5400 * TICKS, "OfficialRating": "PG-13",
            "CommunityRating": 7.5, "Overview": "The story of movie %d.\nIt has two lines." % n, "Genres": ["Drama", "Comedy"],
            "ImageTags": {"Primary": "t%d" % n}, "BackdropImageTags": ["b%d" % n],
            "UserData": {"PlaybackPositionTicks": 0, "PlayedPercentage": 0, "Played": False, "IsFavorite": False}}
    if n % 2 == 0:
        item["ImageTags"].update(Thumb="th%d" % n, Logo="l%d" % n)   # every other movie: a wide still and a title logo
    if n <= 10:
        item["People"] = PEOPLE                                       # Ann is in the first ten
    if n == 1:
        item["UserData"].update(PlaybackPositionTicks=30 * TICKS // 10, PlayedPercentage=12.5)
    return item


SERIES = {"Id": "s1", "Name": "Show One", "Type": "Series", "IsFolder": True, "ProductionYear": 2020, "OfficialRating": "TV-14",
          "CommunityRating": 8.1, "Overview": "A show.", "Genres": ["Comedy"], "ImageTags": {"Primary": "ts1", "Thumb": "ths1", "Logo": "ls1"},
          "BackdropImageTags": ["bs1"], "ChildCount": 1, "People": PEOPLE[:1],
          "UserData": {"PlaybackPositionTicks": 0, "Played": False, "PlayedPercentage": 0}}
SEASON = {"Id": "se1", "Name": "Season 1", "Type": "Season", "IndexNumber": 1, "SeriesId": "s1", "SeriesName": "Show One",
          "IsFolder": True, "ImageTags": {"Primary": "tse1"}, "UserData": {"PlaybackPositionTicks": 0, "Played": False}}


def episode(n):
    return {"Id": "e%d" % n, "Name": "Episode %d" % n, "Type": "Episode", "MediaType": "Video", "IsFolder": False,
            "IndexNumber": n, "ParentIndexNumber": 1, "SeriesName": "Show One", "SeriesId": "s1", "SeasonId": "se1",
            "RunTimeTicks": 1500 * TICKS, "Overview": "Episode %d of Show One." % n, "ImageTags": {"Primary": "te%d" % n},
            "SeriesPrimaryImageTag": "ts1", "ParentBackdropItemId": "s1", "ParentBackdropImageTags": ["bs1"],
            "ParentLogoItemId": "s1", "ParentLogoImageTag": "ls1", "SeriesThumbImageTag": "ths1",
            "UserData": {"PlaybackPositionTicks": 0, "Played": n == 1, "PlayedPercentage": 100 if n == 1 else 0}}


SEASON2 = {"Id": "se2", "Name": "Season 2", "Type": "Season", "IndexNumber": 2, "SeriesId": "s1", "SeriesName": "Show One",
           "IsFolder": True, "ImageTags": {"Primary": "tse2"}, "UserData": {"PlaybackPositionTicks": 0, "Played": False}}


def episode2(n):
    """Season 2: 60 episodes (more than a page)"""
    return dict(episode(n), Id="s2e%d" % n, ParentIndexNumber=2, SeasonId="se2", Overview="Episode %d of season 2." % n,
                UserData={"PlaybackPositionTicks": 0, "Played": False, "PlayedPercentage": 0})


MOVIES = [movie(n) for n in range(1, 76)]
EPISODES = [episode(n) for n in (1, 2, 3)]
EPISODES2 = [episode2(n) for n in range(1, 61)]
ITEMS = {i["Id"]: i for i in MOVIES + EPISODES + EPISODES2 + [SERIES, SEASON, SEASON2]}
VIEWS = [{"Id": "libmovies", "Name": "Movies", "CollectionType": "movies", "Type": "CollectionFolder", "IsFolder": True,
          "ImageTags": {"Primary": "t"}},
         {"Id": "libshows", "Name": "Shows", "CollectionType": "tvshows", "Type": "CollectionFolder", "IsFolder": True},
         {"Id": "libmusic", "Name": "Music", "CollectionType": "music", "Type": "CollectionFolder", "IsFolder": True}]
ITEMS.update({v["Id"]: v for v in VIEWS})
ALBUM = {"Id": "al1", "Name": "An Album", "Type": "MusicAlbum", "IsFolder": True}
ITEMS[ALBUM["Id"]] = ALBUM
ITEMS.update({p["Id"]: {"Id": p["Id"], "Name": p["Name"], "Type": "Person", "ImageTags": {"Primary": p["PrimaryImageTag"]} if p.get("PrimaryImageTag") else {}}
              for p in PEOPLE})


# ---- the server --------------------------------------------------------------

AUTH_RE = re.compile(r'(\w+)="([^"]*)"')


class FakeJellyfin:
    def __init__(self, base="/jellyfin", media=None, quick_connect=True, approve_after=2, log=None, port=0):
        self.base = "/" + base.strip("/") if base.strip("/") else ""
        self.media = media
        make_media(media)
        self.quick_connect = quick_connect
        self.approve_after = approve_after
        self.log = log
        self.lock = threading.Lock()
        self.events = []
        self.requests = []
        self.tokens = set()
        self.revoked = set()
        self.expired = False
        self.qc = {}               # secret -> {code, polls}
        self.sessions = {}         # PlaySessionId -> item id
        self.items = copy.deepcopy(ITEMS)   # its own library (watched marks don't leak between servers)
        self.movies = [self.items["m%d" % n] for n in range(1, 76)]
        self.episodes = [self.items["e%d" % n] for n in (1, 2, 3)]
        self.episodes2 = [self.items["s2e%d" % n] for n in range(1, 61)]
        self.fail_stopped = False  # /Sessions/Playing/Stopped answers 500 (cleanup must still happen)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.handle(self, "GET")

            def do_HEAD(self):
                fake.handle(self, "HEAD")

            def do_POST(self):
                fake.handle(self, "POST")

            def do_DELETE(self):
                fake.handle(self, "DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d%s" % (self.port, self.base)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def issue_token(self):
        """A token as AuthenticateWithQuickConnect would give (for tests that
        start signed in)"""
        tok = "tok-" + secrets.token_hex(12)
        with self.lock:
            self.tokens.add(tok)
            self.expired = False
        return tok

    def expire_token(self):
        with self.lock:
            self.expired = True

    def approve_all(self):
        with self.lock:
            for s in self.qc.values():
                s["polls"] = max(s["polls"], self.approve_after)

    # ---- plumbing ----
    def token_of(self, handler, query):
        auth = handler.headers.get("Authorization") or handler.headers.get("X-Emby-Authorization") or ""
        fields = dict(AUTH_RE.findall(auth)) if auth.strip().startswith(("MediaBrowser", "Emby")) else {}
        return (fields.get("Token") or handler.headers.get("X-Emby-Token") or handler.headers.get("X-MediaBrowser-Token")
                or (query.get("api_key") or query.get("ApiKey") or [""])[0])

    def authed(self, token):
        with self.lock:
            return bool(token) and token in self.tokens and token not in self.revoked and not self.expired

    def send(self, h, status, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list, bool)):
            body = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(body)

    def send_file(self, h, path, ctype, rewrite=None):
        data = open(path, "rb").read()
        if rewrite:
            data = rewrite(data)
        rng = h.headers.get("Range", "")
        m = re.match(r"^bytes=(\d+)-(\d*)$", rng)
        if m:
            a = int(m.group(1))
            b = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
            if a >= len(data):
                self.send(h, 416, b"", ctype, {"Content-Range": "bytes */%d" % len(data)})
                return
            self.send(h, 206, data[a:b + 1], ctype, {"Content-Range": "bytes %d-%d/%d" % (a, b, len(data)), "Accept-Ranges": "bytes"})
            return
        self.send(h, 200, data, ctype, {"Accept-Ranges": "bytes"})

    def handle(self, h, method):
        try:
            self.route(h, method)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def route(self, h, method):
        parts = urllib.parse.urlsplit(h.path)
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        n = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(n) if n else b""
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        auth = h.headers.get("Authorization") or h.headers.get("X-Emby-Authorization") or ""
        rec = {"method": method, "path": parts.path, "query": {k: v[0] for k, v in query.items()}, "auth": auth}
        with self.lock:
            self.requests.append(rec)
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps(rec) + "\n")
        if self.base and not (parts.path == self.base or parts.path.startswith(self.base + "/")):
            return self.send(h, 404, b"")
        path = parts.path[len(self.base):] or "/"
        low = path.lower()
        token = self.token_of(h, query)

        def need_user():
            if not self.authed(token):
                self.send(h, 401, b"")
                return False
            return True

        def event(**extra):
            e = dict(rec, body=body)
            e.update(extra)
            with self.lock:
                self.events.append(e)

        if low == "/__test/expire" and method == "POST":
            self.expire_token()
            return self.send(h, 204)
        if low == "/system/info/public":
            return self.send(h, 200, {"ServerName": "Test Jellyfin", "Version": "10.10.7", "Id": SERVER_ID, "LocalAddress": "",
                                      "ProductName": "Jellyfin Server", "StartupWizardCompleted": True})
        if low == "/quickconnect/enabled":
            return self.send(h, 200, self.quick_connect)
        if low == "/quickconnect/initiate" and method in ("POST", "GET"):
            if not self.quick_connect:
                return self.send(h, 401, b"")
            s = secrets.token_hex(16)
            code = "%06d" % secrets.randbelow(1000000)
            fields = dict(AUTH_RE.findall(auth))
            with self.lock:
                self.qc[s] = {"code": code, "polls": 0, "device": fields.get("DeviceId", "")}
            return self.send(h, 200, {"Secret": s, "Code": code, "DeviceId": fields.get("DeviceId", ""), "DeviceName": fields.get("Device", ""),
                                      "AppName": fields.get("Client", ""), "AppVersion": fields.get("Version", ""),
                                      "DateAdded": "2026-10-12T03:00:00Z", "Authenticated": False})
        if low == "/quickconnect/connect":
            s = (query.get("Secret") or query.get("secret") or [""])[0]
            with self.lock:
                st = self.qc.get(s)
                if st:
                    st["polls"] += 1
            if not st:
                return self.send(h, 404, b"")
            return self.send(h, 200, {"Secret": s, "Code": st["code"], "Authenticated": st["polls"] >= self.approve_after})
        if low == "/users/authenticatebyname" and method == "POST":
            # a username and password (for a server with Quick Connect off)
            ok = isinstance(body, dict) and body.get("Username") == USER["Name"] and body.get("Pw") == PASSWORD
            event()
            if not ok:
                return self.send(h, 401, b"")
            with self.lock:
                tok = "tok-" + secrets.token_hex(12)
                self.tokens.add(tok)
                self.expired = False
            return self.send(h, 200, {"User": USER, "AccessToken": tok, "ServerId": SERVER_ID,
                                      "SessionInfo": {"Id": "sess1", "UserId": USER["Id"]}})
        if low == "/users/authenticatewithquickconnect" and method == "POST":
            s = body.get("Secret") if isinstance(body, dict) else None
            with self.lock:
                st = self.qc.get(s)
                ok = bool(st) and st["polls"] >= self.approve_after
                tok = "tok-" + secrets.token_hex(12) if ok else ""
                if ok:
                    self.tokens.add(tok)
                    self.expired = False
            if not ok:
                return self.send(h, 401, b"")
            return self.send(h, 200, {"User": USER, "AccessToken": tok, "ServerId": SERVER_ID,
                                      "SessionInfo": {"Id": "sess1", "UserId": USER["Id"]}})
        if low == "/sessions/logout" and method == "POST":
            event()
            with self.lock:
                if token:
                    self.revoked.add(token)
            return self.send(h, 204, b"")
        m = re.match(r"^/items/([^/]+)/images/(primary|backdrop|thumb|logo)(/\d+)?$", low)
        if m:
            return self.send_file(h, os.path.join(self.media, "poster.png"), "image/png")
        if low in ("/sessions/playing", "/sessions/playing/progress", "/sessions/playing/stopped") and method == "POST":
            if not need_user():
                return
            event()
            if low == "/sessions/playing/stopped" and self.fail_stopped:
                return self.send(h, 500, b"")
            return self.send(h, 204, b"")
        if low == "/videos/activeencodings" and method == "DELETE":
            if not need_user():
                return
            event()
            return self.send(h, 204, b"")
        if low == "/livestreams/close" and method == "POST":
            if not need_user():
                return
            event()
            return self.send(h, 204, b"")
        m = re.match(r"^/items/([^/]+)/playbackinfo$", low)
        if m and method == "POST":
            if not need_user():
                return
            iid = path.split("/")[2]
            item = self.items.get(iid)
            if not item or item.get("IsFolder"):
                return self.send(h, 404, b"")
            ps = "ps-" + secrets.token_hex(8)
            src = "src-" + iid
            event(deviceProfile=(body or {}).get("DeviceProfile") if isinstance(body, dict) else None, playSessionId=ps)
            with self.lock:
                self.sessions[ps] = iid
            direct = iid != "m2"
            def off(name):
                return any(k.lower() == name.lower() and v[0].lower() == "false" for k, v in query.items())
            can_play, can_stream = direct and not off("EnableDirectPlay"), direct and not off("EnableDirectStream")
            if iid == "m3":
                # an HEVC file, say: not direct play for this profile, though Jellyfin
                # could still stream it as it is; the guide must take the transcode
                can_play, can_stream = False, True
            tq = urllib.parse.urlencode({"DeviceId": dict(AUTH_RE.findall(auth)).get("DeviceId", ""), "MediaSourceId": src,
                                         "PlaySessionId": ps, "api_key": token, "VideoCodec": "h264", "AudioCodec": "aac"})
            source = {"Id": src, "Container": "mp4", "Protocol": "File", "Path": "/media/%s.mp4" % iid, "Name": item["Name"],
                      "RunTimeTicks": item.get("RunTimeTicks", 0), "SupportsDirectPlay": can_play, "SupportsDirectStream": can_stream,
                      "SupportsTranscoding": True, "IsRemote": False, "RequiresOpening": False,
                      "MediaStreams": [{"Type": "Video", "Codec": "h264", "Width": 320, "Height": 240, "Profile": "High", "Level": 30,
                                        "BitDepth": 8, "Index": 0},
                                       {"Type": "Audio", "Codec": "aac", "Channels": 2, "Index": 1}]}
            if True:   # Jellyfin offers a TranscodingUrl whenever transcoding is allowed for the profile
                source["TranscodingUrl"] = "/videos/%s/master.m3u8?%s" % (iid, tq)
                source["TranscodingSubProtocol"] = "hls"
                source["TranscodingContainer"] = "ts"
            return self.send(h, 200, {"MediaSources": [source], "PlaySessionId": ps})
        m = re.match(r"^/videos/([^/]+)/stream(\.[a-z0-9]+)?$", low)
        if m:
            if not need_user():
                return
            return self.send_file(h, os.path.join(self.media, "movie.mp4"), "video/mp4")
        m = re.match(r"^/videos/([^/]+)/(master|main)\.m3u8$", low)
        if m:
            if not need_user():
                return
            q = parts.query
            if m.group(2) == "master":
                text = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,AVERAGE-BANDWIDTH=1000000,CODECS=\"avc1.64001e,mp4a.40.2\","
                        "RESOLUTION=320x240,FRAME-RATE=25\nmain.m3u8?%s\n" % q).encode()
                return self.send(h, 200, text, "application/vnd.apple.mpegurl")
            return self.send_file(h, os.path.join(self.media, "main.m3u8"), "application/vnd.apple.mpegurl",
                                  rewrite=lambda d: re.sub(rb"^(seg\d+\.ts)$", lambda x: x.group(1) + b"?" + q.encode(), d, flags=re.M))
        m = re.match(r"^/videos/([^/]+)/(seg\d+)\.ts$", low)
        if m:
            if not need_user():
                return
            f = os.path.join(self.media, m.group(2) + ".ts")
            if not os.path.isfile(f):
                return self.send(h, 404, b"")
            return self.send_file(h, f, "video/mp2t")
        # watched / unwatched: the legacy route, and 10.9's /UserPlayedItems/{id}?userId=
        m = re.match(r"^/users/[^/]+/playeditems/([^/]+)$", low) or re.match(r"^/userplayeditems/([^/]+)$", low)
        if m and method in ("POST", "DELETE"):
            if not need_user():
                return
            iid = path.rstrip("/").split("/")[-1]
            item = self.items.get(iid)
            if not item:
                return self.send(h, 404, b"")
            event()
            with self.lock:
                item["UserData"] = dict(item.get("UserData") or {}, Played=method == "POST",
                                        PlayedPercentage=100 if method == "POST" else 0, PlaybackPositionTicks=0)
            return self.send(h, 200, item["UserData"])
        m = re.match(r"^/shows/nextup$", low)
        if m:
            if not need_user():
                return
            return self.send(h, 200, {"Items": [self.items["e2"]], "TotalRecordCount": 1, "StartIndex": 0})
        m = re.match(r"^/shows/([^/]+)/seasons$", low)
        if m:
            if not need_user():
                return
            seasons = [self.items["se1"], self.items["se2"]] if path.split("/")[2] == "s1" else []
            return self.send(h, 200, {"Items": seasons, "TotalRecordCount": len(seasons)})
        m = re.match(r"^/shows/([^/]+)/episodes$", low)
        if m:
            if not need_user():
                return
            sid = (query.get("seasonId") or query.get("SeasonId") or [""])[0]
            items = (self.episodes if sid in ("", "se1") else self.episodes2 if sid == "se2" else []) if path.split("/")[2] == "s1" else []
            total = len(items)
            start = int((query.get("startIndex") or query.get("StartIndex") or ["0"])[0] or 0)
            limit = (query.get("limit") or query.get("Limit") or [""])[0]
            items = items[start:start + int(limit)] if limit else items[start:]
            return self.send(h, 200, {"Items": items, "TotalRecordCount": total, "StartIndex": start})
        m = re.match(r"^/users/([^/]+)/(views|items/resume|items/latest|items)$", low)
        if m:
            if not need_user():
                return
            what = m.group(2)
            if what == "views":
                return self.send(h, 200, {"Items": VIEWS, "TotalRecordCount": 2})
            if what == "items/resume":
                return self.send(h, 200, {"Items": [self.items["m1"]], "TotalRecordCount": 1, "StartIndex": 0})
            if what == "items/latest":
                return self.send(h, 200, [self.items["m1"], self.items["al1"], self.items["m2"], self.items["s1"]])
            return self.items_query(h, query)
        m = re.match(r"^/users/([^/]+)/items/([^/]+)$", low)
        if m:
            if not need_user():
                return
            item = self.items.get(path.split("/")[4])
            return self.send(h, 200, item) if item else self.send(h, 404, b"")
        # Jellyfin 10.9+ also has /Items?userId=... and /Items/{id}?userId=...
        if low == "/items":
            if not need_user():
                return
            return self.items_query(h, query)
        m = re.match(r"^/items/([^/]+)$", low)
        if m and method == "GET":
            if not need_user():
                return
            item = self.items.get(path.split("/")[2])
            return self.send(h, 200, item) if item else self.send(h, 404, b"")
        return self.send(h, 404, b"")

    def items_query(self, h, query):
        def q(name, default=""):
            for k, v in query.items():
                if k.lower() == name.lower():
                    return v[0]
            return default
        parent = q("ParentId")
        term = q("searchTerm") or q("SearchTerm")
        person = q("PersonIds")
        start = int(q("StartIndex", "0") or 0)
        limit = int(q("Limit", "100") or 100)
        if person:
            pool = [i for i in self.movies + [self.items["s1"]] if any(p["Id"] == person for p in i.get("People", []))]
        elif term:
            pool = [i for i in self.movies + [self.items["s1"]] + self.episodes if term.lower() in i["Name"].lower()]
        elif parent == "libmovies":
            pool = self.movies
        elif parent == "libshows":
            pool = [self.items["s1"]]
        elif parent == "s1":
            pool = [self.items["se1"]]
        elif parent == "se1":
            pool = self.episodes
        else:
            pool = []
        return self.send(h, 200, {"Items": pool[start:start + limit], "TotalRecordCount": len(pool), "StartIndex": start})


def start(base="/jellyfin", media=None, quick_connect=True, approve_after=2, log=None, port=0):
    if media is None:
        import tempfile
        media = tempfile.mkdtemp(prefix="fake-jellyfin-media-")
    return FakeJellyfin(base, media, quick_connect, approve_after, log, port)


def main():
    p = argparse.ArgumentParser(description="a pretend Jellyfin server")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--base", default="/jellyfin")
    p.add_argument("--media", required=True)
    p.add_argument("--log", default=None)
    p.add_argument("--quick-connect-off", action="store_true")
    p.add_argument("--approve-after", type=int, default=2)
    p.add_argument("--expire-token", action="store_true", help="tokens answer 401 once given")
    a = p.parse_args()
    fake = start(a.base, a.media, not a.quick_connect_off, a.approve_after, a.log, a.port)
    if a.expire_token:
        fake.authed = lambda token: False   # every token, even a new one, answers 401
    print(json.dumps({"port": fake.port}), flush=True)
    try:
        fake.thread.join()
    except KeyboardInterrupt:
        fake.stop()


if __name__ == "__main__":
    main()
