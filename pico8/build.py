#!/usr/bin/env python3
"""Build PICO JAMS: the groove as a PICO-8 cart (picojams.p8).

Four channels, 32-row SFX (one SFX = 2 bars of 16ths at speed 14 ~ 129 bpm):
  ch0 bass (saw, plucked with a fade), ch1 arpeggio (triangle + reverb filter),
  ch2 pads (the fast-arpeggio effect turns a 4-note group into a shimmering chord),
  ch3 drums (a falling triangle for the kick, noise for snare and hat).
Identical 2-bar chunks share one SFX, so the whole song fits in PICO-8's 64 slots.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from groove import ticks, ROOTS, CHORDS  # noqa: E402

SPEED = 14                       # ticks per row: 14 x 183 / 22050 s = 0.116 s per 16th
BASE = 36                        # PICO-8 pitch 0 = C2 (MIDI 36)
TRI, SAW, ORGAN, NOISE = 0, 2, 5, 6
FADE_OUT, FADE_IN, DROP, ARP_FAST = 5, 4, 3, 6


def filters(reverb=0, dampen=0):
    # SFX byte 64 (since PICO-8 0.2.2): bit0 editor mode, bit1 noiz, bit2 buzz, then
    # detune, reverb and dampen as base-3 digits: detune*8 + reverb*24 + dampen*72
    return 1 + 24 * reverb + 72 * dampen


EMPTY = (0, 0, 0, 0)
rows = ticks()                   # [bass, arp, drum] per 16th; 1 = release, 2+ = MIDI note
n_bars = len(rows) // 16         # 33 bars of song + 1 silent bar
CHORD_OF = {}
for r, (root, third) in CHORDS.items():
    CHORD_OF[r] = (root, root + third, root + 7, root + 12)


def bass_rows(bar):
    out = []
    for i in range(16):
        m = rows[bar * 16 + i][0]
        last = bar == n_bars - 2
        if m >= 2:
            out.append((m - BASE, SAW, 6, 0 if last else FADE_OUT))
        elif last and out and 0 < i < 14 and out[-1][2]:
            out.append((out[-1][0], SAW, 5, 0))          # the held last note
        else:
            out.append(EMPTY)
    if bar == n_bars - 2:
        out[13] = (out[0][0], SAW, 4, FADE_OUT)
    return out


def arp_rows(bar):
    out = []
    for i in range(16):
        m = rows[bar * 16 + i][1]
        if m >= 2:
            out.append((m - BASE, TRI, 4, 0))
        elif out and out[-1] != EMPTY and out[-1][3] == 0 and rows[bar * 16 + i][1] == 0:
            out.append((out[-1][0], TRI, 2, FADE_OUT))  # a soft decay after each note
        else:
            out.append(EMPTY)
    return out


def pad_rows(bar):
    if bar < 16 or bar >= n_bars - 1:
        return [EMPTY] * 16
    chord = CHORD_OF[ROOTS[bar]]
    out = []
    for i in range(16):
        vol = 1 if i == 0 else 2                         # a slight swell in
        out.append((chord[i % 4] - BASE, ORGAN, vol if bar != n_bars - 2 or i < 13 else 1, ARP_FAST))
    return out


def drum_rows(bar):
    out = []
    for i in range(16):
        d = rows[bar * 16 + i][2]
        out.append({1: (14, TRI, 7, DROP),          # kick: a low triangle dropping away
                    2: (30, NOISE, 5, FADE_OUT),     # snare
                    3: (56, NOISE, 2, FADE_OUT)}.get(d, EMPTY))  # hat
    return out


CHANNELS = [(bass_rows, filters()), (arp_rows, filters(reverb=2)),
            (pad_rows, filters(reverb=1, dampen=1)), (drum_rows, filters())]

sfx_list, sfx_index, patterns = [], {}, []
for bar in range(0, n_bars, 2):
    ids = []
    for fn, flt in CHANNELS:
        notes = tuple(fn(bar) + (fn(bar + 1) if bar + 1 < n_bars else [EMPTY] * 16))
        if all(n == EMPTY for n in notes):
            ids.append(None)
            continue
        key = (notes, flt)
        if key not in sfx_index:
            sfx_index[key] = len(sfx_list)
            sfx_list.append(key)
        ids.append(sfx_index[key])
    patterns.append(ids)
assert len(sfx_list) <= 64, len(sfx_list)


def sfx_line(notes, flt):
    s = f"{flt:02x}{SPEED:02x}0000"
    for p, w, v, e in notes:
        s += f"{max(0, min(63, p)):02x}{w:x}{v:x}{e:x}"
    return s


sfx_lines = [sfx_line(n, f) for n, f in sfx_list]
sfx_lines += [sfx_line([EMPTY] * 32, filters())] * (64 - len(sfx_lines))
music_lines = []
for k, ids in enumerate(patterns):
    flag = (1 if k == 0 else 0) | (2 if k == len(patterns) - 1 else 0)   # loop start / end
    music_lines.append(f"{flag:02x} " + "".join(f"{(0x41 + c if i is None else i):02x}"
                                                 for c, i in enumerate(ids)))
music_lines += ["00 41424344"] * (64 - len(music_lines))

LUA = r"""-- pico jams: the groove from the retro chip tour, on pico-8's 4 channels
-- ch0 bass  ch1 arp (+reverb)  ch2 pad chords (fast arp fx)  ch3 drums
lvl={0,0,0,0} last={-1,-1,-1,-1} pitch={0,0,0,0}
flash=0 shake=0 t=0
names={"bass","arp","pads","drums"}
cols={11,13,9,10}
notes={"c","c#","d","d#","e","f","f#","g","g#","a","a#","b"}
stars={}
for i=1,40 do add(stars,{x=rnd(128),y=rnd(64),s=0.2+rnd(0.8)}) end

