#!/usr/bin/env python3
"""Build GBA JAMS: generate gen.h (song, note tables, wavetables, drum samples,
font, perspective/sine tables), render the mixer on the Mac to gbajams_preview.wav
(the same mixer.c the GBA runs), then cross-compile gbajams.gba."""
import math
import os
import random
import struct
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS  # noqa: E402
from font5x7 import FONT  # noqa: E402

RATE = 16777216 / 924            # 18157.1 Hz, 304 samples per frame
random.seed(2026)


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- song
VOICINGS = {"A": (57, 60, 64), "F": (53, 57, 60), "C": (55, 60, 64),
            "G": (55, 59, 62), "E": (56, 59, 64)}
chord_names = list(VOICINGS)
rows = ticks()
for bar, root in enumerate(ROOTS):
    for i in range(16):
        v = 0
        if bar >= 16 and i == 0:
            v = 2 + chord_names.index(root)
        if bar == len(ROOTS) - 1 and i == 14:
            v = 1
        rows[bar * 16 + i].append(v)
for row in rows[len(ROOTS) * 16:]:
    row.append(0)
song = [b for row in rows for b in row]

note_inc = [min(0xFFFFFFFF, round(hz(m) / RATE * 2 ** 32)) for m in range(128)]
ks_len = [max(2, min(256, round(RATE / hz(m) - 0.5))) for m in range(128)]   # KS adds ~half a sample

# ---------------------------------------------------------------- wavetables + drums
sine_bass = [round(127 * math.tanh(1.3 * (math.sin(2 * math.pi * i / 256)
                                         + 0.3 * math.sin(4 * math.pi * i / 256))) / math.tanh(1.3 * 1.15))
             for i in range(256)]
saw = [sum(math.sin(2 * math.pi * h * i / 256) / h for h in range(1, 13)) for i in range(256)]
peak = max(abs(v) for v in saw)
saw_tab = [round(v / peak * 127) for v in saw]


def to8(xs, gain=1.0):
    pk = max(abs(x) for x in xs) or 1
    return [max(-128, min(127, round(x / pk * 127 * gain))) for x in xs]


def kick(secs=0.25):
    out, ph = [], 0.0
    for i in range(int(secs * RATE)):
        t = i / RATE
        ph += 2 * math.pi * (46 + 140 * math.exp(-t / 0.03)) / RATE
        click = random.uniform(-1, 1) * math.exp(-t / 0.002) * 0.3
        out.append(math.tanh(1.5 * (math.sin(ph) * math.exp(-t / 0.11) + click)))
    return to8(out)


def snare(secs=0.2):
    out, prev = [], 0.0
    for i in range(int(secs * RATE)):
        t = i / RATE
        n = random.uniform(-1, 1)
        body = (math.sin(2 * math.pi * 190 * t) + 0.5 * math.sin(2 * math.pi * 340 * t)) * math.exp(-t / 0.03) * 0.5
        out.append(math.tanh(1.3 * (body + (n - 0.5 * prev) * math.exp(-t / 0.06) * 0.8)))
        prev = n
    return to8(out)


def hat(secs=0.05):
    out, prev = [], 0.0
    for i in range(int(secs * RATE)):
        n = random.uniform(-1, 1)
        out.append((n - prev) * math.exp(-i / RATE / 0.012))
        prev = n
    return to8(out)


drums = [kick(), snare(), hat()]

# ---------------------------------------------------------------- visuals
def tile4(pixel):                 # 4bpp tile: 32 bytes, low nibble = left pixel
    out = []
    for y in range(8):
        for x in range(0, 8, 2):
            out.append(pixel(x, y) | (pixel(x + 1, y) << 4))
    return out


font_tiles = tile4(lambda x, y: 0)                                       # 0 empty
font_tiles += tile4(lambda x, y: 1 if 1 <= y <= 6 else 0)                # 1 meter block
font_tiles += [0] * (32 * 30)
for code in range(32, 96):
    r = [int(h, 16) for h in FONT.get(chr(code), "00 00 00 00 00 00 00").split()]
    font_tiles += tile4(lambda x, y, r=r: 1 if y < 7 and 1 <= x <= 5 and r[y] >> (5 - x) & 1 else 0)

# floor: 8bpp tiles for the rotating plane (64 bytes each)
floor_tiles = [0] * 64 + [1] * 64 + [2] * 64                             # 0 clear, 1 light, 2 dark
for y in range(8):                                                       # 3: a light tile with a glowing edge
    floor_tiles += [3 if (x == 0 or y == 0) else 1 for x in range(8)]
