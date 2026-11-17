#!/usr/bin/env python3
"""Build SNES JAMS: synthesizes the instrument samples, encodes them as BRR,
packs them with the SPC700 relay into an ARAM image, generates song/pitch/
graphics tables (gen_data.inc), then assembles + links snesjams.sfc."""
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS  # noqa: E402
from font5x7 import FONT  # noqa: E402

DSP_RATE = 32000
random.seed(2026)

# ---------------------------------------------------------------- BRR
def brr(samples, loop=False):
    """Encode floats (-1..1) as BRR, filter 0. Length is padded to 16."""
    pcm = [max(-16000, min(16000, round(x * 14000))) for x in samples]
    if len(pcm) % 16:
        assert not loop, "looped samples must be a multiple of 16 long"
        pcm += [0] * (16 - len(pcm) % 16)
    out = bytearray()
    blocks = len(pcm) // 16
    for b in range(blocks):
        blk = pcm[b * 16:(b + 1) * 16]
        for shift in range(13):
            nib = [round(v * 2 / 2 ** shift) for v in blk]
            if all(-8 <= n <= 7 for n in nib):
                break
        nib = [max(-8, min(7, n)) for n in nib]
        end = b == blocks - 1
        out.append((shift << 4) | ((1 << 1) if loop else 0) | (1 if end else 0))
        for i in range(0, 16, 2):
            out.append(((nib[i] & 15) << 4) | (nib[i + 1] & 15))
    return bytes(out)


def normalize(xs, peak=0.95):
    m = max(abs(x) for x in xs) or 1
    return [x / m * peak for x in xs]


# ---------------------------------------------------------------- instruments
def single_cycle(n, harmonics):
    return normalize([sum(a * math.sin(2 * math.pi * h * i / n) for h, a in harmonics)
                      for i in range(n)])


# bass: 128-sample cycle (250 Hz at pitch $1000), saw-ish with soft top end
BASS_N = 128
bass = single_cycle(BASS_N, [(h, (1 / h) * math.exp(-h / 7)) for h in range(1, 17)])
# arp: 64-sample cycle (500 Hz), sine with a little 2nd/3rd harmonic: soft EP-ish
ARP_N = 64
arp = single_cycle(ARP_N, [(1, 1.0), (2, 0.35), (3, 0.12)])
# pad: three detuned band-limited saws, 63/64/65 cycles in an 8192-sample loop
PAD_N, PAD_K = 8192, 64
pad = normalize([sum((1 / h) * math.exp(-h / 9) * math.sin(2 * math.pi * h * k * i / PAD_N)
                     for k in (PAD_K - 1, PAD_K, PAD_K + 1) for h in range(1, 19))
                 for i in range(PAD_N)], 0.9)

DRUM_RATE = 16000                    # kick/snare stored at 16 kHz (pitch $0800)


def kick(secs=0.22):
    out, ph = [], 0.0
    for i in range(int(secs * DRUM_RATE)):
        t = i / DRUM_RATE
        ph += 2 * math.pi * (48 + 150 * math.exp(-t / 0.03)) / DRUM_RATE
        click = random.uniform(-1, 1) * math.exp(-t / 0.002) * 0.35
        out.append(math.tanh(1.6 * (math.sin(ph) * math.exp(-t / 0.09) + click)))
    return out


def snare(secs=0.2):
    out, prev = [], 0.0
    for i in range(int(secs * DRUM_RATE)):
        t = i / DRUM_RATE
        body = (math.sin(2 * math.pi * 185 * t) + 0.5 * math.sin(2 * math.pi * 330 * t)) \
            * math.exp(-t / 0.035) * 0.55
        n = random.uniform(-1, 1)
        out.append(math.tanh(1.4 * (body + (n - 0.6 * prev) * math.exp(-t / 0.06) * 0.75)))
        prev = n
    return out


def hat(secs=0.07):
    out, prev = [], 0.0
    for i in range(int(secs * DSP_RATE)):
        n = random.uniform(-1, 1)
        out.append((n - prev) * 0.5 * math.exp(-i / DSP_RATE / 0.015))
        prev = n
    return out


SAMPLES = [  # (name, BRR data) in SRCN order
    ("bass", brr(bass, loop=True)),
    ("arp", brr(arp, loop=True)),
    ("pad", brr(pad, loop=True)),
    ("kick", brr(kick())),
    ("snare", brr(snare())),
    ("hat", brr(hat())),
]

