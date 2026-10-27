#!/bin/sh
set -eu
export PATH="/usr/local/bin:/usr/local/lib/qt6/bin:$PATH"
mkdir -p out
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/usr/local
cmake --build build --target engine-version
build/engine-version > out/engine.json
python3 scripts/build_metadata.py
APP_RELEASE=$(python3 -c 'import json; print(json.load(open("out/release.json"))["version"])')
cmake -S . -B build -DAPP_VERSION="$APP_RELEASE"
cmake --build build
ctest --test-dir build --output-on-failure
python3 -m unittest discover -s tests -v
cp build/discord-openbsd out/discord-openbsd
