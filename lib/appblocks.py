"""What a code app may say, exactly: its frames (one JSON object a line) and
the blocks its screens are built from. Everything is checked against these
rules before the guide sees it; what passes is rebuilt from the checked
values only (plain text, finite numbers, known fields), never passed on as
the app wrote it. Kept free of the helper's state so it can be tested on its
own (tests/apprun.test.py).

Blocks are checked against the app's own API: API 2 exactly as it always
was, API 3 with a row's shape and size, hero rows, an item's pictures for
each shape, its line, text and watched mark, and a details page's style,
title logo, line and chips. An API 2 app that
sends an API 3 field is refused, like any unknown field."""

import json
import math
import re

MAX_LINE = 1024 * 1024
MAX_DEPTH = 12
MAX_SCREEN = 256 * 1024
MAX_CONTEXT = 4096
MAX_FETCH_BODY = 256 * 1024
FLOW_RE = re.compile(r"^[0-9a-f]{32}\Z")
HANDLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")   # a server an account lists, by the app's own name for it
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}\Z")
SECRET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
B64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}\Z")
# API 3: a row's id is protocol hygiene (it never reaches an agent): kept the
# same across versions and meaning one thing
ROW_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}\Z")
SHAPES = ("poster", "wide", "square", "logo", "circle")
SIZES = ("small", "medium", "large")
LAYOUTS = {2: ("row", "grid", "list"), 3: ("row", "grid", "list", "hero")}
PICTURES = ("poster", "wide", "square", "backdrop", "logo")
STYLES = ("classic", "cinematic")
HERO_ITEMS = 10
ITEM_FIELDS = {2: ("id", "title", "subtitle", "image", "badge", "progress", "kind")}
ITEM_FIELDS[3] = ITEM_FIELDS[2] + ("images", "meta", "text", "watched")
ROW_FIELDS = {2: ("id", "title", "layout", "items")}
ROW_FIELDS[3] = ROW_FIELDS[2] + ("shape", "size")
DETAIL_FIELDS = {2: ("title", "subtitle", "text", "image", "backdrop", "facts", "actions", "rows")}
DETAIL_FIELDS[3] = DETAIL_FIELDS[2] + ("style", "logo", "meta", "chips")
# api 4: a table row and a ticker row, an item's
# cells (a table's) and chart, a details page's chart; and a page (below)
LAYOUTS[4] = LAYOUTS[3] + ("table", "ticker")
ITEM_FIELDS[4] = ITEM_FIELDS[3] + ("cells", "chart")
ROW_FIELDS[4] = ROW_FIELDS[3] + ("columns",)
DETAIL_FIELDS[4] = DETAIL_FIELDS[3] + ("chart",)
TABLE_COLUMNS = 8
TICKER_ITEMS = 30
PAGE_SECTIONS = 30
PAGE_CHARS = 30000


class Violation(Exception):
    """The app broke the protocol: its runtime is stopped"""


class Invalid(Exception):
    """A result that isn't valid: the call fails, the app keeps running"""


# ---- strict JSON -----------------------------------------------------------

def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise Violation("a frame has the key " + repr(k)[:40] + " twice")
        out[k] = v
    return out


def _constant(name):
    raise Violation("a frame has " + name + " in it")


def depth(obj, limit=MAX_DEPTH):
    """How deep obj nests, stopping once it's past limit"""
    stack, deepest = [(obj, 1)], 0
    while stack:
        o, d = stack.pop()
        if d > deepest:
            deepest = d
            if d > limit:
                return d
        if isinstance(o, dict):
            stack.extend((v, d + 1) for v in o.values())
        elif isinstance(o, list):
            stack.extend((v, d + 1) for v in o)
    return deepest


SURROGATE_ESCAPE = re.compile(rb"\\u[dD][89a-fA-F]")


def lone_surrogate(obj):
    """Text anywhere in obj (names too) with a surrogate on its own: JSON's
    \\ud800 gives Python text that isn't Unicode, which can't be written out
    as UTF-8 again"""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, str):
            try:
                o.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(o, dict):
            stack.extend(o.keys())
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return False


