"""Signed Uber TV app files and their update transport.

This module owns only the small trust boundary that is useful independently
of the guide: canonical Ed25519 keys, signatures in the ``uber-tv-app``
namespace, canonical update folders, and bounded same-host downloads.  The
helper owns app manifests, packages, installed state and transactions.
"""

import asyncio
import base64
import hashlib
import os
import re
import stat
import subprocess
import tempfile
import unicodedata


MAX_PUB = 4 * 1024
MAX_RELEASE = 512 * 1024
MAX_SIG = 16 * 1024
MAX_FILE = 25 * 1024 * 1024
MAX_REVOKED = 1000
SECONDS = 60
PACKAGE_SECONDS = 180
NAMESPACE = "uber-tv-app"
KEY_RE = re.compile(r"^ssh-ed25519 ([A-Za-z0-9+/]{68})\Z")
KEY_HEAD = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20"

# Characters which Unicode confusables data (plus common hand-written
# variants) renders like the letters of "Uber TV".  A third-party app must
# never make its review look first-party.
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
JOINERS = ("\u00f0\u01c0\u01c1\u01c2\u01c3\u0241\u0242\u0294\u05d9\u05f2\u0660\u06f0\u097d\u13ae\u1427\u1433\u1437\u1438\u1440\u1441"
           "\u1444\u1445\u144a\u16b2\u16cc\u2cb2\u2cb3\u2cb4\u2cb5\u2cb7\u2cba\u2cbb\u2cc6\u2cc7\u2d48\u2d51\u304f\u30ce\u4e36\u4e3f"
           "\ua6eb\ua778\ua78b\ua78c\ua78f\ua830\U0001029b\U0001031f\U000118a8\U00016f3f\U0001e8c8\U0001e8cc\U0001e8cd\U00021fe8")
LATIN_NAME = re.compile(r"^(?:(?:NEGATIVE CIRCLED |NEGATIVE SQUARED )?LATIN (?:CAPITAL |SMALL |SMALL CAPITAL )?LETTER (?:SMALL CAPITAL )?"
                        r"|REGIONAL INDICATOR SYMBOL LETTER )([A-Z])(?: |\Z)")


def _lookalikes():
    out = {}
    for letter, chars in LOOKALIKES.items():
        for char in chars:
            out[char] = out.get(char, "") + letter
    return out


READS = _lookalikes()


def _reads_as(char):
    if char.isascii():
        return char.lower() if char.isalpha() else ""
    match = LATIN_NAME.match(unicodedata.name(char, ""))
    return READS.get(char, "") + (match.group(1).lower() if match else "")


def claims_uber_tv(name):
    """Whether a name can visually read as Uber TV's own name."""
    seq = []
    for whole in name:
        parts = []
        for char in unicodedata.normalize("NFKD", whole):
            kind, reads = unicodedata.category(char), _reads_as(char)
            if kind[0] != "M":
                parts.append((reads, not char.isalnum() or kind == "Lm" or char in JOINERS,
                              not reads and kind[0] != "Z"))
        if len(parts) > 1 and not any(reads for reads, _, _ in parts):
            parts = [("", all(joins for _, joins, _ in parts), any(stands for _, _, stands in parts))]
        seq += parts
    tries = set()
    for index, (reads, joins, stands) in enumerate(seq):
        after = set()
        for count, how in tries | {(0, 1 if index == 0 or seq[index - 1][1] else 0)}:
            if joins:
                after.add((count, how))
            if "ubertv"[count] in reads:
                after.add((count + 1, how))
            elif stands and how == 1:
                after.add((count + 1, 2))
        ends = index + 1 == len(seq) or seq[index + 1][1]
        if any(count == 6 and (how < 2 or ends) for count, how in after):
            return True
        tries = {(count, how) for count, how in after if count < 6}
    return False


class Problem(Exception):
    """An app file, signature or update that cannot be trusted."""


