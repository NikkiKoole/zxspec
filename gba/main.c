// GBA JAMS: the groove through a software mixer (mixer.c) on Direct Sound A/B
// (DMA1/DMA2 stream one frame of samples per video frame: 304 = exactly one frame),
// over a Mode 7 style floor: an affine background whose rotation/scale is
// rewritten on every scanline by HBlank DMA (perspective), a sky gradient written
// per line to the backdrop colour by a second HBlank DMA, and a window that hides
// the floor above the horizon. The floor zooms and glows on every kick.
#include <stddef.h>
#include <stdint.h>
#include "mixer.h"
#include "gen.h"

#define REG16(a) (*(volatile uint16_t *)(a))
#define REG32(a) (*(volatile uint32_t *)(a))
#define DISPCNT   REG16(0x04000000)
#define VCOUNT    REG16(0x04000006)
#define BG0CNT    REG16(0x04000008)
#define BG2CNT    REG16(0x0400000C)
#define BG2PA     0x04000020
#define WIN0H     REG16(0x04000040)
#define WIN0V     REG16(0x04000044)
#define WININ     REG16(0x04000048)
#define WINOUT    REG16(0x0400004A)
#define SOUNDCNT_H REG16(0x04000082)
#define SOUNDCNT_X REG16(0x04000084)
#define FIFO_A    0x040000A0
#define FIFO_B    0x040000A4
#define DMA_SAD(n)  REG32(0x040000B0 + 12 * (n))
#define DMA_DAD(n)  REG32(0x040000B4 + 12 * (n))
#define DMA_CNTL(n) REG16(0x040000B8 + 12 * (n))
#define DMA_CNTH(n) REG16(0x040000BA + 12 * (n))
#define TM0_RELOAD REG16(0x04000100)
#define TM0_CNT    REG16(0x04000102)
#define WAITCNT   REG16(0x04000204)
#define PAL       ((volatile uint16_t *)0x05000000)
#define VRAM16(o) ((volatile uint16_t *)(uintptr_t)(0x06000000u + (o)))

#define BG0_MAP   0xE000          // screenblock 28: the text layer
#define BG2_TILES 0x4000          // charblock 1: floor tiles (8bpp)
#define BG2_MAP   0xF000          // screenblock 30: 32x32 bytes

// gcc may emit calls to these even freestanding; there is no C library here
void *memset(void *d, int c, size_t n) { uint8_t *p = d; while (n--) *p++ = (uint8_t)c; return d; }
void *memcpy(void *d, const void *s, size_t n) { uint8_t *p = d; const uint8_t *q = s; while (n--) *p++ = *q++; return d; }

typedef struct { int16_t pa, pb, pc, pd; int32_t x, y; } Affine;   // BG2PA..BG2Y, 16 bytes
static Affine aff[2][161];
static uint16_t skyline[2][161];
// sound: two buffers of one frame each; DMA plays one while we mix the other
static int8_t snd_l[2][MIX_SAMPLES + 16] __attribute__((aligned(4)));
static int8_t snd_r[2][MIX_SAMPLES + 16] __attribute__((aligned(4)));

static int32_t cam_x = 128 << 8, cam_y = 128 << 8;
static int angle, frame;

static void copy16(uint32_t off, const uint8_t *src, int bytes) {
    volatile uint16_t *d = VRAM16(off);
    for (int i = 0; i < bytes; i += 2) d[i >> 1] = src[i] | (src[i + 1] << 8);
}

static void text(int row, int col, const char *s, int bank) {
    volatile uint16_t *m = VRAM16(BG0_MAP);
    for (; *s; s++, col++) m[row * 32 + col] = (uint16_t)((*s & 0x7F) | (bank << 12));
}

static uint16_t rgb(int r, int g, int b) { return (uint16_t)(r | (g << 5) | (b << 10)); }

static void init_video(void) {
    copy16(0x0000, font_tiles, sizeof font_tiles);
    copy16(BG2_TILES, floor_tiles, sizeof floor_tiles);
    copy16(BG2_MAP, floor_map, sizeof floor_map);
    volatile uint16_t *m = VRAM16(BG0_MAP);
    for (int i = 0; i < 32 * 32; i++) m[i] = 0;
    PAL[1] = rgb(9, 6, 16);  PAL[2] = rgb(4, 2, 9);  PAL[3] = rgb(14, 10, 24);   // floor
    PAL[17] = rgb(31, 31, 31);                                                 // text
    PAL[33] = rgb(10, 31, 10); PAL[49] = rgb(26, 12, 31);                       // meters
    PAL[65] = rgb(31, 18, 6);  PAL[81] = rgb(31, 29, 8);
    PAL[97] = rgb(31, 29, 8);  PAL[113] = rgb(10, 28, 31);                      // title, subtitle
    text(1, 11, "GBA JAMS", 6);
    text(2, 1, "SOFTWARE MIXER + ECHO, MODE 7", 7);
    text(3, 1, "BASS", 2); text(4, 1, "PLUCK", 3); text(5, 1, "PADS", 4); text(6, 1, "DRUMS", 5);
    text(19, 4, "GROOVE BY CLAUDE, 2026", 1);
    BG0CNT = 0x1C00;                         // priority 0, charblock 0, 4bpp, screenblock 28
    BG2CNT = 0x7E85;                         // priority 1, charblock 1, 8bpp, sb 30, wrap, 256x256
    WIN0H = 240;                             // window 0: the sky, above the horizon
    WIN0V = HORIZON;
    WININ = 0x0001;                          // inside: text only
    WINOUT = 0x0005;                         // outside: text + floor
    DISPCNT = 0x0001 | 0x0100 | 0x0400 | 0x2000;   // mode 1, BG0, BG2, window 0
}

