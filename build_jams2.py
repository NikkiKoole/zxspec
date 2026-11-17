#!/usr/bin/env python3
"""Speccy Jams 2: a two-channel beeper engine in Z80 machine code + a tune.

Builds emulator/jams2.tap = BASIC loader + CODE block at 32768.

Engine: two 16-bit phase accumulators (ch1 = bass, ch2 = melody). Each sample
the top bit of each phase is sent to the speaker (port $FE bit 4), one after
the other, so the two square waves get time-multiplexed into one 1-bit output.
Each "row" of song data also sets the border colour and lights up piano keys
on screen via attribute pokes.
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from bas2tap import tokenize_program, tap_block  # noqa: E402

ORG = 32768
DUMMY = 0x5B00          # printer buffer: harmless place to "highlight"
KEY_ATTR = 56           # paper 7, ink 0
LOOP_T = 147            # T-states per sample loop (see asm below)
SAMPLE_RATE = 3546900 / LOOP_T

KICK_START, KICK_STEP = 30, 24
SNARE_LEN, SNARE_DELAY = 700, 7
HAT_LEN, HAT_DELAY = 400, 1
# T-states each drum steals from the music (so the tempo stays steady)
KICK_T = sum(110 * c + 55 for c in range(KICK_START, 256, KICK_STEP)) + 60
SNARE_T = SNARE_LEN * (63 + 13 * SNARE_DELAY) + 80
HAT_T = HAT_LEN * (63 + 13 * HAT_DELAY) + 80
DRUM_SAMPLES = {1: KICK_T / LOOP_T, 2: SNARE_T / LOOP_T, 3: HAT_T / LOOP_T}

# ---------------------------------------------------------------- assembler
code = []               # list of ints, ("w", label) or ("label", name)


def emit(*items):
    for it in items:
        code.append(it)


def label(name):
    code.append(("label", name))


def w(name):
    """little-endian 16-bit reference to a label (or int)."""
    code.append(("w", name))


def r(name):
    """relative jump offset (jr/djnz) to a label."""
    code.append(("r", name))


SIZE = {"label": 0, "w": 2, "r": 1}


def assemble(extra_labels):
    labels, pc = dict(extra_labels), ORG
    for it in code:
        if isinstance(it, tuple):
            if it[0] == "label":
                labels[it[1]] = pc
            pc += SIZE[it[0]]
        else:
            pc += 1
    out = bytearray()
    for it in code:
        if isinstance(it, tuple):
            if it[0] == "w":
                v = it[1] if isinstance(it[1], int) else labels[it[1]]
                out += struct.pack("<H", v)
            elif it[0] == "r":
                off = labels[it[1]] - (ORG + len(out) + 1)
                assert -128 <= off < 128, it
                out.append(off & 0xFF)
        else:
            out.append(it)
    return bytes(out), labels


def restore_highlights():
    emit(0x3E, KEY_ATTR)                              # ld a,56
    for v in ("old1", "old2", "old3", "old4"):
        emit(0x2A); w(v); emit(0x77)                  # ld hl,(oldN) ; ld (hl),a


label("start")
emit(0xF3)                                            # di
emit(0x21); w("song"); emit(0x22); w("ptr")           # ld hl,song ; ld (ptr),hl
emit(0x21); w(DUMMY)                                  # ld hl,DUMMY
for v in ("old1", "old2", "old3", "old4"):
    emit(0x22); w(v)                                  # ld (oldN),hl

label("row")
emit(0x3E, 0x7F, 0xDB, 0xFE, 0x1F)                    # ld a,$7f ; in a,($fe) ; rra
emit(0xD2); w("done")                                 # jp nc,done  (SPACE pressed)
restore_highlights()
emit(0x2A); w("ptr")                                  # ld hl,(ptr)
emit(0x5E, 0x23, 0x56, 0x23)                          # ld e,(hl) ; inc hl ; ld d,(hl) ; inc hl
emit(0x7A, 0xB3)                                      # ld a,d ; or e
emit(0xCA); w("done")                                 # jp z,done   (end of song)
emit(0xD5)                                            # push de     (duration)
emit(0x5E, 0x23, 0x56, 0x23)                          # de = freq1
emit(0x4E, 0x23, 0x46, 0x23)                          # bc = freq2
emit(0x7E, 0x23)                                      # ld a,(hl) ; inc hl  (border)
emit(0x32); w("bord1")                                # ld (bord1),a
emit(0x32); w("bord2")                                # ld (bord2),a
emit(0xD5, 0xC5)                                      # push de ; push bc
for o1, o2 in (("old1", "old2"), ("old3", "old4")):
    emit(0x5E, 0x23, 0x56, 0x23)                      # de = addr A
    emit(0xED, 0x53); w(o1)                           # ld (o1),de
    emit(0x4E, 0x23, 0x46, 0x23)                      # bc = addr B
    emit(0xED, 0x43); w(o2)                           # ld (o2),bc
    emit(0x7E, 0x23, 0x12, 0x02)                      # ld a,(hl) ; inc hl ; ld (de),a ; ld (bc),a
emit(0x7E, 0x23)                                      # ld a,(hl) ; inc hl   (drum)
emit(0x22); w("ptr")                                  # ld (ptr),hl
for n, routine in ((1, "kick"), (2, "snare"), (3, "hat")):
    emit(0xFE, n, 0xCC); w(routine)                   # cp n ; call z,routine (they return a=0)
emit(0xC1, 0xD1, 0xFD, 0xE1)                          # pop bc ; pop de ; pop iy
emit(0x2A); w("ph1")                                  # ld hl,(ph1)
emit(0xDD, 0x2A); w("ph2")                            # ld ix,(ph2)

label("loop")                                         # ---- 148 T per pass
emit(0x19)                                            # add hl,de        11
emit(0x7C, 0x0F, 0x0F, 0x0F, 0xE6, 0x10)              # ld a,h ; rrca x3 ; and $10
emit(0xF6); label("bord1"); emit(0)                   # or border (self-modified)
emit(0xD3, 0xFE)                                      # out ($fe),a
emit(0xDD, 0x09)                                      # add ix,bc        15
emit(0xDD, 0x7C, 0xC6, 0x20, 0x9F, 0xE6, 0x10)        # ld a,ixh ; add a,$20 ; sbc a,a ; and $10
                                                      #  -> 1/8 duty pulse: thin, quiet ch2
emit(0xF6); label("bord2"); emit(0)                   # or border
emit(0xD3, 0xFE)                                      # out ($fe),a
emit(0xFD, 0x2B)                                      # dec iy
emit(0xFD, 0x7C, 0xFD, 0xB5)                          # ld a,iyh ; or iyl
emit(0xC2); w("loop")                                 # jp nz,loop
emit(0x22); w("ph1")                                  # ld (ph1),hl
emit(0xDD, 0x22); w("ph2")                            # ld (ph2),ix
emit(0xC3); w("row")                                  # jp row

label("done")
restore_highlights()
emit(0xFD, 0x21); w(0x5C3A)                           # ld iy,$5c3a (BASIC needs it)
emit(0xAF, 0xD3, 0xFE)                                # xor a ; out ($fe),a
emit(0xFB, 0xC9)                                      # ei ; ret

# ---- kick: a square wave whose period grows -> falling "thump"
label("kick")
emit(0x3A); w("bord1")                                # ld a,(bord1)
emit(0x5F, 0xF6, 0x10, 0x57)                          # ld e,a (off) ; or $10 ; ld d,a (on)
emit(0x0E, KICK_START)                                # ld c,KICK_START
label("kc")
for out_reg, lp in ((0x7A, "k1"), (0x7B, "k2")):
    emit(out_reg, 0xD3, 0xFE, 0x41)                   # ld a,d/e ; out ($fe),a ; ld b,c
    label(lp)
    emit(0xE5, 0xE1, 0xE5, 0xE1, 0x10); r(lp)         # push hl ; pop hl (x2) ; djnz
emit(0x79, 0xC6, KICK_STEP, 0x4F)                     # ld a,c ; add a,STEP ; ld c,a
emit(0x30); r("kc")                                   # jr nc,kc
emit(0xAF, 0xC9)                                      # xor a ; ret

# ---- snare / hi-hat: bits of the ROM used as white noise
label("snare")
emit(0x11); w(SNARE_LEN); emit(0x3E, SNARE_DELAY)     # ld de,len ; ld a,delay
emit(0x18); r("noise")                                # jr noise
label("hat")
emit(0x11); w(HAT_LEN); emit(0x3E, HAT_DELAY)
label("noise")
emit(0x32); w("ndel")                                 # ld (ndel),a
emit(0x3A); w("bord1"); emit(0x4F)                    # ld a,(bord1) ; ld c,a
emit(0x2A); w("nptr")                                 # ld hl,(nptr)
label("n1")
emit(0x7E, 0x23, 0xE6, 0x10, 0xB1, 0xD3, 0xFE)        # ld a,(hl) ; inc hl ; and $10 ; or c ; out
emit(0x06); label("ndel"); emit(1)                    # ld b,delay (self-modified)
label("n2"); emit(0x10); r("n2")                      # djnz n2
emit(0x1B, 0x7A, 0xB3, 0x20); r("n1")                 # dec de ; ld a,d ; or e ; jr nz,n1
emit(0x7C, 0xE6, 0x3F, 0x67)                          # keep the pointer inside the ROM
emit(0x22); w("nptr")
emit(0xAF, 0xC9)

for v in ("nptr", "ptr", "old1", "old2", "old3", "old4", "ph1", "ph2"):
    label(v); emit(0, 0)
label("song")

# ---------------------------------------------------------------- the tune
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7,
        "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi(name):
    return NOTE[name[:-1]] + 12 * (int(name[-1]) + 1)


def freq_word(m):
    hz = 440 * 2 ** ((m - 69) / 12)
    return round(hz * 65536 / SAMPLE_RATE)


# keyboard on screen: 30 white keys, D2..E6, cols 1..30
WHITE = [0, 2, 4, 5, 7, 9, 11]
FIRST_WHITE = 7 * 3 + 1            # D2 counted in white keys from C-1


def key_cells(m, colour):
    """(addrA, addrB, value) to light up the key for midi note m."""
    octave, pc = divmod(m, 12)
    if pc in WHITE:
        wi = 7 * octave + WHITE.index(pc) - FIRST_WHITE
        col = 1 + wi
        return (22528 + 32 * 20 + col, 22528 + 32 * 21 + col, 64 + 8 * colour)
    wi = 7 * octave + WHITE.index(pc - 1) - FIRST_WHITE   # white key to the left
    col = 1 + wi
    return (22528 + 32 * 16 + col, 22528 + 32 * 16 + col + 1, 56 + colour)


# melody: (note, length in 16ths); bass chord roots per bar
MELODY_A = """
E5 4 A4 2 C5 2 E5 2 D5 2 C5 4 | A4 4 F4 2 A4 2 C5 4 A4 4 |
G4 2 C5 2 E5 4 G5 4 E5 4 | D5 6 B4 2 G4 4 B4 4 |
E5 4 A5 4 G5 2 E5 2 C5 4 | F5 4 E5 2 D5 2 C5 4 A4 4 |
B4 2 C5 2 D5 4 G5 4 F5 4 | E5 8 G#4 4 B4 4 |
"""
MELODY_B = """
A5 2 E5 2 C5 2 E5 2 A5 2 E5 2 C5 2 E5 2 | A5 2 F5 2 C5 2 F5 2 A5 4 C6 4 |
G5 2 E5 2 C5 2 E5 2 G5 2 E5 2 C6 4 | B5 4 A5 2 G5 2 D5 4 G5 4 |
E5 2 A5 2 B5 2 C6 2 B5 2 A5 2 E5 4 | F5 2 A5 2 C6 2 A5 2 F5 4 E5 4 |
D5 2 G5 2 B5 2 D6 2 C6 4 B5 4 | G#5 4 B5 4 E5 4 G#5 4 |
"""
ENDING = "A5 16"
ROOTS = "A F C G A F G E " * 4 + "A"


def parse(text):
    toks = text.replace("|", " ").split()
    return [(midi(toks[i]), int(toks[i + 1])) for i in range(0, len(toks), 2)]


melody = parse(MELODY_A) + parse(MELODY_A) + parse(MELODY_B) + parse(MELODY_B) + parse(ENDING)
roots = ROOTS.split()

MELODY = False               # melody muted; channel 2 plays a soft arpeggio instead
ARP_FROM_BAR = 8             # arpeggio enters when the snare does
SUB = 4                      # time units per 16th
UNIT = 0.0300                # seconds per unit  (~125 bpm)
total_units = sum(l for _, l in melody) * SUB
assert total_units == len(roots) * 16 * SUB, (total_units, len(roots))

mel = [None] * total_units
t = 0
for m, length in melody:
    for u in range(length * SUB - 1):          # short gap at the end of each note
        mel[t + u] = m
    t += length * SUB

bass = [None] * total_units
for bar, r in enumerate(roots):
    lo = midi(r + ("3" if r == "C" else "2"))
    start = bar * 16 * SUB
    if bar == len(roots) - 1:                  # last bar: hold the low root
        for u in range(16 * SUB - 2):
            bass[start + u] = lo
        continue
    for eighth in range(8):
        n = lo + (12 if eighth % 2 else 0)     # octave bounce
        for u in range(5):                     # staccato eighths
            bass[start + eighth * 2 * SUB + u] = n

# drums: 1 kick, 2 snare, 3 hi-hat, per 16th step of a bar
K, S, H = 1, 2, 3
GROOVES = {
    "intro": {0: K, 8: K, 4: H, 12: H},
    "verse": {0: K, 4: S, 8: K, 12: S, 2: H, 6: H, 10: H, 14: H},
    "drive": {0: K, 3: K, 4: S, 8: K, 10: K, 12: S, 2: H, 6: H, 14: H, 15: H},
    "fill":  {0: K, 4: S, 8: K, 10: S, 12: S, 13: S, 14: S, 15: S},
    "end":   {0: K},
}
arrangement = (["intro"] * 7 + ["fill"] + ["verse"] * 7 + ["fill"]
               + ["drive"] * 7 + ["fill"] + ["drive"] * 7 + ["fill"] + ["end"])
assert len(arrangement) == len(roots)
drum = [0] * total_units
for bar, groove in enumerate(arrangement):
    for step, d in GROOVES[groove].items():
        drum[bar * 16 * SUB + step * SUB] = d

# soft arpeggio: eighth notes up and down the chord, mid register
CHORDS = {"A": (57, 3), "F": (53, 4), "C": (60, 4), "G": (55, 4), "E": (52, 4)}  # root, 3rd
ARP_SHAPE = (0, 1, 2, 3, 2, 1, 0, 2)      # index into root, 3rd, 5th, octave
arp = [None] * total_units
for bar, rname in enumerate(roots):
    if bar < ARP_FROM_BAR:
        continue
    root, third = CHORDS[rname]
    tones = (root, root + third, root + 7, root + 12)
    start = bar * 16 * SUB
    if bar == len(roots) - 1:              # last bar: one long soft root
        for u in range(16 * SUB - 2):
            arp[start + u] = root + 12
        continue
    for eighth, idx in enumerate(ARP_SHAPE):
        for u in range(2 * SUB - 1):
            arp[start + eighth * 2 * SUB + u] = tones[idx]

rows = []
for u in range(total_units):
    b, m = bass[u], (mel[u] if MELODY else arp[u])
    lead = m or b
    colour = (2, 3, 5, 6)[lead % 4] if lead else 0   # border colour follows the music
    mk = key_cells(m, colour) if m else (DUMMY, DUMMY, 0)
    bk = key_cells(b, 4) if b else (DUMMY, DUMMY, 0)
    state = (freq_word(b) if b else 0, freq_word(m) if m else 0, colour, mk, bk)
    if rows and rows[-1][1] == state and not drum[u]:
        rows[-1][0] += 1
    else:
        rows.append([1, state, drum[u]])

song = bytearray()
carry = 0.0          # drum time that spilled past the end of a short row
for n_units, (f1, f2, border, mk, bk), d in rows:
    want = n_units * UNIT * SAMPLE_RATE - carry - DRUM_SAMPLES.get(d, 0)
    dur = max(1, round(want))
    carry = dur - want
    assert dur < 65536
    song += struct.pack("<HHHB", dur, f1, f2, border)
    song += struct.pack("<HHB", *mk) + struct.pack("<HHB", *bk) + bytes([d])
song += b"\x00\x00"

binary, labels = assemble({})
binary += song
assert len(binary) < 65536 - ORG

BASIC = """
10 REM SPECCY JAMS 2 - two channels on one beeper
20 CLEAR 32767: BORDER 0: PAPER 0: INK 7: BRIGHT 0: FLASH 0: CLS
30 LOAD "" CODE
40 GO SUB 7000
50 PRINT AT 3,0; INK 4;"     playing...  SPACE = stop     "
60 RANDOMIZE USR 32768
70 PRINT AT 3,0; INK 5;"   P = play again    Q = quit   "
80 LET i$=INKEY$: IF i$="" THEN GO TO 80
90 IF i$="p" OR i$="P" THEN GO TO 50
100 IF i$="q" OR i$="Q" THEN PRINT AT 3,0; INK 6;"     thanks for listening! :)   ": STOP
110 GO TO 80
7000 REM title + a 30-key piano, D2..E6
7010 PRINT AT 0,0; INK 6; BRIGHT 1;" *** S P E C C Y  J A M S 2 *** "
7020 PRINT AT 1,0; INK 5;"   bass + drums on one beeper   "
7030 PRINT AT 6,3; INK 4;"bass: octave-bouncing, green"
7040 PRINT AT 8,3; INK 3;"chords: soft thin arpeggio"
7045 PRINT AT 10,3; INK 6;"drums: kick, snare, hi-hat"
7050 PRINT AT 12,3; INK 2;"groove by Claude, 2026"
7060 FOR r=16 TO 21: PRINT AT r,1; PAPER 7; INK 0;"                              ": NEXT r
7070 INK 0: PAPER 7
7080 PLOT 8,0: DRAW 239,0: DRAW 0,47: DRAW -239,0: DRAW 0,-47
7090 FOR i=1 TO 29: PLOT 8+8*i,0: DRAW 0,47: NEXT i
7100 FOR i=0 TO 28: LET n=i-7*INT (i/7): IF n=1 OR n=5 THEN GO TO 7130
7110 LET b=16+8*i
7120 FOR j=-2 TO 2: PLOT b+j,20: DRAW 0,27: NEXT j
7130 NEXT i
7140 INK 7: PAPER 0
7150 RETURN
"""

prog = tokenize_program(BASIC)
code_header = (bytes([3]) + b"jams2code "
               + struct.pack("<HHH", len(binary), ORG, 32768))
basic_header = (bytes([0]) + b"jams2     "
                + struct.pack("<HHH", len(prog), 10, len(prog)))
tap = (tap_block(0x00, basic_header) + tap_block(0xFF, prog)
       + tap_block(0x00, code_header) + tap_block(0xFF, binary))
open(__file__.rsplit("/", 1)[0] + "/emulator/jams2.tap", "wb").write(tap)

seconds = sum(row[0] for row in rows) * UNIT
print(f"code {labels['song'] - ORG} bytes, song {len(song)} bytes "
      f"({len(rows)} rows, {seconds:.1f}s), sample rate {SAMPLE_RATE:.0f} Hz")
