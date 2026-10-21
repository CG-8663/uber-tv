"""The recorder's loopback relay (bin/om-pg-dvr): ffmpeg records a channel
through it, so the channel's address, which can hold the provider's login,
is never on a command line, where any account on the computer can read it.

It listens on 127.0.0.1 only, on a free port, under a secret path, for as
long as one recording runs. It serves only what that recording led to: the
channel's address, then the playlists, segments and keys those playlists
name, each under an opaque token it made; never an address someone asks
for. Every address in a playlist (its plain lines and its URI="..."
attributes) is rewritten to point back here, resolved against where the
playlist really came from; anything that isn't http or https becomes a
dead token, so a playlist can't make ffmpeg read a local file or another
program's socket. A master playlist is cut to one picture (H.264 first,
then the biggest up to the height asked for, as the streamer picks) and one
sound (the original, else the default, else the first of its group).
Media is streamed through, never held; playlists and keys are capped, and
so are the requests at once and how long each may stall. Upstream
addresses are never logged.

Kept free of the helper's state so it can be tested on its own.
"""

import collections
import hmac
import http.client
import http.server
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request

PLAYLIST_MAX = 4 * 1024 * 1024
KEY_MAX = 64 * 1024
TIMEOUT = 20
SLOTS = 8
TOKENS_MAX = 4000           # a live playlist names new segments for hours: the oldest are forgotten
CHUNK = 64 * 1024
# a segment's extension as ffmpeg checks it (allowed_segment_extensions, extension_picky)
MEDIA_EXT = {".ts", ".m4s", ".mp4", ".m4v", ".m4a", ".aac", ".ac3", ".ec3", ".eac3", ".mp3", ".mpg", ".mpeg",
             ".mpegts", ".vtt", ".webvtt", ".cmfv", ".cmfa", ".fmp4", ".m3u8", ".mkv", ".mov", ".ogg"}
URI_ATTR = re.compile(r'URI="([^"]*)"')
SENT_HEADERS = ("User-Agent", "Range", "Accept")
PASSED_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")


def web(url):
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


class WebOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follows redirects to http and https only."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not web(newurl):
            raise urllib.error.HTTPError(req.full_url, code, "a redirect away from the web", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    # only http and https: never urllib's file:, ftp: or data: handlers
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
              WebOnlyRedirects(), urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


def attrs(line):
    return dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line.split(":", 1)[1] if ":" in line else ""))


def trim(lines, max_height):
    """A master playlist cut to one picture and the sound that goes with it"""
    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            uri = next((l for l in lines[i + 1:i + 3] if l.strip() and not l.startswith("#")), None)
            if uri is None:
                continue
            a = attrs(line)
            m = re.match(r"\d+x(\d+)", a.get("RESOLUTION", ""))
            height = int(m.group(1)) if m else 0
            try:
                bandwidth = int(a.get("BANDWIDTH", "0"))
            except ValueError:
                bandwidth = 0
            variants.append((height, "avc1" in a.get("CODECS", ""), bandwidth, line, uri))
    if not variants:
        return lines
    fitting = [v for v in variants if v[0] <= max_height] or [min(variants, key=lambda v: (v[0], v[2]))]
    height, _, _, inf, uri = max(fitting, key=lambda v: (v[1], v[0], v[2]))
    group = attrs(inf).get("AUDIO", "").strip('"')
    group_audio = [l for l in lines if l.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in l and group and f'GROUP-ID="{group}"' in l]
    one = next((l for l in group_audio if "original" in l.lower()), None) \
        or next((l for l in group_audio if "DEFAULT=YES" in l), None) or (group_audio[0] if group_audio else None)
    audio = [one] if one else []
    inf = re.sub(r',(SUBTITLES|CLOSED-CAPTIONS)=("[^"]*"|[^,]*)', "", inf)
    if not audio:
        inf = re.sub(r',AUDIO="[^"]*"', "", inf)
    keep = [l for l in lines if l.startswith(("#EXTM3U", "#EXT-X-VERSION", "#EXT-X-INDEPENDENT-SEGMENTS"))]
    return keep + audio + [inf, uri]


class QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                              # ffmpeg hanging up (a stop, a new address) isn't worth a line in the journal


