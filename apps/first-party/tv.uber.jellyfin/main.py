"""Jellyfin: your Jellyfin server's movies and shows in Uber TV.

Sign in with Quick Connect (a code you enter in Jellyfin), then: continue
watching, next up, your libraries (a page at a time), what's new; a show's
seasons and episodes; a title's details; playing it. Jellyfin's own player
profile decides direct play or a transcode: direct play only for MP4 and MKV
with H.264 (up to High, level 5.1, 8-bit, 1920x1080) and AAC or MP3 (up to
6 channels) at up to 20 Mbps; everything else is transcoded to HLS within
those limits. The guide plays it through its relay; this app tells Jellyfin
where you are (started, progress, pause, stop) and ends its transcodes.

API 3: each row says its pictures' shape (each library's grid has its own
id, lib-<its id>, its kind giving its shape), every item hands over a
picture for each shape (a poster, a wide still, a backdrop, its title logo),
a line (year, length, rating, score) and its overview; a movie's or show's
details are cinematic, with its logo, genres and a row of its cast.

Works with Jellyfin 10.8 and later (Quick Connect's Initiate is a POST since
10.9; a GET is tried for older servers), on http or https, at the root or
behind a reverse proxy path (https://home.example/jellyfin). An https server
whose certificate this computer doesn't trust needs its certificate pinned
in this app's settings. A token Jellyfin has revoked shows as "signed out":
sign in again. Subtitles are off; audio is the media's default.
"""

import re
import threading
import uuid
from urllib.parse import quote, urlencode

import uber_tv
from uber_tv import (app, fetch, storage, secret, Screen, Row, Item, Detail, Action, Play, Message,
                     AppError, FetchError, log)

TICKS = 10_000_000          # Jellyfin counts time in 100 ns ticks
CLIENT, DEVICE, VERSION = "Uber TV", "Omarchy", "1.2.0"
PAGE = 48                   # a library page (a row holds 50; one more for "More")
MAX_BITRATE = 20_000_000

