#!/usr/bin/env python3
"""Public release downloader. Trust is rooted in the installed signify key."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

API = "https://api.github.com"
MAX_ARCHIVE = 100 * 1024 * 1024
FILES = {"bin/discord-openbsd", "update.py", "launch.py", "release.json",
         "update-config.json", "update.pub"}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https":
            raise ValueError("Non-HTTPS download redirect")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        # A release asset redirects to signed object storage. Never forward PATs.
        if parsed.netloc != urllib.parse.urlsplit(request.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def fetch(url, limit=1024 * 1024, binary=False):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.username:
        raise ValueError("Only HTTPS GitHub API URLs are accepted")
    request = urllib.request.Request(url, headers={
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "discord-openbsd-updater"})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Update download exceeds size limit")
    return data


def validate_manifest(manifest, current):
    if manifest["os"] != "OpenBSD" or manifest["os_release"] != platform.release():
        raise ValueError("This update requires a different OpenBSD release")
    if manifest["arch"] != platform.machine():
        raise ValueError("This update requires a different architecture")
    if not re.fullmatch(r"[A-Za-z0-9.+_-]{1,120}", manifest["version"]):
        raise ValueError("Unsafe release version")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest["sha256"]):
        raise ValueError("Invalid archive digest")
    if type(manifest["sequence"]) is not int or manifest["sequence"] <= current["sequence"]:
        raise ValueError("Update is not newer than installed release")
    if not manifest["version"].startswith(manifest["chromium"] + "-qt"):
        raise ValueError("Wrapper/browser version mismatch")


def unpack(archive, target):
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        if set(names) != FILES or len(names) != len(FILES):
            raise ValueError("Unexpected archive contents")
        if any(not m.isfile() or m.size > MAX_ARCHIVE for m in members):
            raise ValueError("Unsafe archive entry")
        if sum(m.size for m in members) > MAX_ARCHIVE:
            raise ValueError("Unpacked archive exceeds size limit")
        for member in members:
            dest = target / member.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, dest.open("wb") as output:
                shutil.copyfileobj(source, output)
            dest.chmod(0o700 if member.name == "bin/discord-openbsd" else 0o600)


def install(download, manifest, root, public_key):
    if hashlib.sha256(download).hexdigest() != manifest["sha256"]:
        raise ValueError("Update checksum mismatch")
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    final = versions / manifest["version"]
    # Existing releases are immutable; never overwrite a running binary.
    if final.exists():
        raise ValueError("Release directory already exists")
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=versions))
    try:
        archive = stage / "download.tgz"
        archive.write_bytes(download)
        unpack(archive, stage)
        archive.unlink()
        embedded = json.loads((stage / "release.json").read_text())
        for field in ("version", "sequence", "os", "os_release", "arch", "chromium", "qt", "qt_package"):
            if embedded[field] != manifest[field]:
                raise ValueError("Archive metadata differs from signed manifest")
        if (stage / "update.pub").read_bytes() != public_key.read_bytes():
            raise ValueError("Signing key rotation requires a separate trust migration")
        # Keep the existing trusted signing key across updates.
        stage.rename(final)
        link = root / ".current-next"
        link.unlink(missing_ok=True)
        link.symlink_to(Path("versions") / manifest["version"])
        link.replace(root / "current")
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def check(root, force=False):
    current_dir = (root / "current").resolve(strict=True)
    config = json.loads((current_dir / "update-config.json").read_text())
    current = json.loads((current_dir / "release.json").read_text())
    repo = config["repository"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid update repository")
    checked = root / ".last-check"
    if not force and checked.exists() and time.time() - checked.stat().st_mtime < 86400:
        return
    channel = "openbsd-" + current["os_release"] + "-" + current["arch"]
    # Each OS/arch has an atomic, signed channel manifest in a stable release.
    release = json.loads(fetch(f"{API}/repos/{repo}/releases/tags/{channel}"))
    assets = {a["name"]: a["url"] for a in release["assets"]}
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        directory = Path(tmp)
        for name in ("manifest.json", "manifest.json.sig"):
            (directory / name).write_bytes(fetch(assets[name], binary=True))
        subprocess.run(["signify", "-V", "-p", str(current_dir / "update.pub"),
                        "-m", str(directory / "manifest.json"),
                        "-x", str(directory / "manifest.json.sig")], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["sequence"] <= current["sequence"]:
            checked.touch()
            return
        validate_manifest(manifest, current)
        installed_package = subprocess.check_output(
            ["pkg_info", "-e", "qt6-qtwebengine-*"], text=True).strip()
        if installed_package != manifest["qt_package"]:
            raise ValueError("Update OpenBSD engine packages before installing this release")
        # The authenticated manifest binds an immutable GitHub asset ID.
        asset_id = manifest["asset_id"]
        if type(asset_id) is not int or asset_id <= 0:
            raise ValueError("Invalid asset ID")
        data = fetch(f"{API}/repos/{repo}/releases/assets/{asset_id}",
                     limit=MAX_ARCHIVE, binary=True)
        install(data, manifest, root, current_dir / "update.pub")
    checked.touch()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / ".update-lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            check(args.root, args.force)
        except Exception as error:
            # Do not log request headers, embedded credentials, or signed URLs.
            print("Update unavailable (" + type(error).__name__ + "); installed version retained.")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
