import hashlib
import base64
import importlib.util
import io
import json
from pathlib import Path
import platform
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

spec = importlib.util.spec_from_file_location("updater", Path(__file__).parents[1] / "scripts/update.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
PUBLIC_KEY = b"untrusted comment: test key\n" + base64.b64encode(b"Ed" + bytes(40)) + b"\n"


class UpdateTests(unittest.TestCase):
    def metadata(self):
        return {"os": "OpenBSD", "os_release": platform.release(), "arch": platform.machine(),
                "version": "140.0-qt6.11-r2.1", "chromium": "140.0", "qt": "6.11",
                "sequence": 2001, "qt_package": "qt6-qtwebengine-6.11p1", "sha256": "0" * 64}

    def make_archive(self, contents=None):
        contents = contents or {name: (json.dumps(self.metadata()).encode() if name == "release.json"
                                      else PUBLIC_KEY if name == "update.pub" else b"payload")
                               for name in updater.FILES}
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            for name, data in contents.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_newer_matching_platform(self):
        updater.validate_manifest(self.metadata(), {"sequence": 1001})

    def test_replay_and_downgrade_rejected(self):
        for sequence in (2001, 3001):
            with self.assertRaises(ValueError):
                updater.validate_manifest(self.metadata(), {"sequence": sequence})

    def test_other_platform_and_unsafe_versions_rejected(self):
        for field, value in (("os", "Linux"), ("os_release", "invalid"), ("arch", "invalid"),
                             ("version", "../../payload"), ("sha256", "invalid"),
                             ("version", "139.0-qt6.11-r2.1"), ("sequence", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                updater.validate_manifest({**self.metadata(), field: value}, {"sequence": 1})

    def test_cross_origin_redirect_strips_credentials(self):
        request = urllib.request.Request("https://api.github.com/asset", headers={"Authorization": "Bearer secret"})
        redirect = updater.SafeRedirect().redirect_request(request, None, 302, "", {},
                                                           "https://release-assets.githubusercontent.com/a")
        self.assertIsNone(redirect.get_header("Authorization"))

    def test_plain_http_redirect_rejected(self):
        request = urllib.request.Request("https://api.github.com/asset")
        with self.assertRaises(ValueError):
            updater.SafeRedirect().redirect_request(request, None, 302, "", {}, "http://example.com")

    def test_fetch_rejects_arbitrary_hosts(self):
        for url in ("https://evil.test/a", "http://api.github.com/a", "https://api.github.com.evil.test/a"):
            with self.assertRaises(ValueError):
                updater.fetch(url)

    def test_public_download_has_no_authorization_header(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(updater.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(updater.fetch("https://api.github.com/repos/owner/repo"), b'{}')
        request = opener.open.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))

    def test_path_traversal_and_extra_files_rejected(self):
        for name in ("../../escape", "/tmp/escape", "unexpected.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "archive.tgz"
                archive.write_bytes(self.make_archive({name: b"evil"}))
                with self.assertRaises(ValueError):
                    updater.unpack(archive, Path(tmp) / "output")

    def test_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive.tgz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in updater.FILES:
                    member = tarfile.TarInfo(name)
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc/passwd"
                    tar.addfile(member)
            with self.assertRaises(ValueError):
                updater.unpack(archive, Path(tmp) / "output")

    def test_install_checks_digest_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                updater.install(b"corrupt", self.metadata(), root, root / "key")
            self.assertFalse((root / "versions").exists())

    def test_verified_install_activates_release_and_preserves_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "versions/old"
            old.mkdir(parents=True)
            (root / "current").symlink_to("versions/old")
            key = root / "key.pub"
            key.write_bytes(PUBLIC_KEY.replace(b"test key", b"different comment"))
            data = self.make_archive()
            manifest = {**self.metadata(), "sha256": hashlib.sha256(data).hexdigest()}
            updater.install(data, manifest, root, key)
            self.assertEqual((root / "current").resolve().name, manifest["version"])
            self.assertTrue(old.exists())
            self.assertEqual((root / "current/update-config.json").stat().st_mode & 0o777, 0o600)

    def test_metadata_mismatch_keeps_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "versions/old"
            old.mkdir(parents=True)
            (root / "current").symlink_to("versions/old")
            data = self.make_archive()
            manifest = {**self.metadata(), "version": "140.0-qt6.11-r3.1",
                        "sha256": hashlib.sha256(data).hexdigest()}
            with self.assertRaises(ValueError):
                updater.install(data, manifest, root, root / "key.pub")
            self.assertEqual((root / "current").resolve(), old)
            self.assertFalse(list((root / "versions").glob(".stage-*")))

    def test_signature_failure_prevents_asset_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "versions/old"
            current.mkdir(parents=True)
            (root / "current").symlink_to("versions/old")
            (current / "release.json").write_text(json.dumps(self.metadata()))
            (current / "update-config.json").write_text(json.dumps({"repository": "owner/releases"}))
            release = {"assets": [{"name": name, "url": "https://api.github.com/" + name}
                                  for name in ("manifest.json", "manifest.json.sig")]}
            responses = [json.dumps(release).encode(), b"manifest", b"invalid signature"]
            with patch.object(updater, "fetch", side_effect=responses) as fetch:
                with patch.object(updater.subprocess, "run", side_effect=RuntimeError("bad signature")):
                    with self.assertRaises(RuntimeError):
                        updater.check(root, force=True)
                self.assertEqual(fetch.call_count, 3)
            self.assertEqual((root / "current").resolve(), current)


if __name__ == "__main__":
    unittest.main()
