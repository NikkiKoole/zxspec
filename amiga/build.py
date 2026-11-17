#!/usr/bin/env python3
"""Build AMIGA JAMS: render sampled-FM instruments (after the Mega Drive patches)
and drums as 8-bit samples, period tables, the song, a copper list, the screen
bitmap; assemble the program and the bootblock; write a bootable amigajams.adf."""
import math
import os
import random
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS  # noqa: E402
from font5x7 import FONT  # noqa: E402

PAULA_CLOCK = 3546895            # PAL
OVERSAMPLE = 4
random.seed(2026)
rng = np.random.default_rng(2026)


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def render(fn, secs, rate):
    """Run fn(t) at OVERSAMPLE x rate, then average down (a crude anti-alias)."""
    n = int(secs * rate)
    t = np.arange(n * OVERSAMPLE) / (rate * OVERSAMPLE)
    return fn(t).reshape(n, OVERSAMPLE).mean(axis=1)


def to8(x, peak=118):
    x = np.asarray(x, dtype=float)
    x = x / (np.abs(x).max() or 1) * peak
    b = np.round(x).astype(int)
    if len(b) % 2:
        b = np.append(b, 0)
    return bytes(int(v) & 0xFF for v in b)


# ---------------------------------------------------------------- instruments
BASS_RATE, BASS_NOTE = 11000, 48            # recorded at C3
EP_RATE, EP_NOTE = 13000, 60                # recorded at C4
PAD_RATE = DRUM_RATE = 11025


def fb_sine(phase, fb):
    """Operator 1 with feedback (sample-by-sample, as the YM does)."""
    out = np.zeros_like(phase)
    y = y1 = 0.0
    for i, p in enumerate(phase):
        y = math.sin(p + fb * 0.5 * (y + y1))
        y1 = out[i - 1] if i else 0.0
        out[i] = y
    return out


def bass(t):
    # Mega Drive slap bass: algorithm 0 chain 1:1:2:1 with feedback, brightness falls fast
    w = 2 * math.pi * hz(BASS_NOTE) * t
    op1 = fb_sine(w, 1.6)
    op2 = np.sin(w + 1.5 * np.exp(-t / 0.08) * op1)
    op3 = np.sin(2 * w + (0.8 + 2.2 * np.exp(-t / 0.05)) * op2)
    out = np.sin(w + (0.9 + 2.6 * np.exp(-t / 0.06)) * op3)
    amp = np.minimum(1, t / 0.002) * (0.3 + 0.7 * np.exp(-t / 0.07)) * np.clip(1 - t / 0.28, 0, 1)
    return out * amp


def epiano(t):
    # 1:1 body pair + 14:1 tine pair (algorithm 4)
    w = 2 * math.pi * hz(EP_NOTE) * t
    body = np.sin(w + 1.1 * np.exp(-t / 0.4) * np.sin(w))
    tine = np.sin(w + 0.9 * np.exp(-t / 0.06) * np.sin(14 * w))
    return (0.7 * body + 0.45 * tine) * np.minimum(1, t / 0.002) * np.exp(-t / 0.45)


def pad_chord(notes, secs):
    def f(t):
        out = 0
        for k, m in enumerate(notes):
            w = 2 * math.pi * hz(m) * t
            det = 2 * math.pi * hz(m) * 1.004 * t
            out = out + np.sin(w + 0.7 * np.sin(w + k)) + 0.5 * np.sin(det + 0.5 * np.sin(2 * det))
        env = np.minimum(1, t / 0.35) * np.clip((secs - t) / 0.25, 0, 1)
        return out * env
    return f


def kick(t):
    ph = 2 * math.pi * np.cumsum(48 + 150 * np.exp(-t / 0.03)) / (DRUM_RATE * OVERSAMPLE)
    click = rng.uniform(-1, 1, len(t)) * np.exp(-t / 0.002) * 0.35
    return np.tanh(1.4 * (np.sin(ph) * np.exp(-t / 0.09) + click))


def snare(t):
    n = rng.uniform(-1, 1, len(t))
    body = (np.sin(2 * math.pi * 185 * t) + 0.5 * np.sin(2 * math.pi * 330 * t)) * np.exp(-t / 0.035) * 0.55
    hp = n - 0.6 * np.concatenate([[0], n[:-1]])
    return np.tanh(1.4 * (body + hp * np.exp(-t / 0.065) * 0.75))


