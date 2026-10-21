"""Pause and rewind's rolling buffer (bin/om-pg-dvr buffer): the playlist the
guide's player opens, the buffer's own segments, and the loopback server
that serves them.

ffmpeg copies the channel into short MPEG-TS segments in the session's
folder, finishing each one under its final name only once it's complete,
and lists them in its own playlist there. That playlist is never served:
Buffer.ingest() reads the segments it names, and Buffer keeps its own list,
each segment with where it starts in the session's time (milliseconds from
its first segment, summed from their lengths, so it matches what the player
seeks by). What's published is the newest N minutes of finished segments by
summed length, never none, a longer single segment kept whole. It's marked
EVENT, so the player can seek in it (its length is fixed when it opens:
every move is a new open, at a new address). A segment's file is deleted
only once neither of the last two published lists names it, so a player
holding the previous list can still read it. A segment from a restarted
writer (a reconnect, a new address) starts a discontinuity.

The server listens on 127.0.0.1 only, on a free port, under a secret path
made for the session; it serves the playlist, the segments still kept (by
exact name, opened from the session's folder without following links,
regular files only) and the status, which is also the guide's lease:
asking for it says the guide is still there. Nothing else, no listings,
bounded requests at once, never a log line.

Kept free of the helper's state and of ffmpeg so it can be tested on its own.
"""

import hmac
import http.server
import json
import os
import re
import stat
import threading
import time
import urllib.parse

SEGMENT_RE = re.compile(r"^s(\d{9})\.ts\Z")
SLOTS = 8
CHUNK = 64 * 1024
PLAYLIST_MAX = 2 * 1024 * 1024
SEGMENT_MAX = 512 * 1024 * 1024


def parse(text):
    """A producer playlist's segments: [(seq, length in ms, name)], only names
    this buffer makes"""
    out, dur, seq = [], None, 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                seq = int(line.split(":", 1)[1])
            except ValueError:
                return []
        elif line.startswith("#EXTINF:"):
            try:
                dur = float(line[8:].split(",")[0])
            except ValueError:
                dur = None
        elif line and not line.startswith("#"):
            m = SEGMENT_RE.match(line)
            if dur is not None and dur > 0 and m:
                out.append((int(m.group(1)), int(round(dur * 1000)), line))
            dur = None
    return out


