"""The network side of the app helper: every request a code app makes goes
through here, never through urllib. Origins are checked before anything is
looked up, addresses before anything is connected, and the request is
rebuilt from the checked parts, never sent as the app spelled it.

Kept free of the helper's state so it can be tested on its own
(tests/apprun.test.py)."""

import asyncio
import hashlib
import ipaddress
import re
import socket
import ssl

NET_METHODS = ("GET", "HEAD")
SERVER_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
MAX_HEADERS = 16 * 1024
MAX_REDIRECTS = 5

LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
TOKEN_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}\Z")
DIGITS_RE = re.compile(r"^(?:[0-9]+|0x[0-9a-f]*)\Z")
QUAD_RE = re.compile(r"^(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}\Z")
# what may stay as it is in a path we send; everything else is %-encoded
PATH_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@/")
QUERY_SAFE = PATH_SAFE | set("?%")
# headers the helper writes itself, or that an app may never send
OWN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "keep-alive", "proxy-authorization",
               "proxy-authenticate", "proxy-connection", "te", "trailer", "upgrade", "cookie", "accept-encoding", "expect"}


class NetError(Exception):
    """A request refused or failed: code is short and stable, the text is for the user"""

    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


# ---- hosts and addresses ---------------------------------------------------

def canonical_host(raw):
    """A host as the helper compares and resolves it: lowercase DNS labels,
    a plain dotted IPv4, or a bracketed IPv6. Anything a resolver or another
    parser could read two ways (0x7f.1, 2130706433, 127.1, a zone id, an
    IPv4 address hidden in IPv6) is refused."""
    if not raw or len(raw) > 255:
        raise NetError("host", "the link has no host")
    if raw.startswith("["):
        if not raw.endswith("]") or "%" in raw:
            raise NetError("host", "the link's host isn't valid")
        try:
            ip = ipaddress.IPv6Address(raw[1:-1])
        except ValueError:
            raise NetError("host", "the link's host isn't valid")
        if ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None:
            raise NetError("host", "the link hides an IPv4 address in IPv6")
        return "[" + ip.compressed + "]"
    host = raw.lower()
    if not host.isascii():
        raise NetError("host", "the link's host isn't plain ASCII (use its xn-- form)")
    labels = host.split(".")
    if DIGITS_RE.match(labels[-1]):
        if not QUAD_RE.match(host):
            raise NetError("host", "the link's host is a number written an unusual way")
        return host
    if len(host) > 253 or not all(LABEL_RE.match(l) for l in labels):
        raise NetError("host", "the link's host isn't valid")
    return host


V4_BLOCKED = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4")]
V6_BLOCKED = [ipaddress.ip_network(n) for n in (
    "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20", "2001:10::/28", "2001:20::/28")]
V6_GLOBAL = ipaddress.ip_network("2000::/3")


def global_unicast(addr):
    """Whether an address is a public unicast one: spelled out, because
    ipaddress's is_global calls 224.0.0.1 global on this Python"""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 4:
        return not any(ip in n for n in V4_BLOCKED)
    if ip.ipv4_mapped is not None:
        return False   # never reached through a mapped form, whatever it maps
    if ip not in V6_GLOBAL:
        return False   # loopback, link-local, ULA, multicast, NAT64, unspecified...
    return not any(ip in n for n in V6_BLOCKED)


# ---- paths -------------------------------------------------------------------

HEX = "0123456789abcdefABCDEF"
FORBIDDEN_ESCAPES = {0x25, 0x2E, 0x2F, 0x5C, 0x00}   # % . / \ NUL


def controls(s):
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in s)


def canonical_path(raw):
    """A URL's path, decoded once and with its dot segments removed, the same
    way for the configured server, every request and every redirect.
    Anything that could decode differently twice (an encoded % . / \\ or
    NUL, a backslash, a control character, before or after decoding) is
    refused."""
    if not raw:
        raw = "/"
    if not raw.startswith("/"):
        raise NetError("path", "the link's path isn't absolute")
    if "\\" in raw or controls(raw) or not raw.isascii():
        raise NetError("path", "the link's path has characters that aren't allowed")
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "%":
            h = raw[i + 1:i + 3]
            if len(h) != 2 or h[0] not in HEX or h[1] not in HEX:
                raise NetError("path", "the link's path has a broken %-escape")
            b = int(h, 16)
            if b in FORBIDDEN_ESCAPES:
                raise NetError("path", "the link's path encodes a character that isn't allowed there")
            out.append(b)
            i += 3
        else:
            out.append(ord(c))
            i += 1
    try:
        decoded = out.decode("utf-8")
    except UnicodeDecodeError:
        raise NetError("path", "the link's path isn't valid UTF-8")
    if "\\" in decoded or controls(decoded):
        raise NetError("path", "the link's path has characters that aren't allowed")
    segments = []
    parts = decoded.split("/")[1:]
    for n, seg in enumerate(parts):
        last = n == len(parts) - 1
        if seg == ".":
            if last:
                segments.append("")
        elif seg == "..":
            if segments:
                segments.pop()
            if last:
                segments.append("")
        else:
            segments.append(seg)
    return "/" + "/".join(segments)


