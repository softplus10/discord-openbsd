#!/usr/bin/env python3
"""Bootstrap from downloaded release assets and a separately trusted public key."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import update

parser = argparse.ArgumentParser()
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--signature", type=Path, required=True)
parser.add_argument("--public-key", type=Path, required=True)
parser.add_argument("--root", type=Path, default=Path.home() / ".local/share/discord-openbsd")
args = parser.parse_args()
root = args.root.expanduser().resolve()
os.umask(0o077)
root.mkdir(parents=True, exist_ok=True, mode=0o700)
if (root / "current").exists():
    parser.error("Already installed; use current/update.py --root ROOT --force")
subprocess.run(["signify", "-V", "-p", str(args.public_key), "-m", str(args.manifest),
                "-x", str(args.signature)], check=True)
manifest = json.loads(args.manifest.read_text())
update.validate_manifest(manifest, {"sequence": -1})
package = subprocess.check_output(["pkg_info", "-e", "qt6-qtwebengine-*"], text=True).strip()
if package != manifest["qt_package"]:
    parser.error("Install required engine first: " + manifest["qt_package"])
if args.archive.stat().st_size > update.MAX_ARCHIVE:
    parser.error("Archive exceeds size limit")
update.install(args.archive.read_bytes(), manifest, root, args.public_key)
launcher = Path.home() / ".local/bin/discord-openbsd"
launcher.parent.mkdir(parents=True, exist_ok=True)
if launcher.exists():
    parser.error("Launcher path exists; installed payload retained at " + str(root))
launcher.write_text(f"#!{sys.executable}\nimport os\nos.execv({sys.executable!r}, "
                    f"[{sys.executable!r}, {str(root / 'current/launch.py')!r}, {str(root)!r}])\n")
launcher.chmod(0o700)
print("Installed: " + str(launcher))
