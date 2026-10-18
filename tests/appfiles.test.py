#!/usr/bin/env python3
"""Signed app files and their helper workflow.  Run directly with Python."""

import base64
import asyncio
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
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
    for root, dirs, _ in os.walk(path):
        for name in dirs:
            full = os.path.join(root, name)
            if not os.path.islink(full):
                os.chmod(full, 0o700)
    shutil.rmtree(path)


helper = load("om_pg_apps_appfiles", os.path.join(ROOT, "bin", "om-pg-apps"))


class Response:
    def __init__(self, url, status, body):
        self.url, self.status, self.data, self.headers, self.received = url, status, body, [], 0

    def header(self, name):
        return None

    async def body(self, limit):
        if len(self.data) > limit:
            raise helper.NET().NetError("toobig", "too big")
        return self.data

    def close(self):
        pass


class Web:
    def __init__(self, files):
        self.files, self.asked = files, []

    def __enter__(self):
        self.net, self.real = helper.NET(), helper.NET().exchange
        self.net.exchange = self.exchange
        return self

    def __exit__(self, *args):
        self.net.exchange = self.real

    async def exchange(self, url, method, headers, body, gate, kind, pin="", resolver=None):
        gate.allow(url)
        address = str(url)
        self.asked.append(address)
        status, data = self.files.get(address, (404, b""))
        return Response(url, status, data)


def waiting_for_lock(processes, path, seconds=10):
    inode = ":" + str(os.stat(path).st_ino)
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        with open("/proc/locks") as f:
            rows = [row.split() for row in f]
        blocked = {int(row[5]) for row in rows if len(row) > 6 and row[1] == "->" and row[2] == "FLOCK" and row[6].endswith(inode)}
        if all(process.pid in blocked for process in processes):
            return True
        if any(process.poll() is not None for process in processes):
            return False
        time.sleep(0.01)
    return False


class AppFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="om-pg-appfiles-test-")
        cls.key = os.path.join(cls.root, "key")
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", cls.key], check=True)
        with open(cls.key + ".pub", "rb") as f:
            cls.public = b" ".join(f.read().split()[:2]) + b"\n"

    @classmethod
    def tearDownClass(cls):
        wipe(cls.root)

    def setUp(self):
        self.folder = tempfile.mkdtemp(dir=self.root)
        self.app = os.path.join(self.folder, "app")
        os.mkdir(self.app)
        manifest = {
            "id": "tv.alex.clock", "name": "Clock", "version": "1.0.0",
            "api": 4, "kind": "app", "author": "Alex", "main": "main.py",
            "permissions": {"net": ["time.example.com"]},
        }
        with open(os.path.join(self.app, "app.json"), "w") as f:
            json.dump(manifest, f)
        with open(os.path.join(self.app, "main.py"), "w") as f:
            f.write("def main(ctx, request):\n    return {'blocks': []}\n")
        package, entry, _ = helper.pack_bytes(self.app)
        self.package = package
        self.staging = os.path.join(self.folder, "staging")
        self.apps = os.path.join(self.folder, "apps")
        self.data = os.path.join(self.folder, "data")
        self.release = {
            "format": 1, "id": entry["id"], "version": entry["version"],
            "name": entry["name"], "author": entry["author"],
            "description": entry["description"], "color": entry["color"],
            "kind": entry["kind"], "api": entry["api"],
            "permissions": entry["permissions"], "updated": 1700000000,
            "package": {"url": "tv.alex.clock-1.0.0.tar.gz", "sha256": entry["sha256"], "size": entry["size"]},
            "updates": "https://updates.example.com/clock/", "revoked": [],
        }

    def sign(self, data):
        path = os.path.join(self.folder, "release.json")
        try:
            os.unlink(path + ".sig")
        except FileNotFoundError:
            pass
        with open(path, "wb") as f:
            f.write(data)
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-Y", "sign", "-f", self.key,
                        "-n", "uber-tv-app", path], check=True, capture_output=True)
        with open(path + ".sig", "rb") as f:
            signature = f.read()
        os.unlink(path + ".sig")
        return signature

    def make(self, members=None, release=None):
        data = json.dumps(release or self.release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        signature = self.sign(data)
        helper.APPFILES().verify(data, signature, self.public.decode().strip())
        normal = [("key.pub", self.public), ("release.json", data),
                  ("release.json.sig", signature), ("package.tar.gz", self.package)]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
            for name, body in members or normal:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(body), 0o644, 0
                tf.addfile(info, io.BytesIO(body))
        path = os.path.join(self.folder, "clock.tvapp")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return path

    def read(self, path=None):
        return helper.read_app_file(path or self.make())

    def test_reads_an_exact_signed_app_file(self):
        got = self.read()
        self.assertEqual(got["release"]["id"], "tv.alex.clock")
        self.assertEqual(got["package"], self.package)
        self.assertRegex(got["source"], r"^app:[0-9a-f]{16}$")
        self.assertRegex(got["fingerprint"], r"^SHA256:")

    def test_signature_and_package_are_bound(self):
        for change in ("release", "signature", "package"):
            release = dict(self.release)
            data = json.dumps(release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
            sig, package = self.sign(data), self.package
            if change == "release":
                release["name"] = "Changed"
                data = json.dumps(release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
            elif change == "signature":
                at = len(sig) // 2
                sig = sig[:at] + bytes([sig[at] ^ 1]) + sig[at + 1:]
            else:
                package += b"changed"
            path = self.make([("key.pub", self.public), ("release.json", data),
                              ("release.json.sig", sig), ("package.tar.gz", package)])
            with self.assertRaises(helper.Bad, msg=change):
                self.read(path)

    def test_only_four_plain_members_are_accepted(self):
        data = json.dumps(self.release).encode()
        sig = self.sign(data)
        good = [("key.pub", self.public), ("release.json", data),
                ("release.json.sig", sig), ("package.tar.gz", self.package)]
        cases = [good[:-1], good + [("extra", b"x")], good + [good[0]],
                 [("../key.pub", self.public)] + good[1:]]
        for members in cases:
            with self.subTest(names=[n for n, _ in members]):
                with self.assertRaises(helper.Bad):
                    self.read(self.make(members))

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for name, body in good[1:]:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tf.addfile(info, io.BytesIO(body))
            link = tarfile.TarInfo("key.pub")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tf.addfile(link)
        path = os.path.join(self.folder, "link.tvapp")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        with self.assertRaises(helper.Bad):
            self.read(path)

    def test_file_itself_is_plain_nofollow_and_bounded(self):
        path = self.make()
        link = os.path.join(self.folder, "link.tvapp")
        os.symlink(path, link)
        with self.assertRaises(helper.Bad):
            self.read(link)
        fifo = os.path.join(self.folder, "pipe.tvapp")
        os.mkfifo(fifo)
        with self.assertRaises(helper.Bad):
            self.read(fifo)
        with open(os.path.join(self.folder, "large.tvapp"), "wb") as f:
            f.truncate(25 * 1024 * 1024 + 1)
        with self.assertRaises(helper.Bad):
            self.read(os.path.join(self.folder, "large.tvapp"))

    def test_key_is_exactly_one_canonical_ed25519_key(self):
        data = json.dumps(self.release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        signature = self.sign(data)
        bad = [self.public.rstrip() + b" a comment\n", self.public + self.public, b"ssh-rsa " + self.public.split()[1] + b"\n"]
        for key in bad:
            with self.subTest(key=key[:20]):
                path = self.make([("key.pub", key), ("release.json", data),
                                  ("release.json.sig", signature), ("package.tar.gz", self.package)])
                with self.assertRaises(helper.Bad):
                    self.read(path)

    def test_outer_file_must_be_an_uncompressed_tar(self):
        plain = self.make()
        with open(plain, "rb") as f:
            raw = f.read()
        import gzip
        with open(plain, "wb") as f:
            f.write(gzip.compress(raw))
        with self.assertRaises(helper.Bad):
            self.read(plain)

    def test_release_schema_and_bounds_are_strict(self):
        bad = []
        for key, value in (("updated", True), ("updated", 2 ** 53), ("updates", "http://updates.example.com/"),
                           ("revoked", [{"version": "1.0.0", "reason": ""}])):
            release = dict(self.release)
            release[key] = value
            bad.append(release)
        release = dict(self.release)
        release["surprise"] = True
        bad.append(release)
        release = dict(self.release)
        release["package"] = dict(release["package"], size=len(self.package) + 1)
        bad.append(release)
        for release in bad:
            with self.subTest(release=release):
                with self.assertRaises(helper.Bad):
                    self.read(self.make(release=release))

    def test_a_third_party_release_cannot_claim_to_be_uber_tv(self):
        for field in ("name", "author"):
            release = dict(self.release)
            release[field] = "Uber TV"
            with self.subTest(field=field), self.assertRaises(helper.Bad):
                self.read(self.make(release=release))

    def inspect(self, path=None):
        return helper.do_app_inspect(path or self.make(), self.staging, self.apps)

    def install(self, staged):
        return helper.do_install(staged["staging"], self.apps, self.data, staged["tree"], staged["sourceId"])

    def verified(self):
        found = helper.do_verify(self.apps, os.path.join(self.folder, "no-signers"))["apps"]
        return {item["id"] + "@" + item["version"]: item for item in found}

    def test_inspect_install_and_start_time_proof(self):
        staged = self.inspect()
        self.assertEqual((staged["sourceName"], staged["source"], staged["sourceId"]),
                         ("Signed app file", "appFile", staged["sourceId"]))
        self.assertEqual(staged["manifest"]["id"], "tv.alex.clock")
        done = self.install(staged)
        self.assertEqual(done["proof"], "appFile")
        item = self.verified()["tv.alex.clock@1.0.0"]
        self.assertEqual((item["proof"], item["problem"]), ("appFile", ""))
        self.assertEqual(item["keyFingerprint"], staged["keyFingerprint"])

    def test_a_review_stales_if_the_same_origin_installs_meanwhile(self):
        first, second = self.inspect(), self.inspect()
        self.assertTrue(helper.do_app_current(first["staging"], self.staging, self.apps)["ok"])
        self.install(second)
        with self.assertRaises(helper.Bad):
            helper.do_app_current(first["staging"], self.staging, self.apps)
        with self.assertRaises(helper.Unchanged):
            self.install(first)

    def test_staged_proof_package_and_state_cannot_change_after_review(self):
        for relative in ("proof.json", "package.tar.gz", os.path.join("app-file.state", "state.json")):
            with self.subTest(relative=relative):
                staged = self.inspect()
                path = os.path.join(staged["staging"], relative)
                with open(path, "ab") as f:
                    f.write(b"changed")
                with self.assertRaises(helper.Unchanged):
                    self.install(staged)
                self.assertEqual(self.verified(), {})

    def test_proof_checks_signature_package_files_and_state(self):
        staged = self.inspect()
        done = self.install(staged)
        version, proof = done["path"], done["path"] + ".proof"
        state = os.path.join(os.path.dirname(version), "app-file.state", "state.json")
        cases = [(os.path.join(version, "main.py"), b"changed"),
                 (os.path.join(proof, "package.tar.gz"), self.package + b"changed"),
                 (os.path.join(proof, "proof.json"), b"{}"), (state, b"{}")]
        for path, body in cases:
            with self.subTest(path=path):
                mode = stat.S_IMODE(os.stat(path).st_mode)
                with open(path, "rb") as f:
                    before = f.read()
                os.chmod(path, 0o600)
                with open(path, "wb") as f:
                    f.write(body)
                item = self.verified()["tv.alex.clock@1.0.0"]
                self.assertNotEqual(item["problem"], "")
                with open(path, "wb") as f:
                    f.write(before)
                os.chmod(path, mode)
                self.assertEqual(self.verified()["tv.alex.clock@1.0.0"]["problem"], "")

    def test_key_is_the_origin_and_another_key_is_another_app(self):
        first = self.inspect()
        other = os.path.join(self.folder, "other-key")
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", other], check=True)
        with open(other + ".pub", "rb") as f:
            public = b" ".join(f.read().split()[:2]) + b"\n"
        data = json.dumps(self.release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        note = os.path.join(self.folder, "other-release.json")
        with open(note, "wb") as f:
            f.write(data)
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-Y", "sign", "-f", other, "-n", "uber-tv-app", note],
                       check=True, capture_output=True)
        with open(note + ".sig", "rb") as f:
            sig = f.read()
        second = self.inspect(self.make([("key.pub", public), ("release.json", data),
                                         ("release.json.sig", sig), ("package.tar.gz", self.package)]))
        self.assertNotEqual(first["sourceId"], second["sourceId"])

    def test_replay_downgrade_and_same_time_fork_are_refused(self):
        first = self.inspect()
        self.install(first)
        newer = dict(self.release, updated=self.release["updated"] + 2)
        newer["version"] = "1.1.0"
        # The package still says 1.0.0, so make a legitimate newer app.
        with open(os.path.join(self.app, "app.json")) as f:
            manifest = json.load(f)
        manifest["version"] = "1.1.0"
        with open(os.path.join(self.app, "app.json"), "w") as f:
            json.dump(manifest, f)
        package, entry, _ = helper.pack_bytes(self.app)
        newer["package"] = {"url": "tv.alex.clock-1.1.0.tar.gz", "sha256": entry["sha256"], "size": entry["size"]}
        self.package = package
        second = self.inspect(self.make(release=newer))
        self.install(second)
        with self.assertRaises(helper.Bad):
            self.inspect(self.make(release=self.release))
        fork = dict(newer, name="Another clock")
        with self.assertRaises(helper.Bad):
            self.inspect(self.make(release=fork))

    def test_a_file_that_withdraws_its_own_version_is_refused(self):
        release = dict(self.release, revoked=[{"version": "1.0.0", "reason": "unsafe"}])
        with self.assertRaises(helper.Bad):
            self.inspect(self.make(release=release))

    def test_helper_surface_has_app_files_and_no_link_source_commands(self):
        path = self.make()
        result = subprocess.run([sys.executable, HELPER, "app-inspect", path, self.staging, self.apps],
                                capture_output=True, text=True, check=False)
        self.assertTrue(json.loads(result.stdout)["ok"], result.stdout)
        for command in (("source-list", "x", "y"), ("source-preview", "x", "y", "z"),
                        ("source", "build", "x", "y"), ("prepare", "x", "y", "z"),
                        ("source-current", "x", "y", "z")):
            result = subprocess.run([sys.executable, HELPER] + list(command), capture_output=True, text=True, check=False)
            self.assertFalse(json.loads(result.stdout)["ok"], command)

    def newer(self, version="1.1.0", updated=None, revoked=None):
        with open(os.path.join(self.app, "app.json")) as f:
            manifest = json.load(f)
        manifest["version"] = version
        with open(os.path.join(self.app, "app.json"), "w") as f:
            json.dump(manifest, f)
        package, entry, _ = helper.pack_bytes(self.app)
        release = dict(self.release, version=version, updated=updated or self.release["updated"] + 1,
                       revoked=[] if revoked is None else revoked)
        release["package"] = {"url": "tv.alex.clock-" + version + ".tar.gz",
                              "sha256": entry["sha256"], "size": entry["size"]}
        data = json.dumps(release, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        return release, data, self.sign(data), package

    def test_update_check_gets_only_the_note_then_prepare_gets_the_package(self):
        installed = self.inspect()
        self.install(installed)
        release, data, signature, package = self.newer()
        base = self.release["updates"]
        files = {base + "release.json": (200, data), base + "release.json.sig": (200, signature),
                 base + release["package"]["url"]: (200, package)}
        with Web(files) as web:
            checked = helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
            self.assertEqual(web.asked, [base + "release.json", base + "release.json.sig"])
            self.assertEqual(checked["update"]["version"], "1.1.0")
            staged = helper.do_app_update_prepare(json.dumps(checked["review"]).encode(), self.apps,
                                                  installed["sourceId"], "tv.alex.clock", self.staging)
            self.assertEqual(web.asked[-1], base + release["package"]["url"])
        done = self.install(staged)
        self.assertEqual(done["manifest"]["version"], "1.1.0")
        self.assertEqual(self.verified()["tv.alex.clock@1.1.0"]["problem"], "")

    def test_bad_update_never_changes_the_accepted_note(self):
        installed = self.inspect()
        self.install(installed)
        home = os.path.dirname(self.install(self.inspect())["path"])
        state = os.path.join(home, "app-file.state", "state.json")
        with open(state, "rb") as f:
            before = f.read()
        release, data, signature, package = self.newer()
        base = self.release["updates"]
        cases = [(data + b" ", signature), (data, signature[:150] + b"x" + signature[151:])]
        for note, sig in cases:
            with self.subTest(note=note == data):
                with Web({base + "release.json": (200, note), base + "release.json.sig": (200, sig)}):
                    with self.assertRaises(helper.Bad):
                        helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
                with open(state, "rb") as f:
                    self.assertEqual(f.read(), before)

    def test_update_revocation_is_cumulative_and_turns_off_that_version(self):
        installed = self.inspect()
        self.install(installed)
        release, data, signature, _ = self.newer(version="1.0.1", revoked=[{"version": "1.0.0", "reason": "unsafe"}])
        base = self.release["updates"]
        with Web({base + "release.json": (200, data), base + "release.json.sig": (200, signature)}):
            checked = helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        self.assertEqual(checked["revoked"]["reason"], "unsafe")
        self.assertIn("withdrew", self.verified()["tv.alex.clock@1.0.0"]["problem"])

        # A later signed note omitting it cannot turn the old version on.
        release2, data2, signature2, _ = self.newer(version="1.0.2", updated=release["updated"] + 1, revoked=[])
        with Web({base + "release.json": (200, data2), base + "release.json.sig": (200, signature2)}):
            checked2 = helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        self.assertEqual(checked2["revoked"]["reason"], "unsafe")

    def test_prepare_is_bound_to_the_review_and_current_state(self):
        installed = self.inspect()
        self.install(installed)
        release, data, signature, package = self.newer()
        base = self.release["updates"]
        files = {base + "release.json": (200, data), base + "release.json.sig": (200, signature),
                 base + release["package"]["url"]: (200, package)}
        with Web(files):
            checked = helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        bad = dict(checked["review"], version="9.9.9")
        with Web(files):
            with self.assertRaises(helper.Bad):
                helper.do_app_update_prepare(json.dumps(bad).encode(), self.apps, installed["sourceId"],
                                             "tv.alex.clock", self.staging)
        # A later accepted note makes the earlier consent stale.
        release2, data2, signature2, _ = self.newer(version="1.2.0", updated=release["updated"] + 1)
        with Web({base + "release.json": (200, data2), base + "release.json.sig": (200, signature2)}):
            helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        with Web(files):
            with self.assertRaises(helper.Bad):
                helper.do_app_update_prepare(json.dumps(checked["review"]).encode(), self.apps, installed["sourceId"],
                                             "tv.alex.clock", self.staging)

    def test_install_undo_restores_files_proof_and_state_together(self):
        installed = self.inspect()
        self.install(installed)
        release, _, _, package = self.newer()
        self.package = package
        staged = self.inspect(self.make(release=release))
        real = helper.swap_own

        def fail_state(a, b, at_a, at_b):
            if os.path.basename(b) == helper.APP_FILE_STATE:
                raise OSError("forced state swap failure")
            return real(a, b, at_a, at_b)

        with mock.patch.object(helper, "swap_own", side_effect=fail_state):
            with self.assertRaises(helper.Unchanged):
                self.install(staged)
        found = self.verified()
        self.assertEqual(set(found), {"tv.alex.clock@1.0.0"})
        self.assertEqual(found["tv.alex.clock@1.0.0"]["problem"], "")

    def test_failed_note_state_exchange_leaves_the_previous_state_exact(self):
        installed = self.inspect()
        done = self.install(installed)
        state_path = os.path.join(os.path.dirname(done["path"]), helper.APP_FILE_STATE, "state.json")
        with open(state_path, "rb") as f:
            before = f.read()
        release, data, signature, _ = self.newer()
        base = self.release["updates"]
        with Web({base + "release.json": (200, data), base + "release.json.sig": (200, signature)}), \
                mock.patch.object(helper, "swap_own", side_effect=OSError("forced exchange failure")):
            with self.assertRaises(helper.Bad):
                helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        with open(state_path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.verified()["tv.alex.clock@1.0.0"]["problem"], "")

    def test_note_commit_is_success_when_only_old_state_cleanup_fails(self):
        installed = self.inspect()
        self.install(installed)
        release, data, signature, _ = self.newer()
        base = self.release["updates"]
        with Web({base + "release.json": (200, data), base + "release.json.sig": (200, signature)}), \
                mock.patch.object(helper, "take_own", side_effect=OSError("forced cleanup failure")):
            checked = helper.do_app_update_check(self.apps, installed["sourceId"], "tv.alex.clock")
        self.assertTrue(checked["ok"])
        self.assertIn("warning", checked)
        self.assertEqual(checked["update"]["version"], "1.1.0")


class DeveloperTools(AppFiles):
    def setUp(self):
        super().setUp()
        self.publisher = os.path.join(self.folder, "publisher")

    def initialize(self):
        real = subprocess.run

        def without_passphrase(command, *args, **kwargs):
            if command[:4] == ["/usr/bin/ssh-keygen", "-t", "ed25519", "-f"]:
                command = command[:4] + [command[4], "-N", ""] + command[5:]
            return real(command, *args, **kwargs)

        with mock.patch.object(helper.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(helper.subprocess, "run", side_effect=without_passphrase), \
                mock.patch.dict(os.environ, {"HOME": self.folder}):
            return helper.do_app_key(self.publisher)

    def set_version(self, version):
        with open(os.path.join(self.app, "app.json")) as f:
            manifest = json.load(f)
        manifest["version"] = version
        with open(os.path.join(self.app, "app.json"), "w") as f:
            json.dump(manifest, f)

    def test_app_key_initializes_one_private_workspace(self):
        made = self.initialize()
        self.assertEqual(stat.S_IMODE(os.stat(self.publisher).st_mode), 0o700)
        self.assertTrue(made["key"].startswith(os.path.join(self.folder, ".ssh") + os.sep))
        self.assertEqual(set(os.listdir(self.publisher)), {"publisher.json", "history.json"})
        with self.assertRaises(helper.Bad):
            self.initialize()

    def test_app_key_requires_a_terminal_and_an_empty_nofollow_folder(self):
        with mock.patch.object(helper.sys.stdin, "isatty", return_value=False), mock.patch.dict(os.environ, {"HOME": self.folder}):
            with self.assertRaises(helper.Bad):
                helper.do_app_key(self.publisher)
        os.mkdir(self.publisher)
        with open(os.path.join(self.publisher, "mine"), "w") as f:
            f.write("keep")
        with mock.patch.object(helper.sys.stdin, "isatty", return_value=True):
            with self.assertRaises(helper.Bad):
                helper.do_app_key(self.publisher)
        shutil.rmtree(self.publisher)
        os.symlink(self.app, self.publisher)
        with mock.patch.object(helper.sys.stdin, "isatty", return_value=True):
            with self.assertRaises(helper.Bad):
                helper.do_app_key(self.publisher)

    def test_app_file_writes_a_verified_immutable_release(self):
        self.initialize()
        built = helper.do_app_file(self.app, self.publisher, "https://updates.example.com/clock/")
        self.assertEqual(built["version"], "1.0.0")
        self.assertEqual(set(os.listdir(built["folder"])),
                         {"key.pub", "release.json", "release.json.sig", "package.tar.gz", "tv.alex.clock-1.0.0.tvapp"})
        with open(os.path.join(built["folder"], "release.json")) as f:
            note = json.load(f)
        self.assertEqual(note["package"]["url"], "package.tar.gz")
        self.assertTrue(os.path.isfile(os.path.join(built["folder"], note["package"]["url"])))
        got = helper.read_app_file(built["appFile"])
        self.assertEqual((got["entry"]["id"], got["entry"]["version"]), ("tv.alex.clock", "1.0.0"))

    def test_a_release_is_not_finished_before_its_files_and_names_are_synced(self):
        self.initialize()
        real = helper.os.fsync

        def fail_first_folder_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("forced release-folder sync failure")
            return real(fd)

        with mock.patch.object(helper.os, "fsync", side_effect=fail_first_folder_sync):
            with self.assertRaises(OSError):
                helper.do_app_file(self.app, self.publisher, None)
        names = [name for name in os.listdir(self.publisher) if name.startswith("tv.alex.clock-")]
        self.assertEqual(len(names), 1)
        dfd = os.open(self.publisher, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with open(os.path.join(self.publisher, "publisher.json")) as f:
                line = json.load(f)["public"]
            self.assertIsNone(helper.read_finished_release(dfd, names[0], line, "tv.alex.clock"))
        finally:
            os.close(dfd)

    def test_workspace_is_required_and_its_recorded_tip_must_verify(self):
        os.mkdir(self.publisher)
        with self.assertRaises(helper.Bad):
            helper.do_app_file(self.app, self.publisher, None)
        shutil.rmtree(self.publisher)
        self.initialize()
        first = helper.do_app_file(self.app, self.publisher, None)
        release = os.path.join(first["folder"], "release.json")
        os.chmod(release, 0o600)
        with open(release, "ab") as f:
            f.write(b"changed")
        self.set_version("1.1.0")
        with self.assertRaises(helper.Bad):
            helper.do_app_file(self.app, self.publisher, None)

    def test_releases_move_forward_and_revocations_only_accumulate(self):
        self.initialize()
        with mock.patch.object(helper.time, "time", return_value=1700000000):
            first = helper.do_app_file(self.app, self.publisher, "https://updates.example.com/clock/")
            revoked = helper.do_app_revoke(self.publisher, "tv.alex.clock", "0.9.0", "unsafe")
            self.set_version("1.1.0")
            second = helper.do_app_file(self.app, self.publisher, "https://updates.example.com/clock/")
        self.assertEqual([first["updated"], revoked["updated"], second["updated"]],
                         [1700000000, 1700000001, 1700000002])
        with open(os.path.join(second["folder"], "release.json")) as f:
            note = json.load(f)
        self.assertEqual(note["revoked"], [{"version": "0.9.0", "reason": "unsafe"}])
        with self.assertRaises(helper.Bad):
            helper.do_app_revoke(self.publisher, "tv.alex.clock", "0.9.0", "another reason")

    def test_a_complete_successor_is_adopted_but_an_incomplete_one_is_ignored(self):
        self.initialize()
        first = helper.do_app_file(self.app, self.publisher, None)
        history = os.path.join(self.publisher, "history.json")
        with open(history, "rb") as f:
            old = f.read()
        self.set_version("1.1.0")
        second = helper.do_app_file(self.app, self.publisher, None)
        # Simulate stopping after a complete release, before its history
        # replacement: put the prior state back.
        with open(history, "wb") as f:
            f.write(old)
        incomplete = os.path.join(self.publisher, "tv.alex.clock-9.9.9-999999999999")
        os.mkdir(incomplete)
        with open(os.path.join(incomplete, "release.json"), "w") as f:
            f.write("unfinished")
        self.set_version("1.2.0")
        third = helper.do_app_file(self.app, self.publisher, None)
        self.assertGreater(third["updated"], second["updated"])
        with open(history) as f:
            record = json.load(f)["apps"]["tv.alex.clock"]
        self.assertEqual(record["folder"], os.path.basename(third["folder"]))

    def test_no_release_folder_or_file_is_ever_overwritten(self):
        self.initialize()
        fixed = 1700000000
        taken = os.path.join(self.publisher, "tv.alex.clock-1.0.0-" + str(fixed))
        os.mkdir(taken)
        with open(os.path.join(taken, "keep"), "w") as f:
            f.write("mine")
        with mock.patch.object(helper.time, "time", return_value=fixed):
            with self.assertRaises(helper.Bad):
                helper.do_app_file(self.app, self.publisher, None)
        with open(os.path.join(taken, "keep")) as f:
            self.assertEqual(f.read(), "mine")

    def test_a_history_write_failure_leaves_a_complete_adoptable_release(self):
        self.initialize()
        with mock.patch.object(helper.os, "replace", side_effect=OSError("forced history failure")):
            with self.assertRaises(helper.Bad):
                helper.do_app_file(self.app, self.publisher, None)
        complete = [name for name in os.listdir(self.publisher) if name.startswith("tv.alex.clock-")]
        self.assertEqual(len(complete), 1)
        self.set_version("1.1.0")
        later = helper.do_app_file(self.app, self.publisher, None)
        self.assertEqual(later["version"], "1.1.0")

    def test_history_commit_is_success_when_only_folder_sync_fails(self):
        self.initialize()
        _, dfd, _, before, history = helper.open_publisher(self.publisher)
        real, calls = helper.os.fsync, 0

        def fail_second(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("forced folder sync failure")
            return real(fd)

        try:
            with mock.patch.object(helper.os, "fsync", side_effect=fail_second):
                warning = helper.replace_publisher_history(dfd, before, history)
        finally:
            os.close(dfd)
        self.assertIn("in place", warning)
        with open(os.path.join(self.publisher, "history.json"), "rb") as f:
            self.assertEqual(helper.publisher_history(f.read()), history)

    def test_two_publisher_runs_are_serialized_on_one_tip(self):
        self.initialize()
        import fcntl
        dfd = os.open(self.publisher, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fcntl.flock(dfd, fcntl.LOCK_EX)
        commands = [[sys.executable, HELPER, "app-file", self.app, self.publisher] for _ in range(2)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in commands]
        try:
            self.assertTrue(waiting_for_lock(processes, self.publisher), "both runs wait on the workspace lock")
        finally:
            os.close(dfd)
        answers = []
        for process in processes:
            out, err = process.communicate(timeout=30)
            answers.append(json.loads(out.strip().splitlines()[-1]))
        self.assertEqual(sum(bool(answer["ok"]) for answer in answers), 1)
        with open(os.path.join(self.publisher, "history.json")) as f:
            self.assertIn("tv.alex.clock", json.load(f)["apps"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
