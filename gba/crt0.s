@ GBA JAMS start-up: the cartridge header, stacks, .data copy, .bss clear, then main().
@ The Nintendo logo area is left empty: emulators (mGBA) don't check it; real
@ hardware would need it filled in (devkitPro's gbafix does that).
        .section .text.crt0, "ax"
        .arm
        .global _start
_start:
        b       start_vector
        .fill   156, 1, 0               @ logo (not included)
        .ascii  "GBAJAMS     "          @ title, 12 bytes
        .ascii  "CJAM"                  @ game code
        .ascii  "00"                    @ maker code
        .byte   0x96                    @ fixed value
        .byte   0, 0                    @ unit code, device type
        .fill   7, 1, 0                 @ reserved
        .byte   0                       @ version
        .byte   0                       @ header complement (patched by build.py)
        .fill   2, 1, 0

start_vector:
        mov     r0, #0x12               @ IRQ mode stack
        msr     cpsr_c, r0
        ldr     sp, =0x03007FA0
        mov     r0, #0x1F               @ system mode stack
        msr     cpsr_c, r0
        ldr     sp, =0x03007F00

        ldr     r0, =__data_lma         @ copy initialised data into IWRAM
        ldr     r1, =__data_start
        ldr     r2, =__data_end
1:      cmp     r1, r2
        ldrlt   r3, [r0], #4
        strlt   r3, [r1], #4
        blt     1b
        mov     r3, #0                  @ clear .bss (IWRAM) and .ewram
        ldr     r1, =__bss_start
        ldr     r2, =__bss_end
2:      cmp     r1, r2
        strlt   r3, [r1], #4
        blt     2b
        ldr     r1, =__ewram_start
        ldr     r2, =__ewram_end
3:      cmp     r1, r2
        strlt   r3, [r1], #4
        blt     3b

        ldr     r0, =main
        bx      r0
        .pool
