"""Offline acceptance invariants; no GitHub access or bundle execution."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from release_acceptance_check import checksum_rows, get, validate
from release_publish import manifest


def fixture(tag="v0.3.0-rc.1"):
    names = manifest(tag)
    bundles = [n for n in names if n != "SHA256SUMS" and not n.endswith(".sha256")]
    payloads = {n: ("fixture " + n).encode() for n in bundles}
    checksums = {n + ".sha256": (hashlib.sha256(b).hexdigest() + "  " + n + "\n").encode()
                 for n, b in payloads.items()}
    checksums["SHA256SUMS"] = b"".join(checksums.values())
    payloads.update(checksums)
    release = {"id": 123, "tag_name": tag, "draft": False, "prerelease": "-rc." in tag,
               "assets": [{"name": n, "size": len(b), "digest": "sha256:" + hashlib.sha256(b).hexdigest()}
                          for n, b in payloads.items()]}
    latest = {"id": 122, "tag_name": "v0.0.4", "draft": False, "prerelease": False}
    return release, latest, checksums


class AcceptanceTests(unittest.TestCase):
    def check(self, release, latest, checksums):
        return validate(release, latest, "v0.3.0-rc.1", "v0.0.4", checksums)["pass"]

    def test_rc(self):
        self.assertTrue(self.check(*fixture()))

    def test_stable(self):
        release, _, checksums = fixture("v0.3.0")
        self.assertTrue(validate(release, release, "v0.3.0", "v0.3.0", checksums)["pass"])

    def test_release_identity(self):
        for field, value in (("draft", True), ("tag_name", "untagged-example"), ("prerelease", False)):
            with self.subTest(field=field):
                release, latest, checksums = fixture()
                release[field] = value
                self.assertFalse(self.check(release, latest, checksums))

    def test_latest(self):
        release, latest, checksums = fixture()
        latest["id"] = release["id"]
        self.assertFalse(self.check(release, latest, checksums))
        latest["tag_name"] = "v0.3.0"
        self.assertFalse(self.check(release, latest, checksums))

    def test_manifest(self):
        for mutation in (lambda a: a.pop(), lambda a: a.append(copy.deepcopy(a[0])),
                         lambda a: a[0].update(name="unexpected")):
            release, latest, checksums = fixture()
            mutation(release["assets"])
            self.assertFalse(self.check(release, latest, checksums))

    def test_asset_metadata(self):
        for field, value in (("size", 0), ("digest", None), ("digest", "sha256:" + "0" * 64)):
            release, latest, checksums = fixture()
            release["assets"][0][field] = value
            self.assertFalse(self.check(release, latest, checksums))

    def test_checksum_tampering(self):
        release, latest, checksums = fixture()
        checksums["SHA256SUMS"] += b"bad\n"
        self.assertFalse(self.check(release, latest, checksums))

    def test_missing_sidecar(self):
        release, latest, checksums = fixture()
        checksums.pop(next(iter(checksums)))
        self.assertFalse(self.check(release, latest, checksums))

    def test_duplicate_checksum(self):
        row = ("a" * 64 + "  name\n").encode()
        with self.assertRaises(ValueError):
            checksum_rows(row + row)

    def test_get_is_explicitly_read_only(self):
        with patch("release_acceptance_check.subprocess.run") as run:
            run.return_value.stdout = b"checksum"
            self.assertEqual(get("repos/example/project/releases/assets/1", True), b"checksum")
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["gh", "api", "--method", "GET",
                                      "repos/example/project/releases/assets/1",
                                      "-H", "Accept: application/octet-stream"])
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["timeout"], 45)


if __name__ == "__main__":
    unittest.main()
