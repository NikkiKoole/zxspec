// Render the GBA mixer on the Mac: interleaved signed 8-bit stereo to stdout.
#include <stdio.h>
#include <stdlib.h>
#include "mixer.h"

int main(int argc, char **argv) {
    int frames = argc > 1 ? atoi(argv[1]) : 600;
    int8_t l[MIX_SAMPLES], r[MIX_SAMPLES], lr[2 * MIX_SAMPLES];
    mix_init();
    for (int f = 0; f < frames; f++) {
        mix_frame(l, r);
        for (int i = 0; i < MIX_SAMPLES; i++) { lr[2 * i] = l[i]; lr[2 * i + 1] = r[i]; }
        fwrite(lr, 1, sizeof lr, stdout);
    }
    return 0;
}
