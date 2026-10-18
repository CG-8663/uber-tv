"""Unknown sources: the sources you added, each
pinned by its one key, and what's fetched from them. bin/om-pg-apps loads it
by its path and does the asking; nothing here runs unless you turned Unknown
sources on and added a source with the computer's password (the guide asks
for it, Sources.qml).

A source is one https folder: source.pub (exactly one Ed25519 key, as
`ssh-ed25519 <base64>`), catalog.json (the catalog's format) and
catalog.json.sig (ssh-keygen -Y sign, namespace uber-tv-source). Everything
fetched goes through lib/appnet.py: https on port 443, the source's own host
only (a redirect elsewhere is refused), its addresses public, checked before
connecting and after every redirect, TLS checked; each answer capped and
given a minute.

Kept in sources.json (0600, written whole, changed under the folder's lock):
up to 20 sources, each { id, url, name, key, fingerprint, keyGen, pastKeys,
added, seen, seenSha, pending, rev, life }. id is source:<16 hex> of its first key's SHA-256 and
never changes, so what's installed from it stays with it. key is the one
accepted now; pastKeys the ones before, kept only so apps installed under
them still verify (never for anything new). seen is the newest list's
`updated` and seenSha its SHA-256: an older list is refused, and so is a
different one made the same second (only that list again is taken). pending is a different key the source
publishes now: until you accept it, with the computer's password, nothing
new comes from the source and its list isn't used. A key it used before is
never accepted again. rev goes up with every change to a source, so a fetch
that began before another changed it (even back to how it was) never
commits over it; life is random, made when it's added, so work begun for
a source you removed never touches one added again with the same key (and
so the same id).

Each list that verified is kept byte for byte with its signature, by its
SHA-256, in the source's own folder under the state folder (the current one
and the one before), so an install can check exactly what you saw (M6); and
the checked entries beside them (list.json) for the guide to show.

Kept free of the helper's other state so it can be tested on its own
(tests/sources.test.py)."""

import asyncio
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unicodedata

MAX_SOURCES = 20
MAX_LIST = 2 * 1024 * 1024
MAX_SIG = 8 * 1024
MAX_PUB = 4 * 1024
MAX_STORE = 512 * 1024
MAX_PAST = 16
MAX_SNAPSHOT = 64 * 1024
# what the guide reads of one answer (Apps.qml's runner), and what one
# source's list may take of it as the helper prints it (list.json, as
# source-list, add and fetch print it): its record (public: at most 4 KiB)
# beside it and room to spare, so all MAX_SOURCES of them fit in one
MAX_ANSWER = 8 * 1024 * 1024
MAX_SHOWN = MAX_ANSWER // MAX_SOURCES - 8 * 1024
MAX_PACKAGE = 20 * 1024 * 1024
SECONDS = 60
PACKAGE_SECONDS = 180
NAMESPACE = "uber-tv-source"
ID_RE = re.compile(r"^source:[0-9a-f]{16}\Z")
FP_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}\Z")
KEY_RE = re.compile(r"^ssh-ed25519 ([A-Za-z0-9+/]{68})\Z")
SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")
# an Ed25519 key's blob: its type's length and name, then 32 bytes
KEY_HEAD = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"
STAGE_LIFE = 3600
RESOLVER = None      # tests/sources.test.py: where names point


class Problem(Exception):
    """Something wrong with a source, in words for the user"""


# ---- keys ------------------------------------------------------------------

def parse_key(data):
    """source.pub: exactly one Ed25519 key, `ssh-ed25519 <base64>`, nothing
    else but a final newline: (that line, its fingerprint)"""
    try:
        line = data.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        raise Problem("its source.pub isn't one Ed25519 key")
    if line.endswith("\n"):
        line = line[:-1]
    m = KEY_RE.match(line)
    if not m:
        raise Problem("its source.pub isn't one Ed25519 key (ssh-ed25519 and the key, nothing else)")
    blob = base64.b64decode(m.group(1), validate=True)
    if len(blob) != len(KEY_HEAD) + 32 or not blob.startswith(KEY_HEAD) or base64.b64encode(blob).decode() != m.group(1):
        raise Problem("its source.pub isn't one Ed25519 key")
    return line, fingerprint(blob)


def blob_of(line):
    return base64.b64decode(line.split(" ")[1])


def fingerprint(blob):
    """As ssh-keygen -l shows it"""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def source_id(line):
    return "source:" + hashlib.sha256(blob_of(line)).hexdigest()[:16]


def folder_of(sid):
    """A source's folder name: never a free string on disk (as om-pg-apps'
    source_dir names an app's)"""
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise Problem("that isn't one of your sources")
    return hashlib.sha256(sid.encode()).hexdigest()[:16]


