#!/usr/bin/env python3
"""Build MEGA JAMS: generates gen_equ.s / gen_header.s / gen_data.s (FM patches,
song, font, maps, palettes, scroll waves), then assembles and links mega.bin."""
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS  # noqa: E402
from font5x7 import FONT  # noqa: E402

FM_RATE = 7670453 / 144          # NTSC YM2612 sample rate


def vram(addr):
    return 0x40000000 | ((addr & 0x3FFF) << 16) | (addr >> 14)


def md(r, g, b):                 # 0..7 per channel -> Mega Drive colour word
    return (b << 9) | (g << 5) | (r << 1)


def fm_freq(hz):
    for block in range(8):
        fnum = round(hz * 2 ** 20 / FM_RATE / 2 ** (block - 1))
        if fnum < 2048:
            return (block << 11) | fnum
    return (7 << 11) | 2047          # out of range: clamp (unused notes)


def midi_hz(m):
    return 440 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- FM patches
SLOT = {1: 0, 2: 8, 3: 4, 4: 12}         # operator -> register offset


def op(mul=1, dt=0, tl=127, ar=31, rs=0, d1r=0, d2r=0, d1l=0, rr=15):
    return dict(mul=mul, dt=dt, tl=tl, ar=ar, rs=rs, d1r=d1r, d2r=d2r, d1l=d1l, rr=rr)


L, R, C = 0x80, 0x40, 0xC0
PAD = dict(alg=4, fb=2, ops={       # soft, slow-attack, slightly detuned pad
    1: op(mul=1, dt=1, tl=42, ar=14, d1r=2, d1l=2, rr=5),
    2: op(mul=1, dt=3, tl=30, ar=11, d1r=1, d1l=1, rr=4),
    3: op(mul=2, dt=7, tl=50, ar=14, d1r=2, d1l=2, rr=5),
    4: op(mul=1, dt=5, tl=32, ar=10, d1r=1, d1l=1, rr=4)})

PATCHES = {
    # ch1: slap-ish synth bass. Serial algorithm, modulators decay = "filter" sweep
    (0, 0, C): dict(alg=0, fb=6, ops={
        1: op(mul=1, tl=26, d1r=10, d1l=2, rr=15),
        3: op(mul=2, tl=38, d1r=12, d1l=3, rr=15),
        2: op(mul=1, tl=30, d1r=14, d1l=4, rr=15),
        4: op(mul=1, tl=4, d1r=6, d2r=3, d1l=2, rr=10)}),
    # ch2: soft electric piano: body pair + a quickly fading "tine" pair
    (0, 1, C): dict(alg=4, fb=3, ops={
        1: op(mul=1, tl=36, d1r=8, d1l=4, rr=8),
        2: op(mul=1, tl=22, ar=26, d1r=6, d2r=2, d1l=3, rr=7),
        3: op(mul=14, dt=3, tl=48, d1r=16, d1l=15, rr=10),
        4: op(mul=1, tl=28, ar=28, d1r=8, d2r=3, d1l=4, rr=7)}),
    # ch3, ch4, ch5: pad chord spread left / centre / right
    (0, 2, L): PAD, (1, 0, C): PAD, (1, 1, R): PAD,
}

ym_init = [(0, 0x22, 0), (0, 0x27, 0), (0, 0x2B, 0)]
ym_init += [(0, 0x28, c) for c in (0, 1, 2, 4, 5, 6)]
for (part, ch, pan), p in PATCHES.items():
    for n, o in p["ops"].items():
        r = ch + SLOT[n]
        ym_init += [(part, 0x30 + r, (o["dt"] << 4) | o["mul"]),
                    (part, 0x40 + r, o["tl"]),
                    (part, 0x50 + r, (o["rs"] << 6) | o["ar"]),
                    (part, 0x60 + r, o["d1r"]),
                    (part, 0x70 + r, o["d2r"]),
                    (part, 0x80 + r, (o["d1l"] << 4) | o["rr"]),
                    (part, 0x90 + r, 0)]
    ym_init += [(part, 0xB0 + ch, (p["fb"] << 3) | p["alg"]), (part, 0xB4 + ch, pan)]
ym_init += [(1, 0xB6, C), (0, 0x2B, 0x80)]       # channel 6 = DAC (samples), centre

# ---------------------------------------------------------------- drums
# hi-hat on the PSG; per frame: (0, noise control, noise attenuation)
hat = [(0, 0xE4, 4), (0, 0, 9), (0, 0, 15)]
END = [(0xFFFE, 0, 0)]