def hat(t):
    n = rng.uniform(-1, 1, len(t))
    return (n - np.concatenate([[0], n[:-1]])) * np.exp(-t / 0.016)


STEP = 6 / 50                                   # a 16th: 6 PAL frames
BAR = 16 * STEP
VOICINGS = {"A": (57, 60, 64), "F": (53, 57, 60), "C": (55, 60, 64),
            "G": (55, 59, 62), "E": (56, 59, 64)}
chord_names = list(VOICINGS)

samples = [("bass", to8(render(bass, 0.28, BASS_RATE))),
           ("ep", to8(render(epiano, 0.6, EP_RATE)))]
samples += [(f"pad_{c}", to8(render(pad_chord(VOICINGS[c], BAR), BAR, PAD_RATE))) for c in chord_names]
samples += [("kick", to8(render(kick, 0.22, DRUM_RATE))),
            ("snare", to8(render(snare, 0.2, DRUM_RATE))),
            ("hat", to8(render(hat, 0.06, DRUM_RATE), peak=70))]
SMP = {name: i for i, (name, _) in enumerate(samples)}


def periods(rate, note):
    return [max(124, min(65535, round(PAULA_CLOCK / (rate * 2 ** ((m - note) / 12))))) for m in range(128)]


per_bass, per_arp = periods(BASS_RATE, BASS_NOTE), periods(EP_RATE, EP_NOTE)
PAD_PER = DRUM_PER = round(PAULA_CLOCK / PAD_RATE)

# ---------------------------------------------------------------- song
PAD_FROM_BAR = 16
rows = ticks()
for bar, root in enumerate(ROOTS):
    for i in range(16):
        v = 0
        if bar >= PAD_FROM_BAR and i == 0:
            v = 2 + chord_names.index(root)
        if bar == len(ROOTS) - 1 and i == 14:
            v = 1
        rows[bar * 16 + i].append(v)
for row in rows[len(ROOTS) * 16:]:
    row.append(0)
song = [b for row in rows for b in row]

# ---------------------------------------------------------------- screen + copper
W, H = 320, 256
bitmap = np.zeros((H, W), dtype=np.uint8)


def text(s, y, scale=1, x=None):
    x = (W - len(s) * 8 * scale) // 2 if x is None else x
    for i, ch in enumerate(s):
        rws = [int(v, 16) for v in FONT.get(ch, "00 00 00 00 00 00 00").split()]
        for r, bits in enumerate(rws):
            for c in range(5):
                if bits >> (4 - c) & 1:
                    bx, by = x + i * 8 * scale + (c + 1) * scale, y + r * scale
                    bitmap[by:by + scale, bx:bx + scale] = 1


def rgb12(r, g, b):
    return (r << 8) | (g << 4) | b


LINE_COL = {}                                   # COLOR01 (text colour) per screen line


def colour_lines(y0, y1, col):
    for y in range(y0, y1):
        LINE_COL[y] = col


text("AMIGA JAMS", 16, 2); colour_lines(14, 34, rgb12(15, 13, 3))
text("PAULA: 4 X 8-BIT SAMPLES, HARD STEREO", 42); colour_lines(40, 52, rgb12(5, 13, 15))
text("SAMPLED FM AFTER THE MEGA DRIVE", 56); colour_lines(52, 66, rgb12(5, 13, 15))
METERS = [("BASS  CH0 L", 96, rgb12(5, 14, 5)), ("ARP   CH2 R", 116, rgb12(12, 6, 15)),
          ("PADS  CH3 L", 136, rgb12(15, 9, 4)), ("DRUMS CH1 R", 156, rgb12(15, 14, 4))]
for label, y, col in METERS:
    text(label, y, x=16)
    colour_lines(y - 2, y + 10, col)
text("GROOVE BY CLAUDE, 2026", 216); colour_lines(214, 226, rgb12(5, 13, 15))
meter_offs = [y * 40 + 16 for _, y, _ in METERS]           # x = 128 px, 20 bytes wide
screen = np.packbits(bitmap, axis=1).tobytes()

