#!/usr/bin/python3
"""The bundled Jellyfin app (apps/first-party/tv.uber.jellyfin) through the
real helper and sandbox, against a pretend Jellyfin server
(tests/fake_jellyfin.py): /usr/bin/python3 tests/jellyfin.test.py"""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "apps", "first-party", "tv.uber.jellyfin")


def load(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


apprun = load("apprun", os.path.join(ROOT, "bin", "om-pg-apprun"))
fakejf = load("fake_jellyfin", os.path.join(ROOT, "tests", "fake_jellyfin.py"))
WORK = tempfile.mkdtemp(prefix="om-pg-jellyfin-test-")
MEDIA = os.path.join(WORK, "media")
TICKS = 10_000_000


class Harness:
    """One runtime in this process, as the guide drives it"""

    def __init__(self, **cfg):
        self.frames = []
        self.n = 0
        base = tempfile.mkdtemp(prefix="state-", dir=WORK)
        self.cfg = {"appDir": APP, "gen": 1, "locale": "en-US", "settings": {}, "server": None, "pin": "",
                    "storePath": os.path.join(base, "store.json"), "secretsPath": os.path.join(base, "secrets.json"),
                    "logPath": os.path.join(base, "log"), "imageDir": os.path.join(base, "img"), "online": True}
        self.cfg.update(cfg)

    async def start(self):
        self.rt = apprun.Runtime(self.cfg, self.frames.append)
        return await self.rt.start()

    async def call(self, method, args=None, wait=25):
        self.n += 1
        n = self.n
        await self.rt.from_guide({"t": "call", "id": n, "method": method, "args": args or {}})
        end = time.monotonic() + wait
        while time.monotonic() < end:
            for f in self.frames:
                if f.get("t") == "result" and f.get("id") == n:
                    return f
            if self.rt.done.is_set():
                break
            await asyncio.sleep(0.02)
        return None

    async def frame(self, t, after=0, wait=15, **match):
        end = time.monotonic() + wait
        while time.monotonic() < end:
            for f in self.frames[after:]:
                if f.get("t") == t and all(f.get(k) == v for k, v in match.items()):
                    return f
            await asyncio.sleep(0.05)
        return None

    async def stop(self, forget=""):
        await self.rt.stop("normal", "", forget)

    def log(self):
        self.rt.log.flush()
        try:
            return open(self.cfg["logPath"], encoding="utf-8").read()
        except OSError:
            return ""


async def relay_get(url, headers=None, method="GET"):
    """A plain HTTP request to the relay, as the player makes it"""
    hostport, path = url[len("http://"):].split("/", 1)
    host, port = hostport.split(":")
    r, w = await asyncio.open_connection(host, int(port))
    lines = [method + " /" + path + " HTTP/1.1", "Host: " + hostport] + [k + ": " + v for k, v in (headers or {}).items()]
    w.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await w.drain()
    data = await asyncio.wait_for(r.read(), 30)
    w.close()
    head, _, body = data.partition(b"\r\n\r\n")
    rows = head.decode("latin-1").split("\r\n")
    status = int(rows[0].split()[1])
    hdrs = dict((x.split(":", 1)[0].lower(), x.split(":", 1)[1].strip()) for x in rows[1:] if ":" in x)
    return status, hdrs, body


def items_of(screen):
    return [it for row in screen["rows"] for it in row["items"]]


def signed_in_state(fake, h):
    """Start signed in, as Quick Connect leaves it: the token among the
    secrets kept for this server, the user's id in storage (marked server)"""
    import base64
    tok = fake.issue_token()
    with open(h.cfg["secretsPath"], "w") as f:
        json.dump({"user": {}, "signIn": {"server": fake.url, "values": {"token": tok}}}, f)
    os.chmod(h.cfg["secretsPath"], 0o600)
    with open(h.cfg["storePath"], "w") as f:
        json.dump({"v": 1, "keys": {"userId": {"v": base64.b64encode(b"u1").decode(), "s": True},
                                    "deviceId": {"v": base64.b64encode(b"dev-test-1").decode(), "s": False}}}, f)
    os.chmod(h.cfg["storePath"], 0o600)
    return tok


class Base(unittest.IsolatedAsyncioTestCase):
    quick_connect = True
    approve_after = 1

    async def asyncSetUp(self):
        self.fake = fakejf.start(base="/jellyfin", media=MEDIA, quick_connect=self.quick_connect, approve_after=self.approve_after)

    async def asyncTearDown(self):
        if getattr(self, "h", None):
            await self.h.stop()
        self.fake.stop()

    async def runtime(self, signed=True, server=True):
        self.h = Harness(server=self.fake.url if server else None)
        self.tok = signed_in_state(self.fake, self.h) if signed else ""
        self.assertTrue(await self.h.start(), self.h.rt.stop_why if hasattr(self.h, "rt") else "")
        return self.h

    async def ok(self, method, args=None, kind=None):
        r = await self.h.call(method, args)
        self.assertIsNotNone(r, method + ": no answer")
        if kind:
            self.assertEqual(r["kind"], kind, json.dumps(r)[:600])
        return r["value"]

    def requests(self, needle):
        return [r for r in self.fake.requests if needle.lower() in r["path"].lower()]

    def events(self, needle):
        return [e for e in self.fake.events if e["path"].lower().endswith(needle.lower())]


class NotSignedIn(Base):
    async def test_no_server(self):
        await self.runtime(signed=False, server=False)
        s = await self.ok("home", kind="screen")
        self.assertEqual(s["rows"], [])
        self.assertIn("Set your Jellyfin server", s["empty"])
        self.assertIn("8096", s["empty"])

    async def test_signed_out_home(self):
        await self.runtime(signed=False)
        s = await self.ok("home", kind="screen")
        self.assertEqual(s["title"], "Test Jellyfin", "the server's own name, from /System/Info/Public")
        self.assertEqual(s["rows"], [])
        self.assertIn("Sign in", s["empty"])
        r = await self.h.call("browse", {"item": "lib:libmovies:0"})
        self.assertEqual((r["kind"], r["value"]["code"]), ("error", "signedout"))

    async def test_code_flow(self):
        self.fake.approve_after = 2
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow}, kind="ok")
        code = await self.h.frame("signInCode", flow=flow)
        self.assertIsNotNone(code)
        self.assertRegex(code["code"], r"^\d{6}$")
        self.assertEqual(code["url"], self.fake.url + "/web/", "the page to enter it on, under the base path")
        done = await self.h.frame("signInDone", wait=30, flow=flow)
        self.assertEqual((done["ok"], done["message"]), (True, "Signed in as tester."))
        kept = json.load(open(self.h.cfg["secretsPath"]))
        self.assertEqual(kept["signIn"]["server"], self.fake.url)
        tok = kept["signIn"]["values"]["token"]
        self.assertTrue(tok.startswith("tok-"))
        self.assertIn(tok, self.fake.tokens)
        qc = self.requests("/QuickConnect/Initiate")
        self.assertEqual(qc[0]["method"], "POST", "Initiate is a POST since 10.9")
        self.assertIn('DeviceId="', qc[0]["auth"])
        self.assertGreaterEqual(len(self.requests("/QuickConnect/Connect")), 2, "polled until approved")
        s = await self.ok("home", kind="screen")
        self.assertIn("continue", [r["id"] for r in s["rows"]], "signed in: the home screen fills")
        self.h.rt.store.commit()
        store = json.load(open(self.h.cfg["storePath"]))
        self.assertTrue(store["keys"]["userId"]["s"], "the user id is marked server (forgotten on sign-out)")
        self.assertFalse(store["keys"]["deviceId"]["s"], "the device id survives sign-out")

    async def test_cancelled_flow_stops_polling(self):
        self.fake.approve_after = 99
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow}, kind="ok")
        await self.h.frame("signInCode", flow=flow)
        await self.h.rt.from_guide({"t": "signInCancel", "flow": flow})
        done = await self.h.frame("signInDone", flow=flow)
        self.assertFalse(done["ok"])
        polls = len(self.requests("/QuickConnect/Connect"))
        await asyncio.sleep(6)
        self.assertEqual(len(self.requests("/QuickConnect/Connect")), polls, "no more polling once called off")


