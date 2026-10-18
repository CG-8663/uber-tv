#!/usr/bin/env python3
"""Install transactions, package bounds, atomic renames and cleanup races.

These are the install-side regressions retained when link-based Unknown
sources were replaced by signed app files. Run directly with Python.
"""

import ctypes
import errno
import gzip
import hashlib
import importlib.util
import io
import json
import os
import resource
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zlib
from importlib.machinery import SourceFileLoader


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HELPER = os.path.join(ROOT, "bin", "om-pg-apps")


def load(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def wipe(path):
    """Remove a test folder, including read-only installed copies."""
    for root, dirs, _ in os.walk(path):
        for name in dirs:
            full = os.path.join(root, name)
            if not os.path.islink(full):
                os.chmod(full, 0o700)
    shutil.rmtree(path)


helper = load("om_pg_apps_install", os.path.join(ROOT, "bin", "om-pg-apps"))


def really(path):
    return os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))


def someone_elses(path, file=None):
    os.mkdir(path)
    if file:
        path = os.path.join(path, file)
        with open(path, "w") as stream:
            stream.write("someone else's")
    return os.open(path, os.O_PATH | os.O_NOFOLLOW)


def someone_elses_file(folder, name):
    other = os.path.join(folder, "someone-elses.tmp")
    with open(other, "wb") as stream:
        stream.write(b"someone else's")
    fd = os.open(other, os.O_PATH | os.O_NOFOLLOW)
    os.replace(other, os.path.join(folder, name))
    return fd


def waiting(procs, path, seconds=60):
    ino = ":" + str(os.stat(path).st_ino)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with open("/proc/locks") as stream:
            rows = [row.split() for row in stream]
        blocked = {int(row[5]) for row in rows
                   if len(row) > 6 and row[1] == "->" and row[2] == "FLOCK"
                   and row[6].endswith(ino)}
        if all(proc.pid in blocked for proc in procs):
            return True
        if any(proc.poll() is not None for proc in procs):
            return False
        time.sleep(0.01)
    return False


def answer(proc, seconds=120):
    out, err = proc.communicate(timeout=seconds)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "error": "no JSON: " + out + err}


def slurp(path):
    with open(path, "rb") as stream:
        return stream.read()


def peak(fn):
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(rfd)
        try:
            before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            try:
                out = fn()
            except BaseException as error:
                out = {"raised": repr(error)}
            grew = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) // 1024
            with os.fdopen(wfd, "wb") as stream:
                stream.write(json.dumps([out, grew]).encode())
        finally:
            os._exit(0)
    os.close(wfd)
    with os.fdopen(rfd, "rb") as stream:
        data = stream.read()
    os.waitpid(pid, 0)
    return json.loads(data)


def header(kind, size, name="././@PaxHeader", fmt=tarfile.USTAR_FORMAT):
    info = tarfile.TarInfo(name)
    info.type, info.size = kind, size
    return info.tobuf(fmt)


def blocks(data):
    return data + b"\0" * (-len(data) % tarfile.BLOCKSIZE)


def git_header(commit="aa09031f17e6c173b364e10d88be59bfc73cbc91"):
    record = b"52 comment=" + commit.encode() + b"\n"
    return header(tarfile.XGLTYPE, len(record), "pax_global_header") + blocks(record)


def first(package, *parts):
    return gzip.compress(b"".join(parts) + gzip.decompress(package), 9)


def zeros(size, head=b"", tail=b""):
    stream = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    out, left, mib = [stream.compress(head)], (size + 511) // 512 * 512, b"\0" * (1 << 20)
    while left:
        piece = min(left, len(mib))
        out.append(stream.compress(mib[:piece]))
        left -= piece
    return b"".join(out + [stream.compress(tail), stream.flush()])


def zeros_first(package, size, kind=tarfile.XHDTYPE):
    return zeros(size, header(kind, size), gzip.decompress(package))


class Web:
    """Compatibility shell for retained tests; offer() refreshes locally."""

    def __init__(self, files):
        self.files = files

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class InstallBase(unittest.TestCase):
    SOURCE = "catalog:uber"
    FILE = "file:0123456789abcdef"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="om-pg-install-test-")
        cls.key = os.path.join(cls.tmp, "key")
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                        "-C", "test", "-f", cls.key], check=True)
        with open(cls.key + ".pub") as stream:
            cls.public = " ".join(stream.read().split()[:2])
        cls.signers = os.path.join(cls.tmp, "signers")
        with open(cls.signers, "w") as stream:
            stream.write('uber-tv-catalog namespaces="uber-tv-catalog" ' + cls.public + "\n")

    @classmethod
    def tearDownClass(cls):
        wipe(cls.tmp)

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=self.tmp)
        self.stagingApps = os.path.join(self.dir, "cache", "app-staging")
        self.appsRoot = os.path.join(self.dir, "share", "apps")
        self.dataRoot = os.path.join(self.dir, "share", "app-data")
        self.store = os.path.join(self.dir, "unused-sources.json")
        self.state = os.path.join(self.dir, "unused-source-state")
        self.catalogDir = os.path.join(self.dir, "catalog")
        self.catalogCache = os.path.join(self.dir, "catalog-cache")
        self.catalogPath = os.path.join(self.catalogDir, "catalog.json")
        self.files = {}
        os.makedirs(os.path.join(self.catalogDir, "packages"))
        self.offer()

    def app(self, version="1.0.0", perms=None, name="clock", extra=None):
        folder = os.path.join(self.dir, "app-" + name + "-" + version)
        os.makedirs(folder, exist_ok=True)
        manifest = {
            "id": "tv.alex.clock", "name": "Clock", "version": version,
            "api": 1, "kind": "launcher", "author": "Alex",
            "description": "A test app.", "color": "#224466",
            "launch": {"web": "https://clock.example.com/"},
            "permissions": perms if perms is not None else {"web": ["clock.example.com"]},
        }
        with open(os.path.join(folder, "app.json"), "w") as stream:
            json.dump(manifest, stream)
        with open(os.path.join(folder, "README.md"), "wb") as stream:
            stream.write(b"# Clock\n")
        for rel, data in (extra or {}).items():
            path = os.path.join(folder, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as stream:
                stream.write(data)
        out = os.path.join(self.dir, "clock-" + name + "-" + version + ".tar.gz")
        try:
            os.unlink(out)
        except FileNotFoundError:
            pass
        result = helper.do_pack(folder, out)
        with open(out, "rb") as stream:
            data = stream.read()
        return data, result["catalogEntry"], folder

    def offer(self, version="1.0.0", updated=1000, perms=None, package=None,
              listed_perms=None, extra=None):
        data, entry, _ = self.app(version, perms, extra=extra)
        if listed_perms is not None:
            entry["permissions"] = listed_perms
        name = "clock-" + version + ".tar.gz"
        entry["package"] = "packages/" + name
        with open(os.path.join(self.catalogDir, "packages", name), "wb") as stream:
            stream.write(package if package is not None else data)
        with open(self.catalogPath, "w") as stream:
            json.dump({"format": 1, "name": "Test catalog", "updated": updated,
                       "apps": [entry], "revoked": []}, stream)
        try:
            os.unlink(self.catalogPath + ".sig")
        except FileNotFoundError:
            pass
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-Y", "sign", "-f", self.key,
                        "-n", "uber-tv-catalog", self.catalogPath],
                       check=True, capture_output=True)
        helper.do_catalog(self.catalogPath, self.signers, 0, self.catalogCache)
        self.version = version
        return entry

    def added(self):
        return {"id": self.SOURCE}

    def fetched(self, source):
        return {"ok": True, "source": source}

    def snapshot(self, *args, **kwargs):
        return b"catalog"

    def prepare(self, raw):
        return helper.do_inspect(
            {"type": "catalog", "id": "tv.alex.clock", "cache": self.catalogCache,
             "signers": self.signers, "seen": 0},
            self.stagingApps,
        )

    def install(self, result, source):
        return helper.do_install(result["staging"], self.appsRoot, self.dataRoot,
                                 result["tree"], source)

    def verify(self):
        result = helper.do_verify(self.appsRoot, self.signers)
        return {app["id"] + "@" + app["version"]: app for app in result["apps"]}


