#!/usr/bin/env python3
"""Build MSX JAMS: a 16 KB MSX cartridge for the AY-3-8910 PSG.

  channel A: "buzz bass" - the tone is off and the hardware ENVELOPE runs as a fast
             repeating sawtooth whose repeat rate IS the bass note (the classic AY trick)
  channel B: the arpeggio, a square wave with a software volume decay
  channel C: drums - a falling tone for the kick, noise for snare and hat

Runs on C-BIOS (a free MSX BIOS), so no copyrighted ROMs are needed. There is no Z80
assembler in Homebrew, so this file has a small one: the program is written below as
Python calls that emit Z80 machine code, with labels resolved in a second pass.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks  # noqa: E402

PSG_CLOCK = 3579545 / 2          # 1.79 MHz on an MSX


# ---------------------------------------------------------------- a tiny Z80 assembler
class Z80:
    R = {"b": 0, "c": 1, "d": 2, "e": 3, "h": 4, "l": 5, "(hl)": 6, "a": 7}
    RR = {"bc": 0x00, "de": 0x10, "hl": 0x20, "sp": 0x30}
    PP = {"bc": 0xC5, "de": 0xD5, "hl": 0xE5, "af": 0xF5}
    CC = {"nz": 0, "z": 1, "nc": 2, "c": 3}

    def __init__(self, org):
        self.org, self.items = org, []

    def b(self, *v): self.items += list(v)
    def w(self, v): self.items.append(("w", v))
    def label(self, n): self.items.append(("label", n))

    # loads
    def ld(self, d, s):
        R, RR = self.R, self.RR
        if d in R and s in R: self.b(0x40 + R[d] * 8 + R[s])
        elif d in R: self.b(0x06 + R[d] * 8, s)                       # ld r,n
        elif d in RR: self.b(0x01 + RR[d]); self.w(s)                  # ld rr,nn
        elif d == "(nn)" and s == "a": self.b(0x32); self.w(self._nn)
        elif d == "(nn)" and s == "hl": self.b(0x22); self.w(self._nn)
        else: raise ValueError((d, s))

    def ld_a_mem(self, addr): self.b(0x3A); self.w(addr)
    def ld_mem_a(self, addr): self.b(0x32); self.w(addr)
    def ld_hl_mem(self, addr): self.b(0x2A); self.w(addr)
    def ld_mem_hl(self, addr): self.b(0x22); self.w(addr)
    def ld_a_de(self): self.b(0x1A)

    # arithmetic
    def inc(self, r): self.b(0x03 + self.RR[r]) if r in self.RR else self.b(0x04 + self.R[r] * 8)
    def dec(self, r): self.b(0x0B + self.RR[r]) if r in self.RR else self.b(0x05 + self.R[r] * 8)
    def add_hl(self, rr): self.b(0x09 + self.RR[rr])
    def alu(self, op, x):
        base = {"add": 0x80, "sub": 0x90, "and": 0xA0, "xor": 0xA8, "or": 0xB0, "cp": 0xB8}[op]
        if x in self.R: self.b(base + self.R[x])
        else: self.b(base + 0x46, x)                                   # immediate form
    def rlca(self): self.b(0x07)

    # control flow
    def jp(self, t, cc=None): self.b(0xC3 if cc is None else 0xC2 + self.CC[cc] * 8); self.w(t)
    def jr(self, t, cc=None): self.b(0x18 if cc is None else 0x20 + self.CC[cc] * 8); self.items.append(("r", t))
    def djnz(self, t): self.b(0x10); self.items.append(("r", t))
    def call(self, t): self.b(0xCD); self.w(t)
    def ret(self, cc=None): self.b(0xC9 if cc is None else 0xC0 + self.CC[cc] * 8)
    def push(self, rr): self.b(self.PP[rr])
    def pop(self, rr): self.b(self.PP[rr] - 4)

    # i/o and misc
    def out(self, port): self.b(0xD3, port)                            # out (n),a
    def inp(self, port): self.b(0xDB, port)                            # in a,(n)
    def otir(self): self.b(0xED, 0xB3)
    def ldir(self): self.b(0xED, 0xB0)
    def di(self): self.b(0xF3)
    def ex_de_hl(self): self.b(0xEB)

    def assemble(self):
        labels, pc = {}, self.org
        for it in self.items:
            if isinstance(it, tuple):
                if it[0] == "label": labels[it[1]] = pc
                else: pc += 2 if it[0] == "w" else 1
            else: pc += 1
        out = bytearray()
        val = lambda v: labels[v] if isinstance(v, str) else v  # noqa: E731
        for it in self.items:
            if not isinstance(it, tuple): out.append(it & 0xFF); continue
            if it[0] == "w":
                v = val(it[1]); out += bytes([v & 0xFF, (v >> 8) & 0xFF])
            elif it[0] == "r":
                off = val(it[1]) - (self.org + len(out) + 1)
                assert -128 <= off < 128, ("jr out of range", it[1])
                out.append(off & 0xFF)
        return bytes(out), labels


# ---------------------------------------------------------------- data
def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


tone_period = [max(1, min(4095, round(PSG_CLOCK / (16 * hz(m))))) for m in range(128)]
env_period = [max(1, min(65535, round(PSG_CLOCK / (256 * hz(m))))) for m in range(128)]   # sawtooth shape 8

rows = ticks()                                   # [bass, arp, drum] per 16th
song = [v for r in rows for v in r]

MIX_IDLE = 0b10111101                            # MSX needs bit7=1, bit6=0; tone A off, tone B on
MIX_KICK = 0b10111001                            # + tone C
MIX_NOISE = 0b10011101                           # + noise C
# per drum, 8 frames of (mixer, tone lo, tone hi, noise period, volume); volume 0 = done
DRUMS = []
for f, v in zip((180, 260, 360, 480, 620, 780, 900, 1000), (15, 14, 12, 10, 8, 6, 3, 0)):   # kick
    DRUMS.append((MIX_KICK, f & 0xFF, f >> 8, 0, v))
for v in (14, 12, 10, 8, 6, 4, 2, 0):                                                        # snare
    DRUMS.append((MIX_NOISE, 0, 0, 7, v))
for v in (9, 5, 2, 0, 0, 0, 0, 0):                                                           # hat
    DRUMS.append((MIX_NOISE, 0, 0, 1, v))
drum_tab = [b for d in DRUMS for b in d]
ARP_ENV = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 3, 2, 2, 1, 1, 0]

# screen 1 (32 x 24 tiles). Chars 128/136/144 are meter blocks (one colour group each);
# chars 160..223 form a rainbow band whose 8 colour groups rotate every frame.
name = [32] * 768


def text(row, s, col=None):
    col = (32 - len(s)) // 2 if col is None else col
    for i, ch in enumerate(s):
        name[row * 32 + col + i] = ord(ch)


for row in (1, 22):                              # rainbow bands, 4 chars per colour group
    for c in range(32):
        name[row * 32 + c] = 160 + (c // 4 % 8) * 8
text(4, "MSX JAMS")
text(6, "AY-3-8910 PSG, BUZZ BASS")
text(10, "BASS", 3); text(12, "ARP", 3); text(14, "DRUMS", 3)
text(19, "GROOVE BY CLAUDE, 2026")
METER_ADDR = [0x1800 + row * 32 + 10 for row in (10, 12, 14)]
METER_CHAR = [128, 136, 144]

block = [0x00, 0x7E, 0x7E, 0x7E, 0x7E, 0x7E, 0x7E, 0x00]
patterns = []
for ch in range(128, 224):
    patterns += block if ch in (128, 136, 144) or ch >= 160 else [0] * 8

# TMS9918 colours: 1 black, 2 green, 3 light green, 4 dark blue, 5 light blue, 6 dark red,
# 7 cyan, 8 red, 9 light red, 10 dark yellow, 11 light yellow, 12 dark green, 13 magenta, 14 grey, 15 white
colour = [0xF4] * 32                             # text: white on dark blue
colour[16], colour[17], colour[18] = 0x34, 0xD4, 0xB4    # meters: green, magenta, yellow
RAINBOW = [0x84, 0x94, 0xB4, 0x34, 0x74, 0x54, 0xD4, 0x64]
cycle = RAINBOW * 2

# ---------------------------------------------------------------- the program
RAM = 0xC000
FCNT, ROWPTR, ARPVOL, DRUMIDX, DRUMLEFT, METER, FLASH, PHASE = (
    RAM + 0, RAM + 1, RAM + 3, RAM + 4, RAM + 5, RAM + 6, RAM + 9, RAM + 10)
FRAMES_PER_TICK = 7

z = Z80(0x4000)
z.b(ord("A"), ord("B")); z.w("init"); z.w(0); z.w(0); z.w(0); z.b(*([0] * 6))   # cartridge header

z.label("init")
z.di()
z.ld("sp", 0xF380)
z.ld("a", 15); z.ld_mem_a(0xF3E9)               # FORCLR
z.ld("a", 4); z.ld_mem_a(0xF3EA); z.ld_mem_a(0xF3EB)   # BAKCLR, BDRCLR: dark blue
z.ld("a", 1); z.call(0x005F)                    # CHGMOD: screen 1, font loaded
z.di()
for src, dst, n in (("patterns", 128 * 8, len(patterns)), ("colours", 0x2000, 32),
                    ("names", 0x1800, 768), ("nosprites", 0x1B00, 1)):
    z.ld("hl", src); z.ld("de", dst); z.ld("bc", n); z.call(0x005C)    # LDIRVM
z.di()
z.ld("hl", RAM); z.ld("de", RAM + 1); z.ld("bc", 31); z.ld("(hl)", 0); z.ldir()   # clear vars
z.ld("hl", "song"); z.ld_mem_hl(ROWPTR)
z.ld("hl", "psg_init"); z.ld("b", 14); z.ld("c", 0)                # PSG registers 0..13
z.label("pi")
z.ld("a", "c"); z.out(0xA0); z.ld("a", "(hl)"); z.out(0xA1); z.inc("hl"); z.inc("c"); z.djnz("pi")

z.label("loop")                                  # ---- once per video frame
z.inp(0x99); z.alu("and", 0x80); z.jr("loop", "z")   # VDP status: frame flag (DI, so we poll)
z.call("music")
z.call("visuals")
z.jr("loop")


def psg(reg):                                    # write A to PSG register `reg`
    z.ld("e", "a"); z.ld("a", reg); z.out(0xA0); z.ld("a", "e"); z.out(0xA1)


# ---- music
z.label("music")
z.ld_a_mem(FCNT); z.alu("or", "a"); z.jp("frames", "nz")
z.ld_hl_mem(ROWPTR)                              # a new 16th: read bass, arp, drum
# bass
z.ld("a", "(hl)"); z.inc("hl"); z.alu("cp", 2); z.jr("b_notnote", "c")
z.push("hl"); z.ld("l", "a"); z.ld("h", 0); z.add_hl("hl"); z.ld("de", "env_tab"); z.add_hl("de")
z.ld("a", "(hl)"); psg(11); z.inc("hl"); z.ld("a", "(hl)"); psg(12)
z.ld("a", 8); psg(13)                             # sawtooth, repeating (writing it restarts the envelope)
z.ld("a", 0x10); psg(8)                           # channel A volume = the envelope
z.ld("a", 20); z.ld_mem_a(METER)
z.pop("hl"); z.jr("b_done")
z.label("b_notnote")
z.alu("cp", 1); z.jr("b_done", "nz")
z.ld("a", 0); psg(8)                              # release: silence channel A
z.label("b_done")
# arp
z.ld("a", "(hl)"); z.inc("hl"); z.alu("cp", 2); z.jr("a_done", "c")
z.push("hl"); z.ld("l", "a"); z.ld("h", 0); z.add_hl("hl"); z.ld("de", "tone_tab"); z.add_hl("de")
z.ld("a", "(hl)"); psg(2); z.inc("hl"); z.ld("a", "(hl)"); psg(3)
z.ld("a", 0); z.ld_mem_a(ARPVOL)
z.ld("a", 20); z.ld_mem_a(METER + 1)
z.pop("hl")
z.label("a_done")
# drum
z.ld("a", "(hl)"); z.inc("hl"); z.alu("or", "a"); z.jr("d_done", "z")
z.push("af")
z.dec("a"); z.rlca(); z.rlca(); z.rlca()        # (type-1) * 8 frames
z.ld_mem_a(DRUMIDX); z.ld("a", 8); z.ld_mem_a(DRUMLEFT)
z.ld("a", 20); z.ld_mem_a(METER + 2)
z.pop("af"); z.alu("cp", 1); z.jr("d_done", "nz")
z.ld("a", 6); z.ld_mem_a(FLASH)                   # kick: flash the border
z.label("d_done")
z.ld("de", "song_end"); z.ld("a", "l"); z.alu("cp", "e"); z.jr("r_save", "nz")
z.ld("a", "h"); z.alu("cp", "d"); z.jr("r_save", "nz")
z.ld("hl", "song")                                # loop the song
z.label("r_save")
z.ld_mem_hl(ROWPTR)

z.label("frames")                                 # ---- every frame
z.ld_a_mem(ARPVOL); z.ld("e", "a"); z.ld("d", 0); z.ld("hl", "arp_env"); z.add_hl("de")
z.ld("a", "(hl)"); psg(9)                         # channel B volume from the decay table
z.ld_a_mem(ARPVOL); z.alu("cp", 15); z.jr("av_ok", "z"); z.inc("a"); z.ld_mem_a(ARPVOL)
z.label("av_ok")
z.ld_a_mem(DRUMLEFT); z.alu("or", "a"); z.jr("dr_idle", "z")
z.dec("a"); z.ld_mem_a(DRUMLEFT)
z.ld_a_mem(DRUMIDX); z.ld("l", "a"); z.inc("a"); z.ld_mem_a(DRUMIDX)
z.ld("h", 0); z.ld("e", "l"); z.ld("d", 0)
z.add_hl("hl"); z.add_hl("hl"); z.add_hl("de")    # index * 5
z.ld("de", "drum_tab"); z.add_hl("de")
z.ld("a", "(hl)"); psg(7); z.inc("hl")            # mixer
z.ld("a", "(hl)"); psg(4); z.inc("hl")            # tone C lo
z.ld("a", "(hl)"); psg(5); z.inc("hl")            # tone C hi
z.ld("a", "(hl)"); psg(6); z.inc("hl")            # noise period
z.ld("a", "(hl)"); psg(10)                        # channel C volume
z.jr("dr_done")
z.label("dr_idle")
z.ld("a", 0); psg(10)
z.label("dr_done")
z.ld_a_mem(FCNT); z.inc("a"); z.alu("cp", FRAMES_PER_TICK); z.jr("fc_ok", "nz"); z.ld("a", 0)
z.label("fc_ok")
z.ld_mem_a(FCNT)
z.ret()


def vram_write_addr(addr):                       # set the VDP to write at `addr`
    z.ld("a", addr & 0xFF); z.out(0x99); z.ld("a", (addr >> 8) | 0x40); z.out(0x99)


# ---- visuals
z.label("visuals")
for k in range(3):                                # meters: 20 cells each
    vram_write_addr(METER_ADDR[k])
    z.ld_a_mem(METER + k); z.ld("d", "a"); z.ld("b", 20); z.ld("e", 0)
    z.label(f"m{k}")
    z.ld("a", "e"); z.alu("cp", "d"); z.ld("a", 32); z.jr(f"m{k}_off", "nc"); z.ld("a", METER_CHAR[k])
    z.label(f"m{k}_off")
    z.out(0x98); z.inc("e"); z.djnz(f"m{k}")
    z.ld_a_mem(METER + k); z.alu("or", "a"); z.jr(f"m{k}_z", "z"); z.dec("a"); z.ld_mem_a(METER + k)
    z.label(f"m{k}_z")
vram_write_addr(0x2000 + 20)                      # rainbow: rotate 8 colour groups
z.ld_a_mem(PHASE); z.inc("a"); z.alu("and", 63); z.ld_mem_a(PHASE)
z.rlca(); z.rlca(); z.rlca(); z.rlca(); z.rlca(); z.alu("and", 7)   # (phase >> 3) & 7
z.ld("e", "a"); z.ld("d", 0); z.ld("hl", "cycle"); z.add_hl("de")
z.ld("b", 8); z.ld("c", 0x98); z.otir()
z.ld_a_mem(FLASH); z.alu("or", "a"); z.ld("a", 0x04); z.jr("f_set", "z")   # border: dark blue,
z.ld_a_mem(FLASH); z.dec("a"); z.ld_mem_a(FLASH); z.ld("a", 0x0D)        # magenta on a kick
z.label("f_set")
z.out(0x99); z.ld("a", 0x87); z.out(0x99)         # VDP register 7
z.ret()

# ---- data
for lbl, data in (("psg_init", [0, 0, 0, 0, 0, 0, 0, MIX_IDLE, 0, 0, 0, 0, 0, 0]),
                  ("arp_env", ARP_ENV), ("drum_tab", drum_tab), ("cycle", cycle),
                  ("colours", colour), ("nosprites", [208]), ("patterns", patterns), ("names", name)):
    z.label(lbl); z.b(*data)
z.label("tone_tab")
for v in tone_period: z.w(v)
z.label("env_tab")
for v in env_period: z.w(v)
z.label("song"); z.b(*song); z.label("song_end")

rom, labels = z.assemble()
assert len(rom) <= 16384, len(rom)
rom += bytes([0xFF] * (16384 - len(rom)))
open(os.path.join(HERE, "msxjams.rom"), "wb").write(rom)
print(f"msxjams.rom: {labels['song_end'] - 0x4000} bytes used of 16 KB "
      f"(code {labels['psg_init'] - 0x4000} bytes)")
