#!/usr/bin/env python3
"""bin/om-pg-apps against good apps and bad ones: python3 tests/apps.test.py"""

import gzip
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "om-pg-apps")
work = tempfile.mkdtemp(prefix="om-pg-apps-test-")
failures = 0


def wipe(path):
    """A test folder removed, the read-only copies installs leave in it too"""
    for root, dirs, _ in os.walk(path):
        for d in dirs:
            if not os.path.islink(os.path.join(root, d)):
                os.chmod(os.path.join(root, d), 0o700)
    shutil.rmtree(path)


def run(*args):
    r = subprocess.run([sys.executable, HELPER] + [str(a) for a in args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "error": "no JSON: " + r.stdout + r.stderr}


def check(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
        print("FAIL", name, detail)
    else:
        print("ok  ", name)


def manifest(**over):
    m = {"id": "tv.example.flix", "name": "Flix", "version": "1.0.0", "api": 1, "author": "Example", "kind": "launcher",
         "description": "A test app.", "color": "#e50914", "launch": {"web": "https://www.flix.example.com/browse"},
         "permissions": {"web": ["flix.example.com"]}}
    m.update(over)
    return m


def app_folder(name, m, extra=None):
    folder = os.path.join(work, name)
    os.makedirs(folder)
    with open(os.path.join(folder, "app.json"), "w") as f:
        json.dump(m, f)
    for path, data in (extra or {}).items():
        os.makedirs(os.path.dirname(os.path.join(folder, path)) or folder, exist_ok=True)
        with open(os.path.join(folder, path), "wb") as f:
            f.write(data)
    return folder


def tar_with(name, members):
    """A .tar.gz built by hand: [(TarInfo, bytes or None)]"""
    path = os.path.join(work, name)
    with tarfile.open(path, "w:gz") as tf:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                tf.addfile(info)
    return path


def file_info(name):
    i = tarfile.TarInfo(name)
    i.mode = 0o644
    return i


staging = os.path.join(work, "staging")
signers_placeholder = os.path.join(work, "no-signers")
apps_dir = os.path.join(work, "apps")
data_dir = os.path.join(work, "data")
good_json = json.dumps(manifest()).encode()
PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0) + b"\0" * 40
FILE_SRC = "file:0123456789abcdef"
CAT_SRC = "catalog:uber"


def sdir(source):
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def roots():
    return json.dumps({"apps": apps_dir, "data": data_dir})

# ---- a good app, from a folder and as a package ----
folder = app_folder("good", manifest(icon="icon.png"), {"icon.png": PNG, "README.md": b"# Flix\n"})
res = run("inspect", json.dumps({"type": "file", "path": folder}), staging)
check("a good folder inspects", res.get("ok") and res["manifest"]["name"] == "Flix" and set(res["files"]) == {"app.json", "icon.png", "README.md"}, res)
check("app.json's path means its folder", run("inspect", json.dumps({"type": "file", "path": folder + "/app.json"}), staging).get("ok"))
if res.get("ok"):
    check("the staged folder is private", oct(os.stat(res["staging"]).st_mode & 0o777) == "0o700")
    check("refused: an install of something other than what was shown", not run("install", res["staging"], apps_dir, data_dir, "0" * 64, FILE_SRC).get("ok"))
    inst = run("install", res["staging"], apps_dir, data_dir, res["tree"], FILE_SRC)
    target = os.path.join(apps_dir, sdir(FILE_SRC), "tv.example.flix", "1.0.0")
    check("it installs", inst.get("ok") and os.path.isfile(os.path.join(target, "app.json")), inst)
    check("installed files are read-only", not os.access(os.path.join(target, "app.json"), os.W_OK))
    check("the staged folder is gone", not os.path.exists(res["staging"]))
    files = inst.get("files", {})
    check("a file's app has no proof", inst.get("proof") == "none", inst)
    v = run("verify", apps_dir, signers_placeholder, "")
    one = (v.get("apps") or [{}])[0]
    check("it verifies", v.get("ok") and one.get("files") == files and not one.get("problem") and one.get("manifest", {}).get("name") == "Flix", v)
    os.chmod(os.path.join(target, "README.md"), 0o644)
    with open(os.path.join(target, "README.md"), "ab") as f:
        f.write(b"changed")
    one = (run("verify", apps_dir, signers_placeholder, "").get("apps") or [{}])[0]
    check("a changed file shows", one.get("files") != files, one)
    os.chmod(target, 0o755)
    os.unlink(os.path.join(target, "README.md"))
    os.mkfifo(os.path.join(target, "README.md"))
    one = (run("verify", apps_dir, signers_placeholder, "").get("apps") or [{}])[0]
    check("a pipe in its files is caught, not waited on", "isn't a file" in one.get("problem", ""), one)
    rm = run("remove", "tv.example.flix", FILE_SRC, roots())
    check("it removes", rm.get("ok") and not os.path.exists(os.path.join(apps_dir, sdir(FILE_SRC), "tv.example.flix")), rm)
check("remove refuses a path", not run("remove", "../../etc", FILE_SRC, roots()).get("ok"))
check("remove refuses a made-up source", not run("remove", "tv.example.flix", "file:../../x", roots()).get("ok"))

pkg = os.path.join(work, "flix.tar.gz")
packed = run("pack", folder, pkg)
check("it packs", packed.get("ok") and packed["catalogEntry"]["sha256"] == hashlib.sha256(open(pkg, "rb").read()).hexdigest(), packed)
pkg2 = os.path.join(work, "flix2.tar.gz")
run("pack", folder, pkg2)
check("packing gives the same bytes", open(pkg, "rb").read() == open(pkg2, "rb").read())
res = run("inspect", json.dumps({"type": "file", "path": pkg}), staging)
check("a package inspects", res.get("ok") and res["manifest"]["id"] == "tv.example.flix", res)
if res.get("ok"):
    check("discard", run("discard", res["staging"], staging).get("ok") and not os.path.exists(res["staging"]))

# ---- bad packages ----
def bad_tar(name, members, why):
    path = tar_with(name + ".tar.gz", members)
    r = run("inspect", json.dumps({"type": "file", "path": path}), staging)
    check("refused: " + why, not r.get("ok"), r)
    return r

bad_tar("abs", [(file_info("app.json"), good_json), (file_info("/etc/evil.png"), PNG)], "an absolute path")
bad_tar("dotdot", [(file_info("app.json"), good_json), (file_info("../evil.png"), PNG)], "a .. path")
link = tarfile.TarInfo("icon.png"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
bad_tar("symlink", [(file_info("app.json"), good_json), (link, None)], "a symlink")
hard = tarfile.TarInfo("icon.png"); hard.type = tarfile.LNKTYPE; hard.linkname = "app.json"
bad_tar("hardlink", [(file_info("app.json"), good_json), (hard, None)], "a hard link")
dev = tarfile.TarInfo("dev.png"); dev.type = tarfile.CHRTYPE
bad_tar("device", [(file_info("app.json"), good_json), (dev, None)], "a device")
bad_tar("hidden", [(file_info("app.json"), good_json), (file_info(".bashrc"), b"x")], "a hidden file")
bad_tar("elf", [(file_info("app.json"), good_json), (file_info("icon.png"), b"\x7fELF" + b"\0" * 60)], "a program named .png")
bad_tar("script", [(file_info("app.json"), good_json), (file_info("run.sh"), b"#!/bin/sh\nrm -rf ~\n")], "a script")
bad_tar("code", [(file_info("app.json"), good_json), (file_info("main.js"), b"fetch('x')")], "code in a launcher")
bad_tar("twice", [(file_info("app.json"), good_json), (file_info("app.json"), good_json)], "a file twice")
bad_tar("many", [(file_info("app.json"), good_json)] + [(file_info("f%d.txt" % i), b"x") for i in range(205)], "too many files")
bad_tar("big", [(file_info("app.json"), good_json), (file_info("big.txt"), b"x" * (21 * 1024 * 1024))], "too big unpacked")
bad_tar("deep", [(file_info("app.json"), good_json), (file_info("a/b/c/d/e/f.txt"), b"x")], "five folders deep")
r = run("inspect", json.dumps({"type": "file", "path": tar_with("four.tar.gz", [(file_info("app.json"), good_json), (file_info("a/b/c/d/e.txt"), b"x")])}), staging)
check("four folders deep is fine", r.get("ok"), r)
dirs = [(tarfile.TarInfo("d%d" % i), None) for i in range(401)]
for info, _ in dirs:
    info.type = tarfile.DIRTYPE
bad_tar("folders", [(file_info("app.json"), good_json)] + dirs, "hundreds of empty folders")
bad_tar("dotfile", [(file_info("app.json"), good_json), (file_info("./"), b"x" * 1000)], "data in a member named ./")
bad_tar("licence-elf", [(file_info("app.json"), good_json), (file_info("LICENSE"), b"\x7fELF" + b"\0" * 60)], "a program named LICENSE")
bad_tar("licence-sh", [(file_info("app.json"), good_json), (file_info("COPYING"), b"#!/bin/sh\nrm -rf ~\n")], "a script named COPYING")
bad_tar("licence-lower", [(file_info("app.json"), good_json), (file_info("license"), b"MIT")], "a lowercase license with no extension")
r = run("inspect", json.dumps({"type": "file", "path": tar_with("licence.tar.gz", [(file_info("app.json"), good_json), (file_info("LICENSE"), b"MIT License\n")])}), staging)
check("a plain LICENSE is fine", r.get("ok"), r)
r = bad_tar("nested", [(file_info("app.json"), b"[" * 100000)], "app.json nested too deep")
check("it says why, in one JSON line", not r.get("error", "").startswith("no JSON"), r)
bad_tar("nomanifest", [(file_info("README.md"), b"hi")], "no app.json")
r = run("inspect", json.dumps({"type": "file", "path": os.path.join(work, "flix.tar.gz.missing")}), staging)
check("refused: a missing file", not r.get("ok"))
with open(os.path.join(work, "notgz.tar.gz"), "wb") as f:
    f.write(b"not a package")
check("refused: not a .tar.gz", not run("inspect", json.dumps({"type": "file", "path": os.path.join(work, "notgz.tar.gz")}), staging).get("ok"))

# a folder with a link in it
lf = app_folder("linkfolder", manifest())
os.symlink("/etc/passwd", os.path.join(lf, "passwd.txt"))
check("refused: a link in a folder", not run("inspect", json.dumps({"type": "file", "path": lf}), staging).get("ok"))

# ---- bad manifests ----
def bad_manifest(name, m, why):
    f = app_folder("m-" + name, m)
    r = run("inspect", json.dumps({"type": "file", "path": f}), staging)
    check("refused: " + why, not r.get("ok"), r)
    return r

bad_manifest("userinfo", manifest(launch={"web": "https://flix.example.com@evil.example.net/"}), "a name@ in the link")
bad_manifest("otherhost", manifest(launch={"web": "https://evil.example.net/"}), "a link to a site it didn't ask for")
bad_manifest("lookalike", manifest(launch={"web": "https://flix.example.com.evil.net/"}), "a look-alike site")
bad_manifest("http", manifest(launch={"web": "http://www.flix.example.com/"}), "an http link")
bad_manifest("quote", manifest(launch={"web": "https://www.flix.example.com/\"$(rm -rf ~)"}), "quotes and $ in the link")
bad_manifest("js", manifest(launch={"web": "javascript:alert(1)"}), "a javascript: link")
bad_manifest("ip", manifest(launch={"web": "https://127.0.0.1/"}, permissions={"web": ["127.0.0.1"]}), "an IP address")
bad_manifest("port", manifest(launch={"web": "https://www.flix.example.com:8080/"}), "another port")
bad_manifest("port443", manifest(launch={"web": "https://www.flix.example.com:443/"}), "an explicit :443")
bad_manifest("upper", manifest(launch={"web": "https://WWW.flix.example.com/"}), "an uppercase website")
bad_manifest("newline-id", manifest(id="tv.example.flix\n"), "a newline after the id")
bad_manifest("newline-version", manifest(version="1.0.0\n"), "a newline after the version")
bad_manifest("bidi", manifest(name="Fli‮x"), "a right-to-left override in the name")
bad_manifest("zw", manifest(name="Net​flix"), "a zero-width space in the name")
bad_manifest("scripted", manifest(kind="scripted"), "an app with code")
bad_manifest("unknown", manifest(permissions={"web": ["flix.example.com"], "camera": True}), "a permission it doesn't know")
bad_manifest("net", manifest(permissions={"web": ["flix.example.com"], "net": ["api.example.com"]}), "net for a launcher")
r = bad_manifest("newer", manifest(api=5), "a newer api")
check("a newer api says what's needed", "newer Uber TV" in r.get("error", ""), r)
bad_manifest("launcher4", manifest(api=4), "a launcher that says api 4")
bad_manifest("launcher3", manifest(api=3), "a launcher that says api 3")
bad_manifest("launcher2", manifest(api=2), "a launcher that says api 2")
bad_manifest("id", manifest(id="../flix"), "a bad id")
bad_manifest("version", manifest(version="1.0"), "a bad version")
bad_manifest("noweb", manifest(permissions={}), "a launcher without a website")
bad_manifest("icon", manifest(icon="../../etc/passwd"), "an icon outside the app")
bad_manifest("longname", manifest(name="x" * 41), "a long name")
check("a subdomain of its website is fine", run("inspect", json.dumps({"type": "file", "path": app_folder("sub", manifest(launch={"web": "https://tv.flix.example.com/"}))}), staging).get("ok"))

# ---- the catalog: signed, checked, not replayed ----
key = os.path.join(work, "key")
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", key], check=True)
signers = os.path.join(work, "signers")
with open(signers, "w") as f:
    f.write('uber-tv-catalog namespaces="uber-tv-catalog" ' + open(key + ".pub").read())
other = os.path.join(work, "other")
subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "other", "-f", other], check=True)

