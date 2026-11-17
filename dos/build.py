#!/usr/bin/env python3
"""Build DOS JAMS: OPL3 patches + note tables, the song (with pads and an
arp 'echo' column), Sound Blaster drum samples, plasma tables, palette and
text; then assemble dosjams.com with nasm."""
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS  # noqa: E402

OPL_RATE = 49716
random.seed(2026)

# ---------------------------------------------------------------- notes
def fnum_block(hz):
    for block in range(8):
        fnum = round(hz * 2 ** (20 - block) / OPL_RATE)
        if fnum < 1024:
            return fnum, block
    return 1023, 7


fn_lo, fn_hi = [], []
for m in range(128):
    f, b = fnum_block(440 * 2 ** ((m - 69) / 12))
    fn_lo.append(f & 0xFF)
    fn_hi.append((b << 2) | (f >> 8))

# ---------------------------------------------------------------- OPL3 patches
MOD = [0, 1, 2, 8, 9, 10, 16, 17, 18]          # modulator operator per channel


def opcfg(flags=0, mult=1, ksl=0, tl=63, ar=15, dr=0, sl=0, rr=15, wave=0):
    return dict(f=flags | mult, l=(ksl << 6) | tl, a=(ar << 4) | dr, s=(sl << 4) | rr, w=wave)


SUS, VIB = 0x20, 0x40
BASS = (opcfg(SUS, 1, tl=0x1A, ar=15, dr=4, sl=3, rr=7),
        opcfg(SUS, 1, tl=0x02, ar=15, dr=3, sl=2, rr=6), (5 << 1))
ARP = (opcfg(0, 1, tl=0x23, ar=15, dr=6, sl=4, rr=5),
       opcfg(0, 1, tl=0x0C, ar=15, dr=3, sl=5, rr=5), (2 << 1))
ECHO = (ARP[0], opcfg(0, 1, tl=0x1C, ar=15, dr=3, sl=5, rr=5), (2 << 1))
PAD = (opcfg(SUS | VIB, 1, tl=0x2A, ar=6, dr=2, sl=1, rr=4, wave=1),
       opcfg(SUS | VIB, 1, tl=0x12, ar=5, dr=2, sl=1, rr=4), (3 << 1))
L, R, C = 0x10, 0x20, 0x30
CHANNELS = [(BASS, C), (ARP, L), (PAD, L), (PAD, C), (PAD, R), (ECHO, R)]
ARP_C0 = ARP[2]

opl_init = [(0x01, 0x20), (0x08, 0x00), (0xBD, 0x40)]   # waveforms on, vibrato depth
for ch, ((mod, car, c0), pan) in enumerate(CHANNELS):
    for op, cfg in ((MOD[ch], mod), (MOD[ch] + 3, car)):
        opl_init += [(0x20 + op, cfg["f"]), (0x40 + op, cfg["l"]), (0x60 + op, cfg["a"]),
                     (0x80 + op, cfg["s"]), (0xE0 + op, cfg["w"])]
    opl_init.append((0xC0 + ch, pan | c0))

# ---------------------------------------------------------------- song
ECHO_DELAY = 3
PAD_FROM_BAR = 16
VOICINGS = {"A": (57, 60, 64), "F": (53, 57, 60), "C": (55, 60, 64),
            "G": (55, 59, 62), "E": (56, 59, 64)}
chord_names = list(VOICINGS)
chordtab = [n for name in chord_names for n in VOICINGS[name]]
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
for i, row in enumerate(rows):                  # echo column: arp, 3 16ths later
    src = rows[i - ECHO_DELAY][1] if i >= ECHO_DELAY else 0
    row.append(src if src >= 2 else 0)
song = [b for row in rows for b in row]

# ---------------------------------------------------------------- SB samples
TIME_CONSTANT = 165
SB_RATE = 1_000_000 / (256 - TIME_CONSTANT)


def u8(xs):
    return [max(0, min(255, round(128 + 120 * math.tanh(1.4 * x)))) for x in xs]


def kick(secs=0.2):
    out, ph = [], 0.0
    for i in range(int(secs * SB_RATE)):
        t = i / SB_RATE
        ph += 2 * math.pi * (48 + 150 * math.exp(-t / 0.03)) / SB_RATE
        click = random.uniform(-1, 1) * math.exp(-t / 0.002) * 0.35
        out.append(math.sin(ph) * math.exp(-t / 0.09) + click)
    return u8(out)


