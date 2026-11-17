// GBA JAMS software mixer: portable C (no GBA registers), integer-only per sample.
// The GBA has no hardware that mixes voices, so this IS the sound chip:
//   bass  : a warm sub (sine + a little 2nd harmonic) from a 256-step table
//   arp   : plucked strings, synthesised live (Karplus-Strong), two voices
//           so a note rings on while the next one starts, panned left / right
//   pads  : three chord notes x two detuned saws, through a one-pole low-pass
//   drums : kick / snare / hat samples on their own voices
//   echo  : a stereo ping-pong delay, one dotted eighth, darkened each repeat
// mix_frame() renders one video frame of sound (304 samples at 18157 Hz).
// The same file builds for the GBA and for the Mac (host/render.c -> a WAV).
#include "mixer.h"
#include "gen.h"

#define FRAMES_PER_TICK 7
#define ECHO_LEN (3 * FRAMES_PER_TICK * MIX_SAMPLES)   // a dotted eighth

typedef struct { uint32_t phase, inc; } Osc;

static int fcnt, row;
static uint32_t rng = 0x2026u;
static inline int noise8(void) { rng = rng * 1664525u + 1013904223u; return (int)(rng >> 24) - 128; }

// bass
static Osc bass;
static int bass_env, bass_rel;        // target level for this frame (0..32767)
static int bass_cur, bass_step;       // the level actually used, gliding per sample (x256)

// pads: 3 notes x 2 oscillators
static Osc pad[6];
static int pad_env, pad_target, pad_lp_l, pad_lp_r;
static int pad_cur, pad_step;         // gliding per sample (x256)
static int ks_dc_x, ks_dc_y;          // DC blocker on the strings

// plucked strings
#define KS_MAX 256
typedef struct { int16_t buf[KS_MAX]; int len, pos, amp; } Pluck;
static Pluck ks[2];
static int ks_next;

// drum sample voices
typedef struct { const int8_t *data; int len, pos, vol; } Smp;
static Smp drum[3];

// echo
MIX_EWRAM static int16_t echo_l[ECHO_LEN], echo_r[ECHO_LEN];
static int echo_pos, echo_lp_l, echo_lp_r;

MixState mix_state;

static void pluck(Pluck *p, int note) {
    int len = ks_len[note];
    if (len > KS_MAX) len = KS_MAX;
    p->len = len; p->pos = 0; p->amp = 18;
    int prev = 0;
    for (int i = 0; i < len; i++) {                    // a softened noise burst
        int n = noise8() * 90;
        prev = (prev + n) >> 1;
        p->buf[i] = (int16_t)prev;
    }
}

static void tick(void) {
    const uint8_t *r = &song[row * 4];
    int b = r[0], a = r[1], d = r[2], pd = r[3];
    if (b >= 2) {
        if (bass_cur < (2000 << 8)) bass.phase = 0;   // start from the sine's zero crossing
        bass.inc = note_inc[b]; bass_env = 32767; bass_rel = 0; mix_state.meter[0] = 20;
    }
    else if (b == 1) bass_rel = 1;
    if (a >= 2) { pluck(&ks[ks_next], a); ks_next ^= 1; mix_state.meter[1] = 20; }
    if (pd >= 2) {
        const uint8_t *c = chordtab[pd - 2];
        for (int k = 0; k < 3; k++) {
            pad[2 * k].inc = note_inc[c[k]];
            pad[2 * k + 1].inc = note_inc[c[k]] + (note_inc[c[k]] >> 8);   // ~7 cents up
        }
        pad_target = 15000; mix_state.meter[2] = 20;
    } else if (pd == 1) pad_target = 0;
    if (d >= 1 && d <= 3) {
        Smp *s = &drum[d - 1];
        s->data = drum_pcm[d - 1]; s->len = drum_len[d - 1]; s->pos = 0;
        mix_state.meter[3] = 20;
        if (d == 1) mix_state.flash = 8;
    }
    row++;
    if (row >= SONG_ROWS) row = 0;
}

void mix_init(void) {
    fcnt = 0; row = 0;
    drum[0].vol = 256; drum[1].vol = 190; drum[2].vol = 90;
}