def parse_frame(line):
    """One frame from its bytes (without the newline), or Violation"""
    if len(line) > MAX_LINE:
        raise Violation("a frame is longer than 1 MiB")
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        raise Violation("a frame isn't valid UTF-8")
    try:
        obj = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError) as e:
        if isinstance(e, Violation):
            raise
        raise Violation("a frame isn't valid JSON")
    if not isinstance(obj, dict):
        raise Violation("a frame isn't a JSON object")
    if depth(obj) > MAX_DEPTH:
        raise Violation("a frame nests deeper than " + str(MAX_DEPTH))
    # as invalid UTF-8 is: only looked for when an escape could make one
    if SURROGATE_ESCAPE.search(line) and lone_surrogate(obj):
        raise Violation("a frame has text that isn't Unicode (a lone surrogate)")
    return obj


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


# ---- frames from the app ---------------------------------------------------

def is_id(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 2 ** 31


def is_str(v, hi, lo=0):
    return isinstance(v, str) and lo <= len(v) <= hi


def is_b64(v, raw_limit):
    return isinstance(v, str) and len(v) <= (raw_limit + 2) // 3 * 4 and len(v) % 4 == 0 and B64_RE.match(v) is not None


# t -> (required fields, optional fields); "owner" means exactly one of
# parent (a call), flow (the sign-in) or view (a live view on the screen, api 4)
FRAMES = {
    "ready": ((), ()),
    "result": (("id",), ("screen", "detail", "play", "rows", "message", "ok", "error", "page")),
    "fetch": (("id", "owner", "url", "method"), ("headers", "body")),
    "storeGet": (("id", "owner", "key"), ()),
    "storePut": (("id", "owner", "key", "value"), ("server",)),
    "storeDel": (("id", "owner", "key"), ()),
    "storeList": (("id", "owner"), ()),
    "secretGet": (("id", "owner", "name"), ()),
    "secretSet": (("id", "flow", "name", "value"), ()),
    "signInCode": (("flow", "code", "url", "expires"), ()),
    "signInDone": (("flow", "ok", "message"), ()),
    "signInServers": (("flow", "servers"), ()),
    "update": (("view",), ("rows", "items")),
    "stream": (("id", "view", "url"), ()),
    "streamClose": (("id",), ()),
    "log": (("text",), ()),
}


def check_frame(f):
    """A frame's shape: its type, exactly its fields, each the right kind.
    What's wrong is a Violation (the app is stopped)."""
    t = f.get("t")
    if t not in FRAMES:
        raise Violation("a frame of an unknown type")
    need, may = FRAMES[t]
    keys = set(f) - {"t"}
    owner = "owner" in need
    allowed = set(need) | set(may) | ({"parent", "flow", "view"} if owner else set())
    allowed.discard("owner")
    if keys - allowed:
        raise Violation(t + " has fields it shouldn't: " + ", ".join(sorted(keys - allowed))[:80])
    for k in need:
        if k == "owner":
            if sum(1 for o in ("parent", "flow", "view") if o in f) != 1:
                raise Violation(t + " must name exactly one of parent, flow or view")
            if "view" in f and not is_id(f["view"]):
                raise Violation(t + "'s view isn't a view id")
            if "parent" in f and not is_id(f["parent"]):
                raise Violation(t + "'s parent isn't a call id")
            if "flow" in f and not (isinstance(f["flow"], str) and FLOW_RE.match(f["flow"])):
                raise Violation(t + "'s flow isn't a flow id")
        elif k not in f:
            raise Violation(t + " is missing " + k)
    if "id" in f and not is_id(f["id"]):
        raise Violation(t + "'s id isn't a number from 0 to 2^31")
    if t == "result":
        if len(keys) != 2:
            raise Violation("a result has exactly one of screen, detail, play, rows, message, ok or error")
    elif t == "fetch":
        if not is_str(f["url"], 4096, 1) or not is_str(f["method"], 8, 1):
            raise Violation("fetch's url or method isn't valid")
        if "headers" in f and not isinstance(f["headers"], dict):
            raise Violation("fetch's headers aren't an object")
        if "body" in f and not is_b64(f["body"], MAX_FETCH_BODY):
            raise Violation("fetch's body isn't base64 of at most 256 KiB")
    elif t in ("storeGet", "storePut", "storeDel"):
        if not is_str(f["key"], 128, 1):
            raise Violation(t + "'s key isn't 1 to 128 characters")
        if t == "storePut":
            if not is_b64(f["value"], 64 * 1024):
                raise Violation("storePut's value isn't base64 of at most 64 KiB")
            if "server" in f and not isinstance(f["server"], bool):
                raise Violation("storePut's server isn't true or false")
    elif t in ("secretGet", "secretSet"):
        if not (isinstance(f["name"], str) and SECRET_NAME_RE.match(f["name"])):
            raise Violation(t + "'s name isn't valid")
        if t == "secretSet":
            if not isinstance(f["flow"], str) or not FLOW_RE.match(f["flow"]):
                raise Violation("secretSet's flow isn't a flow id")
            if not is_str(f["value"], 4096) or "\0" in f["value"]:
                raise Violation("secretSet's value isn't up to 4 KB of text")
    elif t == "signInCode":
        if not (isinstance(f["flow"], str) and FLOW_RE.match(f["flow"])):
            raise Violation("signInCode's flow isn't a flow id")
        if not is_str(f["code"], 16, 1) or not is_str(f["url"], 500) or not is_num(f["expires"]):
            raise Violation("signInCode's code, url or expires isn't valid")
    elif t == "signInDone":
        if not (isinstance(f["flow"], str) and FLOW_RE.match(f["flow"])):
            raise Violation("signInDone's flow isn't a flow id")
        if not isinstance(f["ok"], bool) or not is_str(f["message"], 400):
            raise Violation("signInDone's ok or message isn't valid")
    elif t == "signInServers":
        if not (isinstance(f["flow"], str) and FLOW_RE.match(f["flow"])):
            raise Violation("signInServers' flow isn't a flow id")
        servers = f["servers"]
        if not isinstance(servers, list) or len(servers) > 10:
            raise Violation("signInServers has up to 10 servers")
        handles = set()
        for s in servers:
            if (not isinstance(s, dict) or set(s) != {"handle", "label", "urls"} or not isinstance(s["handle"], str)
                    or not HANDLE_RE.match(s["handle"]) or s["handle"] in handles or not is_str(s["label"], 80, 1)
                    or not isinstance(s["urls"], list) or not 1 <= len(s["urls"]) <= 8 or not all(is_str(u, 500, 1) for u in s["urls"])):
                raise Violation("a server in signInServers is { handle, label, urls: up to 8 addresses }, each handle once")
            handles.add(s["handle"])
    elif t == "update":
        if not is_id(f["view"]) or ("rows" in f) == ("items" in f) or not isinstance(f.get("rows", f.get("items")), list):
            raise Violation("an update names its view and has exactly one of rows (a screen's) or items (a Home row's)")
    elif t == "stream":
        if not is_id(f["view"]) or not is_str(f["url"], 4096, 1):
            raise Violation("a stream names its view and a url")
    elif t == "log":
        if not is_str(f["text"], 8192):
            raise Violation("a log line is longer than 8 KB")
    return t


def is_num(v):
    """A finite number, as JSON gave it: an integer too big for a float (a
    310-digit one parses) is refused, never an error"""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (OverflowError, ValueError):
        return False


# ---- blocks ------------------------------------------------------------------

def plain(v, hi, where, lines=0, required=False):
    """Plain text: no control characters (a newline only where lines > 0),
    at most hi characters"""
    if v is None:
        if required:
            raise Invalid(where + " is missing")
        return ""
    if not isinstance(v, str):
        raise Invalid(where + " isn't text")
    if len(v) > hi:
        raise Invalid(where + " is longer than " + str(hi) + " characters")
    for c in v:
        o = ord(c)
        if ((o < 0x20 and not (lines and c == "\n")) or 0x7F <= o < 0xA0 or o in (0x2028, 0x2029) or 0x202A <= o <= 0x202E
                or 0x2066 <= o <= 0x2069 or 0xD800 <= o <= 0xDFFF):
            raise Invalid(where + " has a control character")
    if lines and v.count("\n") >= lines:
        raise Invalid(where + " has more than " + str(lines) + " lines")
    if required and not v.strip():
        raise Invalid(where + " is empty")
    return v


def fields(obj, allowed, where):
    if not isinstance(obj, dict):
        raise Invalid(where + " isn't an object")
    extra = set(obj) - set(allowed)
    if extra:
        raise Invalid(where + " has fields it shouldn't: " + ", ".join(sorted(extra))[:80])
    return obj


def image_ref(v, where, images):
    """An image: a picture in the app's package, or a link (fetched later by
    the image broker); images(ref) checks it and returns what the guide gets"""
    if v is None:
        return None
    fields(v, ("asset", "url"), where)
    if len(v) != 1:
        raise Invalid(where + " is one of asset or url")
    if "asset" in v:
        if not is_str(v["asset"], 200, 1):
            raise Invalid(where + "'s asset isn't valid")
    elif not is_str(v["url"], 4096, 1):
        raise Invalid(where + "'s url isn't valid")
    return images(v, where)


class Budget:
    def __init__(self):
        self.items = 0


def choice(v, allowed, label):
    """One of allowed, or None when it's left out (label: what it is, for
    the message)"""
    if v is None:
        return None
    if v not in allowed:
        raise Invalid(label + " is " + ", ".join(allowed[:-1]) + " or " + allowed[-1])
    return v


def pictures(v, where, images):
    """API 3: an item's pictures, one for each shape it has one for"""
    if v is None:
        return {}
    fields(v, PICTURES, where)
    out = {}
    for k in PICTURES:
        ref = image_ref(v.get(k), where + "' " + k, images)
        if ref is not None:
            out[k] = ref
    return out


def item(v, where, images, budget, api=2):
    fields(v, ITEM_FIELDS[api], where)
    out = {"id": plain(v.get("id"), 200, where + "'s id", required=True),
           "title": plain(v.get("title"), 120, where + "'s title", required=True),
           "subtitle": plain(v.get("subtitle"), 120, where + "'s subtitle"),
           "badge": plain(v.get("badge"), 12, where + "'s badge"),
           "kind": v.get("kind", "open"),
           "image": image_ref(v.get("image"), where + "'s image", images),
           "progress": None}
    if out["kind"] not in ("open", "play", "info"):
        raise Invalid(where + "'s kind is open, play or info")
    p = v.get("progress")
    if p is not None:
        if not is_num(p) or not 0 <= p <= 1:
            raise Invalid(where + "'s progress is a number from 0 to 1")
        out["progress"] = float(p)
    if api >= 4:
        cells = v.get("cells")
        if cells is not None:
            if not isinstance(cells, list) or len(cells) > TABLE_COLUMNS:
                raise Invalid(where + "'s cells are a list of at most " + str(TABLE_COLUMNS))
            out["cells"] = [plain(c, 40, where + "'s cell " + str(n + 1)) for n, c in enumerate(cells)]
        if v.get("chart") is not None:
            out["chart"] = chart(v["chart"], where + "'s chart")
    if api >= 3:
        out["images"] = pictures(v.get("images"), where + "'s pictures", images)
        out["meta"] = plain(v.get("meta"), 80, where + "'s meta")
        out["text"] = plain(v.get("text"), 300, where + "'s text", lines=4)
        w = v.get("watched")
        if w is not None and not isinstance(w, bool):
            raise Invalid(where + "'s watched is true or false")
        out["watched"] = w
    budget.items += 1
    if budget.items > 200:
        raise Invalid("a screen has more than 200 items")
    return out


def chart(v, where):
    """API 4: a line the guide draws: 2 to 120 numbers, and what its low and
    high ends mean (no styling from the app)"""
    fields(v, ("points", "low", "high"), where)
    pts = v.get("points")
    if not isinstance(pts, list) or not 2 <= len(pts) <= 120 or not all(is_num(p) for p in pts):
        raise Invalid(where + "'s points are 2 to 120 numbers")
    return {"points": [float(p) for p in pts], "low": plain(v.get("low"), 24, where + "'s low"),
            "high": plain(v.get("high"), 24, where + "'s high")}


def columns_of(v, where):
    """API 4: a table row's columns, each a label and which side it keeps to"""
    if not isinstance(v, list) or not 1 <= len(v) <= TABLE_COLUMNS:
        raise Invalid(where + " has 1 to " + str(TABLE_COLUMNS) + " columns")
    out = []
    for n, c in enumerate(v):
        w = where + "'s column " + str(n + 1)
        fields(c, ("label", "align"), w)
        out.append({"label": plain(c.get("label"), 24, w + "'s label"), "align": choice(c.get("align"), ("start", "end"), w + "'s align") or "start"})
    return out


def items(v, where, images, budget, cap, api=2):
    if not isinstance(v, list):
        raise Invalid(where + " isn't a list")
    if len(v) > cap:
        raise Invalid(where + " has more than " + str(cap) + " items")
    out, seen = [], set()
    for n, x in enumerate(v):
        it = item(x, where + " item " + str(n + 1), images, budget, api)
        if it["id"] in seen:
            raise Invalid(where + " has the item id " + repr(it["id"])[:40] + " twice")
        seen.add(it["id"])
        out.append(it)
    return out


def rows_of(v, where, images, budget, cap, api=2, heroes=frozenset()):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > cap:
        raise Invalid(where + " is a list of at most " + str(cap) + " rows")
    out, seen = [], set()
    for n, r in enumerate(v):
        w = where + " row " + str(n + 1)
        fields(r, ROW_FIELDS[api], w)
        # API 3 leaves a layout it wasn't given unset, so app.json's default
        # for the row can apply; API 2's is a row (and null is refused)
        layout = r.get("layout", "row" if api < 3 else None)
        if api < 3 and layout is None:
            raise Invalid(w + "'s layout is row, grid or list")
        row = {"id": plain(r.get("id"), 64, w + "'s id", required=True),
               "title": plain(r.get("title"), 80, w + "'s title"),
               "layout": choice(layout, LAYOUTS[api], w + "'s layout")}
        if api >= 3:
            if not ROW_ID_RE.match(row["id"]):
                raise Invalid(w + "'s id is lowercase letters, digits, - and _, starting with a letter")
            row["shape"] = choice(r.get("shape"), SHAPES, w + "'s shape")
            row["size"] = choice(r.get("size"), SIZES, w + "'s size")
        if row["id"] in seen:
            raise Invalid(where + " has the row id " + repr(row["id"])[:40] + " twice")
        seen.add(row["id"])
        # a hero, said here or (its layout left out) in app.json, holds ten
        hero = row["layout"] == "hero" or (row["layout"] is None and row["id"] in heroes)
        lay = row["layout"]
        cap = HERO_ITEMS if hero else TICKER_ITEMS if lay == "ticker" else 50
        if api >= 4 and lay == "table":
            row["columns"] = columns_of(r.get("columns"), w)
        elif "columns" in r:
            raise Invalid(w + " has columns: only a table row does")
        row["items"] = items(r.get("items", []), w, images, budget, cap, api)
        for it in row["items"]:
            if lay == "table":
                if len(it.get("cells") or []) != len(row["columns"]):
                    raise Invalid(w + "'s item " + repr(it["id"])[:40] + " has " + str(len(it.get("cells") or [])) + " cells for " + str(len(row["columns"])) + " columns")
            elif "cells" in it:
                raise Invalid(w + "'s item " + repr(it["id"])[:40] + " has cells: only a table row's items do")
            if lay == "ticker" and (it["image"] or it.get("images") or it.get("chart")):
                raise Invalid(w + "'s item " + repr(it["id"])[:40] + " has a picture or a chart: a ticker's items are text")
        out.append(row)
    return out


def screen(v, images, api=2, heroes=frozenset()):
    fields(v, ("title", "rows", "refresh", "empty") + (("live",) if api >= 4 else ()), "the screen")
    budget = Budget()
    out = {"title": plain(v.get("title"), 80, "the screen's title"),
           "rows": rows_of(v.get("rows", []), "the screen", images, budget, 30, api, heroes),
           "empty": plain(v.get("empty"), 200, "the screen's empty text"),
           "refresh": None}
    r = v.get("refresh")
    if r is not None:
        if not is_num(r) or not 15 <= r <= 3600:
            raise Invalid("the screen's refresh is 15 to 3600 seconds")
        out["refresh"] = float(r)
    if api >= 4:
        lv = v.get("live", False)
        if not isinstance(lv, bool):
            raise Invalid("the screen's live is true or false")
        out["live"] = lv   # api 4: it may update its rows while it's on the screen
    return out


def detail(v, images, api=2, heroes=frozenset()):
    fields(v, DETAIL_FIELDS[api], "the details")
    budget = Budget()
    out = {"title": plain(v.get("title"), 120, "the details' title", required=True),
           "subtitle": plain(v.get("subtitle"), 200, "the details' subtitle"),
           "text": plain(v.get("text"), 4000, "the details' text", lines=60),
           "image": image_ref(v.get("image"), "the details' image", images),
           "backdrop": image_ref(v.get("backdrop"), "the details' backdrop", images),
           "facts": [], "actions": []}
    facts = v.get("facts", [])
    if not isinstance(facts, list) or len(facts) > 12:
        raise Invalid("the details' facts are a list of at most 12")
    for n, f in enumerate(facts):
        w = "fact " + str(n + 1)
        fields(f, ("label", "value"), w)
        out["facts"].append({"label": plain(f.get("label"), 40, w + "'s label", required=True),
                             "value": plain(f.get("value"), 120, w + "'s value")})
    acts = v.get("actions", [])
    if not isinstance(acts, list) or len(acts) > 6:
        raise Invalid("the details' actions are a list of at most 6")
    seen = set()
    for n, a in enumerate(acts):
        w = "action " + str(n + 1)
        fields(a, ("id", "label", "kind"), w)
        act = {"id": plain(a.get("id"), 64, w + "'s id", required=True),
               "label": plain(a.get("label"), 30, w + "'s label", required=True),
               "kind": a.get("kind", "action")}
        if act["kind"] not in ("action", "play"):
            raise Invalid(w + "'s kind is action or play")
        if act["id"] in seen:
            raise Invalid("the details have the action id " + repr(act["id"])[:40] + " twice")
        seen.add(act["id"])
        out["actions"].append(act)
    if api >= 3:
        out["style"] = choice(v.get("style"), STYLES, "the details' style")
        out["logo"] = image_ref(v.get("logo"), "the details' logo", images)
        out["meta"] = plain(v.get("meta"), 120, "the details' meta")
        chips = v.get("chips", [])
        if not isinstance(chips, list) or len(chips) > 8:
            raise Invalid("the details' chips are a list of at most 8")
        out["chips"] = [plain(c, 24, "chip " + str(n + 1), required=True) for n, c in enumerate(chips)]
    if api >= 4 and v.get("chart") is not None:
        out["chart"] = chart(v["chart"], "the details' chart")
    out["rows"] = rows_of(v.get("rows"), "the details", images, budget, 4 if api >= 3 else 3, api, heroes)
    return out


def page(v):
    """API 4: an article: a title and up to 30 sections, each a heading and
    its text (plain, its own lines kept), 30,000 characters in all"""
    fields(v, ("title", "sections"), "the page")
    out = {"title": plain(v.get("title"), 120, "the page's title", required=True), "sections": []}
    secs = v.get("sections", [])
    if not isinstance(secs, list) or len(secs) > PAGE_SECTIONS:
        raise Invalid("the page's sections are a list of at most " + str(PAGE_SECTIONS))
    total = len(out["title"])
    for n, sct in enumerate(secs):
        w = "the page's section " + str(n + 1)
        fields(sct, ("heading", "text"), w)
        one = {"heading": plain(sct.get("heading"), 80, w + "'s heading"), "text": plain(sct.get("text"), 4000, w + "'s text", lines=4001)}   # every line its 4,000 hold
        if not one["heading"] and not one["text"].strip():
            raise Invalid(w + " is empty")
        total += len(one["heading"]) + len(one["text"])
        out["sections"].append(one)
    if total > PAGE_CHARS:
        raise Invalid("the page is longer than " + str(PAGE_CHARS) + " characters")
    return out


def play(v):
    """A play result as the app sent it: the helper keeps the url, headers and
    context; the guide only ever gets a relay address"""
    fields(v, ("url", "headers", "title", "subtitle", "startAt", "live", "context"), "the play result")
    if not is_str(v.get("url"), 4096, 1):
        raise Invalid("the play result's url isn't valid")
    out = {"url": v["url"], "headers": v.get("headers") or {},
           "title": plain(v.get("title"), 120, "the play result's title"),
           "subtitle": plain(v.get("subtitle"), 200, "the play result's subtitle"),
           "startAt": 0.0, "live": False, "context": v.get("context")}
    if not isinstance(out["headers"], dict) or len(out["headers"]) > 16:
        raise Invalid("the play result's headers aren't valid")
    s = v.get("startAt", 0)
    if not is_num(s) or s < 0 or s > 10 ** 7:
        raise Invalid("the play result's startAt is a number of seconds, 0 or more")
    out["startAt"] = float(s)
    if "live" in v and not isinstance(v["live"], bool):
        raise Invalid("the play result's live is true or false")
    out["live"] = v.get("live", False)
    if out["context"] is not None and len(dumps(out["context"]).encode()) > MAX_CONTEXT:
        raise Invalid("the play result's context is bigger than 4 KB")
    return out


def message(v):
    fields(v, ("text",), "the message")
    return {"text": plain(v.get("text"), 400, "the message", required=True)}


def error(v):
    fields(v, ("code", "text"), "the error")
    code = v.get("code")
    if not (isinstance(code, str) and CODE_RE.match(code)):
        raise Invalid("the error's code isn't valid")
    return {"code": code, "text": plain(v.get("text"), 200, "the error's text")}


# what each method may answer (besides an error)
ANSWERS = {
    "home": ("screen",), "browse": ("screen",), "search": ("screen",), "details": ("detail",), "play": ("play",),
    "action": ("message", "screen", "detail"), "homeRow": ("rows",), "playback": ("ok",),
    "playbackFailed": ("play", "message"), "signIn": ("ok",), "signOut": ("ok",),
}


PAGE_ANSWERS = ("browse", "details", "action")   # api 4: what may answer with a page


def result(method, frame, images, api=2, heroes=frozenset()):
    """A result frame for a call of method, normalized: (kind, value),
    checked against the app's own API (2, 3 or 4: 4's results are 3's).
    heroes: the row ids its app.json makes heroes (their ten-item cap holds
    when a result leaves their layout out)"""
    if api not in (2, 3, 4):
        raise Invalid("not an API the guide speaks")
    kind = next(k for k in frame if k not in ("t", "id"))
    v = frame[kind]
    if kind == "error":
        return "error", error(v)
    if kind not in ANSWERS.get(method, ()) and not (kind == "page" and api >= 4 and method in PAGE_ANSWERS):
        raise Invalid(method + " can't answer with " + kind)
    if kind == "screen":
        out = screen(v, images, api, heroes)
    elif kind == "detail":
        out = detail(v, images, api, heroes)
    elif kind == "play":
        out = play(v)
    elif kind == "message":
        out = message(v)
    elif kind == "page":
        out = page(v)
    elif kind == "rows":
        budget = Budget()
        out = items(v, "the row", images, budget, 50, api)
    else:
        if v is not True:
            raise Invalid("ok is true")
        out = True
    if kind in ("screen", "detail", "rows", "page") and len(dumps(out).encode()) > MAX_SCREEN:
        raise Invalid("the " + kind + " is bigger than 256 KB")
    return kind, out


def call_args(method, args):
    """The arguments a call carries, checked on the way out (they come from
    the guide, so this is a guard against the guide's own mistakes)"""
    shapes = {"home": (), "browse": ("item",), "details": ("item",), "search": ("query",), "play": ("item",),
              "action": ("item", "action"), "homeRow": ("key",), "signIn": ("flow", "how"), "signOut": (),
              "playback": ("session", "seq", "state", "position", "duration", "reason", "context"),
              "playbackFailed": ("session", "reason", "context")}
    if method not in shapes or not isinstance(args, dict) or set(args) - set(shapes[method]):
        raise Invalid("not a call the guide makes")
    return args
