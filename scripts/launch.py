#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

# Stable launcher: --root works for local and system-wide bootstrap installs.
root = Path(sys.argv[1]).expanduser().resolve()
current = (root / "current").resolve(strict=True)
info = json.loads((current / "release.json").read_text())
# Never start a wrapper against an older or ABI-incompatible engine package.
package = subprocess.check_output(["pkg_info", "-e", "qt6-qtwebengine-*"], text=True).strip()
if package != info["qt_package"]:
    subprocess.run([sys.executable, str(current / "update.py"), "--root", str(root), "--force"])
    current = (root / "current").resolve(strict=True)
    info = json.loads((current / "release.json").read_text())
if package != info["qt_package"]:
    print("Required engine: " + info["qt_package"] + "; installed: " + package, file=sys.stderr)
    print("Update the OpenBSD packages with doas pkg_add -u before launching.", file=sys.stderr)
    raise SystemExit(1)
with (root / "update.log").open("a") as log:
    subprocess.Popen([sys.executable, str(current / "update.py"), "--root", str(root)],
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
os.execv(str(current / "bin/discord-openbsd"), ["discord-openbsd"])