def parse_key(data):
    """A canonical Ed25519 public-key line and its ssh-keygen fingerprint."""
    try:
        line = data.decode("ascii")
    except (AttributeError, UnicodeDecodeError):
        raise Problem("key.pub isn't one Ed25519 key")
    if line.endswith("\n"):
        line = line[:-1]
    match = KEY_RE.match(line)
    if not match:
        raise Problem("key.pub isn't one Ed25519 key (ssh-ed25519 and the key, nothing else)")
    try:
        blob = base64.b64decode(match.group(1), validate=True)
    except ValueError:
        raise Problem("key.pub isn't one Ed25519 key")
    if (len(blob) != len(KEY_HEAD) + 32 or not blob.startswith(KEY_HEAD)
            or base64.b64encode(blob).decode() != match.group(1)):
        raise Problem("key.pub isn't one Ed25519 key")
    return line, "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def source_id(line):
    """The installed lineage for this signing key."""
    blob = base64.b64decode(line.split(" ", 1)[1])
    return "app:" + hashlib.sha256(blob).hexdigest()[:16]


def verify(data, signature, line):
    """Check a release against exactly ``line`` in the app namespace."""
    with tempfile.TemporaryDirectory(prefix="om-pg-app-signature-") as folder:
        signers = os.path.join(folder, "signers")
        sig = os.path.join(folder, "release.sig")
        for path, body in ((signers, (NAMESPACE + ' namespaces="' + NAMESPACE + '" ' + line + "\n").encode()),
                           (sig, signature)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
        try:
            result = subprocess.run(
                ["/usr/bin/ssh-keygen", "-Y", "verify", "-f", signers, "-I", NAMESPACE,
                 "-n", NAMESPACE, "-s", sig], input=data, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as error:
            raise Problem("couldn't check the app's signature: " + str(error)[:80])
    if result.returncode != 0:
        raise Problem("the app's signature isn't by the key in key.pub, so it was refused")


def update_folder(net, raw):
    """A canonical HTTPS folder used for release notes and their package."""
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw or len(raw) > 2048 or not raw.startswith("https://"):
        raise Problem("updates must be an https folder, or none")
    try:
        url = net.parse_url(raw)
    except net.NetError as error:
        raise Problem(str(error))
    if url.port != 443 or url.query:
        raise Problem("updates must use https's usual port and have no ? part")
    path = url.path
    if path.endswith("/release.json"):
        path = path[:-len("release.json")]
    elif not path.endswith("/"):
        path += "/"
    return str(net.Url("https", url.host, 443, path, ""))


def package_url(net, base, name):
    """The package name in a note, resolved only inside the note's host."""
    if (not isinstance(name, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.tar\.gz\Z", name)
            or "/" in name):
        raise Problem("package.url must be one .tar.gz file name")
    if base is None:
        return None
    return base + name


async def _get(net, url, host, limit, what):
    response = await net.request(net.Rules([host]), url, "GET", None, None, net.Gate())
    try:
        if response.status != 200:
            raise Problem(what + " wasn't there (the site answered " + str(response.status) + ")")
        try:
            return await response.body(limit)
        except net.NetError as error:
            if error.code == "toobig":
                raise Problem(what + " is bigger than " + net.size_words(limit) + ", so it was refused")
            raise
    finally:
        response.close()


def get(net, url, host, limit, what, seconds=SECONDS):
    """A bounded fetch through appnet's public-address and redirect rules."""
    async def one():
        try:
            return await asyncio.wait_for(_get(net, url, host, limit, what), seconds)
        except asyncio.TimeoutError:
            raise Problem("getting " + what + " took too long")
        except net.NetError as error:
            raise Problem("couldn't get " + what + ": " + str(error))
    return asyncio.run(one())


def read_plain(path, limit, what):
    """A bounded plain file, never a link, pipe, device or socket."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        raise Problem("couldn't read " + what + ": " + (error.strerror or str(error)))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Problem(what + " isn't a plain file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Problem(what + " is too big")
    return data