copper, bar_offs = [], []
copper += [0x00E0, 0, 0x00E2, 0]                # bitplane pointer, patched at start-up
first = 0x2C
for y in range(H):
    v = first + y
    if v == 0x100:
        copper += [0xFFDF, 0xFFFE]              # past line 255
    copper += [((v & 0xFF) << 8) | 0x07, 0xFFFE]
    bar_offs.append(len(copper) * 2 + 2)        # byte offset of the COLOR00 value
    copper += [0x0180, 0x0000, 0x0182, LINE_COL.get(y, rgb12(15, 15, 15))]
copper += [0xFFFF, 0xFFFE]

gradtab = []
for level in range(8):
    for i in range(256):
        a = 2 * math.pi * i / 256
        bar = max(0.0, math.sin(3 * a)) ** 6    # three soft bars rolling down the screen
        r = 1 + 2 * bar + 0.8 * level
        g = 0.3 * bar + 0.4 * level
        b = 3 + 2 * math.sin(a) + 3 * bar + 0.9 * level
        gradtab.append(rgb12(*(max(0, min(15, round(c))) for c in (r, g, b))))

# ---------------------------------------------------------------- emit
def W16(label, data):
    out = [f"{label}:"]
    for i in range(0, len(data), 16):
        out.append("        .word " + ", ".join(f"0x{v & 0xFFFF:04X}" for v in data[i:i + 16]))
    return "\n".join(out)


def B8(label, data):
    data = list(data)
    out = [f"{label}:"]
    for i in range(0, len(data), 32):
        out.append("        .byte " + ", ".join(f"0x{v:02X}" for v in data[i:i + 32]))
    return "\n".join(out)


with open(os.path.join(HERE, "gen_equ.s"), "w") as f:
    f.write("| generated by build.py\n")
    for k, v in [("SONG_BYTES", len(song)), ("PAD_PER", PAD_PER), ("DRUM_PER", DRUM_PER),
                 ("SMP_BASS", SMP["bass"]), ("SMP_EP", SMP["ep"]), ("SMP_PAD0", SMP["pad_A"]),
                 ("SMP_KICK", SMP["kick"]), ("ARP_VOL", 40), ("PAD_VOL", 40),
                 ("KICK_VOL", 64), ("SNARE_VOL", 52), ("HAT_VOL", 40)]:
        f.write(f"        .equ {k}, {v}\n")

with open(os.path.join(HERE, "gen_data.s"), "w") as f:
    f.write("| generated by build.py\n        .balign 2\n")
    f.write("\n".join([
        B8("song", song), "        .balign 2",
        W16("per_bass", per_bass), W16("per_arp", per_arp),
        "smp_tab:\n" + "\n".join(f"        .long smp_{n} - start\n        .word {len(d) // 2}" for n, d in samples),
        W16("meter_offs", meter_offs),
        W16("bar_offs", bar_offs),
        W16("gradtab", gradtab),
        W16("copper", copper),
        B8("screen", screen),
    ]) + "\n")
    for name, data in samples:
        f.write("        .balign 2\n" + B8(f"smp_{name}", data) + "\n")

run = lambda *cmd: subprocess.run(cmd, cwd=HERE, check=True)  # noqa: E731
for src in ("boot", "main"):
    run("m68k-elf-as", "-m68000", "-o", f"{src}.o", f"{src}.s")
    run("m68k-elf-ld", "-Ttext=0", "--oformat", "binary", "-o", f"{src}.bin", f"{src}.o")

prog = open(os.path.join(HERE, "main.bin"), "rb").read()
prog += b"\0" * (-len(prog) % 512)
boot = bytearray(open(os.path.join(HERE, "boot.bin"), "rb").read())
boot[-4:] = struct.pack(">I", len(prog))
boot += b"\0" * (1024 - len(boot))
s = 0
for i in range(0, 1024, 4):
    s += struct.unpack(">I", boot[i:i + 4])[0]
    if s > 0xFFFFFFFF:
        s = (s & 0xFFFFFFFF) + 1
boot[4:8] = struct.pack(">I", ~s & 0xFFFFFFFF)

adf = bytes(boot) + prog
assert len(adf) <= 901120, len(adf)
adf += b"\0" * (901120 - len(adf))
open(os.path.join(HERE, "amigajams.adf"), "wb").write(adf)
print(f"amigajams.adf: program {len(prog)} bytes "
      f"({', '.join(f'{n} {len(d)}' for n, d in samples)})")
