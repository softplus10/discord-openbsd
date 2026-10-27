#!/usr/bin/env python3
import json
import os
from pathlib import Path
import platform
import subprocess

engine = json.loads(Path("out/engine.json").read_text())
run = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
metadata = {
    **engine,
    "version": f'{engine["chromium"]}-qt{engine["qt"]}-r{run}.{attempt}',
    "sequence": run * 1000 + attempt,
    "os": platform.system(), "os_release": platform.release(),
    "arch": platform.machine(),
    "qt_package": subprocess.check_output(["pkg_info", "-e", "qt6-qtwebengine-*"], text=True).strip(),
    "commit": os.environ.get("GITHUB_SHA", "local"),
}
Path("out/release.json").write_text(json.dumps(metadata, indent=2) + "\n")
