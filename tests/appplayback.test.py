#!/usr/bin/python3
"""AppPlayback.qml with a real MediaPlayer, against media served the way the
relay serves it, and a pretend runtime that records every playback call:
/usr/bin/python3 tests/appplayback.test.py

It checks the ordered close (one terminal "stopped" call, then the player
destroyed, the relay closed and the lease given back), the one fallback
after a failure, a second failure ending it, and late answers dropped. The
sound is muted."""

import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
work = tempfile.mkdtemp(prefix="om-pg-playback-test-")
ID = "0123456789abcdef0123456789abcdef"
media = os.path.join(work, ID)
os.makedirs(media)
subprocess.run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", os.path.join(media, "media.mp4")], check=True)
with open(os.path.join(media, "broken.mp4"), "wb") as f:
    f.write(b"\0" * 5000)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=work, **k)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d/%s/" % (server.server_address[1], ID)

test = open(os.path.join(ROOT, "tests", "qml", "playback.qml.in")).read()
test = test.replace("@ROOT@", ROOT).replace("@BASE@", base)
qdir = os.path.join(work, "qml")
os.makedirs(qdir)
with open(os.path.join(qdir, "tst_appplayback.qml"), "w") as f:
    f.write(test)
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
r = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-input", qdir], env=env, capture_output=True, text=True, timeout=120)
out = r.stdout + r.stderr
print("\n".join(l for l in out.splitlines() if l.startswith(("PASS", "FAIL", "Totals", "   Loc", "   Actual", "   Expected", "QWARN", "SKIP"))))
server.shutdown()
shutil.rmtree(work, ignore_errors=True)
sys.exit(r.returncode)
