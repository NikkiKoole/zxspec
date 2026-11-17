# Lessons from one groove, every chip

Writing the same song for eleven machines kept running into the same problems
everyday programming has. These are the ones worth keeping, each with the moment
it came from.

## 1. One source of truth; generate the rest

`groove.py` held the song once. Every machine's `build.py` turned it into tables,
so each machine only needed a small player. Heavy thinking (FM synthesis, sample
encoding, tuning searches, copper lists) happened in Python; the code on the
machine stayed tiny.

> Put knowledge in data, generate the boilerplate, and keep the hard-to-change
> layer small.

## 2. Make the core testable away from its hard environment

The GBA mixer (`gba/mixer.c`) has no hardware code, so it also compiles on the Mac
and renders a WAV. That caught 27,000 clipped samples before anyone heard them.

> Functional core, imperative shell: isolate the logic from the I/O so you can test
> it cheaply.

## 3. Measure, and make sure your instruments can't lie

Clipping counts, energy per frequency band, folding audio at the frame length to
expose frame-locked artifacts: these turned "it sounds off" into facts.

- The GBA CPU meter wrapped around: 120% read as 20%. An unambiguous counter of
  failures (`LATE`, frames that overran) can't lie that way.
- The GBA ran fine for 30 seconds and broke when the pads came in.

> Prefer counts of failures over gauges that can saturate or wrap. Test the
> heaviest workload, not the first part.

## 4. Byte-identical rebuilds make refactoring safe

Each time shared code moved (the groove into `groove.py`, the font into
`font5x7.py`), every ROM was rebuilt and compared byte for byte. `build-all.sh`
reproduces every committed ROM exactly.

> When "same input, same output" is checkable, use it as a regression test.

## 5. Diagnose before you redesign

- The GBA "pinging" got a new interrupt-driven streaming design first. It made
  things worse; the real causes were clicks in the mixer and running out of time.
  Going back to the simple design that worked was the right move.
- The Mega Drive's garbage graphics: switching the new line interrupt off showed
  it wasn't the cause in one step. The real bug was an odd-length table.

> Remove features one at a time to find the cause. When a "better" design adds
> risk, reverting to the simple one is legitimate.

## 6. Concurrency: short critical sections, atomic updates, clear ownership

- An interrupt cut in between another's "set address" and "write data" to the
  video chip; the data landed in the wrong place.
- Starting the Z80 reset the sound chip with it (they share a reset line), wiping
  the instruments.
- The 68000 and the Z80 shared the sound chip's address register.

Fixes: split work into a short "touch the shared resource" phase and a longer
"compute privately" phase; prefer a single atomic write (the backdrop register)
over a two-step address/data pair; start things in the right order.

## 7. Bugs often show up long after they're introduced

A 15-byte table, added with the Mega Drive pads, put every table after it on an
odd address. It stayed invisible until something needed even alignment.

> Cheap invariant checks (`assert` alignment, sizes, ranges) catch these at build
> time.

## 8. Respect real-time budgets

Audio has a hard deadline every frame: double-buffer, know the worst case, put the
hot loop where it runs fast (the GBA's IWRAM, as ARM code).

> The same thinking applies to UI frame budgets and request latency.

## 9. Check your tools as carefully as your code

`brew install ares` installed a different program with that name. Homebrew's mGBA
was broken against its libraries. PICO-8's WAV export was silently silent. FCEUX
showed a black screen.

> Verify the tool before blaming the code.

## 10. Precise questions find bugs fast

Only a human could hear the results. The biggest leaps came from narrow questions:
how many seconds in? A or B? what does it sound like? Agree on units, too: "4 bars"
meant different lengths of time to each of us.

## Smaller, very concrete ones

- **Notes start at a zero crossing.** Jumping to full volume mid-waveform is a click.
- **Envelopes glide per sample.** Stepping them once per frame buzzes at 60 Hz.
- **Fast switching smears pitch.** Hopping between notes faster than a note's own
  period puts it out of tune.
- **Measure tuning.** The 2600's tuning search found the song's own key fit best.
- **Render headless for checking.** openMSX scripting, dreamengine's `--wav`, and
  BlastEm's own screenshot key made checks automatic where possible.