class QuickConnectOff(Base):
    quick_connect = False

    async def test_password_sign_in(self):
        """Quick Connect off: your username and password, typed in the guide's
        box, go to the server once; only its token is kept"""
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow, "how": "password"}, kind="ok")
        self.assertIsNone(await self.h.frame("signInCode", wait=0.5), "no code for a password sign-in")
        await self.h.rt.from_guide({"t": "signInPassword", "flow": flow, "username": "tester", "password": fakejf.PASSWORD})
        done = await self.h.frame("signInDone", wait=15, flow=flow)
        self.assertEqual((done["ok"], done["message"]), (True, "Signed in as tester."))
        sent = [e for e in self.fake.events if e["path"].lower().endswith("/users/authenticatebyname")]
        self.assertEqual(len(sent), 1, "sent once")
        self.assertEqual(sent[0]["body"], {"Username": "tester", "Pw": fakejf.PASSWORD})
        self.assertIn('DeviceId="', sent[0]["auth"])
        kept = json.load(open(self.h.cfg["secretsPath"]))
        self.assertTrue(kept["signIn"]["values"]["token"].startswith("tok-"))
        self.assertNotIn(fakejf.PASSWORD, json.dumps(kept), "the password itself isn't kept")
        await self.h.rt.from_guide({"t": "signedIn"})
        s = await self.ok("home", kind="screen")
        self.assertIn("continue", [r["id"] for r in s["rows"]])
        self.h.rt.commit()
        for path in (self.h.cfg["storePath"], self.h.cfg["logPath"]):
            if os.path.exists(path):
                self.assertNotIn(fakejf.PASSWORD, open(path, encoding="utf-8", errors="replace").read())

    async def test_wrong_password(self):
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow, "how": "password"}, kind="ok")
        await self.h.rt.from_guide({"t": "signInPassword", "flow": flow, "username": "tester", "password": "wrong"})
        done = await self.h.frame("signInDone", wait=15, flow=flow)
        self.assertEqual((done["ok"], done["message"]), (False, "Jellyfin didn't take that username and password."))
        self.assertFalse(os.path.exists(self.h.cfg["secretsPath"]) and json.load(open(self.h.cfg["secretsPath"]))["signIn"]["values"])

    async def test_password_box_cancelled(self):
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow, "how": "password"}, kind="ok")
        await self.h.rt.from_guide({"t": "signInCancel", "flow": flow})
        done = await self.h.frame("signInDone", flow=flow)
        self.assertFalse(done["ok"])
        await asyncio.sleep(1)
        self.assertEqual([e for e in self.fake.events if e["path"].lower().endswith("/users/authenticatebyname")], [], "nothing sent")

    async def test_quick_connect_off(self):
        await self.runtime(signed=False)
        flow = os.urandom(16).hex()
        await self.ok("signIn", {"flow": flow}, kind="ok")
        done = await self.h.frame("signInDone", flow=flow)
        self.assertFalse(done["ok"])
        self.assertIn("Quick Connect is off", done["message"])
        self.assertIn("Dashboard", done["message"])
        self.assertIsNone(await self.h.frame("signInCode", wait=0.5), "no code shown")