class Relay:
    """One recording's relay: Relay(url, max_height).start(), then .url"""

    def __init__(self, url, max_height=1080):
        if not web(url):
            raise ValueError("not a web address")
        self.max_height = max_height
        self.secret = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.tokens = collections.OrderedDict()   # token -> (url, kind)
        self.by_url = {}
        self.slots = threading.BoundedSemaphore(SLOTS)
        self.opener = opener()
        # a blocked address, named like a segment so ffmpeg skips it as a
        # missing one instead of giving up on the whole playlist
        self.dead = "x" + secrets.token_urlsafe(9) + ".ts"
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                relay.serve(self)

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.root = self.token_for(url, "root")

    @property
    def port(self):
        return self.server.server_address[1]

    @property
    def url(self):
        return self.address(self.root)

    def address(self, token):
        return f"http://127.0.0.1:{self.port}/{self.secret}/{token}"

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def token_for(self, url, kind):
        with self.lock:
            had = self.by_url.get((url, kind))
            if had and had in self.tokens:
                self.tokens.move_to_end(had)
                return had
            ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
            if kind == "key":
                ext = ".key"
            elif ext in (".m3u", ".m3u8"):
                ext = ".m3u8"
            elif ext not in MEDIA_EXT:
                ext = ".ts" if kind != "root" else ""
            token = secrets.token_urlsafe(12) + ext
            self.tokens[token] = (url, kind)
            self.by_url[(url, kind)] = token
            while len(self.tokens) > TOKENS_MAX:
                old, (old_url, old_kind) = next(iter(self.tokens.items()))
                if old == self.root:
                    self.tokens.move_to_end(old)
                    continue
                del self.tokens[old]
                self.by_url.pop((old_url, old_kind), None)
            return token

    def lookup(self, token):
        with self.lock:
            return self.tokens.get(token)

    def point(self, uri, base, kind):
        full = urllib.parse.urljoin(base, uri.strip())
        if not web(full):
            return self.address(self.dead)
        return self.address(self.token_for(full, kind))

    def rewrite(self, text, base, root):
        lines = [l.rstrip("\r") for l in text.split("\n")]
        if root and any(l.startswith("#EXT-X-STREAM-INF") for l in lines):
            lines = trim(lines, self.max_height)
        out = []
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                kind = "key" if s.startswith(("#EXT-X-KEY", "#EXT-X-SESSION-KEY")) else "media"
                s = URI_ATTR.sub(lambda m: 'URI="%s"' % self.point(m.group(1), base, kind), s)
                out.append(s)
            else:
                out.append(self.point(s, base, "media"))
        return "\n".join(out) + "\n"

    def serve(self, h):
        parts = h.path.split("?", 1)[0].split("/")
        found = self.lookup(parts[2]) if len(parts) == 3 and hmac.compare_digest(parts[1], self.secret) else None
        if not found:
            return self.fail(h, 404)
        url, kind = found
        if not self.slots.acquire(timeout=TIMEOUT):
            return self.fail(h, 503)
        try:
            headers = {k: h.headers[k] for k in SENT_HEADERS if h.headers.get(k)}
            req = urllib.request.Request(url, headers=headers)
            try:
                resp = self.opener.open(req, timeout=TIMEOUT)
            except urllib.error.HTTPError as e:
                return self.fail(h, e.code if 400 <= e.code < 600 else 502)
            except (OSError, ValueError, http.client.HTTPException):
                return self.fail(h, 502)
            if resp is None:
                return self.fail(h, 502)
            with resp:
                final = resp.geturl()
                if not web(final):
                    return self.fail(h, 502)
                ctype = resp.headers.get("Content-Type", "")
                head = resp.read(7)
                listish = "mpegurl" in ctype.lower() or head.startswith(b"#EXTM3U") \
                    or os.path.splitext(urllib.parse.urlsplit(final).path)[1].lower() in (".m3u8", ".m3u")
                if listish and kind != "key":
                    body = head + resp.read(PLAYLIST_MAX + 1 - len(head))
                    if len(body) > PLAYLIST_MAX:
                        return self.fail(h, 502)
                    out = self.rewrite(body.decode("utf-8", "replace"), final, kind == "root").encode()
                    h.send_response(200)
                    h.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    h.send_header("Content-Length", str(len(out)))
                    h.end_headers()
                    h.wfile.write(out)
                    return
                if kind == "key":
                    body = head + resp.read(KEY_MAX + 1 - len(head))
                    if len(body) > KEY_MAX:
                        return self.fail(h, 502)
                    h.send_response(200)
                    h.send_header("Content-Type", "application/octet-stream")
                    h.send_header("Content-Length", str(len(body)))
                    h.end_headers()
                    h.wfile.write(body)
                    return
                h.send_response(resp.status)
                sized = False
                for k in PASSED_HEADERS:
                    if resp.headers.get(k):
                        h.send_header(k, resp.headers[k])
                        sized = sized or k == "Content-Length"
                if not sized:
                    h.send_header("Connection", "close")
                    h.close_connection = True
                h.end_headers()
                h.wfile.write(head)
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    h.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            h.close_connection = True
        finally:
            self.slots.release()

    def fail(self, h, code):
        try:
            h.send_response(code)
            h.send_header("Content-Length", "0")
            h.end_headers()
        except OSError:
            h.close_connection = True