cat_dir = os.path.join(work, "catalog")
os.makedirs(os.path.join(cat_dir, "packages"))
os.makedirs(os.path.join(cat_dir, "icons"))
shutil.copy(pkg, os.path.join(cat_dir, "packages", "flix.tar.gz"))
with open(os.path.join(cat_dir, "icons", "flix.png"), "wb") as f:
    f.write(PNG)
entry = dict(packed["catalogEntry"], package="packages/flix.tar.gz", icon="icons/flix.png", iconSha256=hashlib.sha256(PNG).hexdigest())
cat_path = os.path.join(cat_dir, "catalog.json")
cache = os.path.join(work, "cache")


def write_catalog(updated, apps, revoked=None, signer=key):
    with open(cat_path, "w") as f:
        json.dump({"format": 1, "name": "Test catalog", "updated": updated, "apps": apps, "revoked": revoked or []}, f)
    if os.path.exists(cat_path + ".sig"):
        os.unlink(cat_path + ".sig")
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", signer, "-n", "uber-tv-catalog", cat_path], check=True, capture_output=True)


write_catalog(1000, [entry])
c = run("catalog", cat_path, signers, 0, cache)
check("a signed catalog is read", c.get("ok") and c["catalog"]["apps"][0]["id"] == "tv.example.flix", c)
check("its icon is fetched and checked", c.get("ok") and os.path.isfile(c["catalog"]["apps"][0].get("iconFile", "")))
check("an older catalog is refused", not run("catalog", cat_path, signers, 2000, cache).get("ok"))
check("no key: refused", not run("catalog", cat_path, os.path.join(work, "nokey"), 0, cache).get("ok"))
with open(cat_path, "a") as f:
    f.write(" ")