class Browsing(Base):
    async def test_home_rows(self):
        await self.runtime()
        s = await self.ok("home", kind="screen")
        rows = {r["id"]: r for r in s["rows"]}
        self.assertEqual(list(rows), ["continue", "nextup", "libraries", "latest"])
        cont = rows["continue"]["items"][0]
        self.assertEqual((cont["id"], cont["title"], cont["kind"]), ("play:m1", "Movie 1", "play"))
        self.assertAlmostEqual(cont["progress"], 0.125)
        self.assertEqual([i["id"] for i in rows["libraries"]["items"]], ["lib:libmovies:0", "lib:libshows:0"], "not Music: it plays video")
        self.assertEqual([i["id"] for i in rows["latest"]["items"]], ["item:m1", "item:m2", "series:s1"], "not a new album either")
        nxt = rows["nextup"]["items"][0]
        self.assertEqual((nxt["title"], nxt["subtitle"]), ("Show One", "S1 E2 · Episode 2"))
        for r in self.fake.requests:
            self.assertTrue(r["path"].startswith("/jellyfin/"), "everything under the base path: " + r["path"])
        auths = [r["auth"] for r in self.fake.requests if "/Users/" in r["path"]]
        self.assertTrue(auths and all('Token="' + self.tok + '"' in a for a in auths))

    async def test_library_pages(self):
        await self.runtime()
        s = await self.ok("browse", {"item": "lib:libmovies:0"}, kind="screen")
        items = items_of(s)
        self.assertEqual(len(items), 49, "a page of 48, then More")
        self.assertEqual(items[-1]["id"], "lib:libmovies:48")
        self.assertEqual(items[-1]["kind"], "open")
        self.assertIn("1 to 48 of 75", s["rows"][0]["title"])
        q = [r for r in self.requests("/Users/u1/Items") if r["query"].get("ParentId") == "libmovies"][0]["query"]
        self.assertEqual((q["StartIndex"], q["Limit"]), ("0", "48"))
        self.assertEqual(q.get("IncludeItemTypes"), "Movie,Series,Video,MusicVideo,BoxSet")
        await self.ok("browse", {"item": "folder:s1:0"}, kind="screen")
        q = [r for r in self.requests("/Users/u1/Items") if r["query"].get("ParentId") == "s1"][0]["query"]
        self.assertIn("Audio", q.get("ExcludeItemTypes", "").split(","), "a folder's songs aren't listed")
        s2 = await self.ok("browse", {"item": items[-1]["id"]}, kind="screen")
        items2 = items_of(s2)
        self.assertEqual(len(items2), 27, "the last page, no More")
        self.assertEqual(items2[0]["id"], "item:m49")
        # I on a library tile, or on More: what it is, not a 404
        for lib in ("lib:libmovies:0", "lib:libmovies:48"):
            d = await self.ok("details", {"item": lib}, kind="detail")
            self.assertEqual(d["title"], "Movies")

    async def test_series_seasons_episodes(self):
        await self.runtime()
        s = await self.ok("browse", {"item": "series:s1"}, kind="screen")
        self.assertEqual(s["title"], "Show One")
        rows = {r["id"]: r for r in s["rows"]}
        season = rows["seasons"]["items"][0]
        self.assertEqual((season["id"], season["kind"]), ("season:s1:se1", "open"))
        e = await self.ok("browse", {"item": season["id"]}, kind="screen")
        eps = items_of(e)
        self.assertEqual([i["id"] for i in eps], ["play:e1", "play:e2", "play:e3"])
        self.assertEqual(eps[0]["badge"], "WATCHED")
        self.assertTrue(eps[1]["title"].startswith("S1 E2"))

    async def test_details_and_actions(self):
        await self.runtime()
        d = await self.ok("details", {"item": "item:m1"}, kind="detail")
        self.assertEqual(d["title"], "Movie 1")
        facts = dict((f["label"], f["value"]) for f in d["facts"])
        self.assertEqual(facts["Year"], "1991")
        self.assertEqual(facts["Length"], "1 h 30 min")
        self.assertEqual(facts["Rated"], "PG-13")
        self.assertIn("two lines", d["text"])
        acts = [(a["id"], a["label"], a["kind"]) for a in d["actions"]]
        self.assertEqual(acts[0], ("play:m1", "Resume from 0:03", "play"))
        self.assertEqual(acts[1], ("start:m1", "From the beginning", "play"))
        self.assertIn(("watched", "Mark watched", "action"), acts)
        self.assertIn("token", d["image"])
        self.assertIn("token", d["backdrop"])
        d2 = await self.ok("action", {"item": "item:m1", "action": "watched"}, kind="detail")
        self.assertIn(("unwatched", "Mark unwatched", "action"), [(a["id"], a["label"], a["kind"]) for a in d2["actions"]])
        ep = await self.ok("details", {"item": "play:e2"}, kind="detail")
        facts = dict((f["label"], f["value"]) for f in ep["facts"])
        self.assertEqual((facts["Show"], facts["Episode"]), ("Show One", "S1 E2"))

    async def test_search(self):
        await self.runtime()
        s = await self.ok("search", {"query": "movie 7"}, kind="screen")
        self.assertEqual([i["title"] for i in items_of(s)], ["Movie 7"] + ["Movie %d" % n for n in range(70, 76)])

    async def test_images_through_the_broker(self):
        await self.runtime()
        s = await self.ok("home", kind="screen")
        img = s["rows"][0]["items"][0]["image"]
        self.assertEqual(list(img), ["token"], "the guide gets a token, never the server's link")
        self.assertNotIn(self.fake.url, json.dumps(s))
        n = len(self.h.frames)
        await self.h.rt.from_guide({"t": "image", "token": img["token"]})
        f = await self.h.frame("image", after=n, token=img["token"])
        self.assertIn("path", f, f)
        self.assertTrue(open(f["path"], "rb").read().startswith(b"\x89PNG"))
        self.assertEqual((f["w"], f["h"]), (200, 300), "its size, from its header")
        # each picture asked at a size that fits its box: Continue watching is
        # wide (movie 1 has no Thumb: its Backdrop), Recently added posters
        q = self.requests("/Images/Backdrop")[0]["query"]
        self.assertEqual(q["fillWidth"], "640")
        poster = next(r for r in s["rows"] if r["id"] == "latest")["items"][0]["image"]
        await self.h.rt.from_guide({"t": "image", "token": poster["token"]})
        await self.h.frame("image", after=n, token=poster["token"])
        self.assertEqual(self.requests("/Images/Primary")[0]["query"]["fillHeight"], "480")

    async def test_api3_rows_and_pictures(self):
        await self.runtime()
        s = await self.ok("home", kind="screen")
        rows = {r["id"]: r for r in s["rows"]}
        self.assertEqual({k: r["shape"] for k, r in rows.items()}, {"continue": "wide", "nextup": "wide", "libraries": "wide", "latest": "poster"})
        m1 = rows["latest"]["items"][0]
        self.assertEqual(m1["id"], "item:m1")
        self.assertEqual(sorted(m1["images"]), ["backdrop", "poster", "wide"], "movie 1 has no Thumb or Logo: its backdrop is its wide picture")
        self.assertEqual(m1["image"], m1["images"]["poster"], "its image: the picture for its row's shape")
        self.assertEqual(m1["meta"], "1991 · 1 h 30 min · PG-13 · ★ 7.5")
        self.assertEqual(m1["text"], "The story of movie 1.\nIt has two lines.")
        self.assertEqual(m1["watched"], False)
        m2 = rows["latest"]["items"][1]
        self.assertEqual(sorted(m2["images"]), ["backdrop", "logo", "poster", "wide"], "movie 2: a Thumb and a Logo of its own")
        self.assertNotEqual(m2["images"]["wide"], m2["images"]["backdrop"], "its wide picture is its Thumb")
        cont = rows["continue"]["items"][0]
        self.assertEqual(cont["image"], cont["images"]["wide"], "a wide row's card: its wide picture")
        nxt = rows["nextup"]["items"][0]
        self.assertEqual(sorted(nxt["images"]), ["backdrop", "logo", "poster", "wide"], "an episode: its own still, its show's poster, backdrop and logo")

    async def test_each_library_its_own_row(self):
        await self.runtime()
        movies = (await self.ok("browse", {"item": "lib:libmovies:0"}, kind="screen"))["rows"][0]
        shows = (await self.ok("browse", {"item": "lib:libshows:0"}, kind="screen"))["rows"][0]
        self.assertEqual((movies["id"], movies["shape"], movies["layout"]), ("lib-libmovies", "poster", "grid"), "its id, its kind's shape")
        self.assertEqual((shows["id"], shows["shape"]), ("lib-libshows", "poster"))
        more = (await self.ok("browse", {"item": "lib:libmovies:48"}, kind="screen"))["rows"][0]
        self.assertEqual(more["id"], "lib-libmovies", "its next page is the same row")

    async def test_details_cinematic_with_a_cast(self):
        await self.runtime()
        d = await self.ok("details", {"item": "item:m2"}, kind="detail")
        self.assertEqual((d["style"], d["meta"], d["chips"]), ("cinematic", "1992 · 1 h 30 min · PG-13 · ★ 7.5", ["Drama", "Comedy"]))
        self.assertIn("token", d["logo"], "its title logo")
        cast = next(r for r in d["rows"] if r["id"] == "cast")
        self.assertEqual((cast["shape"], [i["title"] for i in cast["items"]]), ("circle", ["Ann Actor", "Bob Actor"]), "its actors, not its director")
        self.assertEqual(cast["items"][0]["subtitle"], "Herself")
        self.assertIsNotNone(cast["items"][0]["image"])
        self.assertIsNone(cast["items"][1]["image"], "no picture: the guide shows the name")
        ep = await self.ok("details", {"item": "play:e2"}, kind="detail")
        self.assertEqual(ep["style"], "classic", "an episode's details are classic")
        films = await self.ok("browse", {"item": cast["items"][0]["id"]}, kind="screen")
        self.assertEqual(films["title"], "Ann Actor")
        row = films["rows"][0]
        self.assertEqual((row["id"], row["shape"], len(row["items"])), ("filmography", "poster", 11), "the ten movies and the show she's in")
        q = self.requests("/Users/u1/Items")[-1]["query"]
        self.assertEqual(q["PersonIds"], "p1")

    async def test_seasons_are_posters_and_episodes_wide(self):
        await self.runtime()
        s = await self.ok("browse", {"item": "series:s1"}, kind="screen")
        self.assertEqual({r["id"]: r["shape"] for r in s["rows"]}, {"nextup": "wide", "seasons": "poster"})
        e = await self.ok("browse", {"item": "season:s1:se1"}, kind="screen")
        row = e["rows"][0]
        self.assertEqual((row["id"], row["shape"]), ("episodes", "wide"))
        ep = row["items"][1]
        self.assertEqual(ep["image"], ep["images"]["wide"], "an episode's card: its still")
        self.assertEqual((ep["meta"], ep["watched"]), ("25 min", False))
        self.assertTrue(row["items"][0]["watched"], "episode 1 is watched")

    async def test_home_rows_for_home(self):
        await self.runtime()
        rows = await self.ok("homeRow", {"key": "continue"}, kind="rows")
        self.assertEqual(rows[0]["id"], "play:m1")
        latest = await self.ok("homeRow", {"key": "latest"}, kind="rows")
        self.assertEqual(len(latest), 3)

    async def test_expired_token(self):
        await self.runtime()
        self.fake.expire_token()
        r = await self.h.call("home")
        self.assertEqual(r["kind"], "error")
        self.assertEqual(r["value"]["code"], "signedout")
        self.assertIn("Sign out, then Sign in again", r["value"]["text"], "an action the settings page actually offers")
        self.assertEqual(self.h.rt.state, "ready", "a plain message, not a crash")

    async def test_sign_out(self):
        await self.runtime()
        await self.ok("signOut", kind="ok")
        out = self.events("/Sessions/Logout")
        self.assertEqual(len(out), 1)
        self.assertIn('Token="' + self.tok + '"', out[0]["auth"])
        self.assertIn(self.tok, self.fake.revoked)
        await self.h.stop("signIn")
        kept = json.load(open(self.h.cfg["secretsPath"]))
        self.assertEqual(kept["signIn"]["values"], {})
        store = json.load(open(self.h.cfg["storePath"]))
        self.assertNotIn("userId", store["keys"], "its storage marked server is forgotten")
        self.assertIn("deviceId", store["keys"], "the device id stays")
        self.h = None


