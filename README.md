# One groove, every chip

The same little song — an octave-bouncing bass line over Am–F–C–G, kick/snare/hi-hat,
a soft arpeggio from bar 9 and pads from bar 17 — written for a run of retro machines,
each played the way that hardware wants to be played. Every version is real code for the
real machine (BASIC, Z80, 6502, 65816, 68000, x86), built from Python scripts and run in
an emulator.

| machine | sound chip | how it plays the groove | folder |
|---|---|---|---|
| ZX Spectrum | 1-bit beeper | BASIC `BEEP` (jams 1); a hand-assembled Z80 engine mixing two tones + drums on one pin (jams 2) | `jams.bas`, `build_jams2.py`, `emulator/` |
| Atari 2600 | TIA (2 voices, 32 pitches each) | key chosen by a tuning search; drums and arpeggio share a voice; per-scanline colour kernel | `atari2600/` |
| MSX | AY-3-8910 PSG | "buzz bass" (the hardware envelope as a repeating sawtooth tuned to the note), square arpeggio, noise/tone drums; rainbow colour-table cycling | `msx/` |
| NES | 2A03 | triangle bass, pulse arpeggio + a delayed pulse "echo", DMC kick sample, noise snare/hat | `nes/` |
| Commodore 64 | SID | filtered pulse bass, triangle arpeggio, noise drums, raster bars | `c64/` |
| Sega Mega Drive | YM2612 FM + SN76489 | FM slap bass, FM e-piano (stereo ping-pong), FM pads, DAC drum samples via a Z80 player; parallax, per-line sky bars, shadow/highlight orbs | `megadrive/` |
| SNES | S-SMP / S-DSP | BRR samples, hardware echo; a 22-byte SPC700 relay, music logic on the 65816 | `snes/` |
| PC speaker | 1-bit speaker + 8253 timer | a tour of the tricks: one square wave with drums cutting in; hopping between bass and arpeggio (fake polyphony); "RealSound" PWM playing a full software mix | `pcspeaker/` |
| DOS PC | AdLib OPL3 + Sound Blaster | OPL3 FM bass/e-piano/echo/pads, SB DMA drum samples, mode 13h plasma | `dos/` |
| Amiga 500 | Paula (4 x 8-bit, hard stereo) | sampled FM after the Mega Drive patches, bootblock disk, copper bars | `amiga/` |
| Game Boy Advance | Direct Sound (2 x 8-bit DAC) + a software mixer | Karplus-Strong plucked strings synthesised live, warm sub bass, detuned saw pads, drum samples, ping-pong echo; Mode 7 floor via HBlank DMA | `gba/` |
| PICO-8 | 4 channels, 8 waveforms, SFX effects + filters | saw bass, triangle arp with reverb, fast-arpeggio chord pads, kick/snare/hat; 2-bar chunks shared to fit 64 SFX | `pico8/` |

What we learned along the way, for programming in general: [LESSONS.md](LESSONS.md).

`groove.py` is the shared song (one row per 16th note); `font5x7.py` is a small hand-drawn
font for the machines without one. A "next generation" fantasy-chip version, `dreamchip`,
lives in the dreamengine repo (`tools/carts/dreamchip.c`).

## Setup (macOS, Homebrew)

You need Python 3 with `numpy` (used by the Amiga build), plus:

```bash
# assemblers / linkers
brew install acme cc65 nasm m68k-elf-binutils

# emulators
brew install vice blastem stella openmsx       # C64, Mega Drive, Atari 2600, MSX
brew install --cask snes9x fs-uae-emulator dosbox-staging-app   # SNES, Amiga, DOS
brew install arm-none-eabi-gcc && brew install --cask mgba-app  # GBA
```

PICO-8 is commercial (lexaloffle.com); the cart expects it in `/Applications/PICO-8.app`.

The Spectrum and NES versions play in the browser, so they need no emulator install
(JSSpeccy 3 is bundled in `emulator/`; the NES page loads jsnes from unpkg).

No copyrighted system ROMs are needed for anything here: the Spectrum 48K ROM ships with
JSSpeccy (Amstrad allows that), VICE ships the C64 ROMs, the Mega Drive / SNES / NES /
2600 need none, the MSX runs on C-BIOS (a free MSX BIOS that openMSX ships), FS-UAE falls back to the free AROS Kickstart replacement, and DOSBox has
its own BIOS.