def verify(data, sig, line):
    """The list's signature checked against this key only (an allowed-signers
    file made from it, in a private folder); Problem if it isn't by that key"""
    with tempfile.TemporaryDirectory(prefix="om-pg-source-") as d:
        signers, sig_path = os.path.join(d, "signers"), os.path.join(d, "sig")
        for path, body in ((signers, (NAMESPACE + ' namespaces="' + NAMESPACE + '" ' + line + "\n").encode()), (sig_path, sig)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(body)
        try:
            r = subprocess.run(["/usr/bin/ssh-keygen", "-Y", "verify", "-f", signers, "-I", NAMESPACE, "-n", NAMESPACE, "-s", sig_path],
                               input=data, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            raise Problem("couldn't check its list's signature: " + str(e)[:80])
    if r.returncode != 0:
        raise Problem("its list's signature isn't by the source's key, so it was refused")


# ---- links -----------------------------------------------------------------

def parse_link(net, raw):
    """A source's link as you pasted it: its folder (canonical: https, port
    443, no ?part) and its host, and the fingerprint a #key= gives"""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2048:
        raise Problem("that isn't a link")
    link, _, frag = raw.strip().partition("#")
    want = ""
    if frag:
        m = re.match(r"^key=(SHA256:[A-Za-z0-9+/]{43})\Z", frag)
        if not m:
            raise Problem("the link's # part isn't a key (#key=SHA256:…)")
        want = m.group(1)
    if not link.startswith("https://"):
        raise Problem("a source's link starts with https://")
    try:
        u = net.parse_url(link)
    except net.NetError as e:
        raise Problem(str(e))
    if u.port != 443:
        raise Problem("a source is on https's usual port")
    if u.query:
        raise Problem("a source's link has no ? part")
    path = u.path
    if path.endswith("/catalog.json"):
        path = path[:-len("catalog.json")]
    elif not path.endswith("/"):
        path += "/"
    return str(net.Url("https", u.host, 443, path, "")), u.host, want


def host_of(net, url):
    return net.parse_url(url).host


# ---- fetching ----------------------------------------------------------------

async def _get(net, url, host, limit, what):
    res = await net.request(net.Rules([host]), url, "GET", None, None, net.Gate(), resolver=RESOLVER)
    try:
        if res.status != 200:
            raise Problem(what + " wasn't there (the site answered " + str(res.status) + ")")
        try:
            return await res.body(limit)
        except net.NetError as e:
            if e.code == "toobig":
                raise Problem(what + " is bigger than " + net.size_words(limit) + ", so it was refused")
            raise
    finally:
        res.close()


def get(net, url, host, limit, what, seconds=None):
    """One file of the source's: its bytes, at most limit, within a minute
    (a package: three)"""
    seconds = seconds or SECONDS

    async def one():
        try:
            return await asyncio.wait_for(_get(net, url, host, limit, what), seconds)
        except asyncio.TimeoutError:
            raise Problem("getting " + what + " took longer than " + ("a minute" if seconds <= 60 else str(int(seconds // 60)) + " minutes"))
        except net.NetError as e:
            raise Problem("couldn't get " + what + ": " + str(e))
    return asyncio.run(one())


def get_key(net, base, host):
    return get(net, base + "source.pub", host, MAX_PUB, "its source.pub")


def get_list(net, base, host):
    return (get(net, base + "catalog.json", host, MAX_LIST, "its list"),
            get(net, base + "catalog.json.sig", host, MAX_SIG, "its list's signature"))


# ---- the store ---------------------------------------------------------------

@contextlib.contextmanager
def held(path):
    """sources.json's folder held while it's read, changed and written, so
    two changes never cross (never across a fetch: only around the change)"""
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def read_plain(path, limit, what):
    """A plain file of ours (never a link, a pipe or a device), at most limit"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Problem("couldn't read " + what + ": " + (e.strerror or str(e)))
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Problem(what + " isn't a plain file")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise Problem(what + " is too big")
    return data


def write_whole(path, data, mode=0o600):
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_int(v, lo=0):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v < 2 ** 53


def checked_key(k, where):
    if not isinstance(k, dict) or not isinstance(k.get("key"), str):
        raise Problem(where)
    line, fp = parse_key(k["key"].encode("ascii", "replace"))
    if k.get("fingerprint") != fp:
        raise Problem(where)
    return {"key": line, "fingerprint": fp}


def checked_source(s):
    """One source as kept, every field checked: anything else and the whole
    store is refused (losing a pin quietly would trust a key again)"""
    bad = "sources.json has a source that isn't right"
    if not isinstance(s, dict) or set(s) - {"id", "url", "name", "key", "fingerprint", "keyGen", "pastKeys", "added", "seen", "seenSha", "pending", "rev", "life"}:
        raise Problem(bad)
    out = checked_key(s, bad)
    if not isinstance(s.get("id"), str) or not ID_RE.match(s["id"]):
        raise Problem(bad)
    url = s.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or not url.endswith("/") or len(url) > 2048:
        raise Problem(bad)
    name = s.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 60:
        raise Problem(bad)
    past = s.get("pastKeys", [])
    if not isinstance(past, list) or len(past) > MAX_PAST:
        raise Problem(bad)
    for k in ("keyGen", "added", "seen", "rev"):
        if not is_int(s.get(k)):
            raise Problem(bad)
    if not isinstance(s.get("seenSha"), str) or not SHA_RE.match(s["seenSha"]):
        raise Problem(bad)
    if not isinstance(s.get("life"), str) or not re.match(r"^[0-9a-f]{32}\Z", s["life"]):
        raise Problem(bad)
    # its name as it's shown now: one kept before a rule caught it gives way
    # to its host (the url's, as parse_link made it)
    out.update(id=s["id"], url=url, name=shown_name(name, url[len("https://"):].split("/")[0]), keyGen=s["keyGen"], added=s["added"],
               seen=s["seen"], seenSha=s["seenSha"], rev=s["rev"], life=s["life"], pastKeys=[checked_key(k, bad) for k in past])
    if s.get("pending") is not None:
        out["pending"] = checked_key(s["pending"], bad)
    return out


def load(path):
    """The store: [source], [] before the first; Problem if it can't be read"""
    data = read_plain(path, MAX_STORE, "your sources")
    if data is None:
        return []
    try:
        d = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Problem("your sources (sources.json) can't be read")
    if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("sources"), list) or len(d["sources"]) > MAX_SOURCES:
        raise Problem("your sources (sources.json) can't be read")
    out = [checked_source(s) for s in d["sources"]]
    if len({s["id"] for s in out}) != len(out) or len({s["url"] for s in out}) != len(out):
        raise Problem("sources.json has the same source twice")
    return out


def save(path, sources):
    write_whole(path, (json.dumps({"v": 1, "sources": sources}, indent=1) + "\n").encode())


def find(sources, sid):
    for s in sources:
        if s["id"] == sid:
            return s
    raise Problem("that isn't one of your sources")


def public(s):
    """What the guide is told of a source (the keys themselves stay here)"""
    out = {"id": s["id"], "url": s["url"], "name": s["name"], "fingerprint": s["fingerprint"], "keyGen": s["keyGen"],
           "added": s["added"], "seen": s["seen"], "keyChanged": "", "life": s["life"]}
    if s.get("pending"):
        out["keyChanged"] = s["pending"]["fingerprint"]
    return out


def all_keys(s):
    return [s["key"]] + [k["key"] for k in s["pastKeys"]]


# Hidden, control and unknown characters, and the Hangul fillers (letters
# that draw nothing): ways to make one name look like another
HIDDEN = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
FILLERS = "\u115f\u1160\u3164\uffa0"
# Characters (as NFKD leaves them) that can pass for the Latin letters of
# "ubertv": each one Unicode's confusables data (UTS #39, Unicode 17, as
# ICU 78 has it) draws as one of them, or as a variant LATIN_NAME reads,
# its marks and a dot or tick beside it left out (letters of other
# scripts, Latin letters whose names don't say, symbols); and by hand, ones
# it doesn't: Cyrillic letters by their sound too, union, tack and "or"
# signs, crosses and daggers, check marks, money and registered signs, box
# lines, and the Chinese, Bopomofo and Korean letters fancy text spells it
# with. Accents come off by NFKD, and Latin's other variants are read by
# their names (LATIN_NAME)
LOOKALIKES = {
    "u": ("\u01b1\u01b2\u028a\u028b\u03bc\u03c5\u040f\u0423\u0426\u0443\u0446\u045f\u054d\u057d\u1200\u13cc\u144c\u1457\u1458\u1467"
          "\u2210\u222a\u228d\u228e\u2294\u22c3\u2a03\u2a04\u2a06\u3129\u51f5\ua4f4\ua79e\ua79f\uab9c\U000104ce\U000104f6\U000118b8"
          "\U000118d8\U00016f42"),
    "b": ("\u00df\u0184\u0185\u0392\u03b2\u0411\u0412\u042a\u042c\u0431\u0432\u044a\u044c\u0462\u0463\u048c\u048d\u0e3f\u13cf\u13f4"
          "\u13fc\u1472\u1473\u147e\u147f\u1480\u1481\u1488\u15af\u15f7\u1e9e\u20bf\u266d\u2c82\u2c83\u4e43\ua4d0\ua7b4\ua7b5\uab9f"
          "\U00010282\U000102a1\U00010301\U00016eb6"),
    "e": ("\u0190\u025b\u0395\u03b5\u0404\u0415\u0435\u0454\u04bc\u04bd\u04bf\u1110\u13ac\u156e\u15f4\u20ac\u212e\u2208\u220a\u22ff"
          "\u2c88\u2c89\u2d39\u4e47\ua4f0\uab32\uab7c\U00010286\U000118a6\U000118ae"),
    "r": ("\u00ae\u01a6\u0413\u0420\u0433\u0440\u0490\u0491\u0493\u0580\u13a1\u13d2\u1587\u16b1\u1d26\u211e\u211f\u2c84\u2c85\u5c3a"
          "\ua4e3\uab48\uab71\uab81\uaba2\U000104b4\U00016f35\U0001d216"),
    "t": ("\u03a4\u03c4\u0422\u0442\u04ac\u04ad\u116e\u13a2\u13bf\u16cf\u2020\u20ae\u22a4\u22ba\u2361\u23c9\u252c\u252f\u2530\u2533"
          "\u2564\u2565\u2566\u271d\u271e\u271f\u27d9\u2adf\u2ca6\u2ca7\u3112\u4e01\u4e05\ua4d4\ua68c\ua68d\uab72\U00010297\U000102b1"
          "\U00010315\U000118bc\U00016f0a\U0001f768"),
    "v": ("\u01b2\u028b\u03bd\u03c5\u0412\u0432\u0474\u0475\u05d8\u0667\u06f7\u13d9\u142f\u143a\u143b\u221a\u2228\u22c1\u22ce\u2713"
          "\u2714\u2d38\ua4e6\ua6df\uaba9\U00010197\U0001051d\U00011706\U000118a0\U000118c0\U00016f08\U0001d20d\U0001f708"),
}
# Letters that pass for punctuation (the same data draws them as ! ? ' .
# / and the like, and the clicks look like | and ||): they join what's
# around them, as punctuation does
JOINERS = ("\u00f0\u01c0\u01c1\u01c2\u01c3\u0241\u0242\u0294\u05d9\u05f2\u0660\u06f0\u097d\u13ae\u1427\u1433\u1437\u1438\u1440\u1441"
           "\u1444\u1445\u144a\u16b2\u16cc\u2cb2\u2cb3\u2cb4\u2cb5\u2cb7\u2cba\u2cbb\u2cc6\u2cc7\u2d48\u2d51\u304f\u30ce\u4e36\u4e3f"
           "\ua6eb\ua778\ua78b\ua78c\ua78f\ua830\U0001029b\U0001031f\U000118a8\U00016f3f\U0001e8c8\U0001e8cc\U0001e8cd\U00021fe8")
# Latin letters read by their names: a small capital, a letter with a bar
# or a hook, and boxed or flag letters (which NFKD leaves as they are)
LATIN_NAME = re.compile(r"^(?:(?:NEGATIVE CIRCLED |NEGATIVE SQUARED )?LATIN (?:CAPITAL |SMALL |SMALL CAPITAL )?LETTER (?:SMALL CAPITAL )?"
                        r"|REGIONAL INDICATOR SYMBOL LETTER )([A-Z])(?: |\Z)")
# Scripts written together (Chinese, Japanese and Korean, with Latin); any
# other mix is a way to make one name look like another
TOGETHER = ({"LATIN", "CJK", "HIRAGANA", "KATAKANA"}, {"LATIN", "CJK", "BOPOMOFO"}, {"LATIN", "CJK", "HANGUL"})


def lookalikes():
    """LOOKALIKES by character: the letters each can pass for"""
    out = {}
    for letter, chars in LOOKALIKES.items():
        for c in chars:
            out[c] = out.get(c, "") + letter
    return out


READS = lookalikes()


def reads_as(c):
    """The Latin letters a character can pass for ("" for none): a plain
    letter itself; one of another script, or a symbol, by READS; Latin's
    own variants by their names"""
    if c.isascii():
        return c.lower() if c.isalpha() else ""
    m = LATIN_NAME.match(unicodedata.name(c, ""))
    return READS.get(c, "") + (m.group(1).lower() if m else "")


def claims_uber_tv(name):
    """It reads "Uber TV" however it's spelled, spaced or disguised: wide,
    bold and circled letters made plain and accents split off (NFKD), each
    character read as the letters it can pass for. Spaces and accents join
    what's around them, and so can punctuation, symbols and the letters that
    pass for them (an apostrophe, JOINERS): a union sign joins, or reads as
    a U. One character that reads as none may stand in for one of its
    letters (a lookalike no table knows), where the name is words of its
    own: a plain letter never stands in, and a name that only runs into it
    (Cyber TV, Hubert's apps, Tube-TV) is kept"""
    seq = []   # each character: (the letters it reads as, whether it can be left out, whether it can stand in)
    for whole in name:
        parts = []
        for c in unicodedata.normalize("NFKD", whole):
            kind, r = unicodedata.category(c), reads_as(c)
            if kind[0] != "M":
                parts.append((r, not c.isalnum() or kind == "Lm" or c in JOINERS, not r and kind[0] != "Z"))
        if len(parts) > 1 and not any(r for r, _, _ in parts):
            # one character NFKD makes several that read as none (a
            # fraction, a Hangul syllable, a circled number): it's drawn as
            # one, so it stands in as one
            parts = [("", all(j for _, j, _ in parts), any(s for _, _, s in parts))]
        seq += parts
    # each way of reading it so far: (letters of "ubertv" read, 0 if it began
    # inside a word, 1 if where one begins, 2 once its stand-in is used)
    tries = set()
    for i, (r, joins, stands) in enumerate(seq):
        after = set()
        for n, how in tries | {(0, 1 if i == 0 or seq[i - 1][1] else 0)}:
            if joins:
                after.add((n, how))
            if "ubertv"[n] in r:
                after.add((n + 1, how))
            elif stands and how == 1:
                after.add((n + 1, 2))
        ends = i + 1 == len(seq) or seq[i + 1][1]
        if any(n == 6 and (how < 2 or ends) for n, how in after):
            return True
        tries = {(n, how) for n, how in after if n < 6}
    return False


def scripts(name):
    """The scripts of a name's letters (NFKD first), by the first word of
    each one's Unicode name; modifier letters (an apostrophe, a tone mark),
    which go with any script, left out"""
    out = set()
    for c in unicodedata.normalize("NFKD", name):
        if c.isalpha():
            word = unicodedata.name(c, "?").split()[0]
            if word != "MODIFIER":
                out.add({"IDEOGRAPHIC": "CJK", "KATAKANA-HIRAGANA": "KATAKANA"}.get(word, word))
    return out


def shown_name(name, host):
    """The list's name for the source, unless it's empty, has hidden,
    control or unknown characters (a zero-width space, a right-to-left
    override, a Hangul filler: ways to make one name look like another, as
    app names may not), mixes scripts (a Cyrillic letter among Latin ones;
    Chinese, Japanese and Korean as they're written are fine), or claims to
    be Uber TV's own however it's spelled, spaced or disguised (accents,
    small capitals, other scripts' lookalike letters, symbols, or one
    character no table knows in a letter's place): then its host"""
    name = name.strip()[:60] if isinstance(name, str) else ""
    if not name or any(unicodedata.category(c) in HIDDEN or c in FILLERS for c in name):
        return host[:60]
    found = scripts(name)
    if (len(found) > 1 and not any(found <= ok for ok in TOGETHER)) or claims_uber_tv(name):
        return host[:60]
    return name


# ---- what's kept from each fetch ----------------------------------------------

def sha(data):
    return hashlib.sha256(data).hexdigest()


def keep(state_root, sid, data, sig, shown, key_gen):
    """A list that verified, kept byte for byte with its signature by its
    SHA-256 (this one and the one before; older ones deleted), and the
    entries the guide shows (list.json, with the key generation that verified
    it: shown only while that's still the source's); its SHA-256. Called
    under the store's lock, with the decision to take the list."""
    folder = os.path.join(state_root, folder_of(sid))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    h = sha(data)
    if not os.path.isfile(os.path.join(folder, h + ".json")):
        write_whole(os.path.join(folder, h + ".json"), data)
    # the signature just verified, always: the same bytes signed again by a
    # new key must be checkable with that key
    write_whole(os.path.join(folder, h + ".sig"), sig)
    kept = read_json(os.path.join(folder, "kept.json")) or {}
    cur = kept.get("current") if isinstance(kept.get("current"), str) and SHA_RE.match(kept["current"]) else ""
    if cur != h:
        kept = {"current": h, "previous": cur}
    keepers = {kept["current"], kept.get("previous") or ""}
    write_whole(os.path.join(folder, "kept.json"), json.dumps(kept).encode())
    write_whole(os.path.join(folder, "list.json"), json.dumps(dict(shown, listSha256=h, keyGen=key_gen)).encode())
    for name in os.listdir(folder):
        m = re.match(r"^([0-9a-f]{64})\.(?:json|sig)\Z", name)
        if m and m.group(1) not in keepers:
            os.unlink(os.path.join(folder, name))
    return h


def read_json(path, limit=8 * 1024 * 1024):
    try:
        data = read_plain(path, limit, os.path.basename(path))
        return json.loads(data.decode("utf-8")) if data is not None else None
    except (Problem, UnicodeDecodeError, ValueError, RecursionError):
        return None


def printed(shown):
    """How many bytes the guide is shown of a list (list.json), printed as
    om-pg-apps prints it (say)"""
    return len(json.dumps(shown, separators=(",", ":")))


def fits(shown, h, key_gen):
    """A list the guide is shown (shown, with its SHA-256 and key generation,
    as list.json keeps it) within MAX_SHOWN; Problem if not, before
    anything is staged, saved or kept"""
    if printed(dict(shown, listSha256=h, keyGen=key_gen)) > MAX_SHOWN:
        raise Problem("its list is too big for the guide to show, so it was refused")


def shown_list(state_root, s):
    """The entries kept from the source's last list, or None: none while its
    key changed, nor one verified under a key it had before (a past key
    never shows anything new), nor one too big to show beside the others
    (kept before lists were held to MAX_SHOWN)"""
    d = read_json(os.path.join(state_root, folder_of(s["id"]), "list.json"))
    if not isinstance(d, dict) or not isinstance(d.get("apps"), list) or d.get("keyGen") != s["keyGen"] or s.get("pending"):
        return None
    if printed(d) > MAX_SHOWN:
        return None
    return d


# ---- staging what you're shown before adding ----------------------------------

def tidy(staging):
    now = time.time()
    try:
        names = os.listdir(staging)
    except OSError:
        return
    for name in names:
        path = os.path.join(staging, name)
        try:
            if SHA_RE.match(name) and now - os.lstat(path).st_mtime > STAGE_LIFE:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def stage_hash(url, pub, data, sig):
    return sha(json.dumps([url, sha(pub), sha(data), sha(sig)]).encode())


def stage(staging, url, pub, data, sig):
    """What the preview fetched, kept privately by its hash until you add it
    (or an hour passes): adding pins exactly these bytes"""
    os.makedirs(staging, mode=0o700, exist_ok=True)
    tidy(staging)
    h = stage_hash(url, pub, data, sig)
    final = os.path.join(staging, h)
    if os.path.isdir(final):
        shutil.rmtree(final, ignore_errors=True)
    tmp = tempfile.mkdtemp(dir=staging, prefix=".stage-")
    for name, body in (("url", url.encode()), ("source.pub", pub), ("catalog.json", data), ("catalog.json.sig", sig)):
        write_whole(os.path.join(tmp, name), body)
    os.replace(tmp, final)
    return h


def staged(staging, h):
    """What a preview kept: (url, pub, list, sig), checked against its hash"""
    if not isinstance(h, str) or not SHA_RE.match(h):
        raise Problem("that isn't a source you were shown")
    folder = os.path.join(staging, h)
    gone = Problem("what you were shown is gone: add the source again")
    parts = []
    for name, limit in (("url", 4096), ("source.pub", MAX_PUB), ("catalog.json", MAX_LIST), ("catalog.json.sig", MAX_SIG)):
        try:
            data = read_plain(os.path.join(folder, name), limit, name)
        except Problem:
            raise gone
        if data is None:
            raise gone
        parts.append(data)
    try:
        url = parts[0].decode("ascii")
    except UnicodeDecodeError:
        raise gone
    if stage_hash(url, *parts[1:]) != h:
        raise gone
    return (url,) + tuple(parts[1:])


# ---- what the helper's commands do --------------------------------------------
# check_list(data, base, seen): om-pg-apps' check of a list's entries, as the
# catalog's are, plus code apps' permissions: {name, updated, apps, revoked,
# skipped}, or its Bad

def preview(net, store_path, staging, link, check_list):
    """After the add password: the source fetched and checked, what you'll be
    shown, and its bytes staged for adding"""
    base, host, want = parse_link(net, link)
    sources = load(store_path)
    if any(s["url"] == base for s in sources):
        raise Problem("that's one of your sources already")
    if len(sources) >= MAX_SOURCES:
        raise Problem("you have " + str(MAX_SOURCES) + " sources: remove one first")
    pub = get_key(net, base, host)
    line, fp = parse_key(pub)
    if want and fp != want:
        raise Problem("its key isn't the one its link names, so it was refused")
    if any(line in all_keys(s) for s in sources):
        raise Problem("its key is one of your sources' already")
    data, sig = get_list(net, base, host)
    verify(data, sig, line)
    cat = check_list(data, base, 0)
    fits(shown_of(cat), sha(data), 0)
    h = stage(staging, base, pub, data, sig)
    return {"url": base, "host": host, "name": shown_name(cat["name"], host), "fingerprint": fp, "id": source_id(line),
            "apps": cat["apps"], "skipped": cat["skipped"], "staged": h}


def add(net, store_path, state_root, staging, h, check_list, now=None):
    """Add this source: exactly the bytes you were shown, checked again"""
    url, pub, data, sig = staged(staging, h)
    host = host_of(net, url)
    line, fp = parse_key(pub)
    verify(data, sig, line)
    cat = check_list(data, url, 0)
    shown = shown_of(cat, now)
    fits(shown, sha(data), 0)
    sid = source_id(line)
    with held(store_path):
        sources = load(store_path)
        if len(sources) >= MAX_SOURCES:
            raise Problem("you have " + str(MAX_SOURCES) + " sources: remove one first")
        if any(s["url"] == url for s in sources):
            raise Problem("that's one of your sources already")
        if any(s["id"] == sid or line in all_keys(s) for s in sources):
            raise Problem("its key is one of your sources' already")
        s = {"id": sid, "url": url, "name": shown_name(cat["name"], host), "key": line, "fingerprint": fp, "keyGen": 0,
             "pastKeys": [], "added": int(now or time.time()), "seen": cat["updated"], "seenSha": sha(data), "rev": 0,
             "life": os.urandom(16).hex()}
        sources.append(s)
        save(store_path, sources)
        h2 = keep(state_root, sid, data, sig, shown, 0)
    shutil.rmtree(os.path.join(staging, h), ignore_errors=True)
    return {"source": public(s), "list": dict(shown, listSha256=h2, keyGen=0)}


def shown_of(cat, now=None):
    return {"updated": cat["updated"], "fetched": int(now or time.time()), "apps": cat["apps"], "revoked": cat["revoked"],
            "skipped": cat["skipped"]}


def fetch(net, store_path, state_root, sid, check_list, now=None):
    """A source's list fetched (with the catalog, while Unknown sources is
    on): its key compared first, every time, even if the list would verify;
    a different one marks it Key changed and its list isn't used"""
    with held(store_path):
        s = find(load(store_path), sid)
    host = host_of(net, s["url"])
    line, fp = parse_key(get_key(net, s["url"], host))

    if line != s["key"]:
        # a different key blocks it, whenever it was seen (blocking is never
        # the unsafe way round)
        with held(store_path):
            sources = load(store_path)
            x = find(sources, sid)
            if x["life"] != s["life"]:
                raise Problem("the source changed while it was fetched: try again")
            if x["key"] == s["key"] and (x.get("pending") or {}).get("key") != line:
                x["pending"] = {"key": line, "fingerprint": fp}
                x["rev"] += 1
                save(store_path, sources)
        return {"ok": False, "source": public(x), "keyChanged": fp,
                "error": "its key changed, so nothing new comes from it until you accept the new key"}
    data, sig = get_list(net, s["url"], host)
    verify(data, sig, s["key"])
    cat = check_list(data, s["url"], 0)
    h = sha(data)
    shown = shown_of(cat, now)
    fits(shown, h, s["keyGen"])
    # taken only if it's newer than what the source has now (not what it had
    # when this fetch began: another may have finished meanwhile), or exactly
    # that list again; decided and published under one lock, so the store
    # and the list shown never cross
    with held(store_path):
        sources = load(store_path)
        x = find(sources, sid)
        # nothing changed since this fetch began (rev): a key change seen by
        # another fetch meanwhile, or cleared and seen again, stands
        if x["life"] != s["life"] or x["rev"] != s["rev"] or x["key"] != s["key"] or x["keyGen"] != s["keyGen"]:
            raise Problem("the source changed while it was fetched: try again")
        if cat["updated"] < x["seen"] or (cat["updated"] == x["seen"] and h != x["seenSha"]):
            raise Problem("this list is older than one already seen from the source (or another list made at the same time), so it was refused")
        x["seen"], x["seenSha"] = cat["updated"], h
        x.pop("pending", None)
        x["rev"] += 1
        save(store_path, sources)
        keep(state_root, sid, data, sig, shown, x["keyGen"])
    return {"ok": True, "source": public(x), "list": dict(shown, listSha256=h, keyGen=x["keyGen"])}


def same_life(s, life):
    """The source you acted on, not one added again since with the same key
    (life: what the guide was shown)"""
    if s["life"] != life:
        raise Problem("that source was removed and added again meanwhile: look again")


def accept_key(net, store_path, sid, life, old_fp, new_fp):
    """Accept the new key (after the computer's password, for exactly these
    two fingerprints, on the source you were shown): only if the source
    still publishes that key, and it isn't one it used before. The old key
    goes to pastKeys, keyGen goes up, the id stays."""
    with held(store_path):
        s = find(load(store_path), sid)
    same_life(s, life)
    if s["fingerprint"] != old_fp or not s.get("pending") or s["pending"]["fingerprint"] != new_fp:
        raise Problem("the source's key changed again since you were asked: look again")
    if new_fp in [k["fingerprint"] for k in s["pastKeys"]]:
        raise Problem("that's a key this source used before, and an old key never comes back")
    line, fp = parse_key(get_key(net, s["url"], host_of(net, s["url"])))
    if line != s["pending"]["key"]:
        raise Problem("the source doesn't publish the key you accepted any more, so nothing changed")
    with held(store_path):
        sources = load(store_path)
        x = find(sources, sid)
        if x["life"] != s["life"] or x["key"] != s["key"] or x["keyGen"] != s["keyGen"] or (x.get("pending") or {}).get("key") != line:
            raise Problem("the source changed while it was checked: look again")
        x["pastKeys"] = (x["pastKeys"] + [{"key": x["key"], "fingerprint": x["fingerprint"]}])[-MAX_PAST:]
        x["key"], x["fingerprint"], x["keyGen"] = line, fp, x["keyGen"] + 1
        x.pop("pending", None)
        x["rev"] += 1
        save(store_path, sources)
    # keyGen went up: the list kept from the old key is never shown again
    # (shown_list), so the source lists nothing until a list verifies under
    # the new key; what's kept for installed apps' proof stays
    return {"source": public(x)}


# ---- installing: what you reviewed, and nothing else ----------------------------

SNAPSHOT_KEYS = {"source", "life", "keyGen", "listSha256", "updated", "entry"}
ENTRY_KEYS = ("id", "version", "kind", "api", "package", "sha256", "size", "permissions")


def entry_of(e):
    """What a review binds of an entry: what it installs and what it may do"""
    return {k: e[k] for k in ENTRY_KEYS if k in e}


def snapshot_of(raw):
    """What a review was bound to, from the guide on stdin: checked before
    anything else is read"""
    bad = Problem("that isn't what a review keeps")
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_SNAPSHOT:
        raise bad
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise bad
    if not isinstance(d, dict) or set(d) != SNAPSHOT_KEYS or not isinstance(d["entry"], dict):
        raise bad
    if (not isinstance(d["source"], str) or not ID_RE.match(d["source"]) or not isinstance(d["life"], str)
            or not re.match(r"^[0-9a-f]{32}\Z", d["life"]) or not is_int(d["keyGen"]) or not is_int(d["updated"], 1)
            or not isinstance(d["listSha256"], str) or not SHA_RE.match(d["listSha256"])
            or set(d["entry"]) - set(ENTRY_KEYS) or not isinstance(d["entry"].get("id"), str)):
        raise bad
    return d


def current(store_path, snap, locked=False):
    """The source still exactly as the review saw it, read under the store's
    lock: the same added source (life), key generation and no key change,
    and the list you were shown still its current one (a newer list, a
    revocation say, means a fresh review). Checked before the download,
    after it, once it's staged, and by install, which holds the lock (locked)
    from this check until the app is in place: the source; Problem if
    anything changed"""
    if locked:
        s = find(load(store_path), snap["source"])
    else:
        with held(store_path):
            s = find(load(store_path), snap["source"])
    same_life(s, snap["life"])
    if s["keyGen"] != snap["keyGen"] or s.get("pending"):
        raise Problem("the source changed since you were shown it: look again")
    if s["seenSha"] != snap["listSha256"]:
        raise Problem("its source has a newer list since you were shown it: look again")
    return s


def prepare(net, store_path, state_root, raw, check_list):
    """Install or Update, for exactly what you reviewed: the snapshot checked,
    the source still the one you saw (current), the list kept by its hash
    still those bytes and still signed by its key, its entry for the app the
    same as the review's; then the package that entry names, from the
    source's own site, checked against it, and the source checked again
    (a list that came during the download, a key change, a removal: no).
    (snapshot, source, list bytes, signature, entry, package); om-pg-apps
    unpacks and checks it into private staging."""
    snap = snapshot_of(raw)
    s = current(store_path, snap)
    changed = Problem("the source changed since you were shown it: look again")
    folder = os.path.join(state_root, folder_of(s["id"]))
    try:
        data = read_plain(os.path.join(folder, snap["listSha256"] + ".json"), MAX_LIST, "the list you were shown")
        sig = read_plain(os.path.join(folder, snap["listSha256"] + ".sig"), MAX_SIG, "its signature")
    except Problem:
        data = sig = None
    if data is None or sig is None or sha(data) != snap["listSha256"]:
        raise Problem("the list you were shown isn't kept any more: look again")
    verify(data, sig, s["key"])
    cat = check_list(data, s["url"], 0)
    if cat["updated"] != snap["updated"]:
        raise changed
    entry = next((e for e in cat["apps"] if e["id"] == snap["entry"]["id"]), None)
    if not entry:
        raise Problem("its source doesn't list it any more (it may have pulled it)")
    if entry_of(entry) != snap["entry"]:
        raise Problem("its source's list says something else about it now: look again")
    package = get(net, entry["package"], host_of(net, s["url"]), MAX_PACKAGE, "the app", PACKAGE_SECONDS)
    if sha(package) != entry["sha256"] or len(package) != entry["size"]:
        raise Problem("the download isn't the app its source lists (it may have been changed), so it was refused")
    s = current(store_path, snap)
    return snap, s, data, sig, entry, package


def check_proof(store_path, proof, app_id, version, check_list):
    """An app from a source traced back to it: its source still yours, the
    key kept with it the source's key or one of its past keys (a past key
    keeps old installs checkable; it never adds anything new), the list kept
    with it signed by that key and listing this version, its names read
    against the address it came from (the source may have moved since; one
    kept before that address was, against the source's): its entry. Nothing
    is fetched from that address"""
    sid, line = proof.get("source"), proof.get("key")
    if not isinstance(sid, str) or not ID_RE.match(sid) or not isinstance(line, str):
        raise Problem("what shows where it came from was changed")
    s = next((x for x in load(store_path) if x["id"] == sid), None)
    if not s:
        raise Problem("its source was removed")
    url = proof.get("url", s["url"])
    if not isinstance(url, str) or not url.startswith("https://") or not url.endswith("/") or len(url) > 2048:
        raise Problem("what shows where it came from was changed")
    if line not in all_keys(s):
        raise Problem("the key it was signed with isn't its source's")
    try:
        data = base64.b64decode(proof.get("data") or "", validate=True)
        sig = base64.b64decode(proof.get("sig") or "", validate=True)
    except (ValueError, TypeError):
        raise Problem("what shows where it came from was changed")
    verify(data, sig, line)
    cat = check_list(data, url, 0)
    entry = next((e for e in cat["apps"] if e["id"] == app_id), None)
    if not entry or entry["version"] != version:
        raise Problem("the list it came from doesn't list this version")
    return entry


def remove(store_path, state_root, sid, life):
    """The source you were shown taken off: its kept lists deleted (its
    apps are the guide's to turn off, and yours to remove)"""
    folder = folder_of(sid)
    with held(store_path):
        sources = load(store_path)
        same_life(find(sources, sid), life)
        save(store_path, [s for s in sources if s["id"] != sid])
        # under the lock too: one added again with the same key (the same
        # folder) keeps what it writes there
        shutil.rmtree(os.path.join(state_root, folder), ignore_errors=True)
    return {}


def listing(store_path, state_root):
    """Your sources as the guide shows them, each with its last list, read
    under the store's lock: the store and every list.json from one moment
    (a fetch saves both under it), never half of a fetch's commit"""
    with held(store_path):
        return {"sources": [dict(public(s), list=shown_list(state_root, s)) for s in load(store_path)]}
