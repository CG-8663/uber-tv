#!/usr/bin/python3
"""Uber TV's own updates (bin/om-pg-update): /usr/bin/python3 tests/update.test.py

Versions sort as semantic versioning does; only version tags count, and only
above the installed version; the release notes are the CHANGELOG.md sections
between the two. End to end against a local git repository standing in for
the address Uber TV was installed from: check, notes from the newer tag
(its private folder removed after), notes of the installed version, and
failures said, not raised. git's output is read up to a limit and within a
deadline."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "bin", "om-pg-update")
_loader = importlib.machinery.SourceFileLoader("om_pg_update", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_update", _loader)
up = importlib.util.module_from_spec(_spec)
_loader.exec_module(up)

failures = 0


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or detail == "" else "  " + str(detail)[:300]))


# ---- versions ----
check("v1.2.3 and 1.2.3 are versions", up.parse("v0.2.0") == (0, 2, 0, None) and up.parse("0.1.0-beta") == (0, 1, 0, "beta"))
check("other names aren't", all(up.parse(x) is None for x in ["1.2", "v1.2.3-", "latest", "v1.2.3+build", "1.2.3.4", ""]))
ladder = ["0.1.0-beta", "0.1.0-beta.2", "0.1.0-beta.10", "0.1.0-rc.1", "0.1.0", "0.1.1", "0.2.0", "0.10.0-beta", "1.0.0"]
keys = [up.order(up.parse(v)) for v in ladder]
check("versions sort as semantic versioning does", all(keys[i] < keys[i + 1] for i in range(len(keys) - 1)), ladder)

listing = ("a1\trefs/tags/v0.1.0-beta\na2\trefs/tags/v0.2.0\na3\trefs/tags/not-a-version\n"
           "a4\trefs/tags/v0.10.0-beta\na5\trefs/heads/main\n")
names = up.tag_names(listing)
check("tag names from ls-remote, not branches", names == ["v0.1.0-beta", "v0.2.0", "not-a-version", "v0.10.0-beta"], names)
v, tag = up.newest(names, up.parse("0.1.0-beta"))
check("the newest version above the installed one (0.10 after 0.2)", up.plain(v) == "0.10.0-beta" and tag == "v0.10.0-beta", (v, tag))
check("nothing above the newest", up.newest(["v0.1.0-beta", "v0.2.0"], up.parse("0.2.0")) == (None, None))

# ---- release notes ----
LOG = """# Changelog

Intro.

## [Unreleased]

- next

## [0.3.0] - 2026-11-01

### Added

- three

## [0.2.0] - 2026-10-25

- two

## [0.1.0-beta] - 2026-10-17