# ---------------------------------------------------------------- drum samples
Z80_CLOCK = 3579545
SAMPLE_RATE = Z80_CLOCK / 437          # Z80 play loop is 437 T-states per sample
random.seed(2026)


def to_u8(xs):
    return bytes(max(0, min(255, round(128 + 127 * math.tanh(1.4 * x)))) for x in xs)


def kick_sample(secs=0.16):
    out, phase = [], 0.0
    for i in range(int(secs * SAMPLE_RATE)):
        t = i / SAMPLE_RATE
        phase += 2 * math.pi * (45 + 160 * math.exp(-t / 0.028)) / SAMPLE_RATE
        click = random.uniform(-1, 1) * math.exp(-t / 0.002) * 0.4
        out.append(math.sin(phase) * math.exp(-t / 0.085) + click)
    return to_u8(out)


def snare_sample(secs=0.18):
    out, prev = [], 0.0
    for i in range(int(secs * SAMPLE_RATE)):
        t = i / SAMPLE_RATE
        body = (math.sin(2 * math.pi * 185 * t) + 0.5 * math.sin(2 * math.pi * 330 * t)) \
            * math.exp(-t / 0.035) * 0.55
        n = random.uniform(-1, 1)
        noise = (n - 0.6 * prev) * math.exp(-t / 0.055) * 0.75   # slightly bright noise
        prev = n
        out.append(body + noise)
    return to_u8(out)


# Z80 sample player (hand-assembled). Waits for a sample id at $1FF0, looks up
# (start, length) at $1F00 + id*4, streams bytes to the YM2612 DAC ($4001).
# The 68000 leaves the YM address latch on $2A (DAC data) after its own writes.
Z80_DRIVER = bytes([
    0xF3,                   # 0000 di
    0x31, 0x00, 0x20,       # 0001 ld sp,$2000
    0x3A, 0xF0, 0x1F,       # 0004 main: ld a,($1FF0)
    0xB7,                   # 0007 or a
    0x28, 0xFA,             # 0008 jr z,main
    0x87, 0x87,             # 000A fetch: add a,a ; add a,a
    0x6F, 0x26, 0x1F,       # 000C ld l,a ; ld h,$1F
    0xAF, 0x32, 0xF0, 0x1F, # 000F xor a ; ld ($1FF0),a
    0x5E, 0x23, 0x56, 0x23, # 0013 ld e,(hl) ; inc hl ; ld d,(hl) ; inc hl
    0x4E, 0x23, 0x46,       # 0017 ld c,(hl) ; inc hl ; ld b,(hl)
    0xEB,                   # 001A ex de,hl
    0x7E,                   # 001B play: ld a,(hl)
    0x32, 0x01, 0x40,       # 001C ld ($4001),a
    0x23, 0x0B,             # 001F inc hl ; dec bc
    0x3A, 0xF0, 0x1F,       # 0021 ld a,($1FF0)
    0xB7,                   # 0024 or a
    0x20, 0xE3,             # 0025 jr nz,fetch   (new hit cuts the old one)
    0x78, 0xB1,             # 0027 ld a,b ; or c
    0x28, 0x07,             # 0029 jr z,done
    0x16, 0x16,             # 002B ld d,22
    0x15, 0x20, 0xFD,       # 002D delay: dec d ; jr nz,delay
    0x18, 0xE9,             # 0030 jr play
    0x3E, 0x80,             # 0032 done: ld a,$80
    0x32, 0x01, 0x40,       # 0034 ld ($4001),a
    0x18, 0xCB,             # 0037 jr main
])
z80 = bytearray(8192)
z80[0:len(Z80_DRIVER)] = Z80_DRIVER
addr = 0x40
for sid, smp in ((1, kick_sample()), (2, snare_sample())):
    z80[addr:addr + len(smp)] = smp
    z80[0x1F00 + sid * 4:0x1F04 + sid * 4] = bytes([addr & 0xFF, addr >> 8,
                                                    len(smp) & 0xFF, len(smp) >> 8])
    addr += len(smp)
assert addr < 0x1F00, addr
z80_blob = list(z80)

# ---------------------------------------------------------------- pads
PAD_FROM_BAR = 16
VOICINGS = {"A": (57, 60, 64), "F": (53, 57, 60), "C": (55, 60, 64),
            "G": (55, 59, 62), "E": (56, 59, 64)}