Things that tripped us up:

- `brew install ares` is **not** the emulator (it is a text-decoding tool). Use Snes9x.
- The Homebrew **cask** for Stella is disabled (Gatekeeper); the **formula** (`brew install stella`) works.
- FCEUX showed a black screen on this Mac, so the NES version runs in the browser instead.
- The Homebrew `mgba` formula failed to start (ffmpeg library version mismatch); the
  `mgba-app` cask bundles its own libraries.
- PICO-8's headless `-export foo.wav` writes silent files on this Mac, so PICO-8 audio can
  only be checked by ear.

## Build

```bash
./build-all.sh
```

or one machine at a time, e.g. `python3 megadrive/build.py`. Each `build.py` generates its
data tables (song, pitches, samples, graphics) and runs the assembler. The built ROMs and
disk images are committed, so you can also just play them.

## Play

From this folder:

| machine | command |
|---|---|
| ZX Spectrum, NES | `cd emulator && python3 -m http.server 8765`, then open <http://localhost:8765/> (Spectrum 1), `/jams2.html` (Spectrum 2) or `/nes.html` (NES). Click once to allow sound. |
| Atari 2600 | `stella atari2600/atarijams.bin` |
| MSX | `openmsx -machine C-BIOS_MSX1_JP -cart msx/msxjams.rom` |
| C64 | `x64sc -autostart c64/c64jams.prg` |
| Mega Drive | `blastem megadrive/mega.bin` |
| SNES | `/Applications/Snes9x.app/Contents/MacOS/Snes9x snes/snesjams.sfc` (or File > Open in Snes9x) |
| DOS | `"/Applications/DOSBox Staging.app/Contents/MacOS/dosbox" dos/dosjams.com` (ESC quits) |
| PC speaker | `"/Applications/DOSBox Staging.app/Contents/MacOS/dosbox" --set cpu_cycles=max pcspeaker/pcjams.com` (ESC quits) |
| Amiga | `/Applications/FS-UAE.app/Contents/MacOS/fs-uae amiga/amigajams.fs-uae` |
| GBA | `/Applications/mGBA.app/Contents/MacOS/mGBA gba/gbajams.gba` |
| PICO-8 | `/Applications/PICO-8.app/Contents/MacOS/pico8 -run "$PWD/pico8/picojams.p8"` |

## Changing the song

Edit `groove.py` (roots, chord tones, the arpeggio shape, the drum grooves and which bar
uses which), then `./build-all.sh`. The C64, NES, Mega Drive, SNES, DOS, Amiga, 2600,
MSX, PICO-8 and GBA versions all pick it up; the two Spectrum versions predate it and carry their own copy.
For the 2600, `python3 atari2600/tuning.py` shows how far each note lands from true pitch
in every key, since that chip can only play 32 pitches per tone mode.

## Measuring "does it sound like the real chip?"