check("a changed catalog is refused", not run("catalog", cat_path, signers, 0, cache).get("ok"))
write_catalog(1001, [entry], signer=other)
check("a catalog signed by another key is refused", not run("catalog", cat_path, signers, 0, cache).get("ok"))

write_catalog(1002, [entry])
run("catalog", cat_path, signers, 0, cache)
cache_file = os.path.join(cache, "apps-catalog.json")


def get(app_id="tv.example.flix", seen=0):
    return run("inspect", json.dumps({"type": "catalog", "id": app_id, "cache": cache, "signers": signers, "seen": seen}), staging)


res = get()
check("a catalog app inspects", res.get("ok") and res["source"] == "catalog", res)
if res.get("ok"):
    inst = run("install", res["staging"], apps_dir, data_dir, res["tree"], CAT_SRC)
    home = os.path.join(apps_dir, sdir(CAT_SRC), "tv.example.flix")
    check("a catalog app installs with its proof", inst.get("ok") and inst.get("proof") == "catalog"
          and sorted(os.listdir(home)) == ["1.0.0", "1.0.0.proof"], inst)
    one = (run("verify", apps_dir, signers, "").get("apps") or [{}])[0]
    check("it traces back to the signed catalog", one.get("proof") == "catalog" and not one.get("problem")
          and one.get("manifest", {}).get("launch", {}).get("web") == "https://www.flix.example.com/browse", one)
    # a key taken out (stolen, say): the app isn't turned off, it's installed again from the catalog
    only_other = os.path.join(work, "signers-other")
    with open(only_other, "w") as f:
        f.write('uber-tv-catalog namespaces="uber-tv-catalog" ' + open(other + ".pub").read())
    one = (run("verify", apps_dir, only_other, "").get("apps") or [{}])[0]
    check("signed with a key no longer trusted: install it again", one.get("proof") == "untrusted" and not one.get("problem"), one)
    one = (run("verify", apps_dir, os.path.join(work, "nokey"), "").get("apps") or [{}])[0]
    check("with no key at all, the same", one.get("proof") == "untrusted" and not one.get("problem"), one)
    both = os.path.join(work, "signers-both")
    with open(both, "w") as f:
        f.write(open(only_other).read() + open(signers).read())
    one = (run("verify", apps_dir, both, "").get("apps") or [{}])[0]
    check("a spare key beside it keeps old installs good", one.get("proof") == "catalog" and not one.get("problem"), one)
    target = os.path.join(home, "1.0.0")
    os.chmod(target, 0o755)
    shutil.copy(os.path.join(target, "app.json"), os.path.join(work, "app.json.keep"))
    os.chmod(os.path.join(target, "app.json"), 0o644)
    with open(os.path.join(target, "app.json"), "w") as f:
        json.dump(manifest(launch={"web": "https://www.flix.example.com/phish"}), f)
    one = (run("verify", apps_dir, signers, "").get("apps") or [{}])[0]
    check("a changed app.json is caught, though it's a valid one", one.get("problem") and one.get("proof") == "none", one)
    shutil.copy(os.path.join(work, "app.json.keep"), os.path.join(target, "app.json"))
    proof = os.path.join(home, "1.0.0.proof")
    os.chmod(proof, 0o755)
    os.chmod(os.path.join(proof, "package.tar.gz"), 0o644)
    run("pack", app_folder("evil2", manifest(launch={"web": "https://www.flix.example.com/phish"})), os.path.join(proof, "package.tar.gz"))
    one = (run("verify", apps_dir, signers, "").get("apps") or [{}])[0]
    check("a swapped package in its proof is caught", "package" in one.get("problem", ""), one)
    run("remove", "tv.example.flix", CAT_SRC, roots())

# what's kept for the guide to show doesn't decide what installs
with open(cache_file) as f:
    shown = json.load(f)
evil_pkg = os.path.join(cat_dir, "packages", "evil.tar.gz")
evil_packed = run("pack", app_folder("evil", manifest(launch={"web": "https://www.flix.example.com/phish"})), evil_pkg)
shown["apps"][0].update(package=evil_pkg, sha256=evil_packed["catalogEntry"]["sha256"], size=evil_packed["catalogEntry"]["size"])
with open(cache_file, "w") as f:
    json.dump(shown, f)
res = get()
check("an edited copy of the catalog doesn't change what installs", res.get("ok") and res["manifest"]["launch"]["web"] == "https://www.flix.example.com/browse", res)
if res.get("ok"):
    run("discard", res["staging"], staging)
signed_file = os.path.join(cache, "apps-catalog.signed.json")
with open(signed_file) as f:
    blob = json.load(f)
import base64
doctored = json.loads(base64.b64decode(blob["data"]))
doctored["apps"][0]["package"] = "packages/evil.tar.gz"
blob_bad = dict(blob, data=base64.b64encode(json.dumps(doctored).encode()).decode())
with open(signed_file, "w") as f:
    json.dump(blob_bad, f)
check("an edited signed copy is refused", not get().get("ok"))
with open(signed_file, "w") as f:
    json.dump(blob, f)
check("an older catalog than one seen is refused at install too", not get(seen=5000).get("ok"))

# a link where its folder goes
res = get()
if res.get("ok"):
    os.makedirs(os.path.join(apps_dir, sdir(CAT_SRC)), exist_ok=True)
    victim = os.path.join(work, "victim")
    os.makedirs(victim)
    open(os.path.join(victim, "keep.txt"), "w").write("mine")
    os.symlink(victim, os.path.join(apps_dir, sdir(CAT_SRC), "tv.example.flix"))
    r = run("install", res["staging"], apps_dir, data_dir, res["tree"], CAT_SRC)
    check("refused: a link where its folder goes, and nothing behind it touched", not r.get("ok") and os.listdir(victim) == ["keep.txt"], r)
    os.unlink(os.path.join(apps_dir, sdir(CAT_SRC), "tv.example.flix"))
    run("discard", res["staging"], staging)

# a package swapped for another
run("pack", evil_folder := app_folder("evil3", manifest(launch={"web": "https://www.flix.example.com/phish"})), os.path.join(cat_dir, "packages", "flix.tar.gz"))
res = get()
check("a swapped package is refused", not res.get("ok"), res)
shutil.copy(pkg, os.path.join(cat_dir, "packages", "flix.tar.gz"))

# a package that asks for more than its catalog entry says
more = app_folder("more", manifest(launch={"web": "https://www.flix.example.com/"}, permissions={"web": ["example.com", "flix.example.com"]}))
p_more = run("pack", more, os.path.join(cat_dir, "packages", "more.tar.gz"))
lying = dict(p_more["catalogEntry"], package="packages/more.tar.gz", permissions={"web": ["flix.example.com"]})
write_catalog(1003, [lying])
run("catalog", cat_path, signers, 0, cache)
res = get()
check("a package asking for more than its listing is refused", not res.get("ok"), res)

# a package on another site
write_catalog(1004, [dict(entry, package="https://evil.example.net/flix.tar.gz")])
c = run("catalog", cat_path, signers, 0, cache)
check("an app on another site is left out", c.get("ok") and c["catalog"]["apps"] == [] and c["catalog"]["skipped"] == 1, c)
write_catalog(1005, [dict(entry, package="../../outside.tar.gz")])
c = run("catalog", cat_path, signers, 0, cache)
check("an app outside the catalog's folder is left out", c.get("ok") and c["catalog"]["apps"] == [], c)