# What the guide's player plays without a transcode (the acceptance contract);
# Jellyfin transcodes everything else to HLS within the same limits
PROFILE = {
    "Name": "Uber TV",
    "MaxStreamingBitrate": MAX_BITRATE,
    "MaxStaticBitrate": MAX_BITRATE,
    "MusicStreamingTranscodingBitrate": 192000,
    "DirectPlayProfiles": [
        {"Container": "mp4,m4v,mkv", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac,mp3"},
    ],
    "TranscodingProfiles": [
        {"Container": "ts", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac", "Protocol": "hls",
         "Context": "Streaming", "MaxAudioChannels": "6", "MinSegments": 1, "BreakOnNonKeyFrames": True},
    ],
    "ContainerProfiles": [],
    "CodecProfiles": [
        {"Type": "Video", "Codec": "h264", "Conditions": [
            {"Condition": "EqualsAny", "Property": "VideoProfile", "Value": "high|main|baseline|constrained baseline", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "VideoLevel", "Value": "51", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "VideoBitDepth", "Value": "8", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "Width", "Value": "1920", "IsRequired": False},
            {"Condition": "LessThanEqual", "Property": "Height", "Value": "1080", "IsRequired": False},
        ]},
        {"Type": "VideoAudio", "Codec": "aac,mp3", "Conditions": [
            {"Condition": "LessThanEqual", "Property": "AudioChannels", "Value": "6", "IsRequired": False},
        ]},
    ],
    "SubtitleProfiles": [],
}

_cache = threading.local()


def begin():
    """Each answer reads the token, the user and the device id once"""
    _cache.d = {}


def cached(key, get):
    d = getattr(_cache, "d", None)
    if d is None:
        d = _cache.d = {}
    if key not in d:
        d[key] = get()
    return d[key]


def base():
    s = uber_tv.server
    if not s:
        raise AppError("Set your Jellyfin server first: this app's settings (,), then Your Jellyfin server.", "noserver")
    return s.rstrip("/")


def device_id():
    def get():
        d = storage.get("deviceId")
        if not d:
            d = uuid.uuid4().hex
            storage.put("deviceId", d)   # stable: not forgotten on sign-out
        return d
    return cached("device", get)


def token():
    return cached("token", lambda: secret("token"))


def user_id():
    return cached("user", lambda: storage.get("userId"))


def auth(tok=None):
    h = 'MediaBrowser Client="%s", Device="%s", DeviceId="%s", Version="%s"' % (CLIENT, DEVICE, device_id(), VERSION)
    if tok:
        h += ', Token="%s"' % tok
    return h


def api(path, method="GET", body=None, params=None, signed=True):
    """A Jellyfin API call (under the server's base path), its JSON or None"""
    url = base() + path
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    headers = {"Authorization": auth(token() if signed else None), "Accept": "application/json"}
    r = fetch(url, method=method, headers=headers, json=body)
    if r.status == 401 and signed:
        raise AppError("Jellyfin no longer accepts this sign-in. In this app's settings (,), choose Sign out, then Sign in again.", "signedout")
    if r.status >= 400:
        raise AppError("Jellyfin answered " + str(r.status) + " for " + path.split("?")[0] + ".", "status")
    if r.status == 204 or not r.body:
        return None
    try:
        return r.json()
    except ValueError:
        raise AppError("Jellyfin's answer wasn't JSON.", "json")


def items_of(data):
    if isinstance(data, list):
        return data
    return (data or {}).get("Items") or []


def server_name():
    def get():
        try:
            info = api("/System/Info/Public", signed=False) or {}
            return info.get("ServerName") or "Jellyfin"
        except AppError:
            raise
        except FetchError as e:
            raise AppError("Couldn't reach your Jellyfin server (" + str(e) + "). Check its address in this app's settings (,).", "unreachable")
    return cached("name", get)


# ---- what a card shows ----------------------------------------------------

def image(it, kind="Primary", height=360):
    """A picture of an item, from the server (fetched and checked by the
    guide's image broker), or None"""
    iid = it.get("Id")
    if kind == "Backdrop":
        tags = it.get("BackdropImageTags") or []
        if not tags and it.get("ParentBackdropImageTags") and it.get("ParentBackdropItemId"):
            iid, tags = it["ParentBackdropItemId"], it["ParentBackdropImageTags"]
        tag = tags[0] if tags else None
    else:
        tag = (it.get("ImageTags") or {}).get(kind)
        if not tag and it.get("SeriesPrimaryImageTag") and it.get("SeriesId"):
            iid, tag = it["SeriesId"], it["SeriesPrimaryImageTag"]
    if not tag or not iid:
        return None
    return base() + "/Items/%s/Images/%s?fillHeight=%d&quality=90&tag=%s" % (quote(iid), kind, height, quote(tag))


# each picture asked at a size that fits its box (the guide draws them at
# most 960 a side)
FIT = {"poster": ("fillHeight", 480), "wide": ("fillWidth", 640), "backdrop": ("fillWidth", 960),
       "logo": ("fillWidth", 480), "person": ("fillHeight", 360)}


def picture(iid, kind, tag, fit):
    if not iid or not tag:
        return None
    side, n = FIT[fit]
    return base() + "/Items/%s/Images/%s?%s=%d&quality=90&tag=%s" % (quote(iid), kind, side, n, quote(tag))


def first(tags):
    return (tags or [None])[0]


def pictures(it):
    """An item's pictures for each shape: its poster from Primary (an
    episode's is its show's); wide from Thumb then Backdrop (an episode's
    own Primary, a still, then its show's Thumb); its backdrop, then its
    parent's; its title logo, then its parent's"""
    t = it.get("Type") or ""
    iid = it.get("Id")
    tags = it.get("ImageTags") or {}
    out = {}
    if t == "Episode":
        out["poster"] = picture(it.get("SeriesId"), "Primary", it.get("SeriesPrimaryImageTag"), "poster")
        out["wide"] = (picture(iid, "Primary", tags.get("Primary"), "wide")
                       or picture(it.get("ParentThumbItemId") or it.get("SeriesId"), "Thumb", it.get("ParentThumbImageTag") or it.get("SeriesThumbImageTag"), "wide"))
    elif t in ("CollectionFolder", "UserView"):
        out["wide"] = picture(iid, "Primary", tags.get("Primary"), "wide")
    else:
        out["poster"] = picture(iid, "Primary", tags.get("Primary"), "poster") or picture(it.get("SeriesId"), "Primary", it.get("SeriesPrimaryImageTag"), "poster")
        out["wide"] = (picture(iid, "Thumb", tags.get("Thumb"), "wide") or picture(iid, "Backdrop", first(it.get("BackdropImageTags")), "wide")
                       or picture(it.get("ParentThumbItemId"), "Thumb", it.get("ParentThumbImageTag"), "wide"))
    out["backdrop"] = (picture(iid, "Backdrop", first(it.get("BackdropImageTags")), "backdrop")
                       or picture(it.get("ParentBackdropItemId"), "Backdrop", first(it.get("ParentBackdropImageTags")), "backdrop"))
    out["logo"] = picture(iid, "Logo", tags.get("Logo"), "logo") or picture(it.get("ParentLogoItemId"), "Logo", it.get("ParentLogoImageTag"), "logo")
    return {k: v for k, v in out.items() if v}


def meta(it):
    """Its line: year, length, rating, score"""
    parts = []
    if it.get("ProductionYear"):
        parts.append(str(it["ProductionYear"]))
    if it.get("RunTimeTicks"):
        parts.append(clock(it["RunTimeTicks"]))
    if it.get("OfficialRating"):
        parts.append(str(it["OfficialRating"]))
    if it.get("CommunityRating"):
        parts.append("★ %.1f" % it["CommunityRating"])
    return " · ".join(parts)


def row_id(prefix, jid):
    """A row id from a Jellyfin id (the guide takes lowercase letters,
    digits, - and _)"""
    return prefix + re.sub(r"[^a-z0-9_-]", "", str(jid).lower())[:59]


def clock(ticks):
    s = int((ticks or 0) // TICKS)
    h, m = s // 3600, s % 3600 // 60
    return ("%d h %02d min" % (h, m)) if h else ("%d min" % m)


def where(ticks):
    s = int((ticks or 0) // TICKS)
    return ("%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)) if s >= 3600 else ("%d:%02d" % (s // 60, s % 60))


def episode_label(it):
    return "S%d E%d" % (it.get("ParentIndexNumber") or 0, it.get("IndexNumber") or 0)


def progress(it):
    ud = it.get("UserData") or {}
    if ud.get("Played") or not ud.get("PlaybackPositionTicks"):
        return None
    pct = ud.get("PlayedPercentage")
    if pct is None and it.get("RunTimeTicks"):
        pct = 100.0 * ud["PlaybackPositionTicks"] / it["RunTimeTicks"]
    return max(0.0, min(1.0, (pct or 0) / 100.0))


def card(it, play=False, shape="poster"):
    """An item as a card: shows and folders open, the rest show their details
    (or play, in Continue watching and Next up). Its image is its picture for
    the row's shape; images, its pictures for every shape"""
    t = it.get("Type") or ""
    iid = it.get("Id") or ""
    title, sub = it.get("Name") or "Untitled", ""
    if t == "Episode":
        title = it.get("SeriesName") or title
        sub = episode_label(it) + " · " + (it.get("Name") or "")
    elif it.get("ProductionYear"):
        sub = str(it["ProductionYear"])
    played = bool((it.get("UserData") or {}).get("Played"))
    badge = "WATCHED" if played else ""
    pics = pictures(it)
    more = {"subtitle": sub, "image": pics.get(shape) or pics.get("poster") or pics.get("wide"), "images": pics,
            "meta": meta(it), "text": it.get("Overview") or "", "watched": played}
    if t == "Series":
        return Item("series:" + iid, title, badge=badge, kind="open", **more)
    if t == "Season":
        return Item("season:%s:%s" % (it.get("SeriesId") or "", iid), title, kind="open", **more)
    if t in ("BoxSet", "Folder", "CollectionFolder", "UserView"):
        return Item("folder:%s:0" % iid, title, kind="open", **more)
    if play:
        return Item("play:" + iid, title, badge=badge, progress=progress(it), kind="play", **more)
    return Item("item:" + iid, title, badge=badge, progress=progress(it), kind="info", **more)


def bare(item):
    """An item id without its prefix (item:, play:, start:)"""
    for p in ("item:", "play:", "start:"):
        if item.startswith(p):
            return item[len(p):]
    return item


def signed_in():
    return bool(token()) and bool(user_id())


FIELDS = "PrimaryImageAspectRatio,ProductionYear,SeriesPrimaryImageTag,Overview,Genres"
# a library's kind gives its grid's shape; one of another kind works it out
KIND_SHAPE = {"movies": "poster", "tvshows": "poster", "boxsets": "poster", "homevideos": "wide"}
# what this app can't play (it plays video): left out of what it lists
NOT_VIDEO_VIEWS = ("music", "books", "photos", "playlists")
NOT_VIDEO = "Audio,MusicAlbum,MusicArtist,AudioBook,Book,Photo,PhotoAlbum,Playlist"


def resume_items(limit=16):
    return items_of(api("/Users/%s/Items/Resume" % user_id(), params={"Limit": limit, "MediaTypes": "Video", "Fields": FIELDS}))


def latest_items(limit=20):
    found = items_of(api("/Users/%s/Items/Latest" % user_id(), params={"Limit": limit, "Fields": FIELDS}))
    return [x for x in found if x.get("Type") not in NOT_VIDEO.split(",")]


# ---- the screens ----------------------------------------------------------

@app.home
def home():
    begin()
    if not uber_tv.server:
        return Screen("Jellyfin", empty="Set your Jellyfin server: open this app's settings (,) and choose Your Jellyfin server. "
                                        "Its address is like http://192.168.1.20:8096.")
    name = server_name()
    if not signed_in():
        return Screen(name, empty="Sign in to " + name + ": open this app's settings (,) and choose Sign in. "
                                  "You'll get a code to enter in Jellyfin (Quick Connect).")
    uid = user_id()
    rows = []
    resume = resume_items()
    if resume:
        rows.append(Row("continue", "Continue watching", [card(x, play=True, shape="wide") for x in resume], shape="wide"))
    nextup = items_of(api("/Shows/NextUp", params={"userId": uid, "Limit": 16, "Fields": FIELDS}))
    if nextup:
        rows.append(Row("nextup", "Next up", [card(x, play=True, shape="wide") for x in nextup], shape="wide"))
    views = items_of(api("/Users/%s/Views" % uid))
    if views:
        rows.append(Row("libraries", "Your libraries",
                        [Item("lib:%s:0" % v["Id"], v.get("Name") or "Library", image=pictures(v).get("wide"), images=pictures(v), kind="open")
                         for v in views if v.get("Id") and v.get("CollectionType") not in NOT_VIDEO_VIEWS], shape="wide"))
    latest = latest_items()
    if latest:
        rows.append(Row("latest", "Recently added", [card(x) for x in latest], shape="poster"))
    return Screen(name, rows=rows, empty="Nothing in your libraries yet.")


@app.browse
def browse(item):
    begin()
    if not signed_in():
        raise AppError("Sign in first: this app's settings (,), then Sign in.", "signedout")
    uid = user_id()
    kind, _, rest = item.partition(":")
    if kind in ("lib", "folder"):
        pid, _, start = rest.rpartition(":")
        start = max(0, int(start or 0)) if start.isdigit() else 0
        parent = api("/Users/%s/Items/%s" % (uid, quote(pid))) or {}
        params = {"ParentId": pid, "StartIndex": start, "Limit": PAGE, "SortBy": "SortName", "SortOrder": "Ascending", "Fields": FIELDS}
        if kind == "lib" and parent.get("CollectionType") in ("movies", "tvshows", "homevideos", "musicvideos", "boxsets", None):
            params.update(Recursive="true", IncludeItemTypes="Movie,Series,Video,MusicVideo,BoxSet")
        else:
            params["ExcludeItemTypes"] = NOT_VIDEO   # a folder's songs, books and pictures
        data = api("/Users/%s/Items" % uid, params=params) or {}
        found = items_of(data)
        total = data.get("TotalRecordCount", len(found))
        # each library (or folder) its own row: its kind gives its shape
        shape = KIND_SHAPE.get(parent.get("CollectionType")) or ("poster" if parent.get("Type") == "BoxSet" else None)
        cards = [card(x, shape=shape or "poster") for x in found]
        if start + len(found) < total:
            cards.append(Item("%s:%s:%d" % (kind, pid, start + PAGE), "More…",
                              subtitle="%d to %d of %d" % (start + PAGE + 1, min(total, start + 2 * PAGE), total), kind="open"))
        title = parent.get("Name") or "Library"
        shown = "%s · %d to %d of %d" % (title, start + 1, start + len(found), total) if total > PAGE else title
        return Screen(title, rows=[Row(row_id("lib-", pid), shown, cards, layout="grid", shape=shape)], empty="Nothing here.")
    if kind == "person":
        # the movies and shows someone's in, in your libraries
        person = api("/Users/%s/Items/%s" % (uid, quote(rest))) or {}
        found = items_of(api("/Users/%s/Items" % uid, params={"PersonIds": rest, "Recursive": "true", "IncludeItemTypes": "Movie,Series",
                                                            "SortBy": "ProductionYear,SortName", "SortOrder": "Descending", "Limit": PAGE, "Fields": FIELDS}))
        rows = [Row("filmography", "Movies and shows", [card(x) for x in found], layout="grid", shape="poster")] if found else []
        return Screen(person.get("Name") or "Cast", rows=rows, empty="Nothing of theirs is in your libraries.")
    if kind == "series":
        series = api("/Users/%s/Items/%s" % (uid, quote(rest))) or {}
        seasons = items_of(api("/Shows/%s/Seasons" % quote(rest), params={"userId": uid, "Fields": FIELDS}))
        nextup = items_of(api("/Shows/NextUp", params={"userId": uid, "seriesId": rest, "Limit": 1, "Fields": FIELDS}))
        rows = []
        if nextup:
            rows.append(Row("nextup", "Next up", [card(x, play=True, shape="wide") for x in nextup], shape="wide"))
        cards = [card(dict(s, Type="Season", SeriesId=s.get("SeriesId") or rest)) for s in seasons[:PAGE]]
        if len(seasons) > PAGE:
            cards.append(Item("seasons:%s:%d" % (rest, PAGE), "More seasons…", kind="open"))
        rows.append(Row("seasons", "Seasons", cards, shape="poster"))
        return Screen(series.get("Name") or "Show", rows=rows, empty="No seasons.")
    if kind == "seasons":
        # a show with more seasons than a row holds: the rest, a page at a time
        series_id, _, start = rest.rpartition(":")
        start = int(start) if start.isdigit() else 0
        seasons = items_of(api("/Shows/%s/Seasons" % quote(series_id), params={"userId": uid, "Fields": FIELDS}))
        page = seasons[start:start + PAGE]
        cards = [card(dict(s, Type="Season", SeriesId=s.get("SeriesId") or series_id)) for s in page]
        if start + PAGE < len(seasons):
            cards.append(Item("seasons:%s:%d" % (series_id, start + PAGE), "More seasons…", kind="open"))
        return Screen("Seasons", rows=[Row("seasons", "Seasons %d to %d of %d" % (start + 1, start + len(page), len(seasons)), cards,
                                           layout="grid", shape="poster")])
    if kind == "season":
        series_id, _, rest2 = rest.partition(":")
        season_id, _, start = rest2.partition(":")
        start = int(start) if start.isdigit() else 0
        data = api("/Shows/%s/Episodes" % quote(series_id), params={"seasonId": season_id, "userId": uid, "Fields": FIELDS + ",Overview",
                                                                     "StartIndex": start, "Limit": PAGE}) or {}
        eps = items_of(data)
        total = data.get("TotalRecordCount", len(eps)) if isinstance(data, dict) else len(eps)
        cards = []
        for e in eps[:PAGE]:
            pics = pictures(e)
            played = bool((e.get("UserData") or {}).get("Played"))
            cards.append(Item("play:" + e["Id"], episode_label(e) + " · " + (e.get("Name") or ""), subtitle=clock(e.get("RunTimeTicks")) if e.get("RunTimeTicks") else "",
                              image=pics.get("wide") or pics.get("poster"), images=pics, meta=meta(e), text=e.get("Overview") or "", watched=played,
                              badge="WATCHED" if played else "", progress=progress(e), kind="play"))
        if start + len(eps[:PAGE]) < total:
            cards.append(Item("season:%s:%s:%d" % (series_id, season_id, start + PAGE), "More episodes…",
                              subtitle="%d to %d of %d" % (start + PAGE + 1, min(total, start + 2 * PAGE), total), kind="open"))
        title = (eps[0].get("SeriesName") if eps else "") or "Season"
        season = (eps[0].get("SeasonName") if eps else "") or "Episodes"
        if total > PAGE:
            season += " · %d to %d of %d" % (start + 1, start + len(eps[:PAGE]), total)
        return Screen(title, rows=[Row("episodes", season, cards, layout="grid", shape="wide")], empty="No episodes.")
    raise AppError("That isn't something this app opens.", "invalid")


@app.search
def search(query):
    begin()
    if not signed_in():
        raise AppError("Sign in first: this app's settings (,), then Sign in.", "signedout")
    found = items_of(api("/Users/%s/Items" % user_id(), params={"searchTerm": query[:100], "Recursive": "true", "Limit": 40,
                                                                  "IncludeItemTypes": "Movie,Series,Episode", "Fields": FIELDS}))
    return Screen("Search: " + query[:60], rows=[Row("results", "Results", [card(x) for x in found], layout="grid", shape="poster")] if found else [],
                  empty="Nothing matches " + query[:60] + ".")


@app.details
def details(item):
    begin()
    if not signed_in():
        raise AppError("Sign in first: this app's settings (,), then Sign in.", "signedout")
    uid = user_id()
    kind, _, rest = item.partition(":")
    if kind in ("lib", "folder"):
        # a library or a folder (or its "More…"): what it is; Enter opens it
        lib = api("/Users/%s/Items/%s" % (uid, quote(rest.rpartition(":")[0]))) or {}
        count = lib.get("ChildCount") or lib.get("RecursiveItemCount")
        return Detail(lib.get("Name") or "Library", subtitle=(str(count) + " items") if count else "",
                      text=lib.get("Overview") or "Enter opens it.", image=image(lib, "Primary", 480))
    if kind == "series":
        iid = rest
    elif kind == "season":
        iid = rest.split(":")[1] if ":" in rest else rest
    elif kind == "seasons":
        iid = rest.rpartition(":")[0]
    else:
        iid = bare(item)
    it = api("/Users/%s/Items/%s" % (uid, quote(iid))) or {}
    t = it.get("Type") or ""
    facts = []
    if t == "Episode":
        facts.append(("Show", it.get("SeriesName") or ""))
        facts.append(("Episode", episode_label(it)))
    if it.get("ProductionYear"):
        facts.append(("Year", str(it["ProductionYear"])))
    if it.get("RunTimeTicks"):
        facts.append(("Length", clock(it["RunTimeTicks"])))
    if it.get("OfficialRating"):
        facts.append(("Rated", it["OfficialRating"]))
    if it.get("CommunityRating"):
        facts.append(("Rating", "%.1f" % it["CommunityRating"]))
    if it.get("Genres"):
        facts.append(("Genres", ", ".join(it["Genres"][:3])))
    ud = it.get("UserData") or {}
    actions, rows = [], []
    if t in ("Series", "Season"):
        sid = iid if t == "Series" else (it.get("SeriesId") or "")
        nextup = items_of(api("/Shows/NextUp", params={"userId": uid, "seriesId": sid, "Limit": 1, "Fields": FIELDS}))
        if nextup:
            actions.append(Action("play:" + nextup[0]["Id"], "Play " + episode_label(nextup[0]), "play"))
        seasons = items_of(api("/Shows/%s/Seasons" % quote(sid), params={"userId": uid, "Fields": FIELDS}))
        if seasons:
            rows.append(Row("seasons", "Seasons", [card(dict(s, Type="Season", SeriesId=s.get("SeriesId") or sid)) for s in seasons]))
    else:
        if ud.get("PlaybackPositionTicks") and not ud.get("Played"):
            actions.append(Action("play:" + iid, "Resume from " + where(ud["PlaybackPositionTicks"]), "play"))
            actions.append(Action("start:" + iid, "From the beginning", "play"))
        else:
            actions.append(Action("start:" + iid, "Play", "play"))
        actions.append(Action("unwatched" if ud.get("Played") else "watched", "Mark unwatched" if ud.get("Played") else "Mark watched"))
    # its cast, each opening the movies and shows they're in
    cast = [p for p in (it.get("People") or []) if p.get("Type") == "Actor" and p.get("Id")][:20]
    if cast:
        rows.append(Row("cast", "Cast", [Item("person:" + p["Id"], p.get("Name") or "", subtitle=p.get("Role") or "",
                                              image=picture(p["Id"], "Primary", p.get("PrimaryImageTag"), "person"), kind="open")
                                         for p in cast], shape="circle"))
    subtitle = ""
    if t == "Episode":
        subtitle = it.get("SeriesName") or ""
    elif it.get("Taglines"):
        subtitle = it["Taglines"][0]
    return Detail(it.get("Name") or "Untitled", subtitle=subtitle, text=it.get("Overview") or "",
                  image=image(it, "Primary", 480), backdrop=image(it, "Backdrop", 720), facts=facts, actions=actions, rows=rows,
                  style="cinematic" if t in ("Movie", "Series") else "classic", logo=pictures(it).get("logo"), meta=meta(it),
                  chips=it.get("Genres") or [])


@app.action
def action(item, what):
    begin()
    iid = item[len("series:"):] if item.startswith("series:") else bare(item)
    if what == "watched":
        api("/Users/%s/PlayedItems/%s" % (user_id(), quote(iid)), method="POST")
        return details(item)
    if what == "unwatched":
        api("/Users/%s/PlayedItems/%s" % (user_id(), quote(iid)), method="DELETE")
        return details(item)
    raise AppError("That isn't something this app does.", "invalid")


# ---- playing --------------------------------------------------------------

def playback_info(iid, start_ticks, direct=True):
    # direct play or a transcode, never Jellyfin's direct stream: that sends the
    # file's own codecs, which the profile's direct-play limits didn't vouch for
    params = {"userId": user_id(), "StartTimeTicks": int(start_ticks), "IsPlayback": "true", "AutoOpenLiveStream": "true",
              "MaxStreamingBitrate": MAX_BITRATE, "EnableDirectStream": "false"}
    if not direct:
        params.update(EnableDirectPlay="false")
    info = api("/Items/%s/PlaybackInfo" % quote(iid), method="POST", params=params, body={"DeviceProfile": PROFILE}) or {}
    sources = info.get("MediaSources") or []
    if not sources:
        raise AppError("Jellyfin has nothing it can play for that.", "nosource")
    return sources[0], info.get("PlaySessionId") or ""


def stream_of(iid, src, session, direct=True):
    """The URL and method for a source: Jellyfin's file as it is, or its HLS
    transcode (the token goes in the Authorization header, never the URL,
    except where Jellyfin's own transcoding URL carries it)"""
    if direct and src.get("SupportsDirectPlay"):
        params = {"static": "true", "MediaSourceId": src.get("Id") or "", "DeviceId": device_id(), "PlaySessionId": session}
        if src.get("Container"):
            params["Container"] = src["Container"].split(",")[0]
        return base() + "/Videos/%s/stream?%s" % (quote(iid), urlencode(params)), "DirectPlay"
    url = src.get("TranscodingUrl") or ""
    if src.get("SupportsTranscoding") and url:
        return base() + ("" if url.startswith("/") else "/") + url, "Transcode"
    raise AppError("Jellyfin can't make that playable here.", "nosource")


def played(iid, start_ticks, direct=True, it=None):
    it = it or api("/Users/%s/Items/%s" % (user_id(), quote(iid))) or {}
    src, session = playback_info(iid, start_ticks, direct)
    url, method = stream_of(iid, src, session, direct)
    title = it.get("Name") or "Jellyfin"
    subtitle = ""
    if it.get("Type") == "Episode":
        title, subtitle = it.get("SeriesName") or title, episode_label(it) + " · " + (it.get("Name") or "")
    context = {"itemId": iid, "mediaSourceId": src.get("Id") or "", "playSessionId": session, "method": method,
               "liveStreamId": src.get("LiveStreamId") or "", "start": int(start_ticks)}
    return Play(url, headers={"Authorization": auth(token())}, title=title, subtitle=subtitle,
                start_at=start_ticks / TICKS, live=False, context=context)


@app.play
def play(item):
    begin()
    if not signed_in():
        raise AppError("Sign in first: this app's settings (,), then Sign in.", "signedout")
    iid = bare(item)
    it = api("/Users/%s/Items/%s" % (user_id(), quote(iid))) or {}
    start = 0
    ud = it.get("UserData") or {}
    if not item.startswith("start:") and not ud.get("Played"):
        start = ud.get("PlaybackPositionTicks") or 0
    return played(iid, start, True, it)


def report(ctx, state, position, reason=""):
    ticks = int(max(0, position) * TICKS)
    body = {"ItemId": ctx["itemId"], "MediaSourceId": ctx["mediaSourceId"], "PlaySessionId": ctx["playSessionId"],
            "PositionTicks": ticks, "PlayMethod": ctx["method"], "CanSeek": True, "IsPaused": state == "paused"}
    if ctx.get("liveStreamId"):
        body["LiveStreamId"] = ctx["liveStreamId"]
    if state == "started":
        api("/Sessions/Playing", method="POST", body=body)
    elif state == "stopped":
        body.pop("IsPaused")
        body["Failed"] = reason == "error"
        # each on its own: a report that fails doesn't leave a transcode running
        steps = [lambda: api("/Sessions/Playing/Stopped", method="POST", body=body)]
        if ctx["method"] == "Transcode":
            steps.append(lambda: api("/Videos/ActiveEncodings", method="DELETE",
                                     params={"DeviceId": device_id(), "PlaySessionId": ctx["playSessionId"]}))
        if ctx.get("liveStreamId"):
            steps.append(lambda: api("/LiveStreams/Close", method="POST", params={"LiveStreamId": ctx["liveStreamId"]}))
        first = None
        for step in steps:
            try:
                step()
            except (AppError, FetchError) as e:
                first = first or e
        if first:
            raise first
    else:
        body["EventName"] = {"paused": "Pause", "resumed": "Unpause"}.get(state, "TimeUpdate")
        api("/Sessions/Playing/Progress", method="POST", body=body)


@app.playback
def playback(event):
    begin()
    ctx = event.get("context") or {}
    if not ctx.get("itemId"):
        return
    try:
        report(ctx, event.get("state", ""), float(event.get("position") or 0), event.get("reason", ""))
    except (AppError, FetchError) as e:
        log("couldn't tell Jellyfin about", event.get("state"), ":", str(e))


@app.playback_failed
def playback_failed(event):
    """Direct play didn't work here: Jellyfin's HLS transcode instead (once)"""
    begin()
    ctx = event.get("context") or {}
    if ctx.get("method") == "DirectPlay" and ctx.get("itemId"):
        try:
            report(dict(ctx), "stopped", ctx.get("start", 0) / TICKS, "error")
        except (AppError, FetchError):
            pass
        return played(ctx["itemId"], ctx.get("start", 0), direct=False)
    return Message("Jellyfin's stream couldn't be played here (" + str(event.get("reason") or "it failed") + ").")


# ---- signing in and out ---------------------------------------------------

def signed_in_as(flow, data):
    """What Jellyfin gave back kept (its token, who you are), and done"""
    user = data.get("User") or {}
    flow.keep("token", data.get("AccessToken") or "")
    storage.put("userId", user.get("Id") or "", server=True)
    storage.put("userName", user.get("Name") or "", server=True)
    flow.done(True, "Signed in as " + (user.get("Name") or "you") + ".")


def sign_in_with_password(flow):
    """Your username and password, typed in the guide's own box, sent once to
    your server (AuthenticateByName); only the token it gives back is kept"""
    typed = flow.credentials()
    if typed is None:
        return   # called off: nothing to say
    name, password = typed
    res = fetch(base() + "/Users/AuthenticateByName", method="POST",
                headers={"Authorization": auth(), "Accept": "application/json"}, json={"Username": name, "Pw": password})
    name = password = typed = None   # let go of it at once
    if res.status == 401:
        flow.done(False, "Jellyfin didn't take that username and password.")
        return
    if res.status != 200:
        flow.done(False, "Jellyfin didn't sign you in (it answered " + str(res.status) + ").")
        return
    signed_in_as(flow, res.json())


@app.sign_in
def sign_in(flow):
    """Quick Connect: a code from the server, shown big; you enter it in
    Jellyfin (a signed-in app or the web, under Quick Connect); the server
    then gives this app its own token. Or, for a server with Quick Connect
    off, your username and password (flow.how)"""
    begin()
    if not uber_tv.server:
        flow.done(False, "Set your Jellyfin server first.")
        return
    if flow.how == "password":
        sign_in_with_password(flow)
        return
    hello = {"Authorization": auth(), "Accept": "application/json"}
    on = fetch(base() + "/QuickConnect/Enabled", headers=hello)
    if on.status != 200 or on.json() is not True:
        flow.done(False, "Quick Connect is off on this server: turn it on in Jellyfin's Dashboard → General, or sign in with your username and password.")
        return
    r = fetch(base() + "/QuickConnect/Initiate", method="POST", headers=hello)
    if r.status in (404, 405):
        r = fetch(base() + "/QuickConnect/Initiate", headers=hello)   # before 10.9
    if r.status == 401:
        flow.done(False, "Quick Connect is off on this server: turn it on in Jellyfin's Dashboard → General, or sign in with your username and password.")
        return
    if r.status != 200:
        flow.done(False, "Jellyfin didn't give a code (it answered " + str(r.status) + ").")
        return
    start = r.json()
    code, secret_ = start.get("Code") or "", start.get("Secret") or ""
    flow.show_code(code, url=base() + "/web/", expires=600)
    delay = 5
    while flow.sleep(delay):
        try:
            st = fetch(base() + "/QuickConnect/Connect?Secret=" + quote(secret_), headers=hello)
            if st.status != 200:
                raise FetchError("status", "it answered " + str(st.status))
            state = st.json()
            delay = 5
        except (FetchError, ValueError):
            delay = min(15, delay * 2)
            continue
        if state.get("Authenticated"):
            res = fetch(base() + "/Users/AuthenticateWithQuickConnect", method="POST", headers=hello, json={"Secret": secret_})
            if res.status != 200:
                flow.done(False, "Jellyfin didn't finish signing in (it answered " + str(res.status) + ").")
                return
            signed_in_as(flow, res.json())
            return
    if flow.over:
        return   # called off (Esc, leaving): nothing to say
    flow.done(False, "The code expired. Choose Sign in again for a new one.")


@app.sign_out
def sign_out():
    """The token revoked on the server (the guide forgets it either way)"""
    begin()
    if token():
        try:
            api("/Sessions/Logout", method="POST")
        except (AppError, FetchError) as e:
            log("couldn't sign out on the server:", str(e))


# ---- Home rows ------------------------------------------------------------

@app.home_row
def home_row(key):
    begin()
    if not signed_in():
        raise AppError("Sign in to Jellyfin first.", "signedout")
    if key == "continue":
        return [card(x, play=True, shape="wide") for x in resume_items(20)]
    if key == "latest":
        return [card(x) for x in latest_items(20)]
    raise AppError("No such row.", "invalid")


app.run()