class Installing(InstallBase):
    """Install transaction regressions, exercised through signed catalog proof."""

    def installed_state(self, home):
        out = {}
        for root, dirs, files in os.walk(home):
            for f in files:
                p = os.path.join(root, f)
                out[os.path.relpath(p, home)] = slurp(p)
        return out

    def test_a_folder_read_once_is_listed_again_from_its_start(self):
        """btrfs: a folder descriptor that was read once doesn't show what's
        added after that until it's rewound. A catalog app's proof folder is
        checked empty as it's made, then filled and checked: it still goes
        in. Here every listing through a descriptor shows only what it showed
        the first time, unless the descriptor was rewound since"""
        real_scandir, real_listdir, real_lseek = os.scandir, os.listdir, os.lseek
        first = {}   # (descriptor, its folder's inode): the names its first listing showed

        class Listing:
            def __init__(self, entries):
                self.entries = iter(entries)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def __iter__(self):
                return self
            def __next__(self):
                return next(self.entries)
            def close(self):
                pass

        def shown(fd, names):
            key = (fd, os.fstat(fd).st_ino)
            if key not in first:
                first[key] = set(names)
            return [n for n in names if n in first[key]]

        def scandir(target="."):
            if not isinstance(target, int):
                return real_scandir(target)
            with real_scandir(target) as found:
                entries = list(found)
            keep = set(shown(target, [e.name for e in entries]))
            return Listing([e for e in entries if e.name in keep])

        def listdir(target="."):
            if not isinstance(target, int):
                return real_listdir(target)
            return shown(target, real_listdir(target))

        def lseek(fd, pos, how):
            if pos == 0 and how == os.SEEK_SET:
                first.pop((fd, os.fstat(fd).st_ino), None)
            return real_lseek(fd, pos, how)

        s = self.added()
        res = self.prepare(self.snapshot())
        os.scandir, os.listdir, os.lseek = scandir, listdir, lseek
        try:
            done = self.install(res, s["id"])
        finally:
            os.scandir, os.listdir, os.lseek = real_scandir, real_listdir, real_lseek
        home = os.path.dirname(done["path"])
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], "installed, with its proof")
        self.assertTrue(os.path.exists(os.path.join(done["path"], "app.json")))
        # and a new copy that can't be made (a full disk) is one to try again,
        # with nothing changed
        res = self.prepare(self.snapshot())
        before = self.installed_state(home)
        real_copy_one = helper.copy_one

        def full(*a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")
        helper.copy_one = full
        try:
            with self.assertRaises(helper.Retry) as e:
                self.install(res, s["id"])
        finally:
            helper.copy_one = real_copy_one
        said = helper.failure(e.exception)
        self.assertTrue(said["retry"] and said["unchanged"], said)
        self.assertIn("couldn't be made ready", said["error"])
        self.assertEqual(self.installed_state(home), before, "exactly as it was")
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], "nothing left beside it")

    def test_a_swap_that_fails_at_any_point_changes_nothing(self):
        """the same version installed again: a rename failing at each step of
        the swap (each one exchange: the version and its proof are never
        missing) puts back exactly what was there, and leaves nothing beside"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        before = self.installed_state(home)
        for k in range(2):
            res = self.prepare(self.snapshot())
            calls = []

            def failing(a, b, real, k=k, calls=calls):
                calls.append(1)
                if len(calls) == k + 1:
                    raise OSError(5, "Input/output error")
                return real(a, b)
            with self.renames(failing), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
            self.assertIn("nothing changed", str(e.exception), k)
            self.assertIsInstance(e.exception, helper.Unchanged)
            self.assertEqual(self.installed_state(home), before, "failing at step %d: exactly as it was" % (k + 1))
            self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], "nothing left beside it")

    def test_a_new_version_that_cant_be_made_leaves_nothing_beside(self):
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        before = self.installed_state(home)
        res = self.prepare(self.snapshot())
        real = helper.copy_one

        def full(sfd, name, dfd, own, room):
            real(sfd, name, dfd, own, room)   # (one file made, then the disk is full)
            raise OSError(28, "No space left on device")
        helper.copy_one = full
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.copy_one = real
        self.assertIn("couldn't be made ready", str(e.exception))
        self.assertIsInstance(e.exception, helper.Unchanged)
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], "nothing half-made left beside it")
        self.assertEqual(self.installed_state(home), before)

    def test_ctrl_c_while_its_new_copy_is_made_leaves_nothing_beside(self):
        """interrupted while its new copy is made (the proof's files being
        copied): its own copies are taken away, what was there is as it was,
        and the interrupt still stops the command"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        before = self.installed_state(home)
        res = self.prepare(self.snapshot())
        real = helper.copy_one

        def interrupted(*a, **k):
            raise KeyboardInterrupt
        helper.copy_one = interrupted
        try:
            with self.assertRaises(KeyboardInterrupt):
                self.install(res, s["id"])
        finally:
            helper.copy_one = real
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], "nothing half-made left beside it")
        self.assertEqual(self.installed_state(home), before)

    def test_a_first_install_whose_undo_fails_says_so(self):
        """nothing there before; the proof's rename fails and moving the new
        version back out fails too: never 'nothing changed'"""
        s = self.added()
        res = self.prepare(self.snapshot())
        real = helper.move_one
        calls = []

        def failing(a, b):
            calls.append((a, b))
            if len(calls) == 2 or ".new-" in os.path.basename(b):   # the proof's rename, then every move back out
                raise OSError(5, "Input/output error")
            return real(a, b)
        helper.move_one = failing
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.move_one = real
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("is still there (remove it)", msg)

    def test_something_else_at_an_empty_name_isnt_counted_as_put_back(self):
        """a first install undone: its own new version is moved back out, but
        something else is at that name by the time it's checked: not
        'nothing changed', and that something is named, not taken away"""
        s = self.added()
        res = self.prepare(self.snapshot())
        real = helper.move_one
        calls = []

        def meanwhile(a, b):
            calls.append((a, b))
            if len(calls) == 2:
                raise OSError(5, "Input/output error")   # the proof's rename
            real(a, b)
            if os.path.basename(b).startswith(".new-") and os.path.basename(a) == "1.0.0":
                os.mkdir(a)   # someone else's, at the name that was empty
        helper.move_one = meanwhile
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.move_one = real
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("something else is at 1.0.0", msg)
        self.assertTrue(os.path.isdir(os.path.join(self.appsRoot, helper.source_dir(s["id"]), "tv.alex.clock", "1.0.0")), "not taken away")

    def test_a_rename_back_that_moves_something_foreign_is_reverted(self):
        """the same version reinstalled; the swap fails, and just as the undo
        exchanges what was there back in, it's been taken elsewhere and
        something else put in its place: that's exchanged straight back out,
        never left installed, and reported to be looked at"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        res = self.prepare(self.snapshot())
        failed = []

        def meanwhile(a, b, real):
            names = (os.path.basename(a), os.path.basename(b))
            if not failed and "1.0.0.proof" in names:
                failed.append(1)
                raise OSError(5, "Input/output error")   # the proof's step
            if failed and names[0].startswith(".new-") and names[1] == "1.0.0" and not os.path.exists(os.path.join(home, ".gone")):
                os.rename(a, os.path.join(home, ".gone"))   # what was there taken elsewhere,
                os.mkdir(a)                                 # something else in its place
            return real(a, b)
        with self.renames(meanwhile), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("the new 1.0.0 in " + home + " is still there, and what was at it isn't at", msg)
        self.assertTrue(os.path.isfile(os.path.join(home, "1.0.0", "app.json")), "the new one stays: the foreign one isn't left installed")
        aside = [n for n in os.listdir(home) if n.startswith(".new-") and not n.endswith(".proof")]
        self.assertEqual(len(aside), 1)
        self.assertIn(aside[0], msg, "where it was looked for is named")
        self.assertEqual(os.listdir(os.path.join(home, aside[0])), [], "it's back where it was, untouched")
        self.assertTrue(os.path.isfile(os.path.join(home, ".gone", "app.json")), "and what was there wasn't deleted")

    def test_ctrl_c_during_the_swap_changes_nothing(self):
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        before = self.installed_state(home)
        for k in range(2):
            for when in ("before", "after"):
                res = self.prepare(self.snapshot())
                calls = []

                def interrupted(a, b, real, k=k, when=when, calls=calls):
                    calls.append(1)
                    if len(calls) == k + 1:
                        if when == "after":
                            real(a, b)
                        raise KeyboardInterrupt
                    return real(a, b)
                with self.renames(interrupted), self.assertRaises(KeyboardInterrupt):
                    self.install(res, s["id"])
                self.assertEqual(self.installed_state(home), before, "interrupted %s step %d: as it was" % (when, k + 1))
                self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"])

    def test_tidying_after_the_install_cant_deny_it(self):
        """the new version is in; taking the old proof away fails, and so
        does deleting the old version in the private folder: it's installed,
        with a warning naming both, never 'not installed'"""
        s = self.added()
        self.install(self.prepare(self.snapshot()), s["id"])
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        real_take, real_wipe = helper.take_own, helper.wipe_own

        def take(path, ino, trash):
            if os.path.basename(path) == "1.0.0.proof":
                raise OSError(5, "Input/output error")
            return real_take(path, ino, trash)

        def wipe(dfd, name, ino, own, depth=0):
            return False if name == "1.0.0" else real_wipe(dfd, name, ino, own, depth)
        helper.take_own, helper.wipe_own = take, wipe
        try:
            out = self.install(res, s["id"])
        finally:
            helper.take_own, helper.wipe_own = real_take, real_wipe
        self.assertTrue(out["ok"])
        self.assertEqual(out["manifest"]["version"], "1.1.0")
        home = os.path.dirname(out["path"])
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertIn("1.0.0.proof couldn't be tidied away", out["warning"])
        self.assertIn(trash[0] + " in " + home + " holds what couldn't be taken away: look at it before anything else.", out["warning"])
        self.assertEqual(os.listdir(os.path.join(home, trash[0])), ["1.0.0"])
        v = self.verify()
        self.assertEqual(v["tv.alex.clock@1.1.0"]["problem"], "")

    def test_a_swap_whose_rollback_fails_keeps_what_was_there(self):
        """the swap fails at its last step and putting back fails too: never
        'nothing changed'; what was there is kept beside it, named, intact"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        before = self.installed_state(home)
        old = {f: helper.inode(os.path.join(home, f)) for f in ("1.0.0", "1.0.0.proof")}
        res = self.prepare(self.snapshot())
        calls = []

        def failing(a, b, real):
            calls.append((a, b))
            if len(calls) == 2 or (len(calls) > 2 and os.path.basename(b) in old):   # the last step, then every move back
                raise OSError(5, "Input/output error")
            return real(a, b)
        with self.renames(failing), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("didn't finish", msg)
        kept = {n: f for n in os.listdir(home) for f, ino in old.items() if n != f and helper.inode(os.path.join(home, n)) == ino}
        self.assertTrue(kept, "what was there is kept beside it")
        for n, f in kept.items():
            self.assertIn(n, msg, "and named")
            for rel, data in self.installed_state(os.path.join(home, n)).items():
                self.assertEqual(data, before[os.path.join(f, rel)], rel + ": intact")

    def test_an_update_prepared_then_installed(self):
        s = self.added()
        self.install(self.prepare(self.snapshot()), s["id"])
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        self.assertTrue(res["ok"], res)
        self.install(res, s["id"])
        v = self.verify()
        self.assertEqual((v["tv.alex.clock@1.1.0"]["proof"], v["tv.alex.clock@1.1.0"]["problem"]), ("catalog", ""))
        self.assertNotIn("tv.alex.clock@1.0.0", v, "the old version went")

    def renames(self, hook):
        """Every rename of the swap and its undo (move_one, and exchange_one
        where there is one), and every move into or out of its private
        folder (rename_at with a folder held open, its path read back from
        /proc), through hook(a, b, real) with their paths, while in the with"""
        import contextlib

        @contextlib.contextmanager
        def standing_in():
            reals = {n: getattr(helper, n) for n in ("move_one", "exchange_one") if hasattr(helper, n)}
            real_at = helper.rename_at

            def where(fd, name):
                return name if fd is None else os.path.join(os.readlink("/proc/self/fd/%d" % fd), name)

            def at(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
                if src_dir_fd is None and dst_dir_fd is None:
                    return real_at(src, dst, flags)   # (move_one's or exchange_one's own, or the staged files')
                return hook(where(src_dir_fd, src), where(dst_dir_fd, dst), lambda a, b: real_at(src, dst, flags, src_dir_fd, dst_dir_fd))
            for n, real in reals.items():
                setattr(helper, n, (lambda real: lambda a, b: hook(a, b, real))(real))
            helper.rename_at = at
            try:
                yield
            finally:
                for n, real in reals.items():
                    setattr(helper, n, real)
                helper.rename_at = real_at
        return standing_in()

    def held_open(self, fd):
        self.addCleanup(os.close, fd)
        return fd

    def reinstalled(self):
        """1.0.0 from the catalog installed, then prepared again (the same
        version): (the catalog, what's prepared, its folder, what's in it)"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        return s, self.prepare(self.snapshot()), home, self.installed_state(home)

    FILE = "file:0123456789abcdef"

    def from_file(self, version):
        """Clock at version, staged from a file as Developer mode does (no proof)"""
        self.app(version, name="file")
        return helper.do_inspect({"type": "file", "path": os.path.join(self.dir, "app-file-" + version)}, self.stagingApps)

    def file_home(self):
        return os.path.join(self.appsRoot, helper.source_dir(self.FILE), "tv.alex.clock")

    def run_helper(self, *args):
        """The helper as the guide runs it: a process of its own"""
        return subprocess.Popen([sys.executable, HELPER] + [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True)

    def test_an_undo_never_replaces_something_at_an_empty_name(self):
        """Y8-1, the first of the two measured cases: a first install's proof
        can't go in; just as the undo moves the new 1.0.0 back out to its
        empty .new- name, someone else's empty folder is put there: it's
        never replaced, and no clean undo is claimed"""
        s = self.added()
        res = self.prepare(self.snapshot())
        calls, fds = [], []

        def hook(a, b, real):
            calls.append(b)
            if len(calls) == 2:
                raise OSError(5, "Input/output error")   # the proof's rename in
            if os.path.basename(a) == "1.0.0" and os.path.basename(b).startswith(".new-") and not fds:
                fds.append(self.held_open(someone_elses(b)))
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertTrue(fds, "(the undo moved the new 1.0.0 back out)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "someone else's folder is never replaced")
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("is still there (remove it)", msg)

    def test_a_same_version_undo_never_replaces_something_at_its_new_name(self):
        """Y8-1, the second measured case: a same-version reinstall's swap
        fails, and just as the undo moves the new 1.0.0 back out, someone
        else's empty folder is put at its .new- name if nothing is there: it's
        never replaced (each swap is one exchange, so the name is never
        empty), and the undo puts back exactly what was there"""
        s, res, home, before = self.reinstalled()
        failed, fds = [], []

        def hook(a, b, real):
            names = (os.path.basename(a), os.path.basename(b))
            if not failed and "1.0.0.proof" in names:
                failed.append(1)
                raise OSError(5, "Input/output error")   # the proof's step
            if failed and "1.0.0" in names and not fds:
                new = os.path.join(home, next(n for n in names if n.startswith(".new-")))
                if not os.path.lexists(new):
                    fds.append(self.held_open(someone_elses(new)))
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        for fd in fds:
            self.assertGreater(os.fstat(fd).st_nlink, 0, "someone else's folder is never replaced")
        self.assertEqual(fds, [], "the .new- name is never empty while the undo needs it")
        self.assertIn("nothing changed", str(e.exception))
        self.assertEqual(self.installed_state(home), before)
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"])

    def test_after_a_clean_undo_only_its_own_copies_are_taken_away(self):
        """F4: a same-version reinstall's swap fails and is undone; just as
        its own new copy is taken away from its .new- name, someone else's
        folder takes its place: that folder is never deleted, and nothing
        claims 'nothing changed' (its own copy isn't accounted for)"""
        s, res, home, before = self.reinstalled()
        failed, fds = [], []

        def meanwhile(path):
            if not fds and os.path.dirname(really(path)) == home and os.path.basename(path).startswith(".new-"):
                os.rename(path, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))

        def hook(a, b, real):
            names = (os.path.basename(a), os.path.basename(b))
            if not failed and "1.0.0.proof" in names:
                failed.append(1)
                raise OSError(5, "Input/output error")   # the proof's step
            if failed and os.path.basename(os.path.dirname(b)).startswith(".trash-"):
                meanwhile(a)   # taking its own copy away
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertTrue(fds, "(its own copy was being taken away)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "someone else's folder is never deleted")
        self.assertNotIn("nothing changed", str(e.exception))

    def test_after_a_clean_undo_something_else_at_its_name_is_never_moved(self):
        """the own-copies rule: a same-version reinstall's swap fails and is
        undone; before its own new copy is taken away, it's moved elsewhere
        and someone else's folder put at its .new- name: that folder is never
        moved (not even into the private folder and back), and nothing claims
        'nothing changed'"""
        s, res, home, before = self.reinstalled()
        failed, fds, names = [], [], []
        real_take = helper.take_own

        def take(path, ino, trash):
            if not fds and os.path.basename(path).startswith(".new-") and not path.endswith(".proof"):
                os.rename(path, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))
                names.append(really(path))
            return real_take(path, ino, trash)

        def hook(a, b, real):
            if not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                failed.append(1)
                raise OSError(5, "Input/output error")   # the proof's step
            if os.path.basename(os.path.dirname(a)).startswith(".trash-"):
                raise OSError(5, "Input/output error")   # nothing taken in comes back out
            return real(a, b)
        helper.take_own = take
        try:
            with self.renames(hook), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.take_own = real_take
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0)
        self.assertTrue(os.path.isfile(os.path.join(names[0], "notes.txt")), "it's still at its name")
        self.assertNotIn("nothing changed", str(e.exception))

    def test_a_folder_put_at_an_empty_name_just_before_the_new_one_goes_in_is_kept(self):
        """F4: a first install; someone else's empty folder appears at 1.0.0
        just before the new 1.0.0 goes in: it's never replaced (a rename that
        can't), the install fails, and it's named, not claimed unchanged"""
        s = self.added()
        res = self.prepare(self.snapshot())
        fds = []

        def hook(a, b, real):
            if os.path.basename(b) == "1.0.0" and os.path.basename(a).startswith(".new-") and not fds:
                fds.append(self.held_open(someone_elses(b)))
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "someone else's folder is never replaced")
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("something else is at 1.0.0", msg)

    def test_a_proof_name_taken_while_its_made_is_never_deleted(self):
        """F6: the new proof's name (known once the new version's copy is
        there) is taken by someone else's folder just before the proof's
        folder is made: it's never deleted, and the install fails having
        taken away only its own copy"""
        s, res, home, before = self.reinstalled()
        real_mkdir, fds = os.mkdir, []

        def mkdir(path, *a, **k):
            p = path if isinstance(path, str) else ""
            if not fds and os.path.basename(p).startswith(".new-") and p.endswith(".proof"):
                real_mkdir(p)   # someone else's, with a file in it
                with open(os.path.join(p, "notes.txt"), "w") as f:
                    f.write("someone else's")
                fds.append(self.held_open(os.open(os.path.join(p, "notes.txt"), os.O_PATH | os.O_NOFOLLOW)))
            return real_mkdir(path, *a, **k)
        os.mkdir = mkdir
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.mkdir = real_mkdir
        self.assertTrue(fds, "(the proof's folder was being made)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "someone else's folder is never deleted")
        self.assertIn("couldn't be made ready", str(e.exception))
        state = self.installed_state(home)
        self.assertEqual({k: v for k, v in state.items() if not k.startswith(".new-")}, before, "what was there is as it was")
        self.assertEqual([n for n in os.listdir(home) if n not in ("1.0.0", "1.0.0.proof")], [os.path.basename(os.path.dirname(
            os.readlink("/proc/self/fd/%d" % fds[0])))], "and nothing of its own is left beside it")

    def test_a_new_copys_name_already_taken_is_never_deleted(self):
        """F6: someone else's folder is already at the new copy's name (its
        random tag pinned here), with a file in it or empty (which a plain
        rename would replace), when the staged files are moved there and when
        they're copied there from another filesystem: never deleted, and the
        install fails changing nothing"""
        for across, file in ((False, "notes.txt"), (False, None), (True, "notes.txt")):
            self.setUp()
            s, res, home, before = self.reinstalled()
            fd = self.held_open(someone_elses(os.path.join(home, ".new-feedfacecafe"), file))
            real_hex, real_rename, real_at = helper.secrets.token_hex, os.rename, getattr(helper, "rename_at", None)

            def token_hex(n=None):
                return "feedfacecafe" if n == 6 else real_hex(n)

            def cross(real):
                def rename(a, b, *x, **k):
                    if across and os.path.basename(a) == "files":
                        raise OSError(errno.EXDEV, "Invalid cross-device link")
                    return real(a, b, *x, **k)
                return rename
            helper.secrets.token_hex, os.rename = token_hex, cross(real_rename)
            if real_at:
                helper.rename_at = cross(real_at)
            try:
                with self.assertRaises(helper.Bad) as e:
                    self.install(res, s["id"])
            finally:
                helper.secrets.token_hex, os.rename = real_hex, real_rename
                if real_at:
                    helper.rename_at = real_at
            self.assertGreater(os.fstat(fd).st_nlink, 0, "across filesystems: %s, a file in it: %s: never deleted" % (across, file))
            self.assertIn("couldn't be made ready", str(e.exception))
            self.assertIn("nothing changed", str(e.exception))
            self.assertEqual(sorted(os.listdir(os.path.join(home, ".new-feedfacecafe"))), [file] if file else [])
            self.assertEqual({k: v for k, v in self.installed_state(home).items() if not k.startswith(".new-")}, before)

    def test_an_install_without_a_proof_never_takes_someone_elses(self):
        """F6: an app from a file has no proof; someone else's folder appears
        at its .new- proof name before the swap: it's never put in place as
        the app's proof (only what the install made goes in)"""
        res = self.from_file("1.0.0")
        made = []

        def hook(a, b, real):
            new = next((x for x in (a, b) if os.path.basename(x).startswith(".new-")), None)
            if new and not made:
                made.append(1)
                os.close(someone_elses(new + ".proof", "notes.txt"))
            return real(a, b)
        with self.renames(hook):
            out = helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
        self.assertTrue(made)
        self.assertEqual(out["proof"], "none")
        self.assertFalse(os.path.lexists(os.path.join(self.file_home(), "1.0.0.proof")), "someone else's folder isn't its proof")
        v = self.verify()["tv.alex.clock@1.0.0"]
        self.assertEqual((v["proof"], v["problem"]), ("none", ""))

    def test_a_same_version_undo_that_cant_finish_names_what_was_there(self):
        """F21: a same-version reinstall's swap fails, and every move of the
        new 1.0.0 back out fails too: the error names where the previous
        1.0.0 is (the only copy of it), and following its steps gives back
        exactly what was there"""
        s, res, home, before = self.reinstalled()
        old = helper.inode(os.path.join(home, "1.0.0"))
        failed = []

        def hook(a, b, real):
            names = (os.path.basename(a), os.path.basename(b))
            if not failed and "1.0.0.proof" in names:
                failed.append(1)
                raise OSError(5, "Input/output error")   # the proof's step
            if failed and "1.0.0" in names:
                raise OSError(5, "Input/output error")   # every move of 1.0.0 back
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("the new 1.0.0 in " + home + " is still there", msg)
        kept = [n for n in os.listdir(home) if helper.inode(os.path.join(home, n)) == old]
        self.assertEqual(len(kept), 1, "the previous 1.0.0 is beside it")
        self.assertIn("the new 1.0.0 in " + home + " is still there, and " + kept[0] + " there is what was at it (remove the new one, then rename that back);",
                      msg, "and named, with both steps")
        self.assertNotIn("something else", msg, "and nothing else is said of its own new copy")
        # its steps followed: the new one removed (read-only, as installed),
        # the one that was there renamed back
        os.chmod(os.path.join(home, "1.0.0"), 0o700)
        wipe(os.path.join(home, "1.0.0"))
        os.rename(os.path.join(home, kept[0]), os.path.join(home, "1.0.0"))
        self.assertEqual(helper.inode(os.path.join(home, "1.0.0")), old)
        self.assertEqual({k: v for k, v in self.installed_state(home).items() if k.split(os.sep)[0] in ("1.0.0", "1.0.0.proof")}, before)

    def test_something_else_in_place_of_the_new_one_names_what_was_there(self):
        """F21: after the new 1.0.0 went in, something else took its place
        before the undo: that's to be looked at, and the error also names
        where the previous 1.0.0 is"""
        s, res, home, before = self.reinstalled()
        old = helper.inode(os.path.join(home, "1.0.0"))
        failed = []

        def hook(a, b, real):
            if not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                failed.append(1)
                final = os.path.join(home, "1.0.0")
                os.rename(final, os.path.join(home, "taken-elsewhere"))   # the new one taken away,
                os.mkdir(final)                                           # something else in its place
                raise OSError(5, "Input/output error")
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn("something else is at 1.0.0", msg)
        kept = [n for n in os.listdir(home) if helper.inode(os.path.join(home, n)) == old]
        self.assertEqual(len(kept), 1)
        self.assertIn("something else is at 1.0.0 in " + home + " now (look at it before anything else; what was at it is " + kept[0] + " there);",
                      msg, "what was there is named")
        self.assertEqual(os.listdir(os.path.join(home, "1.0.0")), [], "and something else's is left alone")

    def test_two_installs_at_once_take_turns(self):
        """F5: two real helper processes install the same app at once (1.1.0
        and 1.2.0 over 1.0.0): both wait for the apps folder's lock, so they
        run one after the other; both say ok, and what's left is one whole
        version (never an empty folder, never a version that isn't there)"""
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        runs = [self.from_file(v) for v in ("1.1.0", "1.2.0")]
        import fcntl
        fd = os.open(self.appsRoot, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_EX)   # held here first, so both are waiting at once
        procs = [self.run_helper("install", r["staging"], self.appsRoot, self.dataRoot, r["tree"], self.FILE) for r in runs]
        try:
            both = waiting(procs, self.appsRoot)
        finally:
            os.close(fd)
            answers = [answer(p) for p in procs]
        self.assertTrue(both, "both wait for the apps folder")
        self.assertTrue(all(a["ok"] and not a.get("warning") for a in answers), answers)
        left = sorted(os.listdir(self.file_home()))
        self.assertEqual(len(left), 1, left)
        self.assertIn(left[0], ("1.1.0", "1.2.0"))
        self.assertEqual(self.verify()["tv.alex.clock@" + left[0]]["problem"], "")

    def test_an_install_holds_the_apps_folder_until_its_done(self):
        """F5: an install paused just before its swap (here, in this process)
        holds the apps folder: a real helper process installing the same app
        waits until the first is done and tidied, then installs over it, and
        the disk matches both answers"""
        import threading
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        a, b = self.from_file("1.1.0"), self.from_file("1.2.0")
        paused, go, out = threading.Event(), threading.Event(), {}
        real = helper.move_one

        def pause(x, y):
            if not paused.is_set():
                paused.set()
                go.wait(60)
            return real(x, y)

        def installing():
            try:
                out["a"] = helper.do_install(a["staging"], self.appsRoot, self.dataRoot, a["tree"], self.FILE)
            except Exception as e:
                out["a"] = {"ok": False, "error": str(e)}
        helper.move_one = pause
        t = threading.Thread(target=installing)
        t.start()
        try:
            self.assertTrue(paused.wait(60), "(the first install got to its swap)")
            proc = self.run_helper("install", b["staging"], self.appsRoot, self.dataRoot, b["tree"], self.FILE)
            held = waiting([proc], self.appsRoot)
        finally:
            go.set()
            t.join(60)
            helper.move_one = real
        second = answer(proc)
        self.assertTrue(held, "the second install waits for the first")
        self.assertTrue(out["a"]["ok"] and not out["a"].get("warning"), out)
        self.assertTrue(second["ok"] and not second.get("warning"), second)
        self.assertEqual(sorted(os.listdir(self.file_home())), ["1.2.0"])
        self.assertEqual(self.verify()["tv.alex.clock@1.2.0"]["problem"], "")

    def test_a_removal_waits_for_an_install_to_finish(self):
        """F5: a real helper process removing the app while an install is
        tidying (paused here) waits for it: the install's answer has no
        warning (nothing was taken from under it), then the removal takes
        everything"""
        import threading
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        a = self.from_file("1.1.0")
        paused, go, out = threading.Event(), threading.Event(), {}
        real = helper.wipe_own

        def pause(dfd, name, ino, own, depth=0):
            if name == "1.0.0" and not paused.is_set():
                paused.set()
                go.wait(60)
            return real(dfd, name, ino, own, depth)

        def installing():
            try:
                out["a"] = helper.do_install(a["staging"], self.appsRoot, self.dataRoot, a["tree"], self.FILE)
            except Exception as e:
                out["a"] = {"ok": False, "error": str(e)}
        helper.wipe_own = pause
        t = threading.Thread(target=installing)
        t.start()
        try:
            self.assertTrue(paused.wait(60), "(the install got to tidying)")
            proc = self.run_helper("remove", "tv.alex.clock", self.FILE, json.dumps({"apps": self.appsRoot, "data": self.dataRoot}))
            held = waiting([proc], self.appsRoot)
        finally:
            go.set()
            t.join(60)
            helper.wipe_own = real
        removed = answer(proc)
        self.assertTrue(held, "the removal waits for the install")
        self.assertTrue(out["a"]["ok"] and not out["a"].get("warning"), out)
        self.assertTrue(removed["ok"], removed)
        self.assertFalse(os.path.exists(self.file_home()))

    def test_a_failure_that_changed_nothing_says_so(self):
        """F1, the helper's side: an install that fails before anything on
        disk changes, or whose swap is undone and checked, says so
        (Unchanged: "unchanged": true on its line), so the guide can undo
        what it did first; one whose undo didn't finish never does"""
        s, res, home, before = self.reinstalled()

        def fails(*args):
            with self.assertRaises(helper.Bad) as e:
                helper.do_install(*args)
            return e.exception
        cases = [("nothing waiting there", (os.path.join(self.dir, "app-nothing"), self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)),
                 ("not the tree you were shown", (res["staging"], self.appsRoot, self.dataRoot, "0" * 64, s["id"], self.store))]
        for why, args in cases:
            self.assertIsInstance(fails(*args), helper.Unchanged, why)
        # its place in the apps folder isn't a folder
        other = self.from_file("1.0.0")
        os.makedirs(os.path.join(self.appsRoot, helper.source_dir(self.FILE)))
        with open(os.path.join(self.appsRoot, helper.source_dir(self.FILE), "tv.alex.clock"), "w") as f:
            f.write("not a folder")
        self.assertIsInstance(fails(other["staging"], self.appsRoot, self.dataRoot, other["tree"], self.FILE), helper.Unchanged, "a file in its place")
        # its new copy can't be made (the disk full)
        real_copy = helper.copy_one
        helper.copy_one = lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        try:
            e = fails(res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
        finally:
            helper.copy_one = real_copy
        self.assertIsInstance(e, helper.Unchanged, "a new copy that can't be made")
        self.assertIn("nothing changed", str(e))
        # a swap undone and checked; then one whose undo didn't finish
        for finishes in (True, False):
            res = self.prepare(self.snapshot())
            failed = []

            def hook(a, b, real):
                names = (os.path.basename(a), os.path.basename(b))
                if not failed and "1.0.0.proof" in names:
                    failed.append(1)
                    raise OSError(5, "Input/output error")
                if failed and not finishes and "1.0.0" in names:
                    raise OSError(5, "Input/output error")
                return real(a, b)
            with self.renames(hook):
                e = fails(res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
            if finishes:
                self.assertIsInstance(e, helper.Unchanged, "a swap undone")
                self.assertIn("nothing changed", str(e))
                self.assertEqual(self.installed_state(home), before)
            else:
                self.assertNotIsInstance(e, helper.Unchanged, "an undo that didn't finish")
                self.assertNotIn("nothing changed", str(e))
        # each as its line says it
        self.assertEqual(helper.failure(helper.Unchanged("why")), {"ok": False, "error": "why", "unchanged": True})
        self.assertEqual(helper.failure(helper.Bad("why")), {"ok": False, "error": "why"})

    def test_an_apps_folder_that_cant_be_used_changes_nothing(self):
        """an apps folder that's a link (never followed), or a file, or one
        the app's own folder can't be made in: refused before anything,
        and said so; a removal through a link is refused too"""
        res = self.from_file("1.0.0")
        elsewhere = os.path.join(self.dir, "elsewhere")
        os.makedirs(elsewhere)
        link = os.path.join(self.dir, "linked-apps")
        os.symlink(elsewhere, link)
        a_file = os.path.join(self.dir, "apps-file")
        open(a_file, "w").close()
        for root, why in ((link, "can't be a link"), (a_file, "couldn't be installed")):
            with self.assertRaises(helper.Unchanged) as e:
                helper.do_install(res["staging"], root, self.dataRoot, res["tree"], self.FILE)
            self.assertIn(why, str(e.exception))
            self.assertIn("nothing changed", str(e.exception))
        self.assertEqual(os.listdir(elsewhere), [], "a link is never followed")
        os.makedirs(self.appsRoot)
        os.chmod(self.appsRoot, 0o555)
        try:
            with self.assertRaises(helper.Unchanged) as e:
                helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
        finally:
            os.chmod(self.appsRoot, 0o755)
        self.assertIn("couldn't be installed", str(e.exception))
        self.assertTrue(os.path.isdir(os.path.join(res["staging"], "files")), "what was staged is still there")
        with self.assertRaises(helper.Bad):
            helper.do_remove("tv.alex.clock", self.FILE, {"apps": link})

    def failing_proof_step(self, failed):
        """a rename hook: the first step that touches 1.0.0.proof fails"""
        def hook(a, b, real):
            if not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                failed.append(1)
                raise OSError(5, "Input/output error")
            return real(a, b)
        return hook

    def test_something_moved_by_mistake_that_cant_go_back_is_kept_and_named(self):
        """taking its own copy away after a clean undo, what it moved turns out
        to be someone else's (its copy was swapped for it), and before that can
        go back another folder appears at the name: neither is replaced or
        deleted; what was moved stays in the private folder, which is kept,
        and the error says where it is"""
        s, res, home, before = self.reinstalled()
        failed, fds, where = [], [], []
        proof_step = self.failing_proof_step(failed)

        def hook(a, b, real):
            into = os.path.basename(os.path.dirname(b)).startswith(".trash-")
            if failed and into and not fds and os.path.basename(a).startswith(".new-") and not a.endswith(".proof"):
                os.rename(a, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(a, "notes.txt")))   # what will be moved
                out = real(a, b)
                fds.append(self.held_open(someone_elses(a)))                # then another, where it was
                where.append(b)
                return out
            return proof_step(a, b, real)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertEqual(len(fds), 2)
        for fd in fds:
            self.assertGreater(os.fstat(fd).st_nlink, 0, "neither is replaced or deleted")
        self.assertTrue(os.path.isfile(os.path.join(where[0], "notes.txt")), "what was moved is kept in the private folder")
        msg = str(e.exception)
        self.assertNotIn("nothing changed", msg)
        self.assertIn(" is in " + os.path.basename(os.path.dirname(where[0])) + " there now", msg)

    def test_a_folder_that_takes_its_copys_place_is_never_made_writable(self):
        """just as its own copy is about to be taken away, someone else's
        read-only folder takes its place: that folder's mode is never changed
        (a folder is made writable only through itself, once it's shown to be
        its own), and nothing claims 'nothing changed'"""
        s, res, home, before = self.reinstalled()
        failed, fds, state = [], [], {"taking": False}
        real_take, real_inode = helper.take_own, helper.inode

        def take(path, ino, trash):
            state["taking"] = True
            try:
                return real_take(path, ino, trash)
            finally:
                state["taking"] = False

        def looked(path):
            got = real_inode(path)
            if state["taking"] and not fds and os.path.basename(path).startswith(".new-") and not path.endswith(".proof"):
                os.rename(path, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(path)))
                os.chmod(path, 0o555)
            return got
        helper.take_own, helper.inode = take, looked
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.take_own, helper.inode = real_take, real_inode
        self.assertTrue(fds, "(its own copy was about to be taken)")
        self.assertEqual(os.fstat(fds[0]).st_mode & 0o777, 0o555, "its mode never changed")
        self.assertNotIn("nothing changed", str(e.exception))

    def test_a_new_copy_that_isnt_its_own_never_goes_in(self):
        """its new copy is swapped for someone else's folder after it's made,
        before the swap: the swap refuses (only the copy it made goes in), so
        that folder is never moved in, even if a step back could then fail;
        what was there stays exactly as it was"""
        s, res, home, before = self.reinstalled()
        old = helper.inode(os.path.join(home, "1.0.0"))
        real_seal, fds, names, exchanges = helper.seal, [], [], []

        def seal(top, files, folders, own):
            real_seal(top, files, folders, own)
            path = os.readlink("/proc/self/fd/%d" % top)
            if os.path.basename(path).startswith(".new-") and not path.endswith(".proof") and not fds:
                os.rename(path, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))
                names.append(really(path))
        ex = helper.exchange_one

        def hook(a, b, real):
            if real is ex:
                exchanges.append(1)
                if len(exchanges) > 1:
                    raise OSError(5, "Input/output error")   # a step back fails
            return real(a, b)
        helper.seal = seal
        try:
            with self.renames(hook), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.seal = real_seal
        self.assertTrue(fds)
        self.assertEqual(helper.inode(os.path.join(home, "1.0.0")), old, "what was there stays: the folder never goes in")
        self.assertEqual({k: v for k, v in self.installed_state(home).items() if k.split(os.sep)[0] in ("1.0.0", "1.0.0.proof")}, before)
        self.assertTrue(os.path.isfile(os.path.join(names[0], "notes.txt")), "and the folder is left where it is")
        self.assertIn("its new copy isn't the one it made", str(e.exception))
        self.assertNotIn("nothing changed", str(e.exception))

    def test_a_new_one_swapped_for_something_else_as_it_goes_in_isnt_installed(self):
        """just as the new version goes in (exchanged with what's there, or
        moved to the empty name), its copy is swapped for someone else's
        folder: what moved is checked right after and put straight back, so
        that folder is never left installed, and what was there stays"""
        for first in (True, False):   # a first install (a move), a same-version reinstall (an exchange)
            self.setUp()
            if first:
                s = self.added()
                res, old = self.prepare(self.snapshot()), None
            else:
                s, res, home, before = self.reinstalled()
                old = helper.inode(os.path.join(home, "1.0.0"))
            fds, homes = [], []

            def hook(a, b, real):
                if not fds and os.path.basename(a).startswith(".new-") and os.path.basename(b) == "1.0.0":   # the new one going in
                    homes.append(os.path.dirname(really(a)))
                    os.rename(a, os.path.join(homes[0], "its-own-copy-moved-away"))
                    fds.append(self.held_open(someone_elses(a, "notes.txt")))
                return real(a, b)
            with self.renames(hook), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
            self.assertTrue(fds, first)
            final = os.path.join(homes[0], "1.0.0")
            self.assertEqual(helper.inode(final), old, "first install: %s: what was there stays, never the folder" % first)
            self.assertNotIn("nothing changed", str(e.exception))
            self.assertTrue(any(os.path.isfile(os.path.join(homes[0], n, "notes.txt")) for n in os.listdir(homes[0]) if n.startswith(".new-")),
                            "the folder is back where it was")

    def test_an_undo_never_swaps_in_what_isnt_what_was_there(self):
        """a same-version reinstall's swap fails; by then what was there has
        been taken from where it was put aside and someone else's folder put
        there: the undo never exchanges that folder in (it isn't what was
        there), even if a step back could then fail: the new 1.0.0 stays, the
        folder is left where it is, and what was there wasn't deleted"""
        s, res, home, before = self.reinstalled()
        failed, fds, came, undoing = [], [], [], []
        ex = helper.exchange_one

        def hook(a, b, real):
            if not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                failed.append(1)
                aside = next(os.path.join(home, n) for n in os.listdir(home) if n.startswith(".new-") and not n.endswith(".proof"))
                came.append(helper.inode(os.path.join(home, "1.0.0")))
                os.rename(aside, os.path.join(home, "taken-elsewhere"))       # what was there taken,
                fds.append(self.held_open(someone_elses(aside, "notes.txt")))  # someone else's in its place
                raise OSError(5, "Input/output error")
            if failed and real is ex:
                undoing.append(1)
                if len(undoing) > 1:
                    raise OSError(5, "Input/output error")   # a step back fails
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertEqual(helper.inode(os.path.join(home, "1.0.0")), came[0], "the new 1.0.0 stays, never the folder")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0)
        self.assertTrue(os.path.isfile(os.path.join(home, "taken-elsewhere", "app.json")), "what was there wasn't deleted")
        self.assertNotIn("nothing changed", str(e.exception))

    def test_an_undo_never_moves_out_what_isnt_its_new_one(self):
        """a first install's proof can't go in; by then the new 1.0.0 has been
        taken elsewhere and someone else's folder put there: the undo never
        moves that folder (it isn't its own), even if a step back could then
        fail; it's named, never claimed unchanged"""
        s = self.added()
        res = self.prepare(self.snapshot())
        calls, fds, homes = [], [], []

        def hook(a, b, real):
            calls.append(1)
            if len(calls) == 2:   # the proof's rename in
                homes.append(os.path.dirname(really(b)))
                final = os.path.join(homes[0], "1.0.0")
                os.rename(final, os.path.join(homes[0], "taken-elsewhere"))
                fds.append(self.held_open(someone_elses(final, "notes.txt")))
                raise OSError(5, "Input/output error")
            if len(calls) > 2 and os.path.basename(b) == "1.0.0":
                raise OSError(5, "Input/output error")   # a step back fails
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertTrue(os.path.isfile(os.path.join(homes[0], "1.0.0", "notes.txt")), "the folder is never moved")
        msg = str(e.exception)
        self.assertIn("something else is at 1.0.0", msg)
        self.assertNotIn("nothing changed", msg)

    def test_an_old_proof_without_a_new_one_is_put_aside_and_back(self):
        """an app from a file (no proof) installed again where a proof was
        left: the old proof is put aside to a name nothing has, and tidied
        away once it's in; interrupted just after, it's put back; and if
        what was put aside is replaced meanwhile, that's never moved in"""
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        home = self.file_home()
        os.mkdir(os.path.join(home, "1.0.0.proof"))   # left from something else
        with open(os.path.join(home, "1.0.0.proof", "proof.json"), "w") as f:
            f.write("{}")
        before = self.installed_state(home)
        for meanwhile in (False, True):
            res, fds = self.from_file("1.0.0"), []

            def hook(a, b, real):
                if fds and os.path.basename(a) == "1.0.0.proof":
                    raise OSError(5, "Input/output error")   # (a step back out of it fails)
                out = real(a, b)
                if os.path.basename(a) == "1.0.0.proof":   # put aside: then interrupted
                    if meanwhile:
                        os.rename(b, os.path.join(home, "taken-elsewhere"))
                        fds.append(self.held_open(someone_elses(b, "notes.txt")))
                    raise KeyboardInterrupt
                return out
            with self.renames(hook), self.assertRaises((KeyboardInterrupt, helper.Bad)) as e:
                helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
            if not meanwhile:
                self.assertIsInstance(e.exception, KeyboardInterrupt)
                self.assertEqual(self.installed_state(home), before, "put back")
                self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"])
            else:
                self.assertNotIn("nothing changed", str(e.exception))
                self.assertIn("nothing is at 1.0.0.proof in " + home, str(e.exception))
                self.assertFalse(os.path.lexists(os.path.join(home, "1.0.0.proof")), "what took its place is never moved in")
                self.assertGreater(os.fstat(fds[0]).st_nlink, 0)
        # and installed over an old proof again: that's tidied away (what it
        # put aside), and what took its place in the run before is left alone
        wipe(os.path.join(home, "taken-elsewhere"))
        os.mkdir(os.path.join(home, "1.0.0.proof"))
        with open(os.path.join(home, "1.0.0.proof", "proof.json"), "w") as f:
            f.write("{}")
        theirs = [n for n in os.listdir(home) if n.startswith(".old-")]
        res = self.from_file("1.0.0")
        out = helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
        self.assertTrue(out["ok"] and not out.get("warning"), out)
        self.assertEqual(sorted(os.listdir(home)), sorted(theirs + ["1.0.0"]))
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0)

    def test_a_new_copy_that_cant_be_made_or_taken_away_says_where_it_is(self):
        """its new copy can't be made ready (the disk full), and taking it away
        fails too: never 'nothing changed', and the error says where it's left"""
        s, res, home, before = self.reinstalled()
        real_copy = helper.copy_one

        def hook(a, b, real):
            if os.path.basename(os.path.dirname(b)).startswith(".trash-"):
                raise OSError(5, "Input/output error")   # nothing goes into the private folder
            return real(a, b)
        helper.copy_one = lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        try:
            with self.renames(hook), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.copy_one = real_copy
        msg = str(e.exception)
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.assertNotIn("nothing changed", msg)
        left = [n for n in os.listdir(home) if n.startswith(".new-")]
        self.assertTrue(left)
        for n in left:
            self.assertIn(n + " in " + home, msg, "named where it's left")

    def test_a_move_back_never_replaces_what_took_its_place(self):
        """a first install: just as the new 1.0.0 goes in, its copy is swapped
        for someone else's folder, so that moves in; before it can be moved
        straight back, another empty folder is put where it came from: neither
        is replaced, and the error says to look at 1.0.0"""
        s = self.added()
        res = self.prepare(self.snapshot())
        fds = []

        def hook(a, b, real):
            if not fds and os.path.basename(a).startswith(".new-") and os.path.basename(b) == "1.0.0":
                os.rename(a, os.path.join(os.path.dirname(a), "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(a, "notes.txt")))   # what moves in
                out = real(a, b)
                fds.append(self.held_open(someone_elses(a)))                # then another, where it came from
                return out
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertEqual(len(fds), 2)
        for fd in fds:
            self.assertGreater(os.fstat(fd).st_nlink, 0, "neither is replaced")
        msg = str(e.exception)
        self.assertIn("something else is at 1.0.0", msg)
        self.assertNotIn("nothing changed", msg)

    def test_a_check_that_errors_after_the_undo_is_never_counted_as_back(self):
        """a first install's proof can't go in and the undo moves the new 1.0.0
        back out; then the check of 1.0.0 errors: it's never counted as back,
        so nothing claims 'nothing changed'"""
        s = self.added()
        res = self.prepare(self.snapshot())
        calls, state = [], {"moved": False, "erred": False}
        real_inode = helper.inode

        def hook(a, b, real):
            calls.append(1)
            if len(calls) == 2:
                raise OSError(5, "Input/output error")   # the proof's rename in
            out = real(a, b)
            if os.path.basename(a) == "1.0.0" and os.path.basename(b).startswith(".new-"):
                state["moved"] = True   # the undo moved it back out
            return out

        def looked(path):
            if state["moved"] and not state["erred"] and os.path.basename(path) == "1.0.0":
                state["erred"] = True
                raise OSError(5, "Input/output error")
            return real_inode(path)
        helper.inode = looked
        try:
            with self.renames(hook), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.inode = real_inode
        self.assertTrue(state["erred"])
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.assertNotIn("nothing changed", str(e.exception))

    def test_a_private_folder_name_already_taken_is_never_used(self):
        """the private folder's name (its random tag pinned here) is taken by
        someone else's empty folder: the private folder is made before
        anything else, so that folder is never used or removed, and the
        install stops there, nothing changed"""
        s, res, home, before = self.reinstalled()
        fd = self.held_open(someone_elses(os.path.join(home, ".trash-feedfacecafe")))
        os.chmod(os.path.join(home, ".trash-feedfacecafe"), 0o700)   # (private, as its own would be)
        real_hex = helper.secrets.token_hex
        helper.secrets.token_hex = lambda n=None: "feedfacecafe" if n == 6 else real_hex(n)
        try:
            with self.assertRaises(helper.Unchanged) as e:
                self.install(res, s["id"])
        finally:
            helper.secrets.token_hex = real_hex
        self.assertGreater(os.fstat(fd).st_nlink, 0, "never removed")
        self.assertEqual(os.listdir(os.path.join(home, ".trash-feedfacecafe")), [], "nor used")
        self.assertIn("File exists", str(e.exception))
        self.assertTrue(os.path.isdir(os.path.join(res["staging"], "files")), "nothing of what's staged moved")
        self.assertEqual(sorted(os.listdir(home)), [".trash-feedfacecafe", "1.0.0", "1.0.0.proof"], "nothing made beside it")
        self.as_it_was(home, before)

    def test_a_private_folder_whose_place_is_taken_before_its_held_is_never_used(self):
        """just after its private folder is made (before anything else), and
        before it's held open, someone else's file is put in it: that folder
        is never used or removed, and the install stops there, naming it
        (it may be left), never claiming "nothing changed\""""
        s, res, home, before = self.reinstalled()
        real_mkdir, fds = os.mkdir, []

        def mkdir(path, *a, **k):
            real_mkdir(path, *a, **k)
            if os.path.basename(path).startswith(".trash-") and not fds:
                with open(os.path.join(path, "theirs.txt"), "w") as f:
                    f.write("someone else's")
                fds.append(self.held_open(os.open(os.path.join(path, "theirs.txt"), os.O_PATH | os.O_NOFOLLOW)))
        os.mkdir = mkdir
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.mkdir = real_mkdir
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never removed")
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertEqual(os.listdir(os.path.join(home, trash[0])), ["theirs.txt"], "never used")
        self.assertIn(trash[0] + " in " + home + " may be left (look at it before anything else)", str(e.exception))
        self.assertTrue(os.path.isdir(os.path.join(res["staging"], "files")), "nothing of what's staged moved")
        self.as_it_was(home, before)

    def test_the_tree_check_reads_no_more_than_an_app_holds(self):
        """a staged file grown past what an app can hold, before the tree
        check: the check stops once it has read that much (never all of it),
        and nothing changes"""
        s, res, home, before = self.reinstalled()
        main = os.path.join(res["staging"], "files", "README.md")
        os.truncate(main, os.path.getsize(main) + helper.MAX_UNPACKED)   # (a sparse file: no room taken)
        with self.assertRaises(helper.Unchanged) as e:
            self.install(res, s["id"])
        self.assertIn("its files changed while it waited", str(e.exception))
        self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"])
        self.as_it_was(home, before)

    def test_a_folder_is_made_writable_only_through_itself(self):
        """just after its own copy is shown to be its own (through the folder
        held open), it's swapped for someone else's read-only folder: only the
        folder held open is made writable, never what's at the name"""
        s, res, home, before = self.reinstalled()
        failed, fds = [], []
        real_fstat = os.fstat

        def fstat(fd):
            st = real_fstat(fd)
            try:
                where = os.readlink("/proc/self/fd/%d" % fd)
            except OSError:
                return st
            if failed and not fds and os.path.dirname(where) == home and os.path.basename(where).startswith(".new-") and not where.endswith(".proof"):
                os.rename(where, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(where)))
                os.chmod(where, 0o555)
            return st
        os.fstat = fstat
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.fstat = real_fstat
        self.assertTrue(fds, "(its own copy was made writable)")
        self.assertEqual(os.fstat(fds[0]).st_mode & 0o777, 0o555, "what took its place is never made writable")
        self.assertTrue(os.stat(os.path.join(home, "its-own-copy-moved-away")).st_mode & 0o200, "the folder held open is")
        self.assertNotIn("nothing changed", str(e.exception))

    def test_tidying_never_deletes_what_took_an_old_versions_place(self):
        """1.1.0 goes in over 1.0.0; just as the old 1.0.0 is taken away, it's
        moved elsewhere and someone else's folder put in its place: that folder
        is never deleted, and it's installed, with a warning naming 1.0.0"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        fds = []

        def meanwhile(path):
            if not fds and os.path.dirname(really(path)) == home and os.path.basename(path) == "1.0.0":
                os.rename(path, os.path.join(home, "old-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))

        def hook(a, b, real):
            if os.path.basename(os.path.dirname(b)).startswith(".trash-"):
                meanwhile(a)   # (as it's taken into the private folder)
            return real(a, b)
        with self.renames(hook):
            out = self.install(res, s["id"])
        self.assertTrue(out["ok"])
        self.assertIn("1.0.0", out.get("warning", ""))
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never deleted")
        self.assertTrue(os.path.isfile(os.path.join(home, "1.0.0", "notes.txt")))
        self.assertEqual(self.verify()["tv.alex.clock@1.1.0"]["problem"], "")

    def test_tidying_says_nothing_of_what_is_gone_already(self):
        """an old version that's gone by the time the tidy looks at it (after
        the listing) is gone: no warning about it"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        real_tidy, real_inode, state = helper.tidy, helper.inode, {"tidying": False, "gone": False}

        def tidy(*a):
            state["tidying"] = True
            return real_tidy(*a)

        def looked(path):
            if state["tidying"] and not state["gone"] and os.path.basename(path) == "1.0.0":
                state["gone"] = True
                os.chmod(path, 0o755)   # (read-only, it can't move to another folder)
                os.rename(path, os.path.join(self.dir, "gone"))   # taken by someone, after the listing
            return real_inode(path)
        helper.tidy, helper.inode = tidy, looked
        try:
            out = self.install(res, s["id"])
        finally:
            helper.tidy, helper.inode = real_tidy, real_inode
        self.assertTrue(state["gone"])
        self.assertTrue(out["ok"])
        self.assertNotIn("warning", out)
        self.assertEqual(sorted(os.listdir(home)), ["1.1.0", "1.1.0.proof"])

    # ---- its new copies are made through folders it holds open, its own
    # copies only are deleted, and tidying takes only what's provably its own

    def file_update(self, version):
        """a file app at 1.0.0 installed, then version staged: (its folder,
        what's in it, do_install's arguments)"""
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        res = self.from_file(version)
        return self.file_home(), self.installed_state(self.file_home()), (res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)

    def as_it_was(self, home, before, why=""):
        self.assertEqual({k: v for k, v in self.installed_state(home).items() if not k.startswith(".")}, before, why + ": what you have, as it was")

    def test_a_new_folder_whose_place_is_taken_before_its_held_is_never_used(self):
        """F6: just after a new copy's folder is made (the proof's, or the new
        version's when it's copied from another filesystem), before it's held
        open, its place is taken: someone else's folder with a file in it
        renamed onto it, a file, someone else's empty folder, or nothing (it's
        gone). Whatever's there is never written into, made read-only, put in
        place or deleted; the install never says ok or "nothing changed",
        what you have stays as it was, and the error says to look at that
        name"""
        for where in ("proof", "copy"):
            for what in ("folder", "file", "empty", "gone"):
                self.setUp()
                if where == "proof":
                    s, res, home, before = self.reinstalled()
                    args = (res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
                else:
                    home, before, args = self.file_update("1.1.0")
                real_mkdir, real_at, fds, made = os.mkdir, helper.rename_at, [], []

                def mkdir(path, *a, what=what, where=where, home=home, fds=fds, made=made, **k):
                    out = real_mkdir(path, *a, **k)
                    p = path if isinstance(path, str) else ""
                    if not made and os.path.dirname(really(p)) == home and os.path.basename(p).startswith(".new-") and p.endswith(".proof") == (where == "proof"):
                        made.append(really(p))
                        if what == "folder":
                            other = os.path.join(home, "theirs")
                            fds.append(self.held_open(someone_elses(other, "notes.txt")))
                            os.chmod(other, 0o700)   # (private, as its own would be)
                            os.rename(other, p)   # (a rename replaces the empty folder)
                        else:
                            os.rmdir(p)
                            if what == "file":
                                fds.append(self.held_open(someone_elses_file(home, os.path.basename(p))))
                            elif what == "empty":
                                fds.append(self.held_open(someone_elses(p)))
                    return out

                def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
                    if os.path.basename(src) == "files":
                        raise OSError(errno.EXDEV, "Invalid cross-device link")
                    return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)
                os.mkdir = mkdir
                if where == "copy":
                    helper.rename_at = across
                try:
                    with self.assertRaises(helper.Bad) as e:
                        helper.do_install(*args)
                finally:
                    os.mkdir, helper.rename_at = real_mkdir, real_at
                msg, case = str(e.exception), where + ", " + what
                self.assertTrue(made, case)
                self.assertNotIsInstance(e.exception, helper.Unchanged, case)
                self.assertNotIn("nothing changed", msg, case)
                self.assertIn(os.path.basename(made[0]) + " in " + home + " (look at it before anything else)", msg, case)
                self.as_it_was(home, before, case)
                for fd in fds:
                    st = os.fstat(fd)
                    self.assertGreater(st.st_nlink, 0, case + ": never deleted")
                    self.assertEqual(st.st_mode & 0o777, 0o755 if what == "empty" else 0o644, case + ": never made read-only")
                if what in ("folder", "empty"):
                    self.assertEqual(sorted(os.listdir(made[0])), ["notes.txt"] if what == "folder" else [], case + ": never written into")
                self.assertEqual([n for n in os.listdir(home) if n.startswith(".")], [] if what == "gone" else [os.path.basename(made[0])],
                                 case + ": and nothing of its own left beside it")

    def test_a_link_put_in_a_new_folder_is_never_written_through(self):
        """F6: a link to a file elsewhere is put in the new proof's folder as
        proof.json, just after the folder is made, or once it's held and its
        files are being made: the file elsewhere is never written or made
        read-only, the link is never deleted (it isn't its own), and the
        install never says ok or "nothing changed\""""
        for when in ("made", "held"):
            self.setUp()
            s, res, home, before = self.reinstalled()
            victim = os.path.join(self.dir, "victim.json")
            with open(victim, "w") as f:
                f.write("someone else's")
            links = []
            real_mkdir, real_copy = os.mkdir, helper.copy_one

            def plant(where, links=links, victim=victim):
                os.symlink(victim, os.path.join(where, "proof.json"))
                links.append(os.path.join(where, "proof.json"))

            def mkdir(path, *a, when=when, **k):
                out = real_mkdir(path, *a, **k)
                p = path if isinstance(path, str) else ""
                if when == "made" and not links and os.path.basename(p).startswith(".new-") and p.endswith(".proof"):
                    plant(p)
                return out

            def copy(sfd, name, dfd, own, room, when=when):
                if when == "held" and not links and name == "package.tar.gz":
                    plant(os.readlink("/proc/self/fd/%d" % dfd))
                return real_copy(sfd, name, dfd, own, room)
            os.mkdir, helper.copy_one = mkdir, copy
            try:
                with self.assertRaises(helper.Bad) as e:
                    self.install(res, s["id"])
            finally:
                os.mkdir, helper.copy_one = real_mkdir, real_copy
            self.assertTrue(links, when)
            self.assertEqual(slurp(victim), b"someone else's", when + ": never written through")
            self.assertEqual(os.stat(victim).st_mode & 0o777, 0o644, when + ": never made read-only")
            self.assertNotIsInstance(e.exception, helper.Unchanged, when)
            self.assertNotIn("nothing changed", str(e.exception), when)
            found = [os.path.join(r, n) for r, _, ns in os.walk(home) for n in ns if os.path.islink(os.path.join(r, n))]
            self.assertEqual([os.readlink(p) for p in found], [victim], when + ": the link is never deleted")
            self.as_it_was(home, before, when)

    def test_a_new_copy_whose_inode_isnt_known_never_counts_as_nothing_to_move_in(self):
        """F5/F6: a make that comes back with its new version's inode (or its
        proof's) not known: the swap refuses before anything moves, never
        taking it as "nothing to move in", so an update, a same-version
        reinstall or a proof's never says ok with nothing installed, and what
        you have stays"""
        real = helper.make_copies
        for case in ("update", "again", "proof"):
            self.setUp()
            if case == "proof":
                s, res, home, before = self.reinstalled()
                args = (res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
            else:
                home, before, args = self.file_update("1.1.0" if case == "update" else "1.0.0")

            def unknown(folder, files_dir, files, folders, known, new_target, new_proof,
                        new_state, proof_expected, state_expected, made, own, case=case):
                real(folder, files_dir, files, folders, known, new_target, new_proof,
                     new_state, proof_expected, state_expected, made, own)
                made[new_proof if case == "proof" else new_target] = None   # (made, its inode not known)
            helper.make_copies = unknown
            try:
                with self.assertRaises(helper.Bad) as e:
                    helper.do_install(*args)
            finally:
                helper.make_copies = real
            self.assertIn("its new copy isn't the one it made", str(e.exception), case)
            self.assertNotIsInstance(e.exception, helper.Unchanged, case)
            self.as_it_was(home, before, case)

    def test_its_folder_swapped_for_a_link_is_never_followed(self):
        """the app's folder is a link to a folder with versions in it: refused
        before anything, and that folder untouched. Then, during an update,
        the app's folder is moved elsewhere and such a link put at its name:
        the install goes on in the folder it holds open, never through the
        link, so nothing in that other folder is touched, and it says its
        folder isn't there any more"""
        home, before, args = self.file_update("1.1.0")
        other, moved = os.path.join(self.dir, "other"), os.path.join(self.dir, "its-folder-moved")
        os.mkdir(other)
        fds = [self.held_open(someone_elses(os.path.join(other, v), "notes.txt")) for v in ("1.0.0", "0.5.0")]
        os.rename(home, moved)
        os.symlink(other, home)
        with self.assertRaises(helper.Unchanged) as e:
            helper.do_install(*args)
        self.assertIn("isn't a plain folder", str(e.exception))
        self.assertEqual(sorted(os.listdir(other)), ["0.5.0", "1.0.0"], "never followed")
        os.unlink(home)
        os.rename(moved, home)
        real_hex = helper.secrets.token_hex

        def token_hex(n=None):
            if n == 6 and os.path.isdir(home) and not os.path.islink(home):
                os.rename(home, moved)   # (just after its folder was looked up, before anything's made)
                os.symlink(other, home)
            return real_hex(n)
        helper.secrets.token_hex = token_hex
        try:
            out = helper.do_install(*args)
        finally:
            helper.secrets.token_hex = real_hex
        for fd in fds:
            self.assertGreater(os.fstat(fd).st_nlink, 0, "never touched through the link")
        self.assertEqual(sorted(os.listdir(other)), ["0.5.0", "1.0.0"])
        self.assertEqual(sorted(os.listdir(moved)), ["1.1.0"], "installed in the folder it held")
        self.assertTrue(out["ok"])
        self.assertIn(home + " isn't the folder it was installed in any more: look at it before anything else.", out["warning"])

    def test_a_name_taken_by_an_empty_private_folder_is_never_used(self):
        """F6: someone else's empty folder, private as its own would be, is
        already at its new copy's name (its tag pinned here: the copy's from
        another filesystem, or the proof's): it's never used (a folder of its
        own is one its mkdir made), and the install changes nothing"""
        for name in (".new-feedfacecafe", ".new-feedfacecafe.proof"):
            self.setUp()
            if name.endswith(".proof"):
                s, res, home, before = self.reinstalled()
                args = (res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
            else:
                home, before, args = self.file_update("1.1.0")
            fd = self.held_open(someone_elses(os.path.join(home, name)))
            os.chmod(os.path.join(home, name), 0o700)
            real_hex, real_at = helper.secrets.token_hex, helper.rename_at

            def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
                if os.path.basename(src) == "files":
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)
            helper.secrets.token_hex = lambda n=None: "feedfacecafe" if n == 6 else real_hex(n)
            helper.rename_at = across
            try:
                with self.assertRaises(helper.Unchanged, msg=name) as e:
                    helper.do_install(*args)
            finally:
                helper.secrets.token_hex, helper.rename_at = real_hex, real_at
            self.assertIn("File exists", str(e.exception), name)
            self.assertGreater(os.fstat(fd).st_nlink, 0, name)
            self.assertEqual(os.listdir(os.path.join(home, name)), [], name + ": never used")
            self.as_it_was(home, before, name)

    def test_a_file_swapped_in_as_its_copy_is_deleted_is_never_deleted(self):
        """F4: a same-version reinstall's swap fails and is undone; as its own
        copy is deleted in its private folder, just after one of its files is
        looked at, someone else's file is renamed onto that file's name: it's
        never deleted (each entry is deleted only while it's the one looked
        at), so the copy stays there, named, and nothing claims "nothing
        changed\""""
        s, res, home, before = self.reinstalled()
        failed, fds, real_stat = [], [], os.stat

        def stat_(path, *a, dir_fd=None, follow_symlinks=True, **k):
            st = real_stat(path, *a, dir_fd=dir_fd, follow_symlinks=follow_symlinks, **k)
            if dir_fd is not None and path == "app.json" and not fds:
                where = os.readlink("/proc/self/fd/%d" % dir_fd)
                if os.sep + ".trash-" in where:
                    fds.append(self.held_open(someone_elses_file(where, "app.json")))
            return st
        os.stat = stat_
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.stat = real_stat
        self.assertTrue(fds, "(its copy was being deleted)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never deleted")
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertIn(trash[0] + " in " + home + " holds what couldn't be taken away (look at it before anything else)", str(e.exception))
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.as_it_was(home, before)

    def test_a_file_swapped_after_its_copy_is_opened_is_never_deleted(self):
        """a same-version reinstall's swap fails and is undone; after one
        of its own files in the private folder is opened and verified, a
        writer replaces that name: the replacement is never deleted, the
        private folder stays, and nothing claims "nothing changed"""
        s, res, home, before = self.reinstalled()
        failed, fds, real_fstat = [], [], os.fstat

        def fstat_(fd):
            st = real_fstat(fd)
            try:
                where = os.readlink("/proc/self/fd/%d" % fd)
            except OSError:
                return st
            if not fds and os.sep + ".trash-" in where and where.endswith(os.sep + "app.json"):
                fds.append(self.held_open(someone_elses_file(os.path.dirname(where), "app.json")))
            return st
        os.fstat = fstat_
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.fstat = real_fstat
        self.assertTrue(fds, "(its copy was opened and verified)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "the replacement is never deleted")
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertIn(trash[0] + " in " + home + " holds what couldn't be taken away (look at it before anything else)", str(e.exception))
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.as_it_was(home, before)

    def test_a_staged_tree_with_more_folders_than_its_files_need_is_refused(self):
        """what's staged gets more empty folders than any app's files could be
        in: refused before anything is made (what it would make and check is
        bounded), and nothing changes"""
        res = self.from_file("1.0.0")
        files = os.path.join(res["staging"], "files")
        for i in range(helper.MAX_MEMBERS + helper.MAX_FILES * helper.MAX_DEPTH + 1):
            os.mkdir(os.path.join(files, "f%04d" % i))
        with self.assertRaises(helper.Unchanged) as e:
            helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
        self.assertIn("it changed while it waited", str(e.exception))
        self.assertFalse(os.path.exists(self.file_home()), "nothing made")

    def test_a_folder_in_its_copy_swapped_as_its_filled_is_never_written_into(self):
        """F6: copied from another filesystem, a folder in its new copy is made,
        then just before a file is copied into it, someone else's folder is
        renamed onto it: each folder on the way is opened only while it's
        one it made, so that folder is never written into or deleted, and the
        install fails, naming what's left"""
        first = self.from_file("1.0.0")
        helper.do_install(first["staging"], self.appsRoot, self.dataRoot, first["tree"], self.FILE)
        home, before = self.file_home(), self.installed_state(self.file_home())
        self.app("1.1.0", name="file")
        os.mkdir(os.path.join(self.dir, "app-file-1.1.0", "lib"))
        with open(os.path.join(self.dir, "app-file-1.1.0", "lib", "more.txt"), "w") as f:
            f.write("MORE = 1\n")
        res = helper.do_inspect({"type": "file", "path": os.path.join(self.dir, "app-file-1.1.0")}, self.stagingApps)
        real_at, real_open, fds, theirs = helper.rename_at, helper.open_in, [], []

        def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
            if os.path.basename(src) == "files":
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)

        def opening(top, rel, own=None):
            if own is not None and rel == "lib" and not fds:
                where = os.path.join(os.readlink("/proc/self/fd/%d" % top), "lib")
                other = os.path.join(home, "theirs")
                fds.append(self.held_open(someone_elses(other, "notes.txt")))
                os.rename(other, where)   # (a rename replaces the empty folder)
                theirs.append(os.stat(where).st_mtime_ns)
            return real_open(top, rel, own)
        helper.rename_at, helper.open_in = across, opening
        try:
            with self.assertRaises(helper.Bad) as e:
                helper.do_install(res["staging"], self.appsRoot, self.dataRoot, res["tree"], self.FILE)
        finally:
            helper.rename_at, helper.open_in = real_at, real_open
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never deleted")
        where = os.path.dirname(os.readlink("/proc/self/fd/%d" % fds[0]))
        self.assertEqual(os.listdir(where), ["notes.txt"], "never written into")
        self.assertEqual(os.stat(where).st_mtime_ns, theirs[0], "nothing ever made in it")
        self.assertIn("its new copy changed while it was made", str(e.exception))
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.as_it_was(home, before)

    def next_install(self, s, home):
        """the same app installed again from the catalog, as the guide's next
        update would: its answer"""
        out = self.install(self.prepare(self.snapshot()), s["id"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.verify()["tv.alex.clock@1.0.0"]["problem"], "")
        return out

    def test_tidying_leaves_alone_what_a_failed_install_kept(self):
        """F4/F6: what a failed install kept and named (someone else's folder
        at its new copy's name, one put in its copy's place after an undo, or
        one moved into its private folder by mistake) is never taken away by
        the next install, which says ok: only names a version has, and what
        it put aside itself, are tidied"""
        # someone else's folder at its new copy's name (its tag pinned)
        s, res, home, before = self.reinstalled()
        fd = self.held_open(someone_elses(os.path.join(home, ".new-feedfacecafe"), "notes.txt"))
        real_hex = helper.secrets.token_hex
        helper.secrets.token_hex = lambda n=None: "feedfacecafe" if n == 6 else real_hex(n)
        try:
            with self.assertRaises(helper.Unchanged):
                self.install(res, s["id"])
        finally:
            helper.secrets.token_hex = real_hex
        self.next_install(s, home)
        self.assertGreater(os.fstat(fd).st_nlink, 0, "at its new copy's name: never taken away")
        self.assertEqual(sorted(os.listdir(home)), [".new-feedfacecafe", "1.0.0", "1.0.0.proof"])
        # one put in its copy's place after an undo, just before its copy is taken back
        self.setUp()
        s, res, home, before = self.reinstalled()
        failed, fds, real_take = [], [], helper.take_own

        def take(path, ino, trash):
            if not fds and os.path.basename(path).startswith(".new-") and not path.endswith(".proof"):
                os.rename(path, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))
            return real_take(path, ino, trash)
        helper.take_own = take
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.take_own = real_take
        self.assertIn("(look at it before anything else)", str(e.exception))
        self.next_install(s, home)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "in its copy's place: never taken away")
        # one moved into its private folder by mistake, which can't go back
        self.setUp()
        s, res, home, before = self.reinstalled()
        failed, fds = [], []
        proof_step = self.failing_proof_step(failed)

        def hook(a, b, real):
            if failed and not fds and os.path.basename(os.path.dirname(b)).startswith(".trash-") and os.path.basename(a).startswith(".new-") and not a.endswith(".proof"):
                os.rename(a, os.path.join(home, "its-own-copy-moved-away"))
                fds.append(self.held_open(someone_elses(a, "notes.txt")))   # what will be moved
                out = real(a, b)
                fds.append(self.held_open(someone_elses(a)))                # then another, where it was
                return out
            return proof_step(a, b, real)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertIn(" is in " + trash[0] + " there now (look at it before anything else)", str(e.exception))
        self.next_install(s, home)
        for fd in fds:
            self.assertGreater(os.fstat(fd).st_nlink, 0, "in its private folder, or where it was: never taken away")
        self.assertTrue(os.readlink("/proc/self/fd/%d" % fds[0]).startswith(os.path.join(home, trash[0]) + os.sep), "still in its private folder")
        self.assertEqual(len(os.listdir(os.path.join(home, trash[0]))), 1, "which is kept, as it was")

    def test_tidying_takes_an_old_version_only_as_the_listing_found_it(self):
        """F4: 1.1.0 goes in over 1.0.0; after the tidy's listing, just as it
        looks at 1.0.0, the old 1.0.0 is taken and someone else's folder put
        in its place: that folder is never taken (what the listing found is
        what's taken, by its inode), and the install says 1.0.0 is left"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        real_tidy, real_inode, state, fds = helper.tidy, helper.inode, {"tidying": False}, []

        def tidy(*a):
            state["tidying"] = True
            return real_tidy(*a)

        def looked(path):
            if state["tidying"] and not fds and really(path) == os.path.join(home, "1.0.0"):
                os.chmod(path, 0o755)   # (read-only, it can't move to another folder)
                os.rename(path, os.path.join(self.dir, "old-moved-away"))
                fds.append(self.held_open(someone_elses(path, "notes.txt")))
            return real_inode(path)
        helper.tidy, helper.inode = tidy, looked
        try:
            out = self.install(res, s["id"])
        finally:
            helper.tidy, helper.inode = real_tidy, real_inode
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never taken")
        self.assertTrue(os.path.isfile(os.path.join(home, "1.0.0", "notes.txt")))
        self.assertTrue(out["ok"])
        self.assertIn("1.0.0 couldn't be tidied away", out["warning"])
        self.assertEqual(self.verify()["tv.alex.clock@1.1.0"]["problem"], "")

    def test_its_private_folder_is_used_only_through_itself(self):
        """F4: just after its private folder is made, it's moved elsewhere and
        someone else's empty folder is put at its name: what it takes away
        goes into the folder it holds open, never into that one, which it
        never removes either; and nothing claims "nothing changed" (its own
        folder isn't where it was)"""
        s, res, home, before = self.reinstalled()
        real_fd, failed, fds, moved = helper.trash_fd, [], [], []

        def trash_fd(trash):
            fd = real_fd(trash)
            if not fds:
                moved.append(os.path.join(self.dir, "its-private-folder-moved"))
                os.rename(trash["path"], moved[0])
                fds.append(self.held_open(someone_elses(trash["path"])))
            return fd
        helper.trash_fd = trash_fd
        try:
            with self.renames(self.failing_proof_step(failed)), self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.trash_fd = real_fd
        self.assertTrue(fds)
        theirs = os.readlink("/proc/self/fd/%d" % fds[0])
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never removed")
        self.assertEqual(os.listdir(theirs), [], "never used")
        self.assertEqual(os.listdir(moved[0]), [], "what it took went into its own, and was deleted there")
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.assertIn(os.path.basename(theirs) + " in " + home + " may be left (look at it before anything else)", str(e.exception))
        self.as_it_was(home, before)

    def test_something_put_in_its_new_copy_is_never_deleted_with_it(self):
        """F4: a same-version reinstall's proof step fails; just before, a file
        is put inside its new copy (in place by then): when that copy is taken
        back, only what's its own in it is deleted, so that file stays (and so
        does what holds it, named), and nothing claims "nothing changed\""""
        s, res, home, before = self.reinstalled()
        failed, fds = [], []

        def hook(a, b, real):
            if not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                failed.append(1)
                final = os.path.join(home, "1.0.0")   # (its new copy, by now)
                os.chmod(final, 0o755)
                with open(os.path.join(final, "notes.txt"), "w") as f:
                    f.write("someone else's")
                fds.append(self.held_open(os.open(os.path.join(final, "notes.txt"), os.O_PATH | os.O_NOFOLLOW)))
                raise OSError(5, "Input/output error")
            return real(a, b)
        with self.renames(hook), self.assertRaises(helper.Bad) as e:
            self.install(res, s["id"])
        self.assertTrue(fds)
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "never deleted")
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1, "what holds it is kept")
        self.assertIn(trash[0] + " in " + home + " holds what couldn't be taken away (look at it before anything else)", str(e.exception))
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.as_it_was(home, before)

    def test_a_copy_that_changes_after_its_check_never_goes_in(self):
        """after the tree check, before its new copy is made, a file of what
        was staged changes, a file is added to it, or a second name for one
        of its files: the copy is checked again as it's made read-only
        (exactly the files you were shown, under their names), so it never
        goes in; what changed in its own copy goes with it, and what was
        added (not its own) is never made read-only or deleted"""
        for change in ("bytes", "added", "linked"):
            self.setUp()
            s, res, home, before = self.reinstalled()
            real_lock, fds = helper.lock_apps, []

            def lock(root, change=change, res=res, fds=fds):
                held = real_lock(root)   # (after the tree check, before the copy is made)
                files = os.path.join(res["staging"], "files")
                if change == "bytes":
                    with open(os.path.join(files, "README.md"), "ab") as f:
                        f.write(b"# changed\n")
                elif change == "linked":
                    os.link(os.path.join(files, "README.md"), os.path.join(files, "extra.py"))
                else:
                    with open(os.path.join(files, "extra.py"), "w") as f:
                        f.write("# someone else's\n")
                    fds.append(self.held_open(os.open(os.path.join(files, "extra.py"), os.O_PATH | os.O_NOFOLLOW)))
                return held
            helper.lock_apps = lock
            try:
                with self.assertRaises(helper.Bad) as e:
                    self.install(res, s["id"])
            finally:
                helper.lock_apps = real_lock
            self.assertIn("its files changed while it waited", str(e.exception), change)
            self.as_it_was(home, before, change)
            if change in ("bytes", "linked"):
                self.assertIsInstance(e.exception, helper.Unchanged, "all of its copy its own, taken back")
                self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"])
            else:
                self.assertNotIsInstance(e.exception, helper.Unchanged, "what's not its own stays, named")
                st = os.fstat(fds[0])
                self.assertGreater(st.st_nlink, 0, "never deleted")
                self.assertEqual(st.st_mode & 0o777, 0o644, "never made read-only")

    def test_a_file_swapped_in_as_its_copy_is_checked_is_never_touched(self):
        """just as a file of its new copy is looked at, to be checked and made
        read-only, someone else's file is renamed onto its name: it's held by
        a descriptor checked to be what was looked at, so that file is never
        made read-only or deleted, and the copy never goes in"""
        s, res, home, before = self.reinstalled()
        real_stat, fds = os.stat, []

        def stat_(path, *a, dir_fd=None, follow_symlinks=True, **k):
            st = real_stat(path, *a, dir_fd=dir_fd, follow_symlinks=follow_symlinks, **k)
            if dir_fd is not None and path == "README.md" and not fds:
                where = os.readlink("/proc/self/fd/%d" % dir_fd)
                if os.path.basename(where).startswith(".new-"):
                    fds.append(self.held_open(someone_elses_file(where, "README.md")))
            return st
        os.stat = stat_
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            os.stat = real_stat
        self.assertTrue(fds)
        st = os.fstat(fds[0])
        self.assertGreater(st.st_nlink, 0, "never deleted")
        self.assertEqual(st.st_mode & 0o777, 0o644, "never made read-only")
        self.assertNotIsInstance(e.exception, helper.Unchanged)
        self.as_it_was(home, before)

    def test_a_copy_with_more_in_it_is_refused_without_looking_at_all_of_it(self):
        """three hundred files are added to what was staged after the tree
        check: the copy's check stops once it has seen more than it holds,
        never looking at all of them, and none of them is deleted"""
        s, res, home, before = self.reinstalled()
        real_lock, real_seal, real_stat, state, looked = helper.lock_apps, helper.seal, os.stat, {"sealing": False}, []
        files = os.path.join(res["staging"], "files")

        def lock(root):
            held = real_lock(root)
            for i in range(300):
                with open(os.path.join(files, "extra-%03d.txt" % i), "w") as f:
                    f.write("x")
            return held

        def seal(*a):
            state["sealing"] = True
            try:
                return real_seal(*a)
            finally:
                state["sealing"] = False

        def stat_(path, *a, dir_fd=None, follow_symlinks=True, **k):
            if state["sealing"] and dir_fd is not None:
                looked.append(path)
            return real_stat(path, *a, dir_fd=dir_fd, follow_symlinks=follow_symlinks, **k)
        helper.lock_apps, helper.seal, os.stat = lock, seal, stat_
        try:
            with self.assertRaises(helper.Bad) as e:
                self.install(res, s["id"])
        finally:
            helper.lock_apps, helper.seal, os.stat = real_lock, real_seal, real_stat
        self.assertIn("its files changed while it waited", str(e.exception))
        self.assertLessEqual(len(looked), len(res["files"]) + 1, "never all of them")
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        kept = os.path.join(home, trash[0], os.listdir(os.path.join(home, trash[0]))[0])
        self.assertEqual(len([n for n in os.listdir(kept) if n.startswith("extra-")]), 300, "none of them deleted")
        self.as_it_was(home, before)

    def test_an_old_version_with_more_in_it_than_an_app_holds_is_left(self):
        """an old version's folder with more in it than an app can hold (one
        stuffed by something else) is taken into the private folder but not
        gone through: it's left there, named, and it's installed"""
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        os.chmod(done["path"], 0o755)
        for i in range(4 * helper.MAX_MEMBERS + 1):
            open(os.path.join(done["path"], "stuffed-%04d" % i), "w").close()
        self.offer("1.1.0", 2000)
        with Web(self.files):
            self.fetched(s)
        out = self.install(self.prepare(self.snapshot()), s["id"])
        self.assertTrue(out["ok"])
        trash = [n for n in os.listdir(home) if n.startswith(".trash-")]
        self.assertEqual(len(trash), 1)
        self.assertEqual(os.listdir(os.path.join(home, trash[0])), ["1.0.0"])
        self.assertEqual(len(os.listdir(os.path.join(home, trash[0], "1.0.0"))), 4 * helper.MAX_MEMBERS + 3, "left as it is")
        self.assertIn(trash[0] + " in " + home + " holds what couldn't be taken away: look at it before anything else.", out["warning"])

    def updating(self, version):
        """1.0.0 from the catalog installed, then version (a newer one, or
        1.0.0 again) prepared: (the catalog, what's prepared, its folder,
        what's in it)"""
        if version == "1.0.0":
            return self.reinstalled()
        s = self.added()
        done = self.install(self.prepare(self.snapshot()), s["id"])
        home = os.path.dirname(done["path"])
        self.offer(version, 2000)
        with Web(self.files):
            self.fetched(s)
        res = self.prepare(self.snapshot())
        self.assertTrue(res["ok"], res)
        return s, res, home, self.installed_state(home)

    def test_an_app_from_a_source_never_goes_in_without_its_proof(self):
        """r2-F1: what's kept with an app with signed proof (its package and
        proof.json) goes in with it, or nothing does: whether it goes isn't
        a look that hides errors. A look at the staged proof.json that fails
        once changes nothing about it; the staged proof.json gone, or a link,
        stops the install with nothing changed, the version you have and its
        proof as they were (an update and the same version again)"""
        for version in ("1.0.0", "1.1.0"):
            for case in ("a look that fails", "gone", "a link"):
                self.setUp()
                s, res, home, before = self.updating(version)
                staged = os.path.join(res["staging"], "proof.json")
                why = version + ", " + case
                if case == "gone":
                    os.unlink(staged)
                elif case == "a link":
                    theirs = os.path.join(self.dir, "theirs.json")
                    os.rename(staged, theirs)
                    os.symlink(theirs, staged)
                    mode = os.stat(theirs).st_mode
                real_stat, failed = os.stat, []

                def stat_(path, *a, **k):
                    if path == staged and not failed:
                        failed.append(1)
                        raise OSError(errno.EIO, "Input/output error")
                    return real_stat(path, *a, **k)
                os.stat = stat_
                try:
                    if case != "a look that fails":
                        with self.assertRaises(helper.Unchanged, msg=why) as e:
                            self.install(res, s["id"])
                    else:
                        done = self.install(res, s["id"])
                finally:
                    os.stat = real_stat
                v = self.verify()
                if case != "a look that fails":
                    self.assertIn("so nothing changed", str(e.exception), why)
                    self.assertEqual(sorted(os.listdir(home)), ["1.0.0", "1.0.0.proof"], why)
                    self.assertEqual(self.installed_state(home), before, why + ": what you have, and its proof, as they were")
                    self.assertEqual((v["tv.alex.clock@1.0.0"]["proof"], v["tv.alex.clock@1.0.0"]["problem"]), ("catalog", ""), why)
                    if case == "a link":
                        self.assertEqual(os.stat(theirs).st_mode, mode, why + ": never made read-only through it")
                    continue
                self.assertEqual(done["proof"], "catalog", why)
                self.assertEqual(sorted(os.listdir(home)), [version, version + ".proof"], why)
                self.assertEqual((v["tv.alex.clock@" + version]["proof"], v["tv.alex.clock@" + version]["problem"]), ("catalog", ""), why)

    def test_a_file_put_at_a_name_its_copy_holds_is_never_taken_as_its_own(self):
        """before its new copy is checked and made read-only, someone else's
        file is renamed onto a name the copy holds: in what was staged (after
        the tree check), in the staged folder moved into place, in a copy
        made from another filesystem, or in its proof. Only what the tree
        check hashed, or what it made, is its own: that file is never made
        read-only, deleted or installed, and nothing claims "nothing
        changed\""""
        for where in ("staged", "moved", "copied", "proof"):
            self.setUp()
            if where == "copied":
                home, before, args = self.file_update("1.1.0")
            else:
                s, res, home, before = self.reinstalled()
                args = (res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
            real_lock, real_seal, real_at, fds = helper.lock_apps, helper.seal, helper.rename_at, []

            def theirs(folder, name, fds=fds):
                fds.append(self.held_open(someone_elses_file(folder, name)))
                fds.append(os.fstat(fds[0]).st_mode)

            def lock(root, where=where, args=args):
                held = real_lock(root)   # (after the tree check)
                if where == "staged":
                    theirs(os.path.join(args[0], "files"), "README.md")
                return held

            def seal(top, files, folders, own, where=where):
                path = os.readlink("/proc/self/fd/%d" % top)
                if not fds and where != "staged" and path.endswith(".proof") == (where == "proof"):
                    theirs(path, "proof.json" if where == "proof" else "README.md")
                return real_seal(top, files, folders, own)

            def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None, where=where):
                if where == "copied" and os.path.basename(src) == "files":
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)
            helper.lock_apps, helper.seal, helper.rename_at = lock, seal, across
            try:
                with self.assertRaises(helper.Bad, msg=where) as e:
                    helper.do_install(*args)
            finally:
                helper.lock_apps, helper.seal, helper.rename_at = real_lock, real_seal, real_at
            self.assertTrue(fds, where)
            st = os.fstat(fds[0])
            self.assertGreater(st.st_nlink, 0, where + ": never deleted")
            self.assertEqual(st.st_mode, fds[1], where + ": never made read-only")
            self.assertIn("its files changed while it waited", str(e.exception), where)
            self.assertNotIsInstance(e.exception, helper.Unchanged, where)
            self.as_it_was(home, before, where)

    def disk_full(self, state):
        """os.mkdir failing with ENOSPC once state["full"] is set (a disk
        with no room left, where renames and deletes still work), while in
        the with"""
        import contextlib

        @contextlib.contextmanager
        def standing_in():
            real = os.mkdir

            def mkdir(*a, **k):
                if state["full"]:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real(*a, **k)
            os.mkdir = mkdir
            try:
                yield
            finally:
                os.mkdir = real
        return standing_in()

    def test_a_full_disk_never_keeps_it_from_taking_back_or_tidying(self):
        """the disk fills up as its new copy is made (from a source, or from
        another filesystem), or as it's swapped in (and the swap fails), or
        just as it's in: taking its own copies back, and tidying the old
        version away, need no new room, so a failed install changes nothing,
        and a finished one leaves nothing behind"""
        for case in ("made", "copied", "undone", "tidied"):
            self.setUp()
            if case == "copied":
                home, before, args = self.file_update("1.1.0")
            else:
                s, res, home, before = self.updating("1.1.0" if case == "tidied" else "1.0.0")
                args = (res["staging"], self.appsRoot, self.dataRoot, res["tree"], s["id"], self.store)
            kept = sorted(os.listdir(home))
            state, real_copy, real_at = {"full": False}, helper.copy_one, helper.rename_at

            def copy(sfd, name, dfd, own, room, state=state):
                real_copy(sfd, name, dfd, own, room)   # (one file made, then the disk is full)
                if case in ("made", "copied"):
                    state["full"] = True
                    raise OSError(errno.ENOSPC, "No space left on device")

            def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
                if case == "copied" and os.path.basename(src) == "files":
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)

            def swapping(a, b, real, state=state, failed=[]):
                state["full"] = True   # (from the swap on)
                if case == "undone" and not failed and "1.0.0.proof" in (os.path.basename(a), os.path.basename(b)):
                    failed.append(1)
                    raise OSError(errno.EIO, "Input/output error")
                return real(a, b)
            helper.copy_one, helper.rename_at = copy, across
            try:
                with self.disk_full(state), self.renames(swapping):
                    if case == "tidied":
                        done = helper.do_install(*args)
                    else:
                        with self.assertRaises(helper.Bad, msg=case) as e:
                            helper.do_install(*args)
            finally:
                helper.copy_one, helper.rename_at = real_copy, real_at
            self.assertTrue(state["full"], case)
            if case == "tidied":
                self.assertNotIn("warning", done, case)
                self.assertEqual(sorted(os.listdir(home)), ["1.1.0", "1.1.0.proof"], case + ": the old version gone, and nothing else left")
                continue
            self.assertIsInstance(e.exception, helper.Unchanged, case)
            self.assertIn("so nothing changed", str(e.exception), case)
            self.assertEqual(sorted(os.listdir(home)), kept, case + ": nothing left beside it")
            self.as_it_was(home, before, case)


    def test_an_app_with_folders_in_it_installs(self):
        self.offer(extra={"lib/deep/more.txt": b"MORE = 1\n"})
        source = self.added()
        result = self.prepare(self.snapshot())
        done = self.install(result, source["id"])
        self.assertEqual(done["proof"], "catalog")
        nested = os.path.join(done["path"], "lib", "deep")
        self.assertEqual(slurp(os.path.join(nested, "more.txt")), b"MORE = 1\n")
        self.assertEqual(os.stat(nested).st_mode & 0o777, 0o555)
        checked = self.verify()["tv.alex.clock@1.0.0"]
        self.assertEqual((checked["proof"], checked["problem"]), ("catalog", ""))

        self.app("1.0.0", name="file", extra={"lib/deep/more.txt": b"MORE = 1\n"})
        result = helper.do_inspect(
            {"type": "file", "path": os.path.join(self.dir, "app-file-1.0.0")},
            self.stagingApps,
        )
        real_at = helper.rename_at

        def across(src, dst, flags, src_dir_fd=None, dst_dir_fd=None):
            if os.path.basename(src) == "files":
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_at(src, dst, flags, src_dir_fd, dst_dir_fd)

        helper.rename_at = across
        try:
            done = helper.do_install(result["staging"], self.appsRoot, self.dataRoot,
                                     result["tree"], self.FILE)
        finally:
            helper.rename_at = real_at
        nested = os.path.join(done["path"], "lib", "deep")
        self.assertEqual(slurp(os.path.join(nested, "more.txt")), b"MORE = 1\n")
        self.assertEqual(os.stat(nested).st_mode & 0o777, 0o555)
        self.assertEqual(sorted(os.listdir(self.file_home())), ["1.0.0"])