def encode_path(decoded):
    """The canonical path as sent: only what must be is %-encoded"""
    out = []
    for ch in decoded:
        if ch in PATH_SAFE:
            out.append(ch)
        else:
            out.extend("%{:02X}".format(b) for b in ch.encode("utf-8"))
    return "".join(out)


def canonical_query(raw):
    """A query passed through as it is, except for control characters
    (literal or %-encoded), refused, and spaces, re-encoded"""
    if controls(raw) or not raw.isascii():
        raise NetError("query", "the link's query has characters that aren't allowed")
    if re.search(r"%(?:[01][0-9a-fA-F]|7[fF])", raw):
        raise NetError("query", "the link's query encodes a control character")
    if re.search(r"%(?![0-9a-fA-F]{2})", raw):
        raise NetError("query", "the link's query has a broken %-escape")
    return "".join(ch if ch in QUERY_SAFE else "%{:02X}".format(ord(ch)) for ch in raw)


def under(path, prefix):
    """On a segment boundary: /jellyfin holds /jellyfin and /jellyfin/x,
    not /jellyfin-other"""
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


# ---- URLs --------------------------------------------------------------------

URL_RE = re.compile(r"^(https?)://([^/?#]*)([^?#]*)(?:\?([^#]*))?(?:#.*)?\Z", re.S)


class Url:
    """A parsed, canonical URL: what is compared, resolved and sent"""

    def __init__(self, scheme, host, port, path, query):
        self.scheme, self.host, self.port, self.path, self.query = scheme, host, port, path, query

    @property
    def origin(self):
        return (self.scheme, self.host, self.port)

    @property
    def default_port(self):
        return self.port == (443 if self.scheme == "https" else 80)

    @property
    def authority(self):
        return self.host if self.default_port else self.host + ":" + str(self.port)

    @property
    def target(self):
        """The origin-form request target: the canonical path, re-encoded"""
        return encode_path(self.path) + ("?" + self.query if self.query else "")

    def __str__(self):
        return self.scheme + "://" + self.authority + self.target

    @property
    def bare_host(self):
        return self.host[1:-1] if self.host.startswith("[") else self.host


def parse_url(raw):
    """A URL, checked and made canonical, or NetError"""
    if not isinstance(raw, str) or len(raw) > 4096:
        raise NetError("url", "not a link")
    if controls(raw) or " " in raw:
        raise NetError("url", "the link has characters that aren't allowed")
    m = URL_RE.match(raw)
    if not m:
        raise NetError("url", "the link isn't http or https")
    scheme = m.group(1)
    authority = m.group(2)
    if "@" in authority:
        raise NetError("url", "the link has a user name or password in it")
    hp = re.match(r"^(\[[^\]]*\]|[^:\[\]]*)(?::([0-9]{1,5}))?\Z", authority)
    if not hp:
        raise NetError("url", "the link's host or port isn't valid")
    host = canonical_host(hp.group(1))
    port = int(hp.group(2)) if hp.group(2) else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise NetError("url", "the link's port isn't valid")
    path = canonical_path(m.group(3) or "/")
    query = canonical_query(m.group(4)) if m.group(4) else ""
    return Url(scheme, host, port, path, query)


def resolve_ref(base, ref):
    """A reference (a redirect's Location, a playlist's URI) made absolute
    against the URL it came from, then parsed like any other"""
    if not isinstance(ref, str) or not ref or controls(ref):
        raise NetError("url", "a link in the reply isn't valid")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", ref):
        return parse_url(ref)
    if ref.startswith("//"):
        return parse_url(base.scheme + ":" + ref)
    if ref.startswith("/"):
        return parse_url(base.scheme + "://" + base.authority + ref)
    if ref.startswith("?"):
        return parse_url(base.scheme + "://" + base.authority + encode_path(base.path) + ref)
    if ref.startswith("#"):
        return base
    folder = encode_path(base.path)
    folder = folder[:folder.rfind("/") + 1]
    return parse_url(base.scheme + "://" + base.authority + folder + ref)


