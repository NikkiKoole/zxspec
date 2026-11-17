#!/usr/bin/env bash
# Build every machine's version of the groove. See README.md for the tools.
set -euo pipefail
cd "$(dirname "$0")"

echo "== ZX Spectrum";  python3 bas2tap.py jams.bas emulator/jams.tap jams 10
                        python3 build_jams2.py
echo "== C64";          python3 c64/build.py
echo "== NES";          python3 nes/build.py && cp nes/nesjams.nes emulator/nesjams.nes
echo "== Mega Drive";   python3 megadrive/build.py 2>&1 | grep -v "entry symbol"
echo "== SNES";         python3 snes/build.py
echo "== Amiga";        python3 amiga/build.py 2>&1 | grep -v "entry symbol"
echo "== Atari 2600";   python3 atari2600/build.py
echo "== DOS";          python3 dos/build.py
echo "== PICO-8";       python3 pico8/build.py
echo "== GBA";          python3 gba/build.py
echo "all built."
