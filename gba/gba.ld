/* GBA JAMS memory map: code + constants in cartridge ROM, variables in IWRAM
   (fast, 32 KB), the big echo buffers in EWRAM (256 KB). */
MEMORY {
    rom   : ORIGIN = 0x08000000, LENGTH = 32M
    iwram : ORIGIN = 0x03000000, LENGTH = 32K
    ewram : ORIGIN = 0x02000000, LENGTH = 256K
}
ENTRY(_start)
SECTIONS {
    .text : {
        KEEP(*(.text.crt0))
        EXCLUDE_FILE(*mixer.o) *(.text*)
        *(.rodata*)
        . = ALIGN(4);
    } > rom
    .data : {
        __data_start = .;
        *mixer.o(.text*)          /* the mixer runs from IWRAM: fast, 32-bit, no wait states */
        *(.data*)
        . = ALIGN(4);
        __data_end = .;
    } > iwram AT > rom
    __data_lma = LOADADDR(.data);
    .bss (NOLOAD) : {
        __bss_start = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > iwram
    .ewram (NOLOAD) : {
        __ewram_start = .;
        *(.ewram*)
        . = ALIGN(4);
        __ewram_end = .;
    } > ewram
    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}
