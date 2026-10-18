#!/usr/bin/python3
"""The marketplace's limits, checked before each commit: /usr/bin/python3 tests/marketplace.test.py

It looks at what git would commit (tracked files, and new ones that aren't
ignored), the way the marketplace's scanner does (its SECURITY.md): bounded,
and failing closed.

- The scan completes: at most 600 files, 4 MiB of text, 450 KiB in any file,
  and Guide.qml at most 400 KiB. (The scanner itself fails closed past
  1,000 files, 8 MiB of text, or 512 KiB in a file.) Every read is bounded;
  once a limit makes the scan incomplete, it stops and fails.
- Symbolic links are never followed (a link is the path git stores), and
  there's no new one since the baseline (aaf099d).
- Executable files are scanned whatever their name, and none is a program
  (ELF, PE or Mach-O).
- No new mention of sudo, pkexec, systemctl, systemd-run, pacman or sudoers
  in what the scanner reads (script and configuration formats, the root
  README, executables; not the test or documentation folders), so no new
  review capability. The only new ones allowed are named exactly, line by
  line, in ALLOWED (the channel lock's reset asks for the computer's password
  the way the firewall change does, running /usr/bin/true and nothing else).
- No new file named like an installer or a setup script.
- No new dependency: QML imports only the modules the plugin already loads,
  and no Python file imports anything outside the standard library and the
  modules beside it (and, for an app, the uber_tv kit) that it didn't import
  at the baseline; a new file imports nothing outside them.

Paths keep their exact bytes (a name that isn't UTF-8 is still scanned), and
a file that can't be read fails the scan."""

import ast
import os
import re
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = "aaf099d"
MAX_FILES, MAX_TEXT, MAX_FILE, MAX_GUIDE = 600, 4 * 1024 * 1024, 450 * 1024, 400 * 1024
WORDS = ["sudo", "pkexec", "systemctl", "systemd-run", "pacman", "sudoers"]
# New mentions allowed since the baseline, each by its file and the exact text
# of its line (stripped): the channel lock's reset asks for the computer's
# password through the system's prompt, as the firewall change already does,
# and runs /usr/bin/true, nothing else
ALLOWED = {"pkexec": [("ChannelLock.qml", "// The computer's password, through the system's usual prompt (pkexec, as"),
                      ("ChannelLock.qml", 'r.start(["/usr/bin/pkexec", "/usr/bin/true"])')]}
QML_MODULES = {"QtQuick", "QtQuick.Effects", "QtQuick.Shapes", "QtMultimedia", "QtTest",
               "Quickshell", "Quickshell.Io", "Quickshell.Wayland", "Quickshell.Hyprland"}