- one
"""
between = up.notes_between(LOG, up.parse("0.1.0-beta"), up.parse("0.3.0"))
check("notes: the sections above the installed version, up to the newer one",
      between.startswith("## [0.3.0]") and "## [0.2.0]" in between and "0.1.0-beta" not in between and "Unreleased" not in between, between)
check("notes: not past the newer one", up.notes_between(LOG, up.parse("0.1.0-beta"), up.parse("0.2.0")) == "## [0.2.0] - 2026-10-25\n\n- two")
check("notes of the installed version", up.notes_of(LOG, up.parse("0.1.0-beta")) == "## [0.1.0-beta] - 2026-10-17\n\n- one")


# ---- end to end, against a local repository ----
def run(*args, cwd=None, env=None):
    subprocess.run(list(args), cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def helper(*args, env=None):
    out = subprocess.run(["/usr/bin/python3", HELPER] + list(args), env=env, stdout=subprocess.PIPE, timeout=120).stdout
    return json.loads(out.decode() or "null")


with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", XDG_RUNTIME_DIR=os.path.join(tmp, "run"))
    os.mkdir(env["XDG_RUNTIME_DIR"], 0o700)
    G = ["/usr/bin/git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    origin, work, plugin = (os.path.join(tmp, n) for n in ("origin.git", "work", "plugin"))
    run(*G, "init", "-q", "--bare", origin, env=env)
    run(*G, "-C", origin, "config", "uploadpack.allowFilter", "true", env=env)
    run(*G, "init", "-q", work, env=env)
    with open(os.path.join(work, "CHANGELOG.md"), "w") as f:
        f.write(LOG.split("## [0.3.0]")[0].replace("## [Unreleased]\n\n- next\n\n", "") + "## [0.1.0-beta] - 2026-10-17\n\n- one\n")
    run(*G, "-C", work, "add", "CHANGELOG.md", env=env)
    run(*G, "-C", work, "commit", "-q", "-m", "one", env=env)
    run(*G, "-C", work, "tag", "v0.1.0-beta", env=env)
    run(*G, "-C", work, "remote", "add", "origin", origin, env=env)
    run(*G, "-C", work, "push", "-q", "origin", "main", "v0.1.0-beta", env=env)
    run(*G, "clone", "-q", "--branch", "v0.1.0-beta", origin, plugin, env=env)   # Uber TV as installed
    with open(os.path.join(work, "CHANGELOG.md"), "w") as f:
        f.write(LOG)
    run(*G, "-C", work, "commit", "-q", "-am", "three", env=env)
    run(*G, "-C", work, "tag", "v0.3.0", env=env)
    run(*G, "-C", work, "tag", "nightly", env=env)
    run(*G, "-C", work, "push", "-q", "origin", "main", "v0.3.0", "nightly", env=env)

    got = helper("check", plugin, "0.1.0-beta", env=env)
    check("check: a newer version tag is an update", got == {"ok": True, "latest": "0.3.0", "tag": "v0.3.0"}, got)
    got = helper("check", plugin, "0.3.0", env=env)
    check("check: up to date", got == {"ok": True, "latest": "", "tag": ""}, got)
    got = helper("notes", plugin, "0.1.0-beta", "v0.3.0", env=env)
    check("notes from the newer tag", got.get("ok") and got["notes"].startswith("## [0.3.0]") and "## [0.2.0]" in got["notes"]
          and "0.1.0-beta" not in got["notes"], got)
    check("its private folder is gone after", os.listdir(env["XDG_RUNTIME_DIR"]) == [], os.listdir(env["XDG_RUNTIME_DIR"]))
    got = helper("notes", plugin, "0.1.0-beta", env=env)
    check("notes of the installed version, from the plugin folder", got == {"ok": True, "notes": "## [0.1.0-beta] - 2026-10-17\n\n- one"}, got)
    got = helper("notes", plugin, "0.3.0", "v0.1.0-beta", env=env)
    check("notes: an older tag is refused", got.get("ok") is False, got)
    got = helper("notes", plugin, "0.1.0-beta", "v9.9.9", env=env)
    check("notes: a tag that isn't there fails, said", got.get("ok") is False and got.get("error"), got)
    os.makedirs(os.path.join(tmp, "plain"))
    got = helper("check", os.path.join(tmp, "plain"), "0.1.0-beta", env=env)
    check("check: not a git checkout fails, said", got.get("ok") is False and got.get("error"), got)
    got = helper("check", plugin, "not-a-version", env=env)
    check("check: an installed version that isn't one fails, said", got.get("ok") is False, got)
    run(*G, "-C", plugin, "remote", "set-url", "origin", os.path.join(tmp, "gone.git"), env=env)
    got = helper("check", plugin, "0.1.0-beta", env=env)
    check("check: an address that doesn't answer fails, said", got.get("ok") is False and got.get("error"), got)

# ---- git's output, bounded and on a deadline ----
git, timeout = up.GIT, up.TIMEOUT
try:
    up.GIT = "/usr/bin/head"
    try:
        up.git(["-c", "300000", "/dev/zero"], cap=64 * 1024)
        check("more output than allowed is refused", False)
    except RuntimeError as e:
        check("more output than allowed is refused", "more than" in str(e), e)
    up.GIT, up.TIMEOUT = "/usr/bin/sleep", 1
    start = time.monotonic()
    try:
        up.git(["30"])
        check("a command past its deadline is stopped", False)
    except RuntimeError as e:
        check("a command past its deadline is stopped", "too long" in str(e) and time.monotonic() - start < 5, e)
finally:
    up.GIT, up.TIMEOUT = git, timeout

print("\n%d failed" % failures if failures else "\nall good")
sys.exit(1 if failures else 0)