class Buffer:
    """The session's segments and what's published of them"""

    def __init__(self, dfd, minutes, clock=time.monotonic):
        self.dfd = dfd                    # the session's folder
        self.window_ms = int(float(minutes) * 60000)
        self.clock = clock
        self.lock = threading.Lock()
        self.segments = []                # [{seq, ms, start, name, disc}], oldest first
        self.published = []               # the last two published lists' first seqs, newest last
        self.head = 0                     # the first seq published now
        self.edge = 0                     # where the newest segment ends (session ms)
        self.last_seq = -1
        self.completed = None             # when the newest segment came (clock)
        self.disc_next = False            # the next segment starts a discontinuity

    def restarted(self):
        """The writer starts again (a reconnect, a new address): its next
        segment starts a discontinuity"""
        with self.lock:
            self.disc_next = bool(self.segments)

    def next_seq(self):
        return self.last_seq + 1

    def ingest(self, text):
        """A producer playlist read: its finished segments not seen yet are
        kept, the newest window published, files out of the last two
        published lists deleted. How many came."""
        came = 0
        with self.lock:
            for seq, ms, name in parse(text):
                if seq <= self.last_seq:
                    continue
                try:
                    st = os.stat(name, dir_fd=self.dfd, follow_symlinks=False)
                except OSError:
                    break                 # listed before it's in place: the next read
                if not stat.S_ISREG(st.st_mode):
                    break
                self.segments.append({"seq": seq, "ms": ms, "start": self.edge, "name": name, "disc": self.disc_next})
                self.disc_next = False
                self.edge += ms
                self.last_seq = seq
                came += 1
            if came:
                self.completed = self.clock()
                self.publish()
        return came

    def publish(self):
        total, first = 0, len(self.segments)
        for i in range(len(self.segments) - 1, -1, -1):
            if first < len(self.segments) and total + self.segments[i]["ms"] > self.window_ms:
                break
            total += self.segments[i]["ms"]
            first = i
        self.head = self.segments[first]["seq"]
        self.published = (self.published + [self.head])[-2:]
        keep_from = min(self.published)
        while self.segments and self.segments[0]["seq"] < keep_from:
            gone = self.segments.pop(0)
            try:
                os.unlink(gone["name"], dir_fd=self.dfd)
            except OSError:
                pass

    def live(self):
        """Where Live is: the start of the second-newest finished segment"""
        listed = [s for s in self.segments if s["seq"] >= self.head]
        return listed[-2]["start"] if len(listed) >= 2 else (listed[0]["start"] if listed else 0)

    def status(self):
        with self.lock:
            listed = [s for s in self.segments if s["seq"] >= self.head]
            return {"ready": len(listed) >= 2, "count": len(listed), "headSeq": self.head if listed else 0,
                    "oldest": listed[0]["start"] if listed else 0, "live": self.live(), "edge": self.edge,
                    "newest": listed[-1]["ms"] if listed else 0,
                    "longest": max([s["ms"] for s in listed[-5:]] or [0]),
                    "completedAgo": int((self.clock() - self.completed) * 1000) if self.completed is not None else -1}

    def playlist(self, frm):
        """The published list from seq frm while it's still kept (the guide
        measured its seek from it), or from the head once it has gone"""
        with self.lock:
            start = frm if any(s["seq"] == frm for s in self.segments) else self.head
            listed = [s for s in self.segments if s["seq"] >= start]
            if not listed:
                return None
            lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:EVENT",
                     "#EXT-X-TARGETDURATION:%d" % max(1, max((s["ms"] + 999) // 1000 for s in listed)),
                     "#EXT-X-MEDIA-SEQUENCE:%d" % listed[0]["seq"]]
            for i, s in enumerate(listed):
                if s["disc"] and i:
                    lines.append("#EXT-X-DISCONTINUITY")
                lines += ["#EXTINF:%.3f," % (s["ms"] / 1000), s["name"]]
            return ("\n".join(lines) + "\n").encode()

    def open_segment(self, name):
        """A kept segment's file, opened without following links (a regular
        file), or None"""
        with self.lock:
            if not SEGMENT_RE.match(name) or not any(s["name"] == name for s in self.segments):
                return None
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.dfd)
            except OSError:
                return None
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > SEGMENT_MAX:
            os.close(fd)
            return None
        return fd


class QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                              # a player hanging up mid-segment isn't worth a line in the journal


class Server:
    """The buffer on 127.0.0.1: Server(buffer, secret, state).start(), then .port.
    state() is the worker's own part of the status (state, reason);
    every status asked for renews the lease (.asked)."""

    def __init__(self, buffer, secret, state, clock=time.monotonic):
        self.buffer = buffer
        self.secret = secret
        self.state = state
        self.clock = clock
        self.asked = clock()
        self.slots = threading.BoundedSemaphore(SLOTS)
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 20

            def log_message(self, *args):
                pass

            def do_GET(self):
                if not server.slots.acquire(blocking=False):
                    self.send_error(503)
                    return
                try:
                    server.serve(self)
                finally:
                    server.slots.release()

        self.httpd = QuietServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def serve(self, h):
        url = urllib.parse.urlsplit(h.path)
        parts = url.path.split("/")
        if len(parts) != 3 or parts[0] or not hmac.compare_digest(parts[1].encode(), self.secret.encode()):
            h.send_error(404)
            return
        name = parts[2]
        if name == "status":
            self.asked = self.clock()
            body = json.dumps(dict(self.buffer.status(), **self.state())).encode()
            self.send(h, body, "application/json")
        elif name == "live.m3u8":
            q = urllib.parse.parse_qs(url.query)
            frm = (q.get("from") or ["0"])[0]
            body = self.buffer.playlist(int(frm) if frm.isdigit() and len(frm) < 12 else 0)
            if body is None:
                h.send_error(503)
                return
            self.send(h, body, "application/vnd.apple.mpegurl")
        else:
            fd = self.buffer.open_segment(name)
            if fd is None:
                h.send_error(404)
                return
            with os.fdopen(fd, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                h.send_response(200)
                h.send_header("Content-Type", "video/mp2t")
                h.send_header("Content-Length", str(size))
                h.end_headers()
                left = size
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    h.wfile.write(chunk)
                    left -= len(chunk)

    @staticmethod
    def send(h, body, kind):
        h.send_response(200)
        h.send_header("Content-Type", kind)
        h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(body)
