"""The TIA can only divide its ~31.4 kHz audio clock by 1..32, then each tone mode
(AUDC) divides further. So every channel has just 32 pitches per mode. This finds
the closest (AUDC, AUDF) for a note, and the key in which the groove fits best."""
import math

CLOCK = 3579545 / 114            # NTSC TIA audio clock, ~31399.5 Hz
MODES = {4: 2, 12: 6, 1: 15, 6: 31}   # AUDC -> extra divider (pure / pure / 4-bit poly buzz / div-31 buzz)
BASS_MODES = (6, 1, 12)          # buzzy low modes first, pure square for the top
ARP_MODES = (12, 4)              # pure tones


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def closest(midi, modes):
    best = None
    for c in modes:
        for f in range(32):
            p = CLOCK / MODES[c] / (f + 1)
            cents = 1200 * math.log2(p / hz(midi))
            if best is None or abs(cents) < abs(best[2]):
                best = (c, f, cents)
    return best


BASS_LO = {"A": 45, "F": 41, "C": 48, "G": 43, "E": 40}
CHORDS = {"A": (57, 3), "F": (53, 4), "C": (60, 4), "G": (55, 4), "E": (52, 4)}


def notes(t):
    bass = sorted({m + t for r in BASS_LO for m in (BASS_LO[r], BASS_LO[r] + 12)})
    arp = sorted({m + t for r, (root, third) in CHORDS.items() for m in (root, root + third, root + 7, root + 12)})
    return bass, arp


def score(t):
    bass, arp = notes(t)
    errs = [abs(closest(m, BASS_MODES)[2]) for m in bass] + [abs(closest(m, ARP_MODES)[2]) for m in arp]
    return max(errs), sum(errs) / len(errs)


def best_key():
    return min(range(-12, 13), key=lambda t: score(t))


if __name__ == "__main__":
    for t in range(-12, 13):
        worst, mean = score(t)
        print(f"transpose {t:+3d}: worst {worst:5.1f} cents, mean {mean:5.1f}")
    t = best_key()
    print(f"\nbest: {t:+d} semitones")
    bass, arp = notes(t)
    names = "C C# D D# E F F# G G# A A# B".split()
    for label, ms, modes in (("bass", bass, BASS_MODES), ("arp", arp, ARP_MODES)):
        print(label + ": " + ", ".join(f"{names[m % 12]}{m // 12 - 1}={closest(m, modes)[2]:+.0f}c" for m in ms))
