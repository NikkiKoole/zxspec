#ifndef MIXER_H
#define MIXER_H
#include <stdint.h>

#define MIX_RATE    18157          // 16.78 MHz / 924: exactly 304 samples per video frame
#define MIX_SAMPLES 304

#ifdef __arm__
#define MIX_EWRAM __attribute__((section(".ewram")))
#else
#define MIX_EWRAM
#endif

typedef struct { int meter[4]; int flash; } MixState;   // bass, arp, pads, drums
extern MixState mix_state;

void mix_init(void);
void mix_frame(int8_t *out_l, int8_t *out_r);

#endif