`compare/compare.py ref.wav ours.wav` compares two renders of the Mega Drive patch-test
sequence (bass A2 E2 A3, e-piano A3 A4 E5, a C pad chord): a multi-resolution log-mel
distance per note (shown as a % of a plain sine's distance), the level difference,
brightness over time and the first six partials.

```bash
PATCHTEST=1 python3 megadrive/build.py        # -> megadrive/patchtest.bin
mame genesis -cart megadrive/patchtest.bin -wavwrite ref.wav -seconds_to_run 14 \
     -nothrottle -video none -sound none -skip_gameinfo     # the real YM2612 (MAME's core)
# in dreamengine:  node tools/play.js mdref run --headless --frames 840 --wav ours.wav
python3 compare/compare.py ref.wav ours.wav
```

What it found (2026-11): FM4's alt mapping gives all modulators one level, so a YM2612
patch's per-operator volumes don't carry over (the FM4 bass has a strong 2nd harmonic
the chip doesn't). dreamengine's patch matcher fitted the real bass at loss 0.37 (with
INSTR_PIPE plus filter/drive/tape). But in a blind A/B the FM4 e-piano and pad were heard
as "the real chip" and preferred; the matched bass won for punchy grooves, the FM4 bass
(narrowly) for legato ones. Measurements find differences; ears decide what matters.

## Notes per machine

- **Spectrum** — `bas2tap.py` is a tiny BASIC tokenizer that writes a `.tap`. Jams 2's
  engine time-multiplexes two phase accumulators onto the speaker bit; drum hits steal
  time, and the build shortens the following rows so the tempo holds.
- **Atari 2600** — 4 KB ROM: the song is computed per 16th from tiny per-bar tables. The
  kernel writes the background colour and playfield on every line, early enough to beat
  the beam.
- **MSX** — no Z80 assembler is in Homebrew, so `msx/build.py` contains a small one
  (the program is Python calls that emit Z80 code; labels resolve in a second pass, short
  jumps are range-checked). The bass uses the AY's envelope as the waveform: tone A off,
  volume register = envelope, shape 8 (repeating sawtooth), envelope period
  `clock / (256 x note frequency)`. openMSX can be scripted (`record start -audioonly`,
  `screenshot`, `set throttle off`), which is how the pitch and levels were checked.
- **Mega Drive** — the YM2612's reset line is tied to the Z80's, so the Z80 sample player
  is started *before* the FM patches are written. The 68000 parks the YM address latch on
  `$2A` after its writes so the Z80's DAC writes land.
  Visuals: plane B is a 512 px landscape whose lines scroll at their own speeds (parallax,
  and a perspective floor); an H-int on every line picks the sky colour by rewriting the
  backdrop register (`$87xx`) into a 16-colour ramp — a register write, because writing
  CRAM mid-line makes "CRAM dots"; shadow/highlight mode darkens the scene and orb
  sprites in palette 3 colour 14 light it back up on each kick. Lessons that bit:
  the V-blank code is split into a short part that talks to the VDP (H-int masked) and
  the rest (H-int allowed); H-int itself masks to `$2700` so V-int can't cut in between
  a VDP address write and its data write; and every byte table is padded to an even
  length, because one odd-sized table put all the tiles and maps on odd addresses.
- **SNES** — the sound CPU runs a 22-byte relay (port 0 = handshake, port 1 = DSP register,
  port 2 = value); samples are encoded to BRR by `build.py`.
- **PC speaker** — PIT channel 0 is reprogrammed to fire IRQ0 at 18643 Hz throughout
  (restored on exit). Bars 1-8: channel 2 in square-wave mode plays the bass; drum hits
  take over the speaker (a falling sweep for the kick, random pitches for snare/hat).
  Bars 9-16: the speaker hops between bass and arpeggio every ~20 ms; hopping faster than
  a bass note's own period (a low E is ~12 ms) smears the pitch out of tune. Bars 17-33:
  channel 2 becomes a one-shot whose length is each 6-bit sample (pulse-width modulation),
  fed from a ring buffer that a software mixer keeps full. Needs `cpu_cycles=max`.
- **DOS** — Sound Blaster DMA can't cross a 64 KB page, so each sample is copied to a
  page-safe buffer at start-up.
- **GBA** — the GBA can only play two streams of 8-bit samples, so `mixer.c` *is* the
  sound chip: plucked strings (Karplus-Strong), sub bass, saw pads, drum samples and an
  echo, mixed to 304 samples per frame (18157 Hz: exactly one frame). `mixer.c` has no
  GBA code, so `build.py` also compiles it on the Mac and writes `gbajams_preview.wav`,
  which is how levels and clicks were checked. Lessons: envelopes must glide per sample
  (per-frame steps buzz at 60 Hz), notes should start at a zero crossing, and the mixer
  must run from IWRAM as ARM code (`gba.ld` puts `mixer.o` there) — as Thumb code from
  ROM it overran the frame once the pads came in, and an overrun lets the sound DMA run
  past its buffer (pings, noise). The on-screen LATE counter counts overrun frames; the
  CPU meter alone can't show overload because it wraps. The header has no Nintendo logo,
  which emulators ignore but a real GBA would refuse (devkitPro's `gbafix` adds it).
- **PICO-8** — the cart is plain text (`__lua__`, `__sfx__`, `__music__`) written by
  `build.py`. The Lua reads back from SFX memory which note each channel is on to drive
  the meters. The SFX filter byte is encoded as `1 + noiz*2 + buzz*4 + detune*8 +
  reverb*24 + dampen*72`.
- **Amiga** — a 1 KB bootblock loads the program into chip RAM via trackdisk; the program
  then turns the OS off and drives Paula and the copper directly.