# revoked: listed and pulled is pulled
write_catalog(1006, [entry], revoked=[{"id": "tv.example.flix", "version": "1.0.0", "reason": "It sent people to the wrong site."}])
c = run("catalog", cat_path, signers, 0, cache)
check("revocations come through", c.get("ok") and c["catalog"]["revoked"][0]["reason"].startswith("It sent"), c)
check("a pulled version isn't offered", c.get("ok") and c["catalog"]["apps"] == [], c)
r = get()
check("a pulled version doesn't install", not r.get("ok") and "pulled" in r.get("error", ""), r)
write_catalog(1007, [entry], revoked=[{"id": "tv.example.flix", "version": "*"}])
check("pulling every version works too", run("catalog", cat_path, signers, 0, cache).get("catalog", {}).get("apps") == [])
with open(cat_path, "w") as f:
    json.dump({"format": 1, "name": "Test catalog", "updated": 1008, "apps": [entry], "revoked": {"tv.example.flix": "1.0.0"}}, f)
os.unlink(cat_path + ".sig")
subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", key, "-n", "uber-tv-catalog", cat_path], check=True, capture_output=True)
check("a catalog whose revocations can't be read is refused", not run("catalog", cat_path, signers, 0, cache).get("ok"))
write_catalog(1009, [entry], revoked=[{"id": "tv.example.flix"}])
check("so is one with a revocation missing its version", not run("catalog", cat_path, signers, 0, cache).get("ok"))
check("catalogs must be https or a file", not run("catalog", "http://example.com/catalog.json", signers, 0, cache).get("ok"))

# a package git archive made: a global header with the commit it's of (52
# bytes, nothing but a comment) before the files
record = b"52 comment=aa09031f17e6c173b364e10d88be59bfc73cbc91\n"
global_header = tarfile.TarInfo("pax_global_header")
global_header.type, global_header.size = tarfile.XGLTYPE, len(record)
with open(pkg, "rb") as f:
    git_pkg = gzip.compress(global_header.tobuf(tarfile.USTAR_FORMAT) + record + b"\0" * (-len(record) % tarfile.BLOCKSIZE) + gzip.decompress(f.read()))
git_path = os.path.join(cat_dir, "packages", "flix-git.tar.gz")
with open(git_path, "wb") as f:
    f.write(git_pkg)
res = run("inspect", json.dumps({"type": "file", "path": git_path}), staging)
check("a package git archive made (a comment in its global header) inspects from a file", res.get("ok") and res["manifest"]["name"] == "Flix", res)
if res.get("ok"):
    run("discard", res["staging"], staging)
write_catalog(1010, [dict(entry, package="packages/flix-git.tar.gz", sha256=hashlib.sha256(git_pkg).hexdigest(), size=len(git_pkg))])
check("git archive's package is listed in the catalog", run("catalog", cat_path, signers, 0, cache).get("ok"))
res = get()
check("git archive's package inspects from the catalog", res.get("ok"), res)
if res.get("ok"):
    inst = run("install", res["staging"], apps_dir, data_dir, res["tree"], CAT_SRC)
    check("git archive's package installs with its proof", inst.get("ok") and inst.get("proof") == "catalog", inst)
    v = [a for a in run("verify", apps_dir, signers, "").get("apps", []) if a.get("sourceDir") == sdir(CAT_SRC)]
    check("git archive's package traces back to the signed catalog at start", [(a.get("proof"), a.get("problem")) for a in v] == [("catalog", "")], v)
    run("remove", "tv.example.flix", CAT_SRC, roots())

# ---- apps with code (api 2) ----
def code_app(name, src=b"from uber_tv import app\napp.run()\n", extra=None, **over):
    m = {"id": "tv.example.code", "name": "Code", "version": "1.0.0", "api": 2, "kind": "app", "author": "Example",
         "main": "main.py", "permissions": {"net": ["api.example.com"]}}
    m.update(over)
    files = {"main.py": src}
    files.update(extra or {})
    return app_folder(name, m, files)


def inspect_file(folder):
    return run("inspect", json.dumps({"type": "file", "path": folder}), staging)


ok = inspect_file(code_app("code-good"))
check("an app with code inspects", ok.get("ok") and ok["manifest"]["kind"] == "app" and ok["manifest"]["main"] == "main.py", ok)
check("a .py may start with #!", inspect_file(code_app("code-shebang", src=b"#!/usr/bin/env python3\nprint(1)\n")).get("ok"))
r = inspect_file(code_app("code-utf8", src=b"print('\xff')\n"))
check("refused: a .py that isn't UTF-8", not r.get("ok") and "UTF-8" in r.get("error", ""), r)
r = inspect_file(code_app("code-mdutf8", extra={"README.md": b"\xc3\x28"}))
check("refused: a .md that isn't UTF-8", not r.get("ok") and "UTF-8" in r.get("error", ""), r)
r = inspect_file(code_app("code-elf", extra={"data.json": b"\x7fELF\0\0"}))
check("refused: a program named .json", not r.get("ok") and "program" in r.get("error", ""), r)
r = inspect_file(code_app("code-shebang-json", extra={"data.json": b"#!/bin/sh\n"}))
check("refused: #! anywhere but a .py", not r.get("ok") and "program" in r.get("error", ""), r)
r = inspect_file(code_app("code-unknown", homepage="x"))
check("refused: a field app.json doesn't have", not r.get("ok") and "field" in r.get("error", ""), r)
r = inspect_file(code_app("code-wild", permissions={"net": ["*.example.com"]}))
check("refused: a wildcard host", not r.get("ok"), r)
r = inspect_file(code_app("code-signin", permissions={"signIn": "code"}))
check("refused: signing in without a server", not r.get("ok") and "server" in r.get("error", ""), r)
r = inspect_file(code_app("code-main", b"x=1\n", {"lib/main.py": b"x=1\n"}, main="lib/main.py"))
check("refused: main not at the top", not r.get("ok"), r)
r = inspect_file(code_app("code-settings", settings=[{"key": "server", "type": "text", "label": "S"}]))
check("refused: a setting named server", not r.get("ok"), r)
big = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 5000, 16, 8, 6, 0, 0, 0) + b"\0" * 40
r = inspect_file(code_app("code-bigicon", icon="icon.png", extra={"icon.png": big}))
check("refused: a picture wider than 4096", not r.get("ok") and "picture" in r.get("error", ""), r)
r = run("check", code_app("code-lint", src=b"import json, helpers\nfrom lib import util\nfrom uber_tv import app\n",
                          extra={"helpers.py": b"x=1\n", "lib/util.py": b"y=2\n", "lib/__init__.py": b""}))
check("the lint allows the standard library, the toolkit and the app's own modules", r.get("ok") and not r["errors"], r)
r = run("check", code_app("code-lint-bad", src=b"import requests\nfrom numpy import array\n"))
check("the lint names an outside package", not r.get("ok") and [e["code"] for e in r["errors"]] == ["import", "import"], r)
r = run("check", code_app("code-syntax", src=b"def (:\n"))
check("the lint names a syntax error", not r.get("ok") and r["errors"][0]["code"] == "syntax", r)
r = run("check", code_app("code-home", home=[{"key": "now", "label": "Now"}]))
check("Home rows check cleanly", r.get("ok") and not r["warnings"] and r["manifest"]["home"] == [{"key": "now", "label": "Now"}], r)

# api 3: its layout and Home shapes, checked as strictly
lay = {"look": "posters", "rows": [{"id": "latest", "label": "Recently added", "shape": "poster"},
                                   {"id": "lib-0a1b", "label": "Movies", "size": "large", "layout": "grid"}]}