floor_map = [(3 if (x % 4 == 0 and y % 4 == 0) else (1 if (x // 2 + y // 2) % 2 else 2))
             for y in range(32) for x in range(32)]

HORIZON = 56
CAM_H = 22 * 256                  # camera height, 8.8
# per visible line below the horizon: the floor's distance scale (8.8); lines above: 0
lam = [0] * 160
for y in range(HORIZON + 1, 160):
    lam[y] = round(CAM_H / (y - HORIZON))
sin_tab = [round(256 * math.sin(2 * math.pi * i / 256)) for i in range(256)]


def bgr(r, g, b):                 # 0..31 each
    return r | (g << 5) | (b << 10)


# sky: one colour per line above the horizon, 8 brightness levels for the kick flash
sky = []
for level in range(8):
    for y in range(160):
        f = min(1.0, y / HORIZON)
        sky.append(bgr(round(2 + 6 * f + level * 2), round(1 + 3 * f + level), round(8 + 12 * f + level * 2)))

# ---------------------------------------------------------------- emit gen.h
def arr(ctype, name, data, per=16):
    body = ",\n".join("    " + ", ".join(str(v) for v in data[i:i + per]) for i in range(0, len(data), per))
    return f"static const {ctype} {name}[{len(data)}] = {{\n{body}\n}};\n"


h = ["// generated by build.py - do not edit", "#include <stdint.h>",
     f"#define SONG_ROWS {len(song) // 4}", f"#define HORIZON {HORIZON}",
     arr("uint8_t", "song", song, 32),
     "static const uint8_t chordtab[5][3] = {" + ", ".join("{%d,%d,%d}" % VOICINGS[c] for c in chord_names) + "};",
     arr("uint32_t", "note_inc", note_inc, 8),
     arr("uint16_t", "ks_len", ks_len),
     arr("int8_t", "sine_bass", sine_bass), arr("int8_t", "saw_tab", saw_tab)]
for name, d in zip(("kick_pcm", "snare_pcm", "hat_pcm"), drums):
    h.append(arr("int8_t", name, d, 32))
h.append("static const int8_t *const drum_pcm[3] = {kick_pcm, snare_pcm, hat_pcm};")
h.append("static const int drum_len[3] = {%d, %d, %d};" % tuple(len(d) for d in drums))
h += [arr("uint8_t", "font_tiles", font_tiles, 32), arr("uint8_t", "floor_tiles", floor_tiles, 32),
      arr("uint8_t", "floor_map", floor_map, 32), arr("int32_t", "lam", lam),
      arr("int16_t", "sin_tab", sin_tab), arr("uint16_t", "sky", sky)]
open(os.path.join(HERE, "gen.h"), "w").write("\n".join(h) + "\n")

# ---------------------------------------------------------------- preview on the Mac
run = lambda *cmd: subprocess.run(cmd, cwd=HERE, check=True)  # noqa: E731
run("cc", "-O2", "-Wall", "-o", "host_render", "host_render.c", "mixer.c")
frames = int(70 * 59.73)
raw = subprocess.run([os.path.join(HERE, "host_render"), str(frames)], cwd=HERE,
                     check=True, capture_output=True).stdout
with wave.open(os.path.join(HERE, "gbajams_preview.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(1); w.setframerate(round(RATE))
    w.writeframes(bytes((b + 128) & 0xFF for b in struct.unpack(f"{len(raw)}b", raw)))
print(f"gbajams_preview.wav: {frames} frames ({frames / 59.73:.0f} s)")

# ---------------------------------------------------------------- the ROM
if os.path.exists(os.path.join(HERE, "main.c")):
    cflags = ["-mcpu=arm7tdmi", "-mthumb", "-mthumb-interwork", "-O2", "-Wall",
              "-ffreestanding", "-fno-builtin"]
    # the mixer as 32-bit ARM code (it is copied into IWRAM at boot, see gba.ld)
    arm = [f for f in cflags if f != "-mthumb"] + ["-marm"]
    run("arm-none-eabi-gcc", *arm, "-c", "-o", "mixer.o", "mixer.c")
    run("arm-none-eabi-gcc", *cflags, "-nostdlib", "-T", "gba.ld", "-o", "gbajams.elf",
        "crt0.s", "main.c", "mixer.o", "-lgcc")
    run("arm-none-eabi-objcopy", "-O", "binary", "gbajams.elf", "gbajams.gba")
    rom = bytearray(open(os.path.join(HERE, "gbajams.gba"), "rb").read())
    rom[0xBD] = (-(sum(rom[0xA0:0xBD]) + 0x19)) & 0xFF        # header complement check
    open(os.path.join(HERE, "gbajams.gba"), "wb").write(rom)
    print(f"gbajams.gba: {len(rom)} bytes")