chord_names = list(VOICINGS)
chordtab = [n for name in chord_names for n in VOICINGS[name]]
song_rows = ticks()
for bar, root in enumerate(ROOTS):
    pad = [0] * 16
    if bar >= PAD_FROM_BAR:
        pad[0] = 2 + chord_names.index(root)
        if bar == len(ROOTS) - 1:
            pad[14] = 1
    for i in range(16):
        song_rows[bar * 16 + i].append(pad[i])
for row in song_rows[len(ROOTS) * 16:]:
    row.append(0)

# ---------------------------------------------------------------- graphics


def tile(pixel):                 # pixel(x, y) -> colour index 0..15
    words = []
    for y in range(8):
        v = 0
        for x in range(8):
            v = (v << 4) | pixel(x, y)
        words += [v >> 16, v & 0xFFFF]
    return words


tiles = [tile(lambda x, y: 0)]                                   # 0: empty
for k in range(4):                                               # 1-4: (spare)
    tiles.append(tile(lambda x, y: 0))
for c in (2, 3, 4, 5):                                           # 5-8: meter blocks
    tiles.append(tile(lambda x, y, c=c: c if 1 <= y <= 6 else 0))
while len(tiles) < 32:
    tiles.append(tile(lambda x, y: 0))
for code in range(32, 96):                                       # 32-95: font
    rows = [int(h, 16) for h in FONT.get(chr(code), "00 00 00 00 00 00 00").split()]
    tiles.append(tile(lambda x, y, rows=rows:
                      1 if y < 7 and 1 <= x <= 5 and rows[y] >> (5 - x) & 1 else 0))

# 96-111: a glowing orb, 32x32, as a 4x4-tile sprite. Its pixels are palette 3 colour 14:
# in shadow/highlight mode that colour isn't drawn, it LIGHTS UP whatever is underneath.
ORB_TILE = len(tiles)
for tx in range(4):                    # sprites store their tiles column by column
    for ty in range(4):
        tiles.append(tile(lambda x, y, tx=tx, ty=ty:
                          14 if (tx * 8 + x - 15.5) ** 2 + (ty * 8 + y - 15.5) ** 2 < 15.5 ** 2 else 0))
while len(tiles) < 128:
    tiles.append(tile(lambda x, y: 0))

# ---- the parallax scene on plane B: 512 x 224, palette 1, cut into deduplicated tiles
SCENE_W, SCENE_H = 512, 224
MOUNT_Y, HILL_Y, GROUND_Y = 80, 136, 172      # bands that scroll at their own speeds


def wave(x, terms):
    return sum(a * math.sin(2 * math.pi * k * x / SCENE_W + ph) for k, a, ph in terms)