def normalize_base(raw):
    """The server the user chose, as one canonical base URL: scheme, host,
    port and a path prefix (no trailing slash, "/" for the whole origin); no
    user name, query or fragment"""
    if not isinstance(raw, str):
        raise NetError("server", "not a server address")
    raw = raw.strip()
    if not re.match(r"^https?://", raw):
        raw = "http://" + raw
    if "?" in raw or "#" in raw:
        raise NetError("server", "a server address has no ? or # part")
    u = parse_url(raw)
    prefix = u.path.rstrip("/") or "/"
    return Url(u.scheme, u.host, u.port, prefix, "")


# ---- the origin rules ------------------------------------------------------

class Rules:
    """What one app may reach: its exact net hosts (https: GET and HEAD,
    plus the methods its netWrite gives each, api 4) and its server's prefix
    (the server's methods)"""

    def __init__(self, net=(), server=None, net_write=None):
        self.net = set(net)
        self.server = server   # a Url from normalize_base, or None
        self.net_write = {h: tuple(m for m in SERVER_METHODS if m in ms) for h, ms in (net_write or {}).items() if h in self.net}

    def check(self, url, method):
        """'net' or 'server' for a URL (a Url) and method allowed, else NetError"""
        if not isinstance(method, str) or method not in SERVER_METHODS:
            raise NetError("method", "that request method isn't allowed")
        s = self.server
        if s and url.origin == s.origin:
            if not under(url.path, s.path):
                raise NetError("origin", "the link is outside the server's address")
            return "server"
        if url.scheme == "https" and url.port == 443 and url.host in self.net:
            allowed = NET_METHODS + self.net_write.get(url.host, ())
            if method not in allowed:
                raise NetError("method", "only " + ", ".join(allowed[:-1]) + " and " + allowed[-1] + " go to " + url.host)
            return "net"
        raise NetError("origin", "the app isn't allowed to reach " + url.host)

    def parse(self, raw, method):
        url = parse_url(raw)
        return url, self.check(url, method)


def check_headers(headers, kind):
    """An app's request headers as a list of (name, value): token names,
    values without CR, LF or NUL, none the helper writes itself"""
    if headers is None:
        return []
    if not isinstance(headers, dict) or len(headers) > 32:
        raise NetError("headers", "the request's headers aren't valid")
    out, total = [], 0
    for name, value in headers.items():
        if not isinstance(name, str) or not TOKEN_RE.match(name) or not isinstance(value, str):
            raise NetError("headers", "a request header isn't valid")
        if name.lower() in OWN_HEADERS:
            raise NetError("headers", "an app can't send the " + name + " header")
        if any(c in value for c in "\r\n\0") or controls(value.replace("\t", "")) or len(value) > 8192:
            raise NetError("headers", "a request header's value isn't valid")
        total += len(name) + len(value)
        out.append((name, value))
    if total > MAX_HEADERS:
        raise NetError("headers", "the request's headers are too big")
    return out


# ---- connecting ------------------------------------------------------------

class Gate:
    """The one place a request becomes network: offline (in `try`), nothing
    gets past it, checked before any lookup or socket"""

    def __init__(self, online=True):
        self.online = online
        self.attempts = 0

    def allow(self, url):
        if not self.online:
            self.attempts += 1
            raise NetError("offline", "offline: " + str(url) + " isn't in the fixtures")


