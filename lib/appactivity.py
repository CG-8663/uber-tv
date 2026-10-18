"""An app's Activity: which sites it contacted, how often and how much, and
which it tried and was refused. Daily totals,
never a line per request: no path, query, header, body or time of a request
is kept, since any of them can hold a secret.

Two parts, kept differently:
- what it did: for each day and each site it may use (its net hosts and its
  server, a short list app.json fixes), per kind of request and whether it
  read or changed things, how many, bytes each way, answers by class, when
  last; and each day's refused requests, counted by why, without names.
  Kept for 90 days, always.
- the names of refused sites, each once, with how many times it was refused
  each day (kept 90 days too, like the rest), best effort: at most 50 new a
  day, in a budget of their own. When it's full the ones seen longest ago
  go. Losing them never touches the first part, so an app trying long or
  many addresses can't push its real history out.

Kept free of the helper's state so it can be tested on its own
(tests/apprun.test.py). The helper writes it (bin/om-pg-apprun); om-pg-apps
activity reads it for the guide."""

import json
import re
import time

DAYS = 90
MAX_FILE = 1024 * 1024
NAMES_BUDGET = 64 * 1024
NEW_NAMES_A_DAY = 50
MAX_SITES = 32
MAX_NAME = 260
KINDS = {"fetch": "f", "image": "i", "media": "m", "stream": "s"}
DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
# a bucket: requests, bytes sent, bytes received, answers 2xx 3xx 4xx 5xx,
# failed (no answer), and when last (seconds into its day)
N, SENT, RECV, C2, C3, C4, C5, FAILED, LAST = range(9)
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


