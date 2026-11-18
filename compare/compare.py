#!/usr/bin/env python3
"""Compare a candidate render against a reference render of the same note sequence.

  python3 compare.py ref.wav ours.wav

Both files play the Mega Drive patch-test sequence (megadrive/build.py with PATCHTEST=1
for the reference, recorded through MAME's YM2612; dreamengine's tools/carts/mdref.c for
the candidate): bass A2 E2 A3, e-piano A3 A4 E5, the C pad chord, at ticks 4 16 28 40 52
64 76 of 7 NTSC frames.

Per note it reports:
  distance  multi-resolution log-mel L1 (FFT sizes 256..2048, like dreamengine's patch
            matcher), after matching loudness. Shown with "vs sine": the same distance for a
            plain sine at the note's pitch, so 100% = no closer than a sine, 0% = identical.
  level     how much louder (+) or quieter (-) the candidate is, in dB
  bright    spectral centroid (Hz) at 20 / 80 / 200 / 500 ms into the note: the pluck
  partials  the first 6 harmonics in dB relative to the fundamental, 50..250 ms
"""
import sys
import wave

import numpy as np

TICK = 7 / 59.92
EVENTS = [("bass A2", 4, 45, 1.2), ("bass E2", 16, 40, 1.2), ("bass A3", 28, 57, 1.2),
          ("ep A3", 40, 57, 1.2), ("ep A4", 52, 69, 1.2), ("ep E5", 64, 76, 1.2),
          ("pad C", 76, 60, 2.4)]
SR = 44100


def load(path):
    w = wave.open(path)
    sr, ch, bw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768 if bw == 2 else \
        (np.frombuffer(raw, dtype=np.uint8).astype(float) - 128) / 128
    x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR:                                     # resample (linear is fine for analysis)
        t = np.arange(int(len(x) * SR / sr)) / SR
        x = np.interp(t, np.arange(len(x)) / sr, x)
    x = x - np.convolve(x, np.ones(2205) / 2205, mode="same")   # remove DC / sub-20 Hz drift
    return x


def first_onset(x):
    env = np.sqrt(np.convolve(x ** 2, np.ones(220) / 220, mode="same"))
    return np.argmax(env > env.max() * 0.08) / SR


def mel_filters(n_fft, n_mels=64, fmin=30, fmax=12000):
    mel = lambda f: 2595 * np.log10(1 + f / 700)              # noqa: E731
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)             # noqa: E731
    pts = imel(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    bins = np.fft.rfftfreq(n_fft, 1 / SR)
    fb = np.zeros((n_mels, len(bins)))
    for i in range(n_mels):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((bins - lo) / (c - lo), (hi - bins) / (hi - c)), 0, None)
    return fb


FB = {n: mel_filters(n) for n in (256, 512, 1024, 2048)}


def logmel(x, n):
    hop = n // 4
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    return np.log(1e-4 + mag @ FB[n].T)


def distance(a, b):
    return float(np.mean([np.mean(np.abs(logmel(a, n) - logmel(b, n))) for n in FB]))


def centroid_at(x, ms):
    a = int(ms / 1000 * SR); seg = x[a:a + 1024] * np.hanning(1024)
    p = np.abs(np.fft.rfft(seg)); f = np.fft.rfftfreq(1024, 1 / SR); k = f < 8000
    return (p[k] * f[k]).sum() / (p[k].sum() + 1e-12)


def partials(x, midi):
    f0 = 440 * 2 ** ((midi - 69) / 12)
    seg = x[int(0.05 * SR):int(0.25 * SR)]
    seg = seg * np.hanning(len(seg))
    p = np.abs(np.fft.rfft(seg, 16384)); f = np.fft.rfftfreq(16384, 1 / SR)
    amps = [p[np.argmin(abs(f - h * f0))] for h in range(1, 7)]
    return [20 * np.log10(a / (amps[0] + 1e-12) + 1e-9) for a in amps]


def rms(x):
    return np.sqrt(np.mean(x ** 2)) + 1e-12


def main(ref_path, ours_path):
    ref, ours = load(ref_path), load(ours_path)
    r0, o0 = first_onset(ref), first_onset(ours)
    print(f"aligned on the first note: ref {r0:.3f}s, ours {o0:.3f}s\n")
    print(f"{'note':8s} {'dist':>6s} {'vs sine':>8s} {'level':>7s}   bright ref -> ours (Hz @ 20/80/200/500 ms)")
    rows = []
    for name, tick, midi, secs in EVENTS:
        dt = (tick - 4) * TICK
        a = ref[int((r0 + dt) * SR):int((r0 + dt + secs) * SR)]
        b = ours[int((o0 + dt) * SR):int((o0 + dt + secs) * SR)]
        n = min(len(a), len(b)); a, b = a[:n], b[:n]
        level = 20 * np.log10(rms(b) / rms(a))
        bn = b * rms(a) / rms(b)                                    # compare shape, not loudness
        t = np.arange(n) / SR
        sine = np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t) * np.exp(-t / 0.6)
        sine *= rms(a) / rms(sine)
        d, ds = distance(a, bn), distance(a, sine)
        cr = [centroid_at(a, ms) for ms in (20, 80, 200, 500)]
        co = [centroid_at(bn, ms) for ms in (20, 80, 200, 500)]
        print(f"{name:8s} {d:6.3f} {100 * d / ds:7.0f}% {level:+6.1f}dB   "
              + "  ".join(f"{x:5.0f}->{y:<5.0f}" for x, y in zip(cr, co)))
        rows.append((name, midi, a, bn, d, ds))
    print("\npartials (dB vs fundamental, harmonics 1..6, 50-250 ms):")
    for name, midi, a, bn, _, _ in rows:
        pr, po = partials(a, midi), partials(bn, midi)
        print(f"  {name:8s} ref  " + " ".join(f"{v:6.1f}" for v in pr))
        print(f"  {'':8s} ours " + " ".join(f"{v:6.1f}" for v in po))
    mean = np.mean([100 * d / ds for *_, d, ds in rows])
    print(f"\noverall: {mean:.0f}% of a plain sine's distance (lower is closer)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
