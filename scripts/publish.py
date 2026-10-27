#!/usr/bin/env python3
"""Run only on the trusted default branch, after the native OpenBSD tests."""
import hashlib
import base64
import binascii
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request


def normalize_key(value, name):
    """Accept signify file contents, including common secret-paste variants."""
    text = value.strip().lstrip("\ufeff").replace("\\r\\n", "\n").replace("\\n", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    comment = "untrusted comment: discord-openbsd update key"
    if lines and lines[0].startswith("untrusted comment: "):
        comment, lines = lines[0], lines[1:]
    if len(lines) != 1:
        raise ValueError(name + ": expected signify key file CONTENTS (not its filename or an SSH key)")
    try:
        decoded = base64.b64decode(lines[0], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError(name + ": invalid signify key encoding; register the complete file contents") from None
    size = 104 if name == "UPDATE_SIGNING_KEY" else 42
    if len(decoded) != size or decoded[:2] != b"Ed":
        raise ValueError(name + ": expected a signify Ed25519 key; register the complete correct file")
    if name == "UPDATE_SIGNING_KEY" and int.from_bytes(decoded[4:8], "big") != 0:
        raise ValueError(name + ": CI requires a key generated with signify -G -n (no passphrase)")
    return comment + "\n" + lines[0] + "\n"


def check_signing_keys(public, private):
    public = normalize_key(public, "UPDATE_PUBLIC_KEY")
    private = normalize_key(private, "UPDATE_SIGNING_KEY")
    signer = shutil.which("signify-openbsd") or shutil.which("signify")
    if not signer:
        raise ValueError("Install signify-openbsd or signify before publishing")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        pub, sec = directory / "update.pub", directory / "update.sec"
        message, signature = directory / "probe", directory / "probe.sig"
        pub.write_text(public)
        sec.write_text(private)
        sec.chmod(0o600)
        message.write_bytes(b"discord-openbsd signing key preflight\n")
        try:
            for args in (("-S", "-s", str(sec)), ("-V", "-p", str(pub))):
                subprocess.run([signer, *args, "-m", str(message), "-x", str(signature)],
                               check=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise ValueError("UPDATE_SIGNING_KEY and UPDATE_PUBLIC_KEY could not sign/verify together; "
                             "register both complete files from the same signify -G -n invocation") from None
    return public, private


def api(path, token, method="GET", data=None, binary=False):
    url = "https://api.github.com" + path
    if path.startswith("https://uploads.github.com/"):
        url = path
    body = data if binary else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + token, "User-Agent": "discord-openbsd-release",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/octet-stream" if binary else "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = response.read()
        return json.loads(result) if result else None


def release(repo, tag, token):
    try:
        return api(f"/repos/{repo}/releases/tags/{tag}", token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    return None


def upload(repo, rel, file, token):
    for asset in rel.get("assets", []):
        if asset["name"] == file.name:
            api(f'/repos/{repo}/releases/assets/{asset["id"]}', token, "DELETE")
    url = rel["upload_url"].split("{")[0] + "?name=" + urllib.parse.quote(file.name)
    return api(url, token, "POST", file.read_bytes(), binary=True)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid distribution repository")
    writer = os.environ["GITHUB_TOKEN"]
    public, private = os.environ["UPDATE_PUBLIC_KEY"], os.environ["UPDATE_SIGNING_KEY"]
    if not all((writer, public, private)):
        raise ValueError("Release credentials and signing keys must be configured")
    # Check formatting and the actual key pair before creating any draft/assets.
    public, private = check_signing_keys(public, private)
    if api(f"/repos/{repo}", writer)["private"]:
        raise ValueError("Make this repository public before publishing token-free updates")
    metadata = json.loads(Path("out/release.json").read_text())
    fingerprint = hashlib.sha256(json.dumps({
        k: metadata[k] for k in ("chromium", "qt", "qt_package", "os_release", "arch", "commit")
    }, sort_keys=True).encode() + os.environ.get("UPDATE_KEY_REVISION", "1").encode()).hexdigest()
    channel = f'openbsd-{metadata["os_release"]}-{metadata["arch"]}'
    stable = release(repo, channel, writer)
    if stable and stable.get("body") == fingerprint:
        print("Browser package, wrapper source, and signing revision unchanged; no release needed.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        payload = temp / "payload"
        (payload / "bin").mkdir(parents=True)
        shutil.copyfile("out/discord-openbsd", payload / "bin/discord-openbsd")
        (payload / "bin/discord-openbsd").chmod(0o755)
        for name in ("update.py", "launch.py"):
            shutil.copyfile(Path("scripts") / name, payload / name)
        shutil.copyfile("out/release.json", payload / "release.json")
        (payload / "update-config.json").write_text(json.dumps({"repository": repo}))
        (payload / "update-config.json").chmod(0o600)
        (payload / "update.pub").write_text(public.rstrip() + "\n")
        # Verify the signing pair without disclosing either key to logs/artifacts.
        secret = temp / "update.sec"
        secret.write_text(private.rstrip() + "\n")
        secret.chmod(0o600)
        archive = temp / "discord-openbsd.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for file in sorted(payload.rglob("*")):
                if file.is_file():
                    tar.add(file, arcname=str(file.relative_to(payload)), recursive=False)
        tag = channel + "-" + metadata["version"]
        rel = release(repo, tag, writer)
        if rel:
            raise ValueError("Immutable release already exists; rerun with a new attempt")
        rel = api(f"/repos/{repo}/releases", writer, "POST", {
            "tag_name": tag, "name": tag, "draft": True,
            "target_commitish": metadata["commit"], "make_latest": "true",
            "body": "Qt WebEngine package: " + metadata["qt_package"]})
        asset = upload(repo, rel, archive, writer)
        manifest = {**metadata, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "asset_id": asset["id"], "fingerprint": fingerprint}
        manifest_file = temp / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        signer = shutil.which("signify-openbsd") or shutil.which("signify")
        signature = temp / "manifest.json.sig"
        subprocess.run([signer, "-S", "-s", str(secret), "-m", str(manifest_file),
                        "-x", str(signature)], check=True, stdin=subprocess.DEVNULL)
        subprocess.run([signer, "-V", "-p", str(payload / "update.pub"),
                        "-m", str(manifest_file), "-x", str(signature)], check=True)
        for file in (manifest_file, signature):
            upload(repo, rel, file, writer)
        api(f'/repos/{repo}/releases/{rel["id"]}', writer, "PATCH", {"draft": False})
        if not stable:
            stable = api(f"/repos/{repo}/releases", writer, "POST", {
                "tag_name": channel, "name": channel, "body": "", "draft": False,
                "make_latest": "false", "target_commitish": metadata["commit"]})
        # Readers reject a transient mismatched pair and retry on the next launch.
        for file in (manifest_file, signature):
            upload(repo, stable, file, writer)
        api(f'/repos/{repo}/releases/{stable["id"]}', writer, "PATCH", {"body": fingerprint})
        print("Published " + tag)


if __name__ == "__main__":
    main()
