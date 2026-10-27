import base64
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).parents[1] / "scripts/publish.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class SigningKeyTests(unittest.TestCase):
    def encoded(self, private=False):
        size = 104 if private else 42
        return base64.b64encode(b"Ed" + bytes(size - 2)).decode()

    def test_full_signify_file(self):
        key = "untrusted comment: original comment\n" + self.encoded() + "\n"
        normalized = publisher.normalize_key(key, "UPDATE_PUBLIC_KEY")
        self.assertEqual(normalized.splitlines()[1], self.encoded())

    def test_headerless_key_gets_comment(self):
        normalized = publisher.normalize_key(self.encoded(True), "UPDATE_SIGNING_KEY")
        self.assertTrue(normalized.startswith("untrusted comment: "))

    def test_escaped_newlines_and_crlf(self):
        for separator in ("\\n", "\r\n", "\\r\\n"):
            key = separator.join(("untrusted comment: key", self.encoded()))
            self.assertEqual(len(publisher.normalize_key(key, "UPDATE_PUBLIC_KEY").splitlines()), 2)

    def test_filenames_ssh_keys_and_wrong_key_types_rejected_without_echo(self):
        for key in ("update.sec", "$(cat update.sec)", "ssh-ed25519 AAAATEST", self.encoded()):
            with self.subTest(key=key), self.assertRaises(ValueError) as raised:
                publisher.normalize_key(key, "UPDATE_SIGNING_KEY")
            self.assertNotIn(key, str(raised.exception))

    def test_encrypted_key_rejected(self):
        decoded = bytearray(base64.b64decode(self.encoded(True)))
        decoded[4:8] = (42).to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "no passphrase"):
            publisher.normalize_key(base64.b64encode(decoded).decode(), "UPDATE_SIGNING_KEY")

    def test_pair_is_verified_before_returning(self):
        with patch.object(publisher.shutil, "which", return_value="signify"):
            with patch.object(publisher.subprocess, "run") as run:
                publisher.check_signing_keys(self.encoded(), self.encoded(True))
        self.assertEqual(run.call_count, 2)
        self.assertIn("-S", run.call_args_list[0].args[0])
        self.assertIn("-V", run.call_args_list[1].args[0])

    def test_mismatched_pair_rejected(self):
        with patch.object(publisher.shutil, "which", return_value="signify"):
            with patch.object(publisher.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "signify")):
                with self.assertRaisesRegex(ValueError, "same signify"):
                    publisher.check_signing_keys(self.encoded(), self.encoded(True))

    def test_bad_secret_prevents_any_release_api_call(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "test",
               "UPDATE_PUBLIC_KEY": self.encoded(), "UPDATE_SIGNING_KEY": "update.sec"}
        with patch.dict(os.environ, env), patch.object(publisher, "api") as api:
            with self.assertRaises(ValueError):
                publisher.main()
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