r = inspect_file(code_app("code-api3", api=3, layout=lay, home=[{"key": "continue", "label": "Continue", "shape": "wide"}, {"key": "now", "label": "Now"}]))
check("an api 3 app inspects, its api kept", r.get("ok") and r["manifest"]["api"] == 3, r)
check("its layout as it said", r.get("ok") and r["manifest"]["layout"] == lay, r)
check("its Home rows keep their shapes", r.get("ok") and r["manifest"]["home"] == [{"key": "continue", "label": "Continue", "shape": "wide"}, {"key": "now", "label": "Now"}], r)
r = inspect_file(code_app("code-api3-bare", api=3))
check("an api 3 app without a layout", r.get("ok") and r["manifest"]["layout"] == {"look": "", "rows": []}, r)
r = inspect_file(code_app("code-api2"))
check("an api 2 app stays api 2, with no layout", r.get("ok") and r["manifest"]["api"] == 2 and "layout" not in r["manifest"], r)
for name, over, why in [
        ("api2-layout", {"layout": {"look": "posters"}}, "api 2 with a layout"),
        ("api2-homeshape", {"home": [{"key": "now", "label": "Now", "shape": "poster"}]}, "api 2 with a Home shape"),
        ("api3-look", {"api": 3, "layout": {"look": "fancy"}}, "a look that isn't one"),
        ("api3-rowid", {"api": 3, "layout": {"rows": [{"id": "Upper", "label": "x"}]}}, "a row id outside the pattern"),
        ("api3-dup", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]}}, "a row id twice"),
        ("api3-nolabel", {"api": 3, "layout": {"rows": [{"id": "a"}]}}, "a layout row without its label"),
        ("api3-label", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x" * 41}]}}, "a label over 40"),
        ("api3-shape", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "shape": "oval"}]}}, "a shape that isn't one"),
        ("api3-size", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "size": "huge"}]}}, "a size that isn't one"),
        ("api3-rowlayout", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "layout": "carousel"}]}}, "a layout that isn't one"),
        ("api3-rowfield", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "color": "red"}]}}, "a field a layout row doesn't have"),
        ("api3-layoutfield", {"api": 3, "layout": {"look": "wall", "theme": "x"}}, "a field the layout doesn't have"),
        ("api3-rows41", {"api": 3, "layout": {"rows": [{"id": "r" + str(i), "label": "x"} for i in range(41)]}}, "41 layout rows"),
        ("api3-homelogo", {"api": 3, "home": [{"key": "now", "label": "Now", "shape": "logo"}]}, "a Home shape other than poster or wide"),
        ("api3-launcher-layout", {"api": 3, "kind": "launcher"}, "a launcher at api 3"),
        # false-like values are refused as what they are, never taken as absent
        ("api3-look-list", {"api": 3, "layout": {"look": []}}, "a look that's a list"),
        ("api3-look-empty", {"api": 3, "layout": {"look": ""}}, "an empty look"),
        ("api3-size-false", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "size": False}]}}, "a size that's false"),
        ("api3-layout-zero", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "layout": 0}]}}, "a layout that's 0"),
        ("api3-shape-dict", {"api": 3, "layout": {"rows": [{"id": "a", "label": "x", "shape": {}}]}}, "a shape that's an object"),
        ("api3-homeshape-list", {"api": 3, "home": [{"key": "now", "label": "Now", "shape": []}]}, "a Home shape that's a list"),
        ("api3-homeshape-null", {"api": 3, "home": [{"key": "now", "label": "Now", "shape": None}]}, "a Home shape that's null")]:
    r = inspect_file(code_app("code-" + name, **over))
    check("refused: " + why, not r.get("ok"), r)

# api 4: sites it may also change things on, by method
r = inspect_file(code_app("code-api4", api=4, layout=lay, permissions={"net": ["b.example.com", "api.example.com"],
                                                                    "netWrite": {"api.example.com": ["DELETE", "POST"]}}))
check("an api 4 app inspects, with its layout", r.get("ok") and r["manifest"]["api"] == 4 and r["manifest"]["layout"] == lay, r)
check("netWrite is kept canonical: its methods in a fixed order",
      r.get("ok") and r["manifest"]["permissions"]["netWrite"] == {"api.example.com": ["POST", "DELETE"]}, r)
