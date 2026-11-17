"""The shared groove: octave-bouncing bass, a soft arpeggio from bar 9,
kick/snare/hi-hat. Used by the C64 and Mega Drive builds.

ticks() returns one [bass, arp, drum] row per 16th note:
  bass/arp: 0 = hold, 1 = release, 2+ = MIDI note number
  drum:     0 = none, 1 = kick, 2 = snare, 3 = hi-hat
"""

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7,
        "G#": 8, "A": 9, "A#": 10, "B": 11}
RELEASE = 1
K, S, H = 1, 2, 3

ROOTS = ("A F C G A F G E " * 4 + "A").split()
CHORDS = {"A": (57, 3), "F": (53, 4), "C": (60, 4), "G": (55, 4), "E": (52, 4)}
ARP_SHAPE = (0, 1, 2, 3, 2, 1, 0, 2)
ARP_FROM_BAR = 8
GROOVES = {
    "intro": {0: K, 8: K, 4: H, 12: H},
    "verse": {0: K, 4: S, 8: K, 12: S, 2: H, 6: H, 10: H, 14: H},
    "drive": {0: K, 3: K, 4: S, 8: K, 10: K, 12: S, 2: H, 6: H, 14: H, 15: H},
    "fill":  {0: K, 4: S, 8: K, 10: S, 12: S, 13: S, 14: S, 15: S},
    "end":   {0: K},
}
ARRANGEMENT = (["intro"] * 7 + ["fill"] + ["verse"] * 7 + ["fill"]
               + ["drive"] * 7 + ["fill"] + ["drive"] * 7 + ["fill"] + ["end"])
assert len(ARRANGEMENT) == len(ROOTS)


def midi(name):
    return NOTE[name[:-1]] + 12 * (int(name[-1]) + 1)


def ticks():
    out = []
    for bar, r in enumerate(ROOTS):
        rows = [[0, 0, 0] for _ in range(16)]
        lo = midi(r + ("3" if r == "C" else "2"))
        last = bar == len(ROOTS) - 1
        if last:
            rows[0][0] = lo
            rows[14][0] = RELEASE
        else:
            for eighth in range(8):
                rows[eighth * 2][0] = lo + (12 if eighth % 2 else 0)
                rows[eighth * 2 + 1][0] = RELEASE        # staccato
        if bar >= ARP_FROM_BAR:
            root, third = CHORDS[r]
            tones = (root, root + third, root + 7, root + 12)
            if last:
                rows[0][1] = root + 12
                rows[14][1] = RELEASE
            else:
                for eighth, idx in enumerate(ARP_SHAPE):
                    rows[eighth * 2][1] = tones[idx]
        for step, d in GROOVES[ARRANGEMENT[bar]].items():
            rows[step][2] = d
        out += rows
    out += [[0, 0, 0] for _ in range(16)]     # a bar of breath before looping
    return out