class Activity:
    def __init__(self, raw=None, now=time.time):
        self.now = now
        self.sites = []            # [name, is the server], each once
        self.days = {}             # "2026-10-14" -> {"a": {site index: {bucket: [...]}}, "x": {code: n}, "nn": new names}
        self.names = {}            # refused name -> {"d": {day: [times, of them changes it may not make there]}, "l": when last}
        self.load(raw)

    # ---- reading and writing ----
    def load(self, raw):
        try:
            d = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(d, dict) or d.get("v") != 1:
                return
            sites = d.get("sites", [])
            if isinstance(sites, list) and len(sites) <= MAX_SITES and all(
                    isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and 0 < len(x[0]) <= MAX_NAME
                    and x[1] in (0, 1) for x in sites):
                self.sites = [[x[0], x[1]] for x in sites]
            for day, v in (d.get("days") or {}).items():
                if not (isinstance(day, str) and DAY_RE.match(day) and isinstance(v, dict)):
                    continue
                try:
                    time.strptime(day, "%Y-%m-%d")
                except ValueError:
                    continue
                a = {}
                for i, buckets in (v.get("a") or {}).items():
                    if not (i.isdigit() and int(i) < len(self.sites) and isinstance(buckets, dict)):
                        continue
                    a[int(i)] = {k: [int(n) for n in b] for k, b in buckets.items()
                                 if k in BUCKETS and isinstance(b, list) and len(b) == 9 and all(isinstance(n, int) and n >= 0 for n in b)}
                x = {c: n for c, n in (v.get("x") or {}).items() if isinstance(c, str) and len(c) <= 16 and isinstance(n, int) and n >= 0}
                nn = v.get("nn", 0)
                self.days[day] = {"a": a, "x": x, "nn": nn if isinstance(nn, int) and nn >= 0 else 0}
            for name, v in (d.get("names") or {}).items():
                if not (isinstance(name, str) and 0 < len(name) <= MAX_NAME and isinstance(v, dict)
                        and isinstance(v.get("l"), int) and isinstance(v.get("d"), dict)):
                    continue   # (one kept another way, before: its names go, its daily totals stay)
                days = {day: [int(x[0]), int(x[1])] for day, x in v["d"].items()
                        if isinstance(day, str) and DAY_RE.match(day) and isinstance(x, list) and len(x) == 2
                        and all(isinstance(n, int) and n >= 0 for n in x) and x[0] > 0 and x[1] <= x[0]}
                if days:
                    self.names[name] = {"d": days, "l": v["l"]}
        except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
            self.sites, self.days, self.names = [], {}, {}
        self.prune()

    def dumps(self):
        """The file, at most MAX_FILE bytes: past it, names go first, then
        the oldest days"""
        self.prune()
        while True:
            out = json.dumps({"v": 1, "sites": self.sites,
                              "days": {d: {"a": {str(i): b for i, b in v["a"].items()}, "x": v["x"], "nn": v["nn"]}
                                       for d, v in self.days.items()},
                              "names": self.names}, separators=(",", ":")).encode()
            if len(out) <= MAX_FILE:
                return out
            if self.names:
                self.drop_names(len(out) - MAX_FILE)
            elif self.days:
                del self.days[min(self.days)]
            else:
                return out

    # ---- keeping it bounded ----
    def today(self):
        return time.strftime("%Y-%m-%d", time.localtime(self.now()))

    def prune(self):
        """The last 90 days; sites no day uses any more let go"""
        cut = time.strftime("%Y-%m-%d", time.localtime(self.now() - DAYS * 86400))
        for d in [d for d in self.days if d <= cut]:
            del self.days[d]
        for n in list(self.names):
            days = self.names[n]["d"]
            for d in [d for d in days if d <= cut]:
                del days[d]
            if not days:
                del self.names[n]
        self.compact()

    def compact(self):
        used = sorted(set(i for v in self.days.values() for i in v["a"]))
        if used == list(range(len(self.sites))):
            return
        renum = {old: new for new, old in enumerate(used)}
        self.sites = [self.sites[i] for i in used]
        for v in self.days.values():
            v["a"] = {renum[i]: b for i, b in v["a"].items()}

    def name_size(self, n):
        return len(n) + 24 + 24 * len(self.names[n]["d"])

    def names_size(self):
        return sum(self.name_size(n) for n in self.names)

    def drop_names(self, room):
        """The names seen longest ago go, until room bytes are freed"""
        freed = 0
        for n in sorted(self.names, key=lambda n: self.names[n]["l"]):
            if freed >= room:
                break
            freed += self.name_size(n)
            del self.names[n]

    def site(self, name, server):
        key = [name, 1 if server else 0]
        if key in self.sites:
            return self.sites.index(key)
        self.prune()
        while len(self.sites) >= MAX_SITES and self.days:
            del self.days[min(self.days)]   # only a server changed again and again gets here
            self.compact()
        self.sites.append(key)
        return len(self.sites) - 1

    def day(self):
        d = self.today()
        if d not in self.days:
            self.days[d] = {"a": {}, "x": {}, "nn": 0}
        return self.days[d]

    # ---- counting ----
    def seconds(self):
        t = time.localtime(self.now())
        return t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec

    def contacted(self, kind, name, server, method, status, sent):
        """A request sent to an allowed site (status None: no answer)"""
        b = self.bucket(kind, name, server, method)
        b[N] += 1
        b[SENT] += max(0, int(sent))
        if status is None:
            b[FAILED] += 1
        elif 200 <= status < 600:
            b[C2 + status // 100 - 2] += 1
        b[LAST] = self.seconds()

    def received(self, kind, name, server, method, n):
        self.bucket(kind, name, server, method)[RECV] += max(0, int(n))

    def failed(self, kind, name, server, method):
        b = self.bucket(kind, name, server, method)
        b[N] += 1
        b[FAILED] += 1
        b[LAST] = self.seconds()

    def bucket(self, kind, name, server, method):
        i = self.site(name, server)
        key = KINDS.get(kind, "f") + ("w" if method in WRITES else "")
        return self.day()["a"].setdefault(i, {}).setdefault(key, [0] * 9)

    def refused(self, code, name=None):
        """A request the rules refused: counted by why; its site's name kept
        if there's room (name None: it had none that could be read), marked
        when it was a change the app may not make there (code method)"""
        d = self.day()
        code = str(code)[:16]
        d["x"][code] = d["x"].get(code, 0) + 1
        if not name or len(name) > MAX_NAME:
            return
        t, change, today = int(self.now()), 1 if code == "method" else 0, self.today()
        if name not in self.names:
            if d["nn"] >= NEW_NAMES_A_DAY:
                return
            d["nn"] += 1
            self.names[name] = {"d": {}, "l": t}
        v = self.names[name]
        times = v["d"].setdefault(today, [0, 0])
        times[0] += 1
        times[1] += change
        v["l"] = t
        over = self.names_size() - NAMES_BUDGET
        if over > 0:
            self.drop_names(over)

    # ---- for the guide ----
    def summary(self):
        """Each site contacted (newest first) with its totals, and the
        refused names kept (newest first), with how many more were refused"""
        sites = {}
        for day in sorted(self.days):
            base = time.mktime(time.strptime(day, "%Y-%m-%d"))
            for i, buckets in self.days[day]["a"].items():
                name, server = self.sites[i]
                s = sites.setdefault(i, {"site": name, "server": server == 1, "reads": 0, "writes": 0, "sent": 0,
                                         "received": 0, "failed": 0, "kinds": [], "last": 0})
                for key, b in buckets.items():
                    s["writes" if key.endswith("w") else "reads"] += b[N]
                    s["sent"] += b[SENT]
                    s["received"] += b[RECV]
                    s["failed"] += b[FAILED]
                    kind = next(k for k, v in KINDS.items() if v == key[0])
                    if kind not in s["kinds"]:
                        s["kinds"].append(kind)
                    s["last"] = max(s["last"], int(base) + b[LAST])
        refused_total = sum(n for v in self.days.values() for n in v["x"].values())
        named = sorted(({"site": n, "count": sum(x[0] for x in v["d"].values()), "last": v["l"],
                         "change": any(x[1] for x in v["d"].values())} for n, v in self.names.items()), key=lambda r: -r["last"])
        return {"sites": sorted(sites.values(), key=lambda s: -s["last"]), "refused": named,
                "refusedMore": max(0, refused_total - sum(r["count"] for r in named)), "days": DAYS}


BUCKETS = {v + w for v in KINDS.values() for w in ("", "w")}