# ---------------------------------------------------------------- ARAM image
# $0200: relay. Waits for port 0 to change, then writes port 2 -> DSP register
# named by port 1, and echoes port 0 back as the acknowledgement.
RELAY = bytes([
    0xE4, 0xF4,         # 0200 mov a,$F4      (whatever the IPL left there)
    0xC4, 0x00,         # 0202 mov $00,a
    0xE4, 0xF4,         # 0204 loop: mov a,$F4
    0x64, 0x00,         # 0206 cmp a,$00
    0xF0, 0xFA,         # 0208 beq loop
    0xC4, 0x00,         # 020A mov $00,a
    0xFA, 0xF5, 0xF2,   # 020C mov $F2,$F5    DSP address <- port 1
    0xFA, 0xF6, 0xF3,   # 020F mov $F3,$F6    DSP data    <- port 2
    0xC4, 0xF4,         # 0212 mov $F4,a      acknowledge
    0x2F, 0xEE,         # 0214 bra loop
])
ARAM_BASE, DIR_ADDR, SAMPLE_ADDR = 0x0200, 0x0300, 0x0400
ECHO_ADDR, ECHO_DELAY = 0x8000, 15          # 15 x 16 ms = 240 ms, 30 KB buffer

aram = bytearray(SAMPLE_ADDR - ARAM_BASE)
aram[0:len(RELAY)] = RELAY
addr = SAMPLE_ADDR
for srcn, (name, data) in enumerate(SAMPLES):
    d = DIR_ADDR - ARAM_BASE + srcn * 4
    aram[d:d + 4] = bytes([addr & 0xFF, addr >> 8, addr & 0xFF, addr >> 8])  # start, loop
    aram += data
    addr += len(data)
assert addr <= ECHO_ADDR, hex(addr)

# ---------------------------------------------------------------- pitch tables
def pitch_table(base_hz):
    return [min(0x3FFF, round(4096 * 440 * 2 ** ((m - 69) / 12) / base_hz)) for m in range(128)]


bass_pitch = pitch_table(DSP_RATE / BASS_N)
arp_pitch = pitch_table(DSP_RATE / ARP_N)
pad_pitch = pitch_table(DSP_RATE * PAD_K / PAD_N)

# ---------------------------------------------------------------- DSP setup
def voice(v, voll, volr, srcn, adsr1, adsr2, pitch=None):
    regs = [(v * 16 + 0, voll), (v * 16 + 1, volr), (v * 16 + 4, srcn),
            (v * 16 + 5, adsr1), (v * 16 + 6, adsr2), (v * 16 + 7, 0)]
    if pitch:
        regs += [(v * 16 + 2, pitch & 0xFF), (v * 16 + 3, pitch >> 8)]
    return regs


dsp_init = [(0x6C, 0x60),                       # FLG: mute, echo writes off
            (0x0C, 0x70), (0x1C, 0x70),         # main volume
            (0x2C, 0), (0x3C, 0), (0x0D, 0),    # echo silent until flushed
            (0x5D, DIR_ADDR >> 8),
            (0x6D, ECHO_ADDR >> 8), (0x7D, ECHO_DELAY),
            (0x4D, 0x5E),                       # echo on arp, pads, snare
            (0x3D, 0), (0x2D, 0), (0x5C, 0)]