r = inspect_file(code_app("code-api4-none", api=4))
check("an app that writes nowhere has an empty netWrite", r.get("ok") and r["manifest"]["permissions"]["netWrite"] == {}, r)
for name, over, why in [
        ("w-api3", {"api": 3, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": ["POST"]}}}, "netWrite at api 3"),
        ("w-api2", {"permissions": {"net": ["api.example.com"], "netWrite": {}}}, "netWrite at api 2, even empty"),
        ("w-notnet", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"other.example.com": ["POST"]}}}, "a write host that isn't in net"),
        ("w-sub", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"x.api.example.com": ["POST"]}}}, "a subdomain of a net host"),
        ("w-wild", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"*.example.com": ["POST"]}}}, "a wildcard write host"),
        ("w-get", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": ["GET"]}}}, "GET as a write method"),
        ("w-lower", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": ["post"]}}}, "a method in lowercase"),
        ("w-empty", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": []}}}, "no methods"),
        ("w-twice", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": ["POST", "POST"]}}}, "a method twice"),
        ("w-str", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": "POST"}}}, "methods as a string"),
        ("w-list", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": ["api.example.com"]}}, "netWrite as a list"),
        ("w-other", {"api": 4, "permissions": {"net": ["api.example.com"], "netWrite": {"api.example.com": ["CONNECT"]}}}, "a method that isn't a write")]:
    r = inspect_file(code_app("code-" + name, **over))
    check("refused: " + why, not r.get("ok") and "netWrite" in r.get("error", ""), r)

# api 4: signing in with a password, or both ways
srv = {"server": {"label": "S"}}
for name, sign, want in [("si-pw", "password", "password"), ("si-both", ["code", "password"], "code+password"),
                         ("si-both-rev", ["password", "code"], "code+password"), ("si-code-list", ["code"], "code"), ("si-code", "code", "code")]:
    r = inspect_file(code_app("code-" + name, api=4, permissions=dict(srv, signIn=sign)))
    check("signIn " + json.dumps(sign) + " is kept as " + want, r.get("ok") and r["manifest"]["permissions"]["signIn"] == want, r)
for name, over, why in [
        ("si-pw3", {"api": 3, "permissions": dict(srv, signIn="password")}, "a password at api 3"),
        ("si-list3", {"api": 3, "permissions": dict(srv, signIn=["code"])}, "the list form at api 3"),
        ("si-empty", {"api": 4, "permissions": dict(srv, signIn=[])}, "an empty list"),
        ("si-twice", {"api": 4, "permissions": dict(srv, signIn=["code", "code"])}, "a way twice"),
        ("si-other", {"api": 4, "permissions": dict(srv, signIn=["code", "fingerprint"])}, "a way it doesn't know"),
        ("si-noserver", {"api": 4, "permissions": {"signIn": "password"}}, "a password without a server"),
        ("si-bool", {"api": 4, "permissions": dict(srv, signIn=True)}, "true")]:
    r = inspect_file(code_app("code-" + name, **over))
    check("refused: " + why, not r.get("ok") and ("signIn" in r.get("error", "") or "signing in" in r.get("error", "")), r)

# api 4: the server chosen while signing in
r = inspect_file(code_app("code-fsi", api=4, permissions={"server": {"label": "S", "fromSignIn": True}, "signIn": "code"}))
check("server.fromSignIn kept", r.get("ok") and r["manifest"]["permissions"]["server"] == {"label": "S", "defaultPort": 0, "fromSignIn": True}, r)
r = inspect_file(code_app("code-fsi-off", api=4, permissions={"server": {"label": "S", "fromSignIn": False}, "signIn": "code"}))
check("fromSignIn false is left out", r.get("ok") and "fromSignIn" not in r["manifest"]["permissions"]["server"], r)
for name, over, why in [
        ("fsi3", {"api": 3, "permissions": {"server": {"label": "S", "fromSignIn": True}, "signIn": "code"}}, "fromSignIn at api 3"),
        ("fsi-nosign", {"api": 4, "permissions": {"server": {"label": "S", "fromSignIn": True}}}, "fromSignIn without a sign-in"),
        ("fsi-str", {"api": 4, "permissions": {"server": {"label": "S", "fromSignIn": "yes"}, "signIn": "code"}}, "fromSignIn that isn't true or false")]:
    r = inspect_file(code_app("code-" + name, **over))
    check("refused: " + why, not r.get("ok"), r)

# a guide that speaks only api 2 refuses an api 3 app at install, saying why
import importlib.util
from importlib.machinery import SourceFileLoader
_spec = importlib.util.spec_from_file_location("om_pg_apps", HELPER, loader=SourceFileLoader("om_pg_apps", HELPER))
older = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(older)
older.API = 2
try:
    older.check_manifest({"id": "tv.example.code", "name": "C", "version": "1.0.0", "api": 3, "kind": "app", "author": "E",
                          "main": "main.py", "permissions": {}}, {"main.py": 1, "app.json": 1})
    check("an older guide refuses an api 3 app", False)
except older.Bad as e:
    check("an older guide refuses an api 3 app", "needs a newer Uber TV" in str(e), str(e))

# the catalog offers launchers only
code_pkg = os.path.join(cat_dir, "packages", "code.tar.gz")
cp = run("pack", code_app("code-pack"), code_pkg)
write_catalog(1010, [dict(cp["catalogEntry"], package="packages/code.tar.gz")])
# its entry says its api, and its permissions as its app.json does (an api 2
# app can't name netWrite): a source's list can carry it as it is
check("pack's entry says the api and the permissions in app.json's words",
      cp.get("ok") and cp["catalogEntry"].get("api") == 2 and cp["catalogEntry"]["permissions"] == {"net": ["api.example.com"]}, cp)
crowded = code_app("code-crowded", extra={"data/" + str(i) + "/notes/about.txt": b"x" for i in range(140)})
for step in (["check", crowded], ["pack", crowded, os.path.join(work, "crowded.tar.gz")]):
    r = run(*step)
    check(step[0] + " refuses a package with more than 400 files and folders, as an install would",
          not r.get("ok") and "more than 400 files and folders" in json.dumps(r) and not os.path.exists(os.path.join(work, "crowded.tar.gz")), r)
c = run("catalog", cat_path, signers, 0, cache)
check("the catalog leaves out apps with code", c.get("ok") and c["catalog"]["apps"] == [] and c["catalog"]["skipped"] == 1, c)

# the same id from two sources: kept apart
for src in (FILE_SRC, "file:fedcba9876543210"):
    res = inspect_file(code_app("code-" + src[-4:]))
    r = run("install", res["staging"], apps_dir, data_dir, res["tree"], src)
    check("installs from " + src, r.get("ok") and r["sourceDir"] == sdir(src), r)
check("two sources, two places", all(os.path.isdir(os.path.join(apps_dir, sdir(s), "tv.example.code", "1.0.0")) for s in (FILE_SRC, "file:fedcba9876543210")))
run("remove", "tv.example.code", FILE_SRC, roots())
check("removing one leaves the other", not os.path.exists(os.path.join(apps_dir, sdir(FILE_SRC), "tv.example.code"))
      and os.path.isdir(os.path.join(apps_dir, sdir("file:fedcba9876543210"), "tv.example.code")))
check("its source's empty folder goes too", not os.path.exists(os.path.join(apps_dir, sdir(FILE_SRC))))
run("remove", "tv.example.code", "file:fedcba9876543210", roots())
check("a source that isn't one is refused", not run("install", "x", apps_dir, data_dir, "0" * 64, "catalog:other").get("ok"))

# bundled: from the plugin's own folder, traced back to it
plugin = os.path.join(work, "plugin")
bundled_app = os.path.join(plugin, "apps", "first-party", "tv.example.code")
shutil.copytree(code_app("code-bundled"), bundled_app)
b = run("bundled", plugin)
check("the plugin's apps are listed", b.get("ok") and b["apps"][0]["id"] == "tv.example.code" and b["apps"][0]["manifest"]["kind"] == "app", b)
res = run("inspect", json.dumps({"type": "bundled", "id": "tv.example.code", "plugin": plugin}), staging)
check("a bundled app inspects", res.get("ok") and res["source"] == "bundled", res)
r = run("install", res["staging"], apps_dir, data_dir, res["tree"], "bundled")
check("a bundled app installs", r.get("ok") and r["sourceDir"] == sdir("bundled"), r)
v = [a for a in run("verify", apps_dir, signers, plugin).get("apps", []) if a["sourceDir"] == sdir("bundled")]
check("it traces back to the plugin", v and v[0]["proof"] == "bundled" and not v[0]["problem"], v)
with open(os.path.join(bundled_app, "main.py"), "ab") as f:
    f.write(b"# 1.0.1\n")
v = [a for a in run("verify", apps_dir, signers, plugin).get("apps", []) if a["sourceDir"] == sdir("bundled")]
check("a plugin update that changes it shows", v and v[0]["proof"] == "bundledChanged", v)
res = run("inspect", json.dumps({"type": "bundled", "id": "tv.example.code", "plugin": plugin}), staging)
r = run("install", res["staging"], apps_dir, data_dir, res["tree"], "bundled")
v = [a for a in run("verify", apps_dir, signers, plugin).get("apps", []) if a["sourceDir"] == sdir("bundled")]
check("installed again, it traces back again", r.get("ok") and v and v[0]["proof"] == "bundled", v)
check("an app the plugin doesn't have", not run("inspect", json.dumps({"type": "bundled", "id": "tv.example.none", "plugin": plugin}), staging).get("ok"))
check("a bundled id that's a path", not run("inspect", json.dumps({"type": "bundled", "id": "../../x", "plugin": plugin}), staging).get("ok"))

# migration: the old id-only layout into (source, id), surviving an interruption
mig = os.path.join(work, "mig")
for app_id in ("tv.example.one", "tv.example.two", "tv.example.three"):
    os.makedirs(os.path.join(mig, app_id, "1.0.0"))
journal = os.path.join(work, "mig-journal", "migration.json")
legacy = [{"id": "tv.example.one", "from": "catalog"}, {"id": "tv.example.two", "from": "file"},
          {"id": "tv.example.three", "from": "catalog", "proof": "untrusted"}]
helper_src = open(HELPER).read()
broken = os.path.join(work, "broken-helper")
with open(broken, "w") as f:   # the same helper, dying after its first move
    f.write(helper_src.replace("                    rename_at(old, new, RENAME_NOREPLACE)\n",
                               "                    rename_at(old, new, RENAME_NOREPLACE)\n                    raise SystemExit('interrupted')\n"))
subprocess.run([sys.executable, broken, "migrate", mig, journal, json.dumps(legacy)], capture_output=True)
decided = json.load(open(journal))
moved_first = [a for a in decided if not os.path.exists(os.path.join(mig, a))]
check("an interrupted migration kept its decisions, and moved one", set(decided) == {"tv.example.one", "tv.example.two", "tv.example.three"}
      and len(moved_first) == 1, moved_first)
r = run("migrate", mig, journal, json.dumps(legacy))
check("a rerun finishes it, with the same decisions", r.get("ok") and json.load(open(journal)) == decided
      and all(r["moved"][a]["source"] == decided[a] for a in decided), r)
check("catalog apps stay catalog apps, proof or not", decided["tv.example.one"] == CAT_SRC and decided["tv.example.three"] == CAT_SRC)
check("a file app gets its own lineage", decided["tv.example.two"].startswith("file:") and len(decided["tv.example.two"]) == 21)
check("everything moved", all(os.path.isdir(os.path.join(mig, sdir(decided[a]), a, "1.0.0")) and not os.path.exists(os.path.join(mig, a)) for a in decided))
r = run("migrate", mig, journal, json.dumps(legacy))
check("a third run changes nothing", r.get("ok") and json.load(open(journal)) == decided)

# two moves at once (two guides): the second waits for the apps folder's
# lock before it even reads the journal, so it answers the very lineage the
# first chose, and that's where the app is. The first is paused just after
# its read, holding the lock; the second is seen waiting in /proc/locks
import fcntl
mig2 = os.path.join(work, "mig2")
os.makedirs(os.path.join(mig2, "tv.example.race", "1.0.0"))
journal2 = os.path.join(work, "mig2-journal", "m.json")
race = [{"id": "tv.example.race", "from": "file"}]
read_flag, go_flag = os.path.join(work, "mig2-read"), os.path.join(work, "mig2-go")
paused = os.path.join(work, "paused-helper")
hook = "        for item in legacy if isinstance(legacy, list) else []:\n"
with open(paused, "w") as f:   # the same helper, waiting after its journal read until told to go on
    f.write(helper_src.replace(hook, "        open(os.environ['MIG_READ'], 'w').close()\n        while not os.path.exists(os.environ['MIG_GO']):\n            time.sleep(0.01)\n" + hook, 1))
penv = dict(os.environ, MIG_READ=read_flag, MIG_GO=go_flag)
first = subprocess.Popen([sys.executable, paused, "migrate", mig2, journal2, json.dumps(race)], env=penv,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
for _ in range(6000):
    if os.path.exists(read_flag) or first.poll() is not None:
        break
    time.sleep(0.01)
second = subprocess.Popen([sys.executable, HELPER, "migrate", mig2, journal2, json.dumps(race)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
ino, waited = ":" + str(os.stat(mig2).st_ino), False
for _ in range(6000):
    with open("/proc/locks") as f:
        if any(len(r) > 6 and r[1] == "->" and r[2] == "FLOCK" and int(r[5]) == second.pid and r[6].endswith(ino) for r in (l.split() for l in f)):
            waited = True
            break
    if second.poll() is not None:
        break
    time.sleep(0.01)
untouched = not os.path.exists(journal2)   # (nothing written while the first holds the lock)
open(go_flag, "w").close()
answers = []
for p in (first, second):
    out, _ = p.communicate(timeout=60)
    try:
        answers.append(json.loads(out.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        answers.append({"ok": False, "error": out})
said = [a.get("moved", {}).get("tv.example.race", {}).get("source") for a in answers]
kept = json.load(open(journal2)).get("tv.example.race") if os.path.exists(journal2) else None
check("two moves at once: the second waits before reading, and both name where the app went",
      waited and untouched and all(a.get("ok") for a in answers) and said[0] == said[1] == kept and kept
      and os.path.isdir(os.path.join(mig2, sdir(kept), "tv.example.race", "1.0.0")), (waited, untouched, said, kept, answers))

# secrets: the value on stdin, never in argv; the file private
sec = os.path.join(work, "secrets", sdir(FILE_SRC), "tv.example.code.json")
p = subprocess.run([sys.executable, HELPER, "secret-set", sec, "apiKey"], input="hunter2-secret\n", capture_output=True, text=True)
check("a secret is kept", json.loads(p.stdout)["ok"] and json.load(open(sec))["user"]["apiKey"] == "hunter2-secret")
check("its file and folder are private", oct(os.stat(sec).st_mode & 0o777) == "0o600" and oct(os.stat(os.path.dirname(sec)).st_mode & 0o777) == "0o700")
check("a bad secret name is refused", not run("secret-set", sec, "../x").get("ok"))
run("secret-clear", sec, "apiKey")
check("a secret is cleared", json.load(open(sec))["user"] == {})
for k in ("a", "b", "c"):
    subprocess.run([sys.executable, HELPER, "secret-set", sec, k], input=k + "-value\n", capture_output=True, text=True)
check("several names clear in one write", run("secret-clear", sec, "a", "b").get("ok") and json.load(open(sec))["user"] == {"c": "c-value"})
check("a bad name among several clears none", not run("secret-clear", sec, "c", "../x").get("ok") and json.load(open(sec))["user"] == {"c": "c-value"})
# every change is made under a lock on the folder: a writer waits for the one before
import fcntl
lockfd = os.open(os.path.dirname(sec), os.O_RDONLY | os.O_DIRECTORY)
fcntl.flock(lockfd, fcntl.LOCK_EX)
waiting = subprocess.Popen([sys.executable, HELPER, "secret-clear", sec, "c"], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
time.sleep(0.6)
check("a second writer waits for the lock", waiting.poll() is None and json.load(open(sec))["user"] == {"c": "c-value"})
os.close(lockfd)
waiting.wait(10)
check("and then writes", waiting.returncode == 0 and json.load(open(sec))["user"] == {})

# forgetting, with no runtime: sign-out, a new server, clear its data
froots = {"store": os.path.join(work, "f-store"), "secrets": os.path.join(work, "f-secrets"), "images": os.path.join(work, "f-img")}
fsd = sdir("bundled")
os.makedirs(os.path.join(froots["store"], fsd))
os.makedirs(os.path.join(froots["images"], fsd, "tv.example.f"))
open(os.path.join(froots["images"], fsd, "tv.example.f", "pic"), "w").write("x")
with open(os.path.join(froots["store"], fsd, "tv.example.f.json"), "w") as f:
    json.dump({"v": 1, "keys": {"deviceId": {"v": "ZA==", "s": False}, "userId": {"v": "dQ==", "s": True}}}, f)
fsec = os.path.join(froots["secrets"], fsd, "tv.example.f.json")
os.makedirs(os.path.dirname(fsec))
with open(fsec, "w") as f:
    json.dump({"user": {"apiKey": "k"}, "signIn": {"server": "http://h", "values": {"token": "t"}}}, f)
r = run("forget", "signIn", "tv.example.f", "bundled", json.dumps(froots))
check("forget signIn works with no runtime", r.get("ok"), r)
kept = json.load(open(os.path.join(froots["store"], fsd, "tv.example.f.json")))["keys"]
check("sign-out forgets server-marked storage, keeps the rest", list(kept) == ["deviceId"], kept)
sec = json.load(open(fsec))
check("sign-out forgets the sign-in's secrets, keeps yours", sec["signIn"]["values"] == {} and sec["user"] == {"apiKey": "k"}, sec)
check("sign-out forgets its pictures", not os.path.exists(os.path.join(froots["images"], fsd, "tv.example.f")))
# its Activity (lib/appactivity.py): read as totals, kept through a sign-out, gone with its data
froots["activity"] = os.path.join(work, "f-activity")
fact = os.path.join(froots["activity"], fsd, "tv.example.f.json")
os.makedirs(os.path.dirname(fact))
day = time.strftime("%Y-%m-%d")
with open(fact, "w") as f:
    json.dump({"v": 1, "sites": [["api.example.com", 0]], "days": {day: {"a": {"0": {"fw": [2, 100, 50, 2, 0, 0, 0, 0, 60], "f": [3, 0, 900, 3, 0, 0, 0, 0, 30]}},
                                                                          "x": {"origin": 4}, "nn": 1}},
               "names": {"tracker.example": {"d": {day: [4, 0]}, "l": int(time.time())}}}, f)
r = run("activity", "tv.example.f", "bundled", json.dumps(froots))
site = (r.get("sites") or [{}])[0]
check("activity reads the totals for the guide", r.get("ok") and site.get("site") == "api.example.com" and site.get("reads") == 3
      and site.get("writes") == 2 and site.get("received") == 950 and r["refused"][0]["site"] == "tracker.example" and r["refusedMore"] == 0, r)
r = run("forget", "signIn", "tv.example.f", "bundled", json.dumps(froots))
check("a sign-out keeps its Activity", r.get("ok") and os.path.exists(fact), r)
with open(fact, "w") as f:
    f.write("{not json")
r = run("activity", "tv.example.f", "bundled", json.dumps(froots))
check("an unreadable Activity reads as nothing, not an error", r.get("ok") and r["sites"] == [] and r["refused"] == [], r)
check("activity refuses an id that's a path", not run("activity", "../x", "bundled", json.dumps(froots)).get("ok"))
check("activity refuses a made-up source", not run("activity", "tv.example.f", "file:../../x", json.dumps(froots)).get("ok"))
r = run("activity", "tv.example.nothing", "bundled", json.dumps(froots))
check("an app with no Activity yet has none", r.get("ok") and r["sites"] == [] and r["refusedMore"] == 0, r)
r = run("forget", "data", "tv.example.f", "bundled", json.dumps(froots))
check("clear its data removes its storage", r.get("ok") and not os.path.exists(os.path.join(froots["store"], fsd, "tv.example.f.json")), r)
check("and its Activity", not os.path.exists(fact))
os.makedirs(os.path.dirname(fact), exist_ok=True)
open(fact, "w").write("{}")
r = run("remove", "tv.example.f", "bundled", json.dumps(froots))
check("removing an app removes its Activity", r.get("ok") and not os.path.exists(fact), r)
check("forget refuses an id that's a path", not run("forget", "data", "../x", "bundled", json.dumps(froots)).get("ok"))

# ---- the guide's own private files (milestone 3): read and confirmed write --
import importlib.machinery
import importlib.util
_loader = importlib.machinery.SourceFileLoader("om_pg_apps", HELPER)
_spec = importlib.util.spec_from_loader("om_pg_apps", _loader)
appsmod = importlib.util.module_from_spec(_spec)
_loader.exec_module(appsmod)

pdir = os.path.join(work, "private")
ppath = os.path.join(pdir, "app-screens.json")
r = run("private-read", ppath)
check("private-read: no file yet is empty, not an error", r.get("ok") and r.get("missing") and r["text"] == "", r)
w = subprocess.run([sys.executable, HELPER, "private-write", ppath], input=b'{"v":1}', capture_output=True)
r = json.loads(w.stdout.decode().strip().splitlines()[-1])
check("private-write: saved", r.get("outcome") == "saved", r)
check("made 0600 in a 0700 folder", (os.stat(ppath).st_mode & 0o777, os.stat(pdir).st_mode & 0o777) == (0o600, 0o700))
check("and read back whole", run("private-read", ppath) == {"ok": True, "text": '{"v":1}'})
check("only its own names", not run("private-read", os.path.join(pdir, "secrets.json")).get("ok") and not run("private-read", "relative/app-screens.json").get("ok"))
os.symlink(ppath, os.path.join(pdir, "settings.json"))
r = run("private-read", os.path.join(pdir, "settings.json"))
check("a link isn't followed", not r.get("ok") and r.get("code") == "unreadable", r)
os.unlink(os.path.join(pdir, "settings.json"))
os.mkfifo(os.path.join(pdir, "settings.json"))
r = run("private-read", os.path.join(pdir, "settings.json"))
check("a pipe isn't waited on", not r.get("ok") and r.get("code") == "notfile", r)
os.unlink(os.path.join(pdir, "settings.json"))
with open(ppath, "wb") as f:
    f.write(b"x" * (64 * 1024 + 1))
r = run("private-read", ppath)
check("over its cap: refused, not cut", not r.get("ok") and r.get("code") == "toobig", r)
with open(os.path.join(pdir, "settings.json"), "wb") as f:
    f.write(b"x" * (1024 * 1024))
check("settings.json's cap is 1 MiB", run("private-read", os.path.join(pdir, "settings.json")).get("ok"))
w = subprocess.run([sys.executable, HELPER, "private-write", ppath], input=b"y" * (64 * 1024 + 1), capture_output=True)
check("a write over the cap fails, nothing changed", json.loads(w.stdout.decode().strip().splitlines()[-1]).get("outcome") == "failed"
      and os.path.getsize(ppath) == 64 * 1024 + 1)


class StepFS:
    """os, with each step of a confirmed write recorded and one made to fail"""
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []
        self.dirfd = set()

    def makedirs(self, *a, **k):
        return os.makedirs(*a, **k)

    def open(self, path, flags, mode=0o777):
        step = "dir" if flags & os.O_DIRECTORY else "create" if flags & os.O_CREAT else "reopen"
        self.calls.append(step)
        if self.fail == step:
            raise OSError("injected: " + step)
        fd = os.open(path, flags, mode)
        if flags & os.O_DIRECTORY:
            self.dirfd.add(fd)
        return fd

    def fsync(self, fd):
        step = "dirsync" if fd in self.dirfd else "sync"
        self.calls.append(step)
        if self.fail == step:
            raise OSError("injected: " + step)
        return os.fsync(fd)

    def replace(self, a, b):
        self.calls.append("rename")
        if self.fail == "rename":
            raise OSError("injected: rename")
        return os.replace(a, b)


def confirmed(fail, old=b'{"old":1}', new=b'{"new":2}'):
    d = tempfile.mkdtemp(dir=work)
    path = os.path.join(d, "app-screens.json")
    with open(path, "wb") as f:
        f.write(old)
    fs = StepFS(fail)
    appsmod._fs = fs
    try:
        res = appsmod.do_private_write(path, new)
    finally:
        appsmod._fs = os
    return res, fs.calls, open(path, "rb").read(), sorted(os.listdir(d))


res, calls, now, left = confirmed(None)
check("the steps in order: the new name made, synced, read back, renamed, the folder synced",
      calls == ["create", "sync", "reopen", "rename", "dir", "dirsync"], calls)
check("saved only after all of them", res == {"ok": True, "outcome": "saved"} and now == b'{"new":2}' and left == ["app-screens.json"], (res, left))
for step in ["create", "sync", "reopen", "rename"]:
    res, calls, now, left = confirmed(step)
    check("a failure at " + step + ": failed, the old file whole, nothing left behind",
          res.get("outcome") == "failed" and now == b'{"old":1}' and left == ["app-screens.json"], (res, now, left))
    check("and said in the guide's words, not the error's", "injected" not in json.dumps(res), res)
res, calls, now, left = confirmed("dirsync")
check("only the folder sync failed: unconfirmed, the new file in place", res.get("outcome") == "unconfirmed" and now == b'{"new":2}', res)
# a power cut then keeps the rename or loses it: either file is whole (the new
# one was synced before the rename, the old one never touched)
check("after a power cut, either is whole", json.loads(now) == {"new": 2} and json.loads(b'{"old":1}') == {"old": 1})
res, calls, now, left = confirmed(None, new=b'{"same":"bytes"}')
check("what's read back is what was written", now == b'{"same":"bytes"}')


class Liar(StepFS):
    """The disk hands back other bytes than it was given"""
    def open(self, path, flags, mode=0o777):
        fd = super().open(path, flags, mode)
        if not flags & (os.O_CREAT | os.O_DIRECTORY):
            with open(path, "ab") as f:
                f.write(b"!")
        return fd


d = tempfile.mkdtemp(dir=work)
lpath = os.path.join(d, "app-screens.json")
with open(lpath, "wb") as f:
    f.write(b'{"old":1}')
appsmod._fs = Liar()
try:
    res = appsmod.do_private_write(lpath, b'{"new":2}')
finally:
    appsmod._fs = os
check("a read-back that differs: failed, the old file kept", res.get("outcome") == "failed" and open(lpath, "rb").read() == b'{"old":1}' and os.listdir(d) == ["app-screens.json"], res)

wipe(work)
print("\n" + ("all passed" if not failures else str(failures) + " failed"))
sys.exit(1 if failures else 0)