TEXT = (".qml", ".js", ".mjs", ".py", ".md", ".json", ".sh", ".txt", ".toml", ".conf", ".css", ".html", ".in", "")
SCRIPT = (".qml", ".js", ".mjs", ".py", ".json", ".sh", ".toml", ".conf", ".in", "")
# ELF, PE, and Mach-O: thin (32- and 64-bit, both byte orders) and fat
# (32- and 64-bit, both byte orders)
BINARY = (b"\x7fELF", b"MZ",
          b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
          b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca")
failed = []


def check(ok, what):
    # a path that isn't UTF-8 is printed escaped, never a crash
    print((("ok   " if ok else "FAIL ") + what).encode("utf-8", "backslashreplace").decode("utf-8"))
    if not ok:
        failed.append(what)


def stop(what):
    """A limit made the scan incomplete: fail closed, now"""
    check(False, what + " (the scan stops here, incomplete)")
    print("%d failed" % len(failed))
    sys.exit(1)


def git(*args, binary=False):
    out = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def read_bounded(rel, cap):
    """A regular file's bytes, at most cap + 1 of them, never through a link"""
    fd = os.open(os.path.join(ROOT, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks, left = [], cap + 1
        while left > 0:
            b = os.read(fd, min(65536, left))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def blob(rev, rel, cap):
    """A baseline file's bytes, at most cap"""
    size = int(git("cat-file", "-s", rev + ":" + rel).strip() or 0)
    if size > cap:
        return None
    return git("show", rev + ":" + rel, binary=True)


# ---- what git would commit, with modes -----------------------------------------
entries = {}   # path (its exact bytes, as os.fsdecode keeps them) -> mode
for rec in git("ls-files", "-s", "-z", binary=True).split(b"\0"):
    if rec:
        meta, path = rec.split(b"\t", 1)
        entries[os.fsdecode(path)] = int(meta.split()[0], 8)
for path in git("ls-files", "--others", "--exclude-standard", "-z", binary=True).split(b"\0"):
    if path:
        entries[os.fsdecode(path)] = None
sizes = {}
for rel in list(entries):
    try:
        st = os.lstat(os.path.join(ROOT, rel))
    except FileNotFoundError:
        if entries[rel] is not None:      # tracked, deleted here: not part of what's committed
            del entries[rel]
            continue
        stop("%r can't be read" % rel)
    except OSError as e:
        stop("%r can't be read (%s)" % (rel, e))
    if entries[rel] is None:
        entries[rel] = st.st_mode
    sizes[rel] = st.st_size
entries = {p: m for p, m in entries.items() if "__pycache__" not in p}
for rel in sorted(entries):
    if not stat.S_ISLNK(entries[rel]) and sizes.get(rel, 0) > MAX_FILE:
        stop("%r is over %d KiB" % (rel, MAX_FILE // 1024))
if len(entries) > MAX_FILES:
    stop("%d files (at most %d)" % (len(entries), MAX_FILES))
check(True, "%d files (at most %d)" % (len(entries), MAX_FILES))

links = sorted(p for p, m in entries.items() if stat.S_ISLNK(m))
base_modes = {}
for rec in git("ls-tree", "-r", "-z", BASELINE, binary=True).split(b"\0"):
    if rec:
        meta, path = rec.split(b"\t", 1)
        base_modes[os.fsdecode(path)] = int(meta.split()[0], 8)
new_links = [p for p in links if not stat.S_ISLNK(base_modes.get(p, 0))]
check(not new_links, "no new symbolic link" + (": " + ", ".join(new_links) if new_links else ""))


def executable(m):
    return stat.S_ISREG(m) and bool(m & 0o111)


def scanned(rel, m):
    """What the marketplace scanner reads: script and configuration formats,
    the root README, executables, outside test and documentation folders"""
    if stat.S_ISLNK(m) or rel.startswith("tests/") or rel.startswith("docs/"):
        return False
    return rel == "README.md" or rel.startswith("bin/") or executable(m) or os.path.splitext(rel)[1] in SCRIPT


# ---- read everything once, bounded ----------------------------------------------
content, total = {}, 0
for rel, m in sorted(entries.items()):
    if stat.S_ISLNK(m):
        continue
    is_text = os.path.splitext(rel)[1] in TEXT or executable(m)
    if not is_text and not scanned(rel, m):
        continue
    data = read_bounded(rel, MAX_FILE)
    if data is None:
        stop("%s isn't a regular file" % rel)
    if len(data) > MAX_FILE:
        stop("%s is over %d KiB" % (rel, MAX_FILE // 1024))
    if executable(m) and data[:4].startswith(BINARY):
        check(False, "%r is a program (an executable binary)" % rel)
    total += len(data)
    if total > MAX_TEXT:
        stop("more than %d MiB of text" % (MAX_TEXT // 1024 // 1024))
    content[rel] = data
check(True, "%d bytes of text (at most 4 MiB), no file over 450 KiB" % total)
guide = len(content.get("Guide.qml", b""))
check(guide <= MAX_GUIDE, "Guide.qml is %d bytes (at most 400 KiB)" % guide)

# ---- no new capability word in what's scanned ---------------------------------------
base_text = {}
for rel, m in base_modes.items():
    if scanned(rel, m) and not stat.S_ISLNK(m):
        b = blob(BASELINE, rel, MAX_FILE)
        if b is not None:
            base_text[rel] = b
for w in WORDS:
    pat = re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", re.I)
    now = sum(len(pat.findall(content[rel].decode("utf-8", "replace"))) for rel, m in entries.items() if rel in content and scanned(rel, m))
    then = sum(len(pat.findall(b.decode("utf-8", "replace"))) for b in base_text.values())
    allowed = 0
    for rel, line in ALLOWED.get(w, []):
        lines = [l.strip() for l in content.get(rel, b"").decode("utf-8", "replace").splitlines()]
        allowed += sum(len(pat.findall(l)) for l in lines if l == line)
    check(now <= then + allowed, "%s: %d mentions in what's scanned (%d at the baseline%s)" % (w, now, then, ", %d allowed by name" % allowed if allowed else ""))

# ---- no new setup-named file ---------------------------------------------------------
named = [p for p in entries if p not in base_modes and re.search(r"install|setup", os.path.basename(p), re.I)]
check(not named, "no new file named install, installer, setup or uninstall" + (": " + ", ".join(named) if named else ""))

# ---- no new dependency -------------------------------------------------------------
mods = set()
for rel, data in content.items():
    if rel.endswith(".qml") or rel.endswith(".qml.in"):
        mods |= set(re.findall(r"^import ([A-Z][\w.]*)", data.decode("utf-8", "replace"), re.M))
check(mods <= QML_MODULES, "QML imports only modules the plugin already loads" + (": new " + ", ".join(sorted(mods - QML_MODULES)) if mods - QML_MODULES else ""))

def siblings(rel, tree_paths):
    """The modules a file can import by name: the ones beside it, and for an
    app's code, the uber_tv kit the helper puts on its path"""
    d = os.path.dirname(rel)
    out = set()
    for p in tree_paths:
        if os.path.dirname(p) == d and p.endswith(".py"):
            out.add(os.path.splitext(os.path.basename(p))[0])
        elif os.path.dirname(os.path.dirname(p)) == d and os.path.basename(p) == "__init__.py":
            out.add(os.path.basename(os.path.dirname(p)))
    if rel.startswith("apps/"):
        out.add("uber_tv")
    return out


def third_party(source, own):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
        for n in names:
            top = n.split(".")[0]
            if top not in sys.stdlib_module_names and top not in own:
                out.add(top)
    return out


def python(rel, head):
    return rel.endswith(".py") or (rel.startswith("bin/") and head.startswith(b"#!/usr/bin/python3"))


was = {}
for rel, m in base_modes.items():
    if rel.endswith(".py") or rel.startswith("bin/"):
        b = blob(BASELINE, rel, MAX_FILE)
        if b is not None and python(rel, b[:20]):
            was[rel] = third_party(b.decode("utf-8", "replace"), siblings(rel, base_modes))
new_imports = []
for rel, data in content.items():
    if python(rel, data[:20]):
        extra = third_party(data.decode("utf-8", "replace"), siblings(rel, entries)) - was.get(rel, set())
        new_imports += ["%s (%s)" % (n, rel) for n in sorted(extra)]
already = sorted({n for v in was.values() for n in v})
check(not new_imports, "no Python file imports anything new outside the standard library and the modules beside it (already: %s)" % ", ".join(already)
      + (": " + ", ".join(new_imports) if new_imports else ""))

print("all passed" if not failed else "%d failed" % len(failed))
sys.exit(1 if failed else 0)