FIR = [0x40, 0x20, 0x10, 0x08, 0, 0, 0, 0]      # echo repeats get darker
dsp_init += [(0x0F + 0x10 * i, c) for i, c in enumerate(FIR)]
dsp_init += voice(0, 0x58, 0x58, 0, 0xDF, 0x6E)                  # bass
dsp_init += voice(1, 0x40, 0x40, 1, 0xBC, 0x50)                  # arp
dsp_init += voice(2, 0x38, 0x0C, 2, 0x89, 0xE0)                  # pad left
dsp_init += voice(3, 0x28, 0x28, 2, 0x89, 0xE0)                  # pad centre
dsp_init += voice(4, 0x0C, 0x38, 2, 0x89, 0xE0)                  # pad right
dsp_init += voice(5, 0x7F, 0x7F, 3, 0x8F, 0xE0, 0x1000 * DRUM_RATE // DSP_RATE)
dsp_init += voice(6, 0x50, 0x50, 4, 0x8F, 0xE0, 0x1000 * DRUM_RATE // DSP_RATE)
dsp_init += voice(7, 0x30, 0x24, 5, 0x8F, 0xE0, 0x1000)
dsp_init += [(0x6C, 0x00)]                      # unmute, echo writes on

# ---------------------------------------------------------------- song
PAD_FROM_BAR = 16
VOICINGS = {"A": (57, 60, 64), "F": (53, 57, 60), "C": (55, 60, 64),
            "G": (55, 59, 62), "E": (56, 59, 64)}
chord_names = list(VOICINGS)
chordtab = [n for name in chord_names for n in VOICINGS[name]]
rows = ticks()
for bar, root in enumerate(ROOTS):
    padcol = [0] * 16
    if bar >= PAD_FROM_BAR:
        padcol[0] = 2 + chord_names.index(root)
        if bar == len(ROOTS) - 1:
            padcol[14] = 1
    for i in range(16):
        rows[bar * 16 + i].append(padcol[i])
for row in rows[len(ROOTS) * 16:]:
    row.append(0)
song = [b for row in rows for b in row]

# ---------------------------------------------------------------- graphics
def tile2bpp(pixel):
    out = []
    for y in range(8):
        p0 = p1 = 0
        for x in range(8):
            c = pixel(x, y)
            p0 = (p0 << 1) | (c & 1)
            p1 = (p1 << 1) | (c >> 1 & 1)
        out += [p0, p1]
    return out


tiles = tile2bpp(lambda x, y: 0) + tile2bpp(lambda x, y: 1 if 1 <= y <= 6 else 0)
tiles += [0] * (16 * 30)
for code in range(32, 96):
    rws = [int(h, 16) for h in FONT.get(chr(code), "00 00 00 00 00 00 00").split()]
    tiles += tile2bpp(lambda x, y, r=rws: 1 if y < 7 and 1 <= x <= 5 and r[y] >> (5 - x) & 1 else 0)

tilemap = [0] * (32 * 32)


def text(row, s, pal, col=None):
    col = (32 - len(s)) // 2 if col is None else col
    for i, ch in enumerate(s):
        tilemap[row * 32 + col + i] = ord(ch) | (pal << 10)


text(3, "SNES JAMS", 1)
text(5, "SAMPLES + HARDWARE ECHO", 2)
for row, label in ((11, "BASS"), (13, "ARP"), (15, "PADS"), (17, "DRUMS")):
    text(row, label, 0, col=3)
text(23, "GROOVE BY CLAUDE, 2026", 2)
meter_addr = [0x0400 + row * 32 + 10 for row in (11, 13, 15, 17)]
meter_pal = [1 | (pal << 10) for pal in (3, 4, 5, 6)]


def bgr(r, g, b):
    return (b << 10) | (g << 5) | r


palette = [0] * 32
for pal, colour in enumerate([(31, 31, 31), (31, 29, 8), (12, 28, 31), (10, 30, 10),
                              (24, 12, 31), (31, 18, 6), (31, 28, 4)]):
    palette[pal * 4 + 1] = bgr(*colour)

gradtab = []
for level in range(8):
    for i in range(256):
        a = 2 * math.pi * i / 256
        r = 3 + 3 * math.sin(a) + level * 2.2
        g = 1 + 2 * math.sin(a + 2.1) + level * 1.6
        b = 9 + 5 * math.sin(a + 4.2) + level * 2.2
        gradtab.append(bgr(*(max(0, min(31, round(c))) for c in (r, g, b))))

# ---------------------------------------------------------------- emit
def rows_of(directive, data, fmt, per):
    return "\n".join(f"        {directive} " + ", ".join(fmt.format(v) for v in data[i:i + per])
                     for i in range(0, len(data), per))


def B(label, data):
    return f"{label}:\n" + rows_of(".byte", list(data), "${:02x}", 32)


def W(label, data):
    return f"{label}:\n" + rows_of(".word", list(data), "${:04x}", 16)


with open(os.path.join(HERE, "gen_data.inc"), "w") as f:
    f.write(f"""; generated by build.py - do not edit
ARAM_LEN = {len(aram)}
SONG_BYTES = {len(song)}
TILE_BYTES = {len(tiles)}
ARP_NEAR = $50
ARP_FAR = $14
ECHO_FEEDBACK = $48
ECHO_VOLUME = $30

.segment "RODATA"
""")
    f.write("\n".join([
        B("dsp_init_tab", [b for pair in dsp_init for b in pair] + [0xFF]),
        B("song", song),
        B("chordtab", chordtab),
        W("bass_pitch", bass_pitch),
        W("arp_pitch", arp_pitch),
        W("pad_pitch", pad_pitch),
        W("meter_addr", meter_addr),
        W("meter_pal", meter_pal),
        W("palette", palette),
        W("gradtab", gradtab),
        B("tiles", tiles),
        W("tilemap", tilemap),
        B("aram_blob", aram),
    ]) + "\n")

run = lambda *cmd: subprocess.run(cmd, cwd=HERE, check=True)  # noqa: E731
run("ca65", "-o", "main.o", "main.s")
run("ld65", "-C", "snes.cfg", "-o", "snesjams.sfc", "main.o")

rom = bytearray(open(os.path.join(HERE, "snesjams.sfc"), "rb").read())
rom[0x7FDC:0x7FE0] = b"\xff\xff\x00\x00"
chk = sum(rom) & 0xFFFF
rom[0x7FDC:0x7FE0] = bytes([(chk ^ 0xFFFF) & 0xFF, (chk ^ 0xFFFF) >> 8, chk & 0xFF, chk >> 8])
open(os.path.join(HERE, "snesjams.sfc"), "wb").write(rom)
print(f"snesjams.sfc: {len(rom)} bytes; ARAM image {len(aram)} bytes "
      f"(samples {', '.join(f'{n} {len(d)}' for n, d in SAMPLES)})")