void mix_frame(int8_t *out_l, int8_t *out_r) {
    if (fcnt == 0) tick();
    if (++fcnt == FRAMES_PER_TICK) fcnt = 0;

    // envelopes, once per frame (60 Hz, like a tracker)
    // frame-rate targets; each glides there sample by sample (no 60 Hz steps)
    bass_step = ((bass_env << 8) - bass_cur) / MIX_SAMPLES;
    pad_step = ((pad_env << 8) - pad_cur) / MIX_SAMPLES;
    if (bass_rel) bass_env = bass_env * 150 >> 8;
    else bass_env = 12000 + ((bass_env - 12000) * 236 >> 8);   // pluck down to ~37%
    if (pad_env < pad_target) { pad_env += 500; if (pad_env > pad_target) pad_env = pad_target; }
    else if (pad_env > pad_target) pad_env = pad_env * 230 >> 8;
    for (int k = 0; k < 4; k++) if (mix_state.meter[k]) mix_state.meter[k]--;
    if (mix_state.flash) mix_state.flash--;

    for (int i = 0; i < MIX_SAMPLES; i++) {
        int l = 0, r = 0, send = 0;

        // bass: centre
        bass.phase += bass.inc;
        bass_cur += bass_step;
        int bs = (sine_bass[bass.phase >> 24] * (bass_cur >> 8)) >> 15;
        l += bs; r += bs;

        // pads: 6 saws, low-passed, left/right spread
        pad_cur += pad_step;
        if (pad_cur > 0) {
            int pl = 0, pr = 0;
            for (int k = 0; k < 6; k++) {
                pad[k].phase += pad[k].inc;
                int s = saw_tab[pad[k].phase >> 24];
                if (k & 1) pr += s; else pl += s;
            }
            pad_lp_l += ((pl - pad_lp_l) * 60) >> 8;
            pad_lp_r += ((pr - pad_lp_r) * 60) >> 8;
            int vl = (pad_lp_l * (pad_cur >> 8)) >> 17, vr = (pad_lp_r * (pad_cur >> 8)) >> 17;
            l += vl; r += vr; send += (vl + vr) >> 2;
        }

        // plucked strings: voice 0 leans left, voice 1 right (DC-blocked together)
        int sl = 0, sr = 0;
        for (int k = 0; k < 2; k++) {
            Pluck *p = &ks[k];
            if (!p->len) continue;
            int a = p->buf[p->pos];
            int nxt = p->pos + 1; if (nxt == p->len) nxt = 0;
            p->buf[p->pos] = (int16_t)(((a + p->buf[nxt]) * 254 + 256) >> 9);   // average, rounded evenly, a little loss
            p->pos = nxt;
            int s = (a * p->amp) >> 10;
            if (k == 0) { sl += s; sr += s >> 2; } else { sr += s; sl += s >> 2; }
        }
        {
            int x = sl + sr;
            ks_dc_y = x - ks_dc_x + ((ks_dc_y * 250) >> 8);   // one-pole high-pass, ~70 Hz
            int corr = x - ks_dc_y;                           // the DC part, removed from both sides
            ks_dc_x = x;
            sl -= corr >> 1; sr -= corr >> 1;
            l += sl; r += sr; send += (sl + sr) >> 2;
        }

        // drums
        for (int k = 0; k < 3; k++) {
            Smp *s = &drum[k];
            if (s->data && s->pos < s->len) {
                int v = (s->data[s->pos++] * s->vol) >> 8;
                if (k == 2) { r += v; l += v >> 1; }      // hat a little right
                else { l += v; r += v; }
                if (k == 1) send += v >> 3;                // a touch of echo on the snare
            }
        }

        // ping-pong echo: left repeats into right and back, darker each time
        int el = echo_l[echo_pos], er = echo_r[echo_pos];
        echo_lp_l += ((er - echo_lp_l) * 140) >> 8;
        echo_lp_r += ((el - echo_lp_r) * 140) >> 8;
        echo_l[echo_pos] = (int16_t)(send * 64 + ((echo_lp_l * 100) >> 8));
        echo_r[echo_pos] = (int16_t)((echo_lp_r * 100) >> 8);
        if (++echo_pos == ECHO_LEN) echo_pos = 0;
        l += el >> 7; r += er >> 7;

        // master: soft-ish limit into 8 bits
        l = (l * 70) >> 8; r = (r * 70) >> 8;
        if (l > 127) l = 127; else if (l < -128) l = -128;
        if (r > 127) r = 127; else if (r < -128) r = -128;
        out_l[i] = (int8_t)l; out_r[i] = (int8_t)r;
    }
}