class Packages(unittest.TestCase):
    """A package read within its caps, as an install unpacks it (unpack)
    and as every start checks it (package_tree): its whole tar stream, its
    extended headers (tarfile reads each whole into memory), no sparse
    files; the small headers other tools write still read"""

    APP = b'{"id": "tv.alex.clock"}'

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="om-pg-sources-test-")
        self.addCleanup(wipe, self.dir)

    def read(self, package):
        """[what unpack takes from it, or why it refused; package_tree's]"""
        path = os.path.join(self.dir, "package.tar.gz")
        with open(path, "wb") as f:
            f.write(package)
        out = []
        for read in (lambda: helper.unpack(path, tempfile.mkdtemp(dir=self.dir)), lambda: helper.package_tree(package)):
            try:
                out.append(read())
            except helper.Bad as e:
                out.append(str(e))
        return out

    def made(self, fmt, names, **how):
        """a package as another tool makes one, and its files' SHA-256s"""
        buf, files = io.BytesIO(), {}
        with tarfile.open(fileobj=buf, mode="w:gz", format=fmt, **how) as tf:
            for n in names:
                data = self.APP if n == "app.json" else ("this is " + n + "\n").encode()
                info = tarfile.TarInfo(n)
                # a time to the quarter second: pax keeps it in a header of its own
                info.size, info.mode, info.mtime = len(data), 0o644, 1700000000.25
                tf.addfile(info, io.BytesIO(data))
                files[n] = hashlib.sha256(data).hexdigest()
        return buf.getvalue(), files

    def test_what_other_tools_write_is_still_read(self):
        """a pax header for each of 200 files (Python's tarfile, GNU tar
        --format=posix), each with a long name; or GNU's long names; or
        git archive's: those pax headers after its global one"""
        names = ["app.json"] + ["a" * 60 + "/" + "b" * 60 + "/%03d.txt" % i for i in range(199)]
        for fmt in (tarfile.PAX_FORMAT, tarfile.GNU_FORMAT):
            package, files = self.made(fmt, names)
            self.assertEqual(self.read(package), [files, files], fmt)
        package, files = self.made(tarfile.PAX_FORMAT, names)
        self.assertEqual(self.read(first(package, git_header())), [files, files], "git archive")

    def test_a_package_at_every_cap_is_still_read(self):
        """all an install allows (20 MB of files, 200 of them in 399 entries)
        with a pax header for each entry: it all fits in what's read"""
        class Zeros:
            def read(self, n):
                return b"\0" * n
        buf, files, small = io.BytesIO(), {}, 0
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
            for i in range(199):
                d = tarfile.TarInfo("d%03d" % i)
                d.type, d.mode, d.mtime = tarfile.DIRTYPE, 0o755, 1700000000.25
                tf.addfile(d)
            for i, n in enumerate(["app.json"] + ["d%03d/f.txt" % i for i in range(198)]):
                data = self.APP if i == 0 else ("this is " + n + "\n").encode()
                info = tarfile.TarInfo(n)
                info.size, info.mode, info.mtime = len(data), 0o644, 1700000000.25
                tf.addfile(info, io.BytesIO(data))
                files[n], small = hashlib.sha256(data).hexdigest(), small + len(data)
            big = tarfile.TarInfo("d198/f.txt")
            big.size, big.mode, big.mtime = helper.MAX_UNPACKED - small, 0o644, 1700000000.25
            tf.addfile(big, Zeros())
        h = hashlib.sha256()
        for left in range(big.size, 0, -(1 << 20)):
            h.update(b"\0" * min(left, 1 << 20))
        files["d198/f.txt"] = h.hexdigest()
        self.assertEqual(self.read(buf.getvalue()), [files, files])

    def test_a_huge_extended_header_is_refused_before_its_read(self):
        """a pax header (a global one too) or a GNU long name of 32 MiB (32
        KiB in its gzip): refused from its header, before tarfile reads it"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        why = "it isn't an app package (a .tar.gz): its headers are too big"
        for kind in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME):
            self.assertEqual(self.read(zeros_first(package, 32 * 1024 * 1024, kind)), [why, why], kind)

    def test_extended_headers_take_room_together(self):
        """each small, but together more than any package needs: refused
        partway; a negative size; more than four in a row (pax headers, or
        git archive's global one)"""
        names = ["app.json"] + ["f%03d.txt" % i for i in range(199)]
        package, _ = self.made(tarfile.USTAR_FORMAT, names)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
            for n in names:
                info = tarfile.TarInfo(n)
                info.pax_headers = {"comment": "x" * 4000}
                tf.addfile(info, io.BytesIO(b""))
        why = "it isn't an app package (a .tar.gz): its headers are too big"
        self.assertEqual(self.read(buf.getvalue()), [why, why], "4 KB for each of 200 files")
        below = "it isn't an app package (a .tar.gz): a header in it has a size below zero"
        self.assertEqual(self.read(first(package, header(tarfile.XHDTYPE, -1024, fmt=tarfile.GNU_FORMAT))), [below, below])
        record = b"8 a=bcd\n"
        for each in (header(tarfile.XHDTYPE, len(record)) + blocks(record), git_header()):
            for n, ok in ((4, True), (5, False)):
                out = self.read(first(package, *[each] * n))
                if ok:
                    self.assertEqual([sorted(x) for x in out], [names, names], "four in a row")
                else:
                    self.assertEqual(out, ["it isn't an app package (a .tar.gz): it has too many headers in a row"] * 2)

    def test_a_global_header_says_only_a_comment(self):
        """its records go into every entry after it: a comment (git
        archive's, or one made by hand) changes nothing and reads; more is
        refused before the entry after it is read, first or further in (a
        name for every file, an owner, a thousand records)"""
        package, files = self.made(tarfile.PAX_FORMAT, ["app.json"], pax_headers={"comment": "made by hand"})
        self.assertEqual(self.read(package), [files, files])
        why = "it isn't an app package (a .tar.gz): its global header says more than a comment: pack it with om-pg-apps pack"
        for pax in ({"path": "notes.txt"}, {"comment": "made by hand", "uname": "alex"}, {"k%03d" % i: "" for i in range(1000)}):
            package, _ = self.made(tarfile.PAX_FORMAT, ["app.json"], pax_headers=pax)
            self.assertEqual(self.read(package), [why, why], sorted(pax)[:2])
        record = b"14 uname=alex\n"
        notes = tarfile.TarInfo("notes.txt")
        notes.size = 3
        tar = gzip.decompress(self.made(tarfile.USTAR_FORMAT, ["app.json"])[0])[:1024]   # app.json's header and its one block
        further = tar + header(tarfile.XGLTYPE, len(record), "pax_global_header") + blocks(record) + notes.tobuf(tarfile.USTAR_FORMAT) + blocks(b"abc")
        self.assertEqual(self.read(gzip.compress(further + bytes(1024))), [why, why], "further in")

    def test_sparse_files_are_refused(self):
        """GNU's own, and pax's three kinds (the last with its map in its
        data, read whole)"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        old = tarfile.TarInfo("notes.txt")
        old.type = tarfile.GNUTYPE_SPARSE
        found = [first(package, old.tobuf(tarfile.GNU_FORMAT))]
        data = blocks(b"1\n0\n3\n") + b"abc"
        for pax, body in (({"GNU.sparse.size": "3", "GNU.sparse.offset": "0", "GNU.sparse.numbytes": "3"}, b"abc"),
                          ({"GNU.sparse.map": "0,3", "GNU.sparse.realsize": "3"}, b"abc"),
                          ({"GNU.sparse.major": "1", "GNU.sparse.minor": "0", "GNU.sparse.name": "notes.txt", "GNU.sparse.realsize": "3"}, data)):
            info = tarfile.TarInfo("notes.txt")
            info.pax_headers, info.size = pax, len(body)
            found.append(first(package, info.tobuf(tarfile.PAX_FORMAT), blocks(body)))
        why = "it isn't an app package (a .tar.gz): it has a sparse file"
        for i, p in enumerate(found):
            self.assertEqual(self.read(p), [why, why], i)

    def test_gnu_headers_read_whole_are_refused_in_little_memory(self):
        """the GNU headers tarfile reads whole before the entry they're for,
        each about a hundred KB in its gzip: a long link name of 64 MiB, a
        long name that's a good one with 64 MiB of zeros after it, a sparse
        file whose map runs on for 100,000 blocks. Refused at prepare
        (unpack) and at every start (package_tree), in little memory"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        tar, size = gzip.decompress(package), 64 * 1024 * 1024
        named = header(tarfile.GNUTYPE_LONGNAME, size, "././@LongLink", tarfile.GNU_FORMAT) + blocks(b"app.json\0")
        sparse = bytearray(header(tarfile.GNUTYPE_SPARSE, 0, "app.json", tarfile.GNU_FORMAT))
        sparse[386:482] = b"00000000001\0" * 8   # four pieces in the header, then more blocks of them
        sparse[482] = 1
        sparse[148:156] = b" " * 8
        sparse[148:155] = b"%06o\0" % sum(sparse)
        more = b"00000000001\0" * 42 + b"\1" + bytes(7)
        z = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        chain = [z.compress(bytes(sparse))] + [z.compress(more * 1000) for _ in range(100)]
        chain.append(z.compress(more[:504] + bytes(8) + tar) + z.flush())
        big = "it isn't an app package (a .tar.gz): its headers are too big"
        for p, why in ((zeros(size, header(tarfile.GNUTYPE_LONGLINK, size, "././@LongLink", tarfile.GNU_FORMAT), tar), big),
                       (zeros(size - 512, named, tar), big),
                       (b"".join(chain), "it isn't an app package (a .tar.gz): it has a sparse file")):
            self.assertLess(len(p), 256 * 1024)
            path = os.path.join(self.dir, "package.tar.gz")
            with open(path, "wb") as f:
                f.write(p)
            for read in (lambda: helper.unpack(path, tempfile.mkdtemp(dir=self.dir)), lambda: helper.package_tree(p)):
                def said():
                    try:
                        return read()
                    except helper.Bad as e:
                        return str(e)
                out, grew = peak(said)
                self.assertEqual(out, why)
                self.assertLess(grew, 24, "MiB")

    def test_the_whole_stream_is_capped(self):
        """past MAX_TAR bytes unpacked, whatever they're in (here data
        tarfile skips for an entry no one reads), never read on; exactly
        that many are"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        skipped = tarfile.TarInfo("./")
        skipped.size = helper.MAX_TAR
        with self.assertRaises(helper.Bad) as e:
            helper.package_tree(zeros(skipped.size, skipped.tobuf(), gzip.decompress(package)))
        self.assertIn("bigger than 20 MB unpacked", str(e.exception))
        for size, ok in ((helper.MAX_TAR, True), (helper.MAX_TAR + 1, False)):
            r, got = helper.Unzipped(io.BytesIO(zeros(helper.MAX_TAR, tail=b"\0" * (size - helper.MAX_TAR)))), 0
            try:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    got += len(chunk)
            except helper.Bad:
                got = -1
            self.assertEqual(got, size if ok else -1, size)

    def test_package_tree_counts_its_files(self):
        """more than 20 MB of files: refused at every start too, not hashed
        on (an install never took one)"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        big = tarfile.TarInfo("big.txt")
        big.size = 21 * 1024 * 1024
        out = self.read(zeros(big.size, big.tobuf(), gzip.decompress(package)))
        self.assertEqual(out, ["it's bigger than 20 MB unpacked", "its package is bigger than 20 MB unpacked"])

    def test_a_header_tarfile_cant_make_sense_of_is_refused(self):
        """a size tarfile can't read as a number: refused as any bad package
        is, never "something went wrong" """
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        info = tarfile.TarInfo("notes.txt")
        info.pax_headers = {"GNU.sparse.realsize": "three"}
        out = self.read(first(package, info.tobuf(tarfile.PAX_FORMAT)))
        self.assertTrue(out[0].startswith("it isn't an app package (a .tar.gz): "), out)
        self.assertEqual(out[1], "its package can't be read")

    def test_only_the_gzips_first_member_is_read(self):
        """as tarfile's own r|gz read it: a tar split between gzip members,
        or empty members before it, is refused at once, not read through
        member by member; what comes after the first member is never read
        (of 2 MB of members, before the app or after it, one 64 KiB read)"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        tar, empty = gzip.decompress(package), gzip.compress(b"")
        cut = "it isn't an app package (a .tar.gz): unexpected end of data"
        self.assertEqual(self.read(gzip.compress(tar[:512]) + empty * 1000 + gzip.compress(tar[512:])), [cut, "its package can't be read"])
        none = "it isn't an app package (a .tar.gz): empty file"
        self.assertEqual(self.read(empty * 1000 + package), [none, "its package can't be read"])
        r = helper.Unzipped(io.BytesIO(gzip.compress(b"abc") + gzip.compress(b"def")))
        self.assertEqual([r.read(100), r.read(100)], [b"abc", b""])

        class Counted(io.BytesIO):
            took = 0

            def read(self, n=-1):
                data = super().read(n)
                self.took += len(data)
                return data
        for raw, ok in ((Counted(empty * 100000 + package), False), (Counted(package + empty * 100000), True)):
            try:
                with helper.open_package(raw) as tf:
                    got = [m.name for m in tf]
            except tarfile.ReadError:
                got = None
            self.assertEqual(got, ["app.json"] if ok else None)
            self.assertLessEqual(raw.took, 65536)

    def test_a_package_thats_not_a_whole_gzip_is_refused(self):
        """not a gzip; one zlib can't read (an unknown way of packing); one
        cut short after a whole file, which tarfile alone would take as the
        end; and a read of nothing reads nothing (to zlib, 0 is no limit)"""
        package, _ = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        why = "it isn't an app package (a .tar.gz): "
        self.assertEqual(self.read(b"PK" + package[2:]), [why + "not a gzip file", "its package can't be read"])
        self.assertEqual(self.read(package[:2] + b"\x07" + package[3:]), [why + "invalid compressed data", "its package can't be read"])
        z = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        whole = gzip.decompress(package)[:1024]   # app.json's header and its one block
        self.assertEqual(self.read(z.compress(whole) + z.flush(zlib.Z_FULL_FLUSH)), [why + "unexpected end of data", "its package can't be read"])
        r = helper.Unzipped(io.BytesIO(zeros(1 << 20)))
        self.assertEqual([r.read(0), len(r.read(65536))], [b"", 65536])

    def test_a_gzip_header_with_every_field_still_reads(self):
        """zlib reads the gzip's header itself: an extra field, a long name
        (a MiB of it), a comment and the header's own check all read"""
        package, files = self.made(tarfile.USTAR_FORMAT, ["app.json"])
        tar = gzip.decompress(package)
        z = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
        head = b"\x1f\x8b\x08\x1e" + bytes(6) + struct.pack("<H", 4) + b"abcd" + b"n" * (1 << 20) + b"\x00" + b"a comment\x00"
        head += struct.pack("<H", zlib.crc32(head) & 0xffff)
        whole = head + z.compress(tar) + z.flush() + struct.pack("<II", zlib.crc32(tar), len(tar))
        self.assertEqual(self.read(whole), [files, files])


class Renames(unittest.TestCase):
    """rename_at: renameat2's no-replace and exchange, which never destroy
    what's at the other name"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="om-pg-sources-test-")
        self.addCleanup(wipe, self.dir)

    def at(self, *names):
        return os.path.join(self.dir, *names)

    def make(self, name, data=None):
        if data is None:
            os.mkdir(self.at(name))
        else:
            with open(self.at(name), "w") as f:
                f.write(data)
        return helper.inode(self.at(name))

    def test_no_replace_moves_onto_an_empty_name(self):
        f, d = self.make("f", "one"), self.make("d")
        helper.rename_at(self.at("f"), self.at("f2"), helper.RENAME_NOREPLACE)
        helper.rename_at(self.at("d"), self.at("d2"), helper.RENAME_NOREPLACE)
        self.assertEqual((helper.inode(self.at("f2")), helper.inode(self.at("d2"))), (f, d))
        self.assertEqual((helper.inode(self.at("f")), helper.inode(self.at("d"))), (None, None))

    def test_no_replace_never_replaces_what_is_there(self):
        # a file, an empty folder (which a plain rename of a folder replaces)
        # and a link (never followed): each left exactly as it was
        self.make("victim", "keep")
        os.symlink(self.at("victim"), self.at("link"))
        for src, dst in (("f", "file"), ("d", "empty"), ("g", "link")):
            with self.subTest(dst=dst):
                mine = self.make(src, None if src == "d" else "mine")
                if dst != "link":
                    self.make(dst, None if dst == "empty" else "theirs")
                was = helper.inode(self.at(dst))
                fd = os.open(self.at(dst), os.O_PATH | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(OSError) as e:
                        helper.rename_at(self.at(src), self.at(dst), helper.RENAME_NOREPLACE)
                    self.assertEqual(e.exception.errno, errno.EEXIST)
                    self.assertGreater(os.fstat(fd).st_nlink, 0)   # (replaced, it'd be 0)
                finally:
                    os.close(fd)
                self.assertEqual((helper.inode(self.at(src)), helper.inode(self.at(dst))), (mine, was))
        with open(self.at("victim")) as f:
            self.assertEqual(f.read(), "keep")

    def test_exchange_swaps_the_two(self):
        f, d = self.make("f", "one"), self.make("d")
        helper.rename_at(self.at("f"), self.at("d"), helper.RENAME_EXCHANGE)
        self.assertEqual((helper.inode(self.at("f")), helper.inode(self.at("d"))), (d, f))

    def test_exchange_with_an_empty_name_changes_nothing(self):
        f = self.make("f", "one")
        with self.assertRaises(OSError) as e:
            helper.rename_at(self.at("f"), self.at("none"), helper.RENAME_EXCHANGE)
        self.assertEqual(e.exception.errno, errno.ENOENT)
        self.assertEqual((helper.inode(self.at("f")), helper.inode(self.at("none"))), (f, None))

    def test_names_in_folders_held_open(self):
        os.mkdir(self.at("a"))
        os.mkdir(self.at("b"))
        f = self.make(os.path.join("a", "x"), "one")
        afd, bfd = (os.open(self.at(n), os.O_RDONLY | os.O_DIRECTORY) for n in "ab")
        try:
            helper.rename_at("x", "y", helper.RENAME_NOREPLACE, src_dir_fd=afd, dst_dir_fd=bfd)
        finally:
            os.close(afd)
            os.close(bfd)
        self.assertEqual(helper.inode(self.at("b", "y")), f)

    def test_without_it_nothing_is_moved(self):
        # a kernel or filesystem that refuses the flag: an error, never a
        # plain rename instead
        f, g = self.make("f", "one"), self.make("g", "two")
        real = helper._renameat2
        helper._renameat2 = lambda *a: (ctypes.set_errno(errno.EINVAL), -1)[1]
        try:
            with self.assertRaises(OSError) as e:
                helper.rename_at(self.at("f"), self.at("g"), helper.RENAME_NOREPLACE)
        finally:
            helper._renameat2 = real
        self.assertEqual(e.exception.errno, errno.EINVAL)
        self.assertEqual((helper.inode(self.at("f")), helper.inode(self.at("g"))), (f, g))

    def test_a_name_with_a_null_byte_is_refused(self):
        self.make("f", "one")
        with self.assertRaises(ValueError):
            helper.rename_at(self.at("f\0x"), self.at("g"), helper.RENAME_NOREPLACE)
        self.assertIsNone(helper.inode(self.at("g")))


class CleanupRaces(unittest.TestCase):
    """Cleanup never removes an entry substituted after its ownership
    check; a held descriptor proves whether the replacement kept a name."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="om-pg-sources-test-")
        self.addCleanup(wipe, self.dir)

    def test_clear_own_never_unlinks_a_replacement_made_before_its_move(self):
        path = os.path.join(self.dir, "old")
        with open(path, "w") as f:
            f.write("the build's")
        own = helper.inode(path)
        dfd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, dfd)
        real_inode, fds = helper.inode_at, []

        def checked(fd, n):
            got = real_inode(fd, n)
            if fd == dfd and n == "old" and got == own and not fds:
                fds.append(someone_elses_file(self.dir, "old"))
                self.addCleanup(os.close, fds[0])
            return got
        helper.inode_at = checked
        try:
            helper.clear_own(dfd, {own})
        finally:
            helper.inode_at = real_inode
        self.assertTrue(fds, "(the build's file was checked)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "the replacement is never unlinked")
        self.assertEqual(slurp(path), b"someone else's", "the replacement stays at its name")

    def test_end_trash_never_removes_a_replacement_made_before_its_move(self):
        path = os.path.join(self.dir, ".trash-test")
        moved = os.path.join(self.dir, "its-trash-moved-after-check")
        os.mkdir(path, 0o700)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        trash = {"path": path, "fd": fd, "ino": helper.fd_ino(fd), "tried": True, "maybe": False, "stuck": []}
        real_inode, fds = helper.inode, []

        def checked(at):
            got = real_inode(at)
            if at == path and not fds:
                os.rename(path, moved)
                fds.append(someone_elses(path))
                self.addCleanup(os.close, fds[0])
            return got
        helper.inode = checked
        try:
            said = helper.end_trash(trash, self.dir)
        finally:
            helper.inode = real_inode
        self.assertTrue(fds, "(the private folder was checked)")
        self.assertGreater(os.fstat(fds[0]).st_nlink, 0, "the replacement is never removed")
        self.assertTrue(os.path.isdir(path), "the replacement stays at its name")
        self.assertTrue(said, "cleanup never claims success")

if __name__ == "__main__":
    unittest.main()