static void init_sound(void) {
    SOUNDCNT_X = 0x0080;                     // sound on
    SOUNDCNT_H = 0x9A0C;                     // A -> left, B -> right, both full volume, timer 0, reset FIFOs
    TM0_RELOAD = 65536 - 924;                // 16.78 MHz / 924 = 18157 Hz
    TM0_CNT = 0x0080;
}

static int late;                         // frames whose work ran into the next frame
static void wait_vblank(void) { if (VCOUNT >= 160) late++; while (VCOUNT >= 160) {} while (VCOUNT < 160) {} }

static void meters(void) {
    static const uint8_t which[4] = {0, 1, 2, 3};
    volatile uint16_t *m = VRAM16(BG0_MAP);
    for (int k = 0; k < 4; k++) {
        int lvl = mix_state.meter[which[k]];
        for (int c = 0; c < 20; c++)
            m[(3 + k) * 32 + 8 + c] = (uint16_t)(c < lvl ? (1 | ((2 + k) << 12)) : 0);
    }
}

// one frame of floor maths into aff[b], sky colours into skyline[b]
static void compute(int b) {
    int s = sin_tab[angle & 255], c = sin_tab[(angle + 64) & 255];
    int zoom = 256 - mix_state.flash * 6;            // the kick pushes the floor closer
    for (int y = 0; y <= 160; y++) {
        int line = y < 160 ? y : 0;
        Affine *a = &aff[b][y];
        int lvl = mix_state.flash;
        skyline[b][y] = sky[(lvl > 7 ? 7 : lvl) * 160 + line];
        if (line <= HORIZON) { a->pa = 0; a->pb = 0; a->pc = 0; a->pd = 0; a->x = 0; a->y = 0; continue; }
        int32_t lam8 = lam[line] * zoom >> 8;        // texels per pixel, 8.8
        int32_t depth = lam8 * 120;                  // distance ahead, 8.8
        a->pa = (int16_t)(lam8 * c >> 8);
        a->pc = (int16_t)(lam8 * s >> 8);
        a->pb = 0; a->pd = 0;
        a->x = cam_x - (depth * s >> 8) - 120 * a->pa;
        a->y = cam_y + (depth * c >> 8) - 120 * a->pc;
    }
    PAL[3] = mix_state.flash ? rgb(20 + mix_state.flash, 16 + mix_state.flash, 31) : rgb(14, 10, 24);
    cam_x -= (s * (3 + mix_state.flash)) >> 6;       // glide forward, a little faster on the kick
    cam_y += (c * (3 + mix_state.flash)) >> 6;
    if ((frame & 3) == 0) angle++;                    // a slow turn
}

int main(void) {
    WAITCNT = 0x4317;                                 // faster cartridge access + prefetch
    init_video();
    init_sound();
    mix_init();
    int cur = 0;
    mix_frame(snd_l[0], snd_r[0]);
    compute(0);
    char cpu[8] = "CPU   %";
    for (;;) {
        wait_vblank();
        // sound: stream the buffer mixed last frame (304 samples = exactly one frame)
        DMA_CNTH(1) = 0; DMA_SAD(1) = (uint32_t)(uintptr_t)snd_l[cur]; DMA_DAD(1) = FIFO_A; DMA_CNTH(1) = 0xB640;
        DMA_CNTH(2) = 0; DMA_SAD(2) = (uint32_t)(uintptr_t)snd_r[cur]; DMA_DAD(2) = FIFO_B; DMA_CNTH(2) = 0xB640;
        // video: line 0 by hand, then HBlank DMA feeds lines 1..159
        volatile uint32_t *regs = (volatile uint32_t *)BG2PA;
        const uint32_t *l0 = (const uint32_t *)&aff[cur][0];
        for (int i = 0; i < 4; i++) regs[i] = l0[i];
        PAL[0] = skyline[cur][0];
        DMA_CNTH(0) = 0; DMA_SAD(0) = (uint32_t)(uintptr_t)&aff[cur][1]; DMA_DAD(0) = BG2PA;
        DMA_CNTL(0) = 4; DMA_CNTH(0) = 0xA660;       // 4 words per HBlank, dest reload, repeat
        DMA_CNTH(3) = 0; DMA_SAD(3) = (uint32_t)(uintptr_t)&skyline[cur][1]; DMA_DAD(3) = 0x05000000;
        DMA_CNTL(3) = 1; DMA_CNTH(3) = 0xA260;       // 1 halfword per HBlank -> backdrop colour
        meters();
        cur ^= 1;
        mix_frame(snd_l[cur], snd_r[cur]);
        compute(cur);
        frame++;
        int v = VCOUNT;                               // how far into the frame we got
        int used = (v >= 160 ? v - 160 : v + 68) * 100 / 228;
        cpu[4] = (char)('0' + used / 10 % 10); cpu[5] = (char)('0' + used % 10);
        if ((frame & 15) == 0) {
            text(18, 22, cpu, 1);
            int n = late > 999 ? 999 : late;      // frames that overran (should stay 000)
            char t2[9] = {'L','A','T','E',' ',(char)('0' + n / 100),(char)('0' + n / 10 % 10),(char)('0' + n % 10),0};
            text(18, 1, t2, 1);
        }
    }
}