async def connect(url, kind, gate, pin="", resolver=None):
    """A connection to one approved address of url's host, TLS checked for the
    original hostname (or against the user's pin for the server). For a net
    host, every address it resolves to must be public, before any connect."""
    gate.allow(url)
    loop = asyncio.get_running_loop()
    host = url.bare_host
    try:
        infos = await (resolver(host, url.port) if resolver else
                       loop.getaddrinfo(host, url.port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP))
    except (socket.gaierror, OSError) as e:
        raise NetError("dns", "couldn't find " + host + " (" + (e.strerror or str(e)) + ")")
    if not infos:
        raise NetError("dns", "couldn't find " + host)
    if kind == "net" and not all(global_unicast(i[4][0]) for i in infos):
        raise NetError("private", host + " points at a private or special address, so it wasn't reached")
    family, _, _, _, sockaddr = infos[0]
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, sockaddr)
        if sock.getpeername()[:2] != sockaddr[:2]:
            raise NetError("connect", "connected somewhere else than " + host)
    except NetError:
        sock.close()
        raise
    except OSError as e:
        sock.close()
        raise NetError("connect", "couldn't connect to " + host + " (" + (e.strerror or str(e))[:80] + ")")
    # From here the socket is asyncio's: it's closed only through its
    # transport. (Closing it here too would free its descriptor while the
    # transport still means to unregister that number later, by which time
    # it can belong to something else, an app's pipe say.)
    try:
        if url.scheme == "https":
            if pin:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            else:
                ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            reader, writer = await asyncio.open_connection(sock=sock, ssl=ctx, server_hostname=host, limit=MAX_HEADERS * 2)
        else:
            reader, writer = await asyncio.open_connection(sock=sock, limit=MAX_HEADERS * 2)
    except ssl.SSLCertVerificationError as e:
        raise NetError("tls", "the certificate of " + host + " isn't valid (" + str(e.verify_message or e)[:80] + ")")
    except (OSError, ssl.SSLError) as e:
        raise NetError("connect", "couldn't connect to " + host + " (" + (getattr(e, "strerror", None) or str(e))[:80] + ")")
    if pin:
        der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        if not der or hashlib.sha256(der).hexdigest() != pin:
            writer.close()
            raise NetError("pin", "the server's certificate isn't the one you pinned")
    return reader, writer


# ---- HTTP/1.1 ----------------------------------------------------------------

class Response:
    def __init__(self, status, headers, reader, writer, url, method):
        self.status, self.headers, self.reader, self.writer, self.url, self.method = status, headers, reader, writer, url, method
        self._left = None
        self._chunked = False
        self._done = method == "HEAD" or status in (204, 304) or 100 <= status < 200
        self.received = 0          # body bytes read, for the app's Activity
        self.on_close = None       # told them once, when it's closed
        te = self.header("transfer-encoding")
        cl = self.header("content-length")
        if not self._done:
            if te is not None:
                if te.lower() != "chunked":
                    raise NetError("http", "the reply uses a transfer encoding the helper doesn't read")
                self._chunked = True
            elif cl is not None:
                if not re.match(r"^[0-9]{1,15}\Z", cl):
                    raise NetError("http", "the reply's length isn't valid")
                self._left = int(cl)
                self._done = self._left == 0

    def header(self, name):
        name = name.lower()
        found = [v for k, v in self.headers if k.lower() == name]
        if len(found) > 1 and name in ("content-length", "transfer-encoding", "location", "content-range"):
            raise NetError("http", "the reply has two " + name + " headers")
        return found[0] if found else None

    @property
    def length(self):
        return self._left if not self._chunked else None

    async def chunk(self, size=65536):
        """The next bytes of the body (b"" at its end)"""
        data = await self._chunk(size)
        self.received += len(data)
        return data

    async def _chunk(self, size):
        if self._done:
            return b""
        if self._chunked:
            if not self._left:
                line = await self.reader.readline()
                if not line.endswith(b"\n") or len(line) > 1024:
                    raise NetError("http", "the reply's chunks aren't valid")
                m = re.match(rb"^([0-9a-fA-F]{1,12})(?:;[^\r\n]*)?\r?\n\Z", line)
                if not m:
                    raise NetError("http", "the reply's chunks aren't valid")
                self._left = int(m.group(1), 16)
                if self._left == 0:
                    total = 0
                    while True:   # trailers, up to a blank line
                        t = await self.reader.readline()
                        total += len(t)
                        if t in (b"\r\n", b"\n", b"") or total > MAX_HEADERS:
                            break
                    self._done = True
                    return b""
            data = await self.reader.read(min(size, self._left))
            if not data:
                raise NetError("http", "the reply ended early")
            self._left -= len(data)
            if self._left == 0:
                end = await self.reader.readline()
                if end not in (b"\r\n", b"\n"):
                    raise NetError("http", "the reply's chunks aren't valid")
            return data
        if self._left is None:   # until the connection closes
            data = await self.reader.read(size)
            if not data:
                self._done = True
            return data
        data = await self.reader.read(min(size, self._left))
        if not data:
            raise NetError("http", "the reply ended early")
        self._left -= len(data)
        if self._left == 0:
            self._done = True
        return data

    async def body(self, limit):
        """The whole body, or NetError past limit bytes"""
        if self._left is not None and not self._chunked and self._left > limit:
            raise NetError("toobig", "the reply is bigger than " + size_words(limit))
        parts, total = [], 0
        while True:
            data = await self.chunk()
            if not data:
                break
            total += len(data)
            if total > limit:
                raise NetError("toobig", "the reply is bigger than " + size_words(limit))
            parts.append(data)
        return b"".join(parts)

    def close(self):
        try:
            self.writer.close()
        except Exception:
            pass
        told, self.on_close = self.on_close, None
        if told:
            told(self.received)