function _init() music(0) end

-- what is a channel playing right now? read the note back out of sfx memory
function now_playing(c)
 local s,n=stat(46+c),stat(50+c)
 if s<0 or n<0 then return nil end
 local a=0x3200+s*68+n*2
 local w=peek(a)|(peek(a+1)<<8)
 return n,w&63,(w>>6)&7,(w>>9)&7
end

function _update60()
 t+=1
 for c=0,3 do
  local n,p,wf,v=now_playing(c)
  if n and n~=last[c+1] then
   last[c+1]=n
   if v>0 and (c<3 or v>=2) then
    lvl[c+1]=1 pitch[c+1]=p
    if c==3 and wf==0 then flash=6 shake=3 end
   end
  end
  lvl[c+1]*=0.9
 end
 flash=max(0,flash-1) shake=max(0,shake-0.5)
 for s in all(stars) do s.x-=s.s*(1+flash*0.3) if s.x<0 then s.x+=128 end end
end

function _draw()
 cls(flash>3 and 2 or (flash>0 and 1 or 0))
 camera(rnd(shake)-shake/2,rnd(shake)-shake/2)
 for s in all(stars) do pset(s.x,s.y,s.s>0.6 and 7 or 5) end
 print("\^w\^tpico jams",28,6,10)
 print("4 channels, 8 waves, 1 groove",6,22,12)
 for c=1,4 do
  local y=40+(c-1)*16
  print(names[c],6,y,cols[c])
  rect(30,y-1,121,y+5,1)
  local w=flr(lvl[c]*90)
  if w>0 then rectfill(31,y,30+w,y+4,cols[c]) end
  if c<4 and lvl[c]>0.05 then
   local p=pitch[c]+36
   print(notes[p%12+1]..flr(p/12)-1,6,y+6,5)
  end
 end
 -- a tiny piano roll: the bass line drawn as it plays
 local x=(t/2)%128
 if lvl[1]>0.5 then rectfill(x,124-pitch[1],x+1,125-pitch[1],11) end
 print("groove by claude, 2026",20,120,6)
 camera()
end
"""

cart = ["pico-8 cartridge // http://www.pico-8.com", "version 41", "__lua__", LUA.strip(),
        "__sfx__"] + sfx_lines + ["__music__"] + music_lines
open(os.path.join(HERE, "picojams.p8"), "w").write("\n".join(cart) + "\n")
print(f"picojams.p8: {len(sfx_list)} unique SFX, {len(patterns)} patterns")