scene = [[0] * SCENE_W for _ in range(SCENE_H)]
for x in range(SCENE_W):
    top = round(104 + wave(x, [(3, 13, 1.0), (7, 8, 0.0), (13, 4, 2.0)]))
    slope = wave(x + 1, [(3, 13, 1.0), (7, 8, 0.0), (13, 4, 2.0)]) - wave(x, [(3, 13, 1.0), (7, 8, 0.0), (13, 4, 2.0)])
    for y in range(MOUNT_Y, HILL_Y):                              # far mountains, snowy peaks
        if y >= top:
            scene[y][x] = 6 if (y < top + 3 and top < 98) else (2 if slope < 0 else 3)
    hill = round(150 + wave(x, [(4, 8, 0.5), (9, 5, 1.0)]))
    for y in range(HILL_Y, GROUND_Y):                             # nearer hills
        scene[y][x] = 4 if y < hill else (7 if y == hill else 5)
    for y in range(GROUND_Y, SCENE_H):                            # the ground: a checkerboard
        scene[y][x] = 10 if y == GROUND_Y else 8 + (((x // 32) + (y - GROUND_Y) // 6) % 2)

plane_b = [0] * (64 * 32)
scene_tiles = {}
for ty in range(SCENE_H // 8):
    for tx in range(SCENE_W // 8):
        px = tuple(scene[ty * 8 + y][tx * 8 + x] for y in range(8) for x in range(8))
        if not any(px):
            continue
        if px not in scene_tiles:
            scene_tiles[px] = len(tiles)
            tiles.append(tile(lambda x, y, px=px: px[y * 8 + x]))
        plane_b[ty * 64 + tx] = (1 << 13) | scene_tiles[px]       # palette 1, low priority
assert len(tiles) < 1536, len(tiles)
tile_words = [w for t in tiles for w in t]

# per-line scroll speed in 1/16 px per frame: sky still, slow mountains, faster hills,
# and the ground faster line by line toward the bottom: a fake-perspective floor
speedtab = []
for y in range(SCENE_H):
    if y < MOUNT_Y:
        speedtab.append(0)
    elif y < HILL_Y:
        speedtab.append(4)
    elif y < GROUND_Y:
        speedtab.append(10)
    else:
        speedtab.append(16 + (y - GROUND_Y) * 48 // (SCENE_H - GROUND_Y))

# ---- plane A: text + meters, HIGH priority so shadow mode leaves them at full brightness
plane_a = [0] * (64 * 32)
PRIO = 0x8000


def text(row, s, pal, col=None):
    col = (40 - len(s)) // 2 if col is None else col
    for i, ch in enumerate(s):
        plane_a[row * 64 + col + i] = PRIO | (pal << 13) | ord(ch)


text(1, "MEGA JAMS", 1)            # palette 1 colour 1 = yellow
text(2, "FM, DAC, PARALLAX, SHADOW + HIGHLIGHT", 3)
METER_ROWS = {"BASS": 4, "ARP": 5, "PADS": 6, "DRUMS": 7}
for label, row in METER_ROWS.items():
    text(row, label, 0, col=3)
text(27, "GROOVE BY CLAUDE, 2026", 3)
meter_cmds = [vram(0xC000 + (row * 64 + 10) * 2) for row in
              (METER_ROWS["BASS"], METER_ROWS["ARP"], METER_ROWS["DRUMS"], METER_ROWS["PADS"])]
meter_tiles = [PRIO | t for t in (5, 6, 7, 8)]           # bass, arp, drums, pads

# ---- sprites: five orbs over the mountains that light up on the kick, and a moon
ORBS = [(24, 92), (88, 104), (152, 88), (216, 100), (280, 94)]
MOON = (264, 40)
SPRITE_ATTR = PRIO | (3 << 13) | ORB_TILE                # palette 3: the highlight operator

palette = [0] * 64
palette[0:6] = [md(0, 0, 0), md(7, 7, 7), md(2, 7, 2), md(6, 2, 7), md(7, 7, 1), md(7, 4, 1)]
palette[16:27] = [0, md(7, 7, 2), md(4, 3, 6), md(3, 2, 5), md(1, 2, 4), md(2, 4, 4), md(7, 7, 7),
                  md(3, 6, 5), md(4, 2, 5), md(2, 1, 3), md(6, 4, 7)]   # the scene
palette[49] = md(3, 7, 7)        # pal 3: cyan (colours 14/15 are the highlight/shadow operators)

# ---- sky: palette 2 holds a 16-step colour ramp; the per-line interrupt picks a step
# for each line by rewriting the BACKDROP REGISTER ($87xx). A register write never makes
# "CRAM dots" (writing palette memory mid-line does). The kick flash swaps in a brighter
# ramp during V-blank.
skyidx = []
for i in range(256):
    a = 2 * math.pi * i / 256
    bar = max(0.0, math.sin(3 * a)) ** 4
    skyidx.append(max(0, min(15, round(2 + 2 * math.sin(a) + 11 * bar))))
skypals = []
for level in range(8):
    for k in range(16):
        f = k / 15
        r = 1 + 4 * f * f + level * 0.45
        g = 0.2 + 1.5 * f * f + level * 0.3
        b_ = 2 + 4 * f + level * 0.45
        skypals.append(md(*(max(0, min(7, round(v))) for v in (r, g, b_))))
palette[32:48] = skypals[0:16]

VDP_REGS = [0x8014,              # line interrupt on
            0x8174, 0x8230, 0x832C, 0x8407, 0x855C, 0x8600, 0x8700,
            0x8800, 0x8900, 0x8A00,  # line interrupt on every line
            0x8B03,              # per-line horizontal scroll
            0x8C89,              # H40 + shadow/highlight
            0x8D2F, 0x8E00, 0x8F02, 0x9001, 0x9100, 0x9200]

# ---------------------------------------------------------------- emit
# PATCHTEST=1: a fixed sequence of single patches for measuring against other engines
# (see tools in ../compare): bass A2 E2 A3, e-piano A3 A4 E5, the C pad chord; each held
# 8 ticks with silence between. Writes patchtest.bin instead of mega.bin.
PATCHTEST = os.environ.get("PATCHTEST") == "1"
if PATCHTEST:
    song_rows = [[0, 0, 0, 0] for _ in range(120)]
    t = 4
    for n in (45, 40, 57):                       # bass
        song_rows[t][0] = n; song_rows[t + 8][0] = 1; t += 12
    for n in (57, 69, 76):                       # e-piano (channel 2)
        song_rows[t][1] = n; song_rows[t + 8][1] = 1; t += 12
    song_rows[t][3] = 2 + chord_names.index("C"); song_rows[t + 16][3] = 1   # pad chord
song = [b for row in song_rows for b in row]
freqtab = [fm_freq(midi_hz(m)) for m in range(128)]


def words(label, data, per=16):
    out = [f"{label}:"]
    for i in range(0, len(data), per):
        out.append("        .word " + ", ".join(f"0x{v:04X}" for v in data[i:i + per]))
    return "\n".join(out)


def longs(label, data):
    return f"{label}:\n        .long " + ", ".join(f"0x{v:08X}" if isinstance(v, int) else v for v in data)


def bytes_(label, data, per=24):
    out = [f"{label}:"]
    for i in range(0, len(data), per):
        out.append("        .byte " + ", ".join(f"0x{v:02X}" for v in data[i:i + per]))
    out.append("        .balign 2      | keep whatever follows on an even address (68000 words)")
    return "\n".join(out)


def drumseq(label, seq):
    return words(label, [w for kf, nc, na in seq + END for w in (kf, (nc << 8) | na)], 8)


with open(os.path.join(HERE, "gen_equ.s"), "w") as f:
    f.write(f"""| generated by build.py
        .equ CMD_PLANE_A, 0x{vram(0xC000):08X}
        .equ CMD_PLANE_B, 0x{vram(0xE000):08X}
        .equ CMD_HSCROLL_B, 0x{vram(0xBC02):08X}
        .equ CMD_PAL1_C1, 0x{0xC0000000 | (34 << 16):08X}
        .equ TILE_WORDS, {len(tile_words)}
        .equ VDP_REG_COUNT, {len(VDP_REGS)}
        .equ CMD_SPRITES, 0x{vram(0xB800):08X}
        .equ SPRITE_ATTR, 0x{SPRITE_ATTR:04X}
        .equ Z80_BLOB_LEN, {len(z80_blob)}
""")


def pad(s, n):
    assert len(s) <= n
    return s.ljust(n)


with open(os.path.join(HERE, "gen_header.s"), "w") as f:
    f.write("| generated by build.py: cartridge header at 0x100\n")
    for s, n in (("SEGA MEGA DRIVE", 16), ("(C)CLDE 2026.NOV", 16),
                 ("MEGA JAMS", 48), ("MEGA JAMS", 48), ("GM 00000000-00", 14)):
        f.write(f'        .ascii "{pad(s, n)}"\n')
    f.write('        .word 0\n')
    f.write(f'        .ascii "{pad("J", 16)}"\n')
    f.write('        .long 0, rom_end-1, 0xFF0000, 0xFFFFFF\n')
    for s, n in (("", 12), ("", 12), ("", 40), ("JUE", 16)):
        f.write(f'        .ascii "{pad(s, n)}"\n')

with open(os.path.join(HERE, "gen_data.s"), "w") as f:
    f.write("\n\n".join([
        "| generated by build.py",
        words("vdp_regs", VDP_REGS),
        words("palette", palette),
        words("freqtab", freqtab),
        longs("meter_cmds", meter_cmds),
        words("meter_tiles", meter_tiles),
        drumseq("hat_seq", hat),
        bytes_("chordtab", chordtab),
        bytes_("z80_blob", z80_blob, 32),
        words("skypals", skypals),
        bytes_("skyidx", skyidx),
        words("speedtab", speedtab),
        words("orbs", [v for x, y in ORBS for v in (x, y)]),
        words("moon", list(MOON)),
        words("tiles", tile_words),
        words("plane_a", plane_a, 32),
        words("plane_b", plane_b, 32),
        bytes_("ym_init", [b for t in ym_init for b in t] + [0xFF]),
        bytes_("song", song) + "\nsong_end:",
        "        .balign 2",
    ]) + "\n")

subprocess.run(["m68k-elf-as", "-m68000", "-o", "main.o", "main.s"], cwd=HERE, check=True)
OUT = "patchtest.bin" if PATCHTEST else "mega.bin"
subprocess.run(["m68k-elf-ld", "-Ttext=0", "--oformat", "binary", "-o", OUT, "main.o"],
               cwd=HERE, check=True)
size = os.path.getsize(os.path.join(HERE, OUT))
print(f"{OUT}: {size} bytes; samples end at Z80 ${addr:04X}, "
      f"sample rate {SAMPLE_RATE:.0f} Hz")