class Playing(Base):
    async def play(self, item):
        v = await self.ok("play", {"item": item}, kind="play")
        self.assertRegex(v["url"], r"^http://127\.0\.0\.1:[0-9]+/[0-9a-f]{32}/media\.")
        self.assertNotIn(self.tok, json.dumps(v), "the token never reaches the guide")
        self.assertNotIn(str(self.fake.port), v["url"])
        return v

    async def report(self, v, seq, state, position, reason=None):
        args = {"session": v["session"], "seq": seq, "state": state, "position": position, "duration": 5400}
        if reason:
            args["reason"] = reason
        return await self.ok("playback", args, kind="ok")

    async def test_direct_play_and_reports(self):
        await self.runtime()
        v = await self.play("play:m1")
        self.assertEqual(v["startAt"], 3.0, "resumed where it was")
        info = self.events("/PlaybackInfo")[0]
        self.assertEqual(info["query"].get("StartTimeTicks"), str(3 * TICKS))
        prof = info["deviceProfile"]
        self.assertEqual(prof["MaxStreamingBitrate"], 20_000_000)
        self.assertEqual(prof["TranscodingProfiles"][0]["Protocol"], "hls")
        st, hd, body = await relay_get(v["url"])
        self.assertEqual(st, 200)
        self.assertEqual(body, open(os.path.join(MEDIA, "movie.mp4"), "rb").read())
        up = self.requests("/Videos/m1/stream")[-1]
        self.assertIn('Token="' + self.tok + '"', up["auth"], "the token went upstream, in the header")
        self.assertEqual(up["query"]["static"], "true")
        self.assertNotIn("api_key", up["query"])
        await self.report(v, 1, "started", 3)
        await self.report(v, 2, "progress", 13)
        await self.report(v, 3, "paused", 15)
        await self.report(v, 4, "resumed", 15)
        await self.report(v, 5, "stopped", 20.5, "user")
        ps = info["playSessionId"]
        started, = self.events("/Sessions/Playing")
        self.assertEqual((started["body"]["ItemId"], started["body"]["MediaSourceId"], started["body"]["PlaySessionId"]), ("m1", "src-m1", ps))
        self.assertEqual(started["body"]["PositionTicks"], 3 * TICKS)
        self.assertEqual(started["body"]["PlayMethod"], "DirectPlay")
        prog = self.events("/Sessions/Playing/Progress")
        self.assertEqual([(p["body"]["EventName"], p["body"]["PositionTicks"], p["body"]["IsPaused"]) for p in prog],
                         [("TimeUpdate", 13 * TICKS, False), ("Pause", 15 * TICKS, True), ("Unpause", 15 * TICKS, False)])
        stopped, = self.events("/Sessions/Playing/Stopped")
        self.assertEqual(stopped["body"]["PositionTicks"], int(20.5 * TICKS))
        self.assertEqual(stopped["body"]["PlaySessionId"], ps)
        self.assertFalse(stopped["body"]["Failed"])
        self.assertEqual(self.events("/Videos/ActiveEncodings"), [], "no transcode to end for direct play")

    async def test_from_the_beginning(self):
        await self.runtime()
        v = await self.play("start:m1")
        self.assertEqual(v["startAt"], 0.0)

    async def test_transcode_hls_and_cleanup(self):
        await self.runtime()
        v = await self.play("item:m2")
        st, hd, master = await relay_get(v["url"])
        self.assertEqual((st, hd["content-type"]), (200, "application/vnd.apple.mpegurl"))
        text = master.decode()
        self.assertNotIn(self.tok, text, "the token in Jellyfin's transcoding URL stays with the helper")
        self.assertNotIn(str(self.fake.port), text)
        child = [l for l in text.splitlines() if l.startswith("http://127.0.0.1:")][0]
        st, _, media = await relay_get(child)
        self.assertEqual(st, 200)
        segs = [l for l in media.decode().splitlines() if l.startswith("http://127.0.0.1:")]
        self.assertGreaterEqual(len(segs), 4)
        st, hd, seg = await relay_get(segs[0])
        self.assertEqual((st, hd["content-type"]), (200, "video/mp2t"))
        self.assertEqual(seg, open(os.path.join(MEDIA, "seg0.ts"), "rb").read())
        m = self.requests("/videos/m2/master.m3u8")[0]
        self.assertTrue(m["path"].startswith("/jellyfin/videos/"), "Jellyfin's TranscodingUrl is relative to the base path")
        await self.report(v, 1, "started", 0)
        await self.report(v, 2, "stopped", 4, "user")
        started, = self.events("/Sessions/Playing")
        self.assertEqual(started["body"]["PlayMethod"], "Transcode")
        enc, = self.events("/Videos/ActiveEncodings")
        ps = self.events("/PlaybackInfo")[0]["playSessionId"]
        self.assertEqual(enc["method"], "DELETE")
        self.assertEqual((enc["query"].get("PlaySessionId"), enc["query"].get("DeviceId")), (ps, "dev-test-1"))

    async def test_direct_stream_only_takes_the_transcode(self):
        """DirectPlay false but DirectStream true (an HEVC file, say): the
        transcode, never the file as it is"""
        await self.runtime()
        v = await self.play("item:m3")
        st, hd, _ = await relay_get(v["url"])
        self.assertEqual((st, hd["content-type"]), (200, "application/vnd.apple.mpegurl"))
        info = self.events("/PlaybackInfo")[0]
        self.assertEqual(info["query"].get("EnableDirectStream"), "false", "direct stream is never asked for")
        self.assertFalse(self.requests("/Videos/m3/stream"), "the file as it is was never fetched")

    async def test_cleanup_when_stopped_fails(self):
        await self.runtime()
        self.fake.fail_stopped = True
        v = await self.play("item:m2")
        await self.report(v, 1, "started", 0)
        await self.report(v, 2, "stopped", 4, "user")
        self.assertEqual(len(self.events("/Sessions/Playing/Stopped")), 1)
        self.assertEqual(len(self.events("/Videos/ActiveEncodings")), 1, "the transcode is ended even though Stopped failed")

    async def test_a_long_season_pages(self):
        await self.runtime()
        s = await self.ok("browse", {"item": "series:s1"}, kind="screen")
        seasons = {r["id"]: r for r in s["rows"]}["seasons"]["items"]
        self.assertEqual([x["id"] for x in seasons], ["season:s1:se1", "season:s1:se2"])
        e = await self.ok("browse", {"item": "season:s1:se2"}, kind="screen")
        eps = items_of(e)
        self.assertEqual(len(eps), 49, "48 episodes, then More")
        self.assertEqual(eps[-1]["id"], "season:s1:se2:48")
        e2 = await self.ok("browse", {"item": eps[-1]["id"]}, kind="screen")
        eps2 = items_of(e2)
        self.assertEqual(len(eps2), 12, "the last 12, no More")
        self.assertEqual(eps2[0]["id"], "play:s2e49")
        q = [r for r in self.requests("/Shows/s1/Episodes") if r["query"].get("seasonId") == "se2"][-1]["query"]
        self.assertEqual((q.get("StartIndex"), q.get("Limit")), ("48", "48"))
        d = await self.ok("details", {"item": "season:s1:se2:48"}, kind="detail")
        self.assertEqual(d["title"], "Season 2")

    async def test_fallback_to_a_transcode(self):
        await self.runtime()
        v = await self.play("play:m1")
        r = await self.h.call("playbackFailed", {"session": v["session"], "reason": "the player couldn't open it"})
        self.assertEqual(r["kind"], "play", json.dumps(r)[:400])
        v2 = r["value"]
        self.assertNotEqual(v2["session"], v["session"])
        failed, = self.events("/Sessions/Playing/Stopped")
        self.assertTrue(failed["body"]["Failed"], "the failed direct play is reported as failed")
        info2 = self.events("/PlaybackInfo")[1]
        self.assertEqual((info2["query"].get("EnableDirectPlay"), info2["query"].get("EnableDirectStream")), ("false", "false"))
        self.assertEqual(self.events("/PlaybackInfo")[0]["query"].get("EnableDirectStream"), "false")
        st, hd, body = await relay_get(v2["url"])
        self.assertEqual((st, hd["content-type"]), (200, "application/vnd.apple.mpegurl"))
        await self.report(v2, 1, "started", 3)
        self.assertEqual(self.events("/Sessions/Playing")[-1]["body"]["PlayMethod"], "Transcode")
        st, _, _ = await relay_get(v["url"])
        self.assertEqual(st, 404, "the first attempt's relay ids are gone")

    async def test_play_an_episode(self):
        await self.runtime()
        v = await self.play("play:e2")
        self.assertEqual((v["title"], v["subtitle"]), ("Show One", "S1 E2 · Episode 2"))


if __name__ == "__main__":
    os.makedirs(MEDIA, exist_ok=True)
    fakejf.make_media(MEDIA)
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