def size_words(n):
    return str(n // (1024 * 1024)) + " MB" if n >= 1024 * 1024 else str(max(1, n // 1024)) + " KB"


async def exchange(url, method, headers, body, gate, kind, pin="", resolver=None):
    """One request and its reply's head (no redirects followed): the request
    line and Host come only from the checked URL and method"""
    reader, writer = await connect(url, kind, gate, pin, resolver)
    lines = [method + " " + url.target + " HTTP/1.1", "Host: " + url.authority, "Accept-Encoding: identity",
             "Connection: close"]
    if body or method in ("POST", "PUT", "PATCH"):
        lines.append("Content-Length: " + str(len(body or b"")))
    lines.extend(n + ": " + v for n, v in headers)
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (body or b""))
    try:
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError:
        writer.close()
        raise NetError("http", "the reply's headers are too big")
    except asyncio.IncompleteReadError:
        writer.close()
        raise NetError("http", "the server closed the connection without a reply")
    except OSError as e:
        writer.close()
        raise NetError("connect", "the connection failed (" + (e.strerror or str(e))[:80] + ")")
    if len(head) > MAX_HEADERS:
        writer.close()
        raise NetError("http", "the reply's headers are too big")
    try:
        text = head.decode("latin-1")
    except UnicodeDecodeError:
        writer.close()
        raise NetError("http", "the reply isn't HTTP")
    rows = text.split("\r\n")
    m = re.match(r"^HTTP/1\.[01] ([1-5][0-9][0-9])(?: .*)?\Z", rows[0])
    if not m:
        writer.close()
        raise NetError("http", "the reply isn't HTTP")
    out = []
    for row in rows[1:]:
        if not row:
            continue
        name, sep, value = row.partition(":")
        if not sep or not TOKEN_RE.match(name):
            writer.close()
            raise NetError("http", "the reply's headers aren't valid")
        out.append((name, value.strip(" \t")))
    try:
        return Response(int(m.group(1)), out, reader, writer, url, method)
    except NetError:
        writer.close()
        raise


async def request(rules, raw_url, method, headers, body, gate, pin="", resolver=None, follow=True, checked=None, observe=None):
    """A request under an app's origin rules, redirects followed, each hop
    checked like the first with the method it will be sent with: a 301, 302
    or 303 becomes a GET without the body (a HEAD stays one); a 307 or 308
    keeps the method and body, but neither a write (POST, PUT, PATCH,
    DELETE) nor a body is ever carried to another origin: that redirect is
    the answer, and the app may make a new request, checked on its own. When
    the origin changes, every header the app set is dropped (a token in
    X-Plex-Token or X-Api-Key as much as in Authorization). Returns the final
    Response, its body unread. checked: headers already checked (a list of
    (name, value)), used instead of headers.

    observe(url, kind, method, status, sent, code), for the app's Activity:
    told of every hop, against the site it went to: sent and answered
    (status), or not (code: a refusal or a failure, as the caller counts
    codes); and of a redirect the rules refused, or whose Location couldn't
    be read (url None)."""
    url, kind = rules.parse(raw_url, method)
    sent = list(checked) if checked is not None else check_headers(headers, kind)
    for hop in range(MAX_REDIRECTS + 1):
        try:
            res = await exchange(url, method, sent, body, gate, kind, pin if kind == "server" else "", resolver)
        except NetError as e:
            if observe:
                observe(url, kind, method, None, len(body or b""), e.code)
            raise
        if observe:
            observe(url, kind, method, res.status, len(body or b""), None)
        if not follow or res.status not in (301, 302, 303, 307, 308):
            return res
        where = res.header("location")
        try:
            if hop == MAX_REDIRECTS:
                raise NetError("redirects", "too many redirects")
            if not where:
                raise NetError("http", "a redirect without a Location")
            nxt = resolve_ref(url, where)
        except NetError as e:
            res.close()
            if observe:
                observe(None, None, method, None, 0, e.code)
            raise
        if res.status in (307, 308):
            if (method not in NET_METHODS or body) and nxt.origin != url.origin:
                return res
        elif method != "HEAD":
            method, body = "GET", None
        try:
            kind = rules.check(nxt, method)
        except NetError as e:
            res.close()
            if observe:
                observe(nxt, None, method, None, 0, e.code)
            raise
        res.close()
        if nxt.origin != url.origin:
            sent = []
        url = nxt
    raise NetError("redirects", "too many redirects")