def snare(secs=0.2):
    out, prev = [], 0.0
    for i in range(int(secs * SB_RATE)):
        t = i / SB_RATE
        n = random.uniform(-1, 1)
        body = (math.sin(2 * math.pi * 185 * t) + 0.5 * math.sin(2 * math.pi * 330 * t)) \
            * math.exp(-t / 0.035) * 0.55
        out.append(body + (n - 0.6 * prev) * math.exp(-t / 0.06) * 0.7)
        prev = n
    return u8(out)


def hat(secs=0.06):
    out, prev = [], 0.0
    for i in range(int(secs * SB_RATE)):
        n = random.uniform(-1, 1)
        out.append((n - prev) * 0.35 * math.exp(-i / SB_RATE / 0.015))
        prev = n
    return u8(out)


samples = [kick(), snare(), hat()]

# ---------------------------------------------------------------- visuals
def sin_table(periods, phase):
    return [round(31.5 + 31.4 * math.sin(2 * math.pi * periods * i / 256 + phase)) for i in range(256)]


sin_a, sin_b, sin_c = sin_table(2, 0), sin_table(3, 1.3), sin_table(1, 2.6)
plasma_pal = []
for i in range(192):                            # dark, moody: blue / purple / teal
    a = 2 * math.pi * i / 192
    r = 6 + 6 * math.sin(a)
    g = 3 + 4 * math.sin(a + 2.1)
    b = 14 + 10 * math.sin(a + 4.2)
    plasma_pal += [max(0, min(63, round(c))) for c in (r, g, b)]
# 248 dark grey, 249 pink, 250 white, 251 yellow, 252 cyan, 253 green, 254 purple, 255 orange
text_pal = [12, 12, 12, 63, 30, 50, 63, 63, 63, 63, 58, 16, 24, 56, 63, 20, 62, 20, 48, 24, 63, 63, 38, 10]

STRINGS = [(2, "DOS JAMS", 251), (4, "ADLIB OPL3 FM + SOUND BLASTER", 252),
           (21, "GROOVE BY CLAUDE, 2026", 252), (23, "ESC QUITS", 248)]
METER_ROWS = [(9, "BASS", 253), (11, "ARP", 254), (13, "PADS", 255), (15, "ECHO", 252),
              (17, "DRUMS", 251)]
strings = []
for row, text, col in STRINGS:
    strings += [row, (40 - len(text)) // 2, col] + [ord(c) for c in text] + [0]
for row, text, col in METER_ROWS:
    strings += [row, 4, col] + [ord(c) for c in text] + [0]
strings.append(0xFF)
meter_off = [(row * 8 + 1) * 320 + 96 for row, _, _ in METER_ROWS]
meter_col = [col for _, _, col in METER_ROWS]

# ---------------------------------------------------------------- emit
def db(label, data, per=24):
    data = list(data)
    lines = [f"{label}:"]
    for i in range(0, len(data), per):
        lines.append("        db " + ", ".join(str(v) for v in data[i:i + per]))
    return "\n".join(lines)


def dw(label, data):
    return f"{label}:\n        dw " + ", ".join(str(v) for v in data)


with open(os.path.join(HERE, "gen_equ.asm"), "w") as f:
    f.write(f"""; generated by build.py
ROW_BYTES equ 5
METERS equ {len(METER_ROWS)}
ARP_C0 equ {ARP_C0}
SB_TIME_CONSTANT equ {TIME_CONSTANT}
""")
with open(os.path.join(HERE, "gen_data.asm"), "w") as f:
    f.write("\n".join([
        "; generated by build.py - do not edit",
        db("song", song) + "\nsong_end:",
        db("fn_lo", fn_lo), db("fn_hi", fn_hi), db("chordtab", chordtab),
        db("opl_init_tab", [b for pair in opl_init for b in pair] + [0xFF]),
        db("sin_a", sin_a), db("sin_b", sin_b), db("sin_c", sin_c),
        db("plasma_pal", plasma_pal), db("text_pal", text_pal),
        db("strings", strings),
        dw("meter_off", meter_off), db("meter_col", meter_col),
        dw("sample_len", [len(s) for s in samples]),
        "sample_src:\n        dw kick_data, snare_data, hat_data",
        db("kick_data", samples[0]), db("snare_data", samples[1]), db("hat_data", samples[2]),
    ]) + "\n")

subprocess.run(["nasm", "-f", "bin", "-o", "dosjams.com", "main.asm"], cwd=HERE, check=True)
size = os.path.getsize(os.path.join(HERE, "dosjams.com"))
print(f"dosjams.com: {size} bytes (+24 KB DMA buffers at run time); "
      f"samples {[len(s) for s in samples]} at {SB_RATE:.0f} Hz")
assert size + 3 * 8192 + 4096 < 0xF000, "too big for a .COM"
