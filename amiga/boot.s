| Amiga bootblock (1 KB, the first two sectors of the floppy).
| The ROM calls the code at offset 12 with A6 = ExecBase and A1 = an open
| trackdisk IORequest. We allocate chip RAM, read the program from the disk
| (it starts right after the bootblock), stop the motor and jump to it.
| PROG_BYTES is patched in by build.py (multiple of 512).

        .text
        .ascii  "DOS"
        .byte   0
        .long   0                       | checksum, filled in by build.py
        .long   880                     | root block

boot:
        move.l  %a1,%a4                 | keep the IORequest
        move.l  prog_bytes(%pc),%d0
        move.l  #0x10002,%d1            | MEMF_CHIP | MEMF_CLEAR
        jsr     -198(%a6)               | AllocMem
        tst.l   %d0
        beq.s   fail
        move.l  %d0,%a5

        move.l  %a4,%a1
        move.w  #2,28(%a1)              | io_Command = CMD_READ
        move.l  %a5,40(%a1)             | io_Data
        move.l  prog_bytes(%pc),36(%a1) | io_Length
        move.l  #1024,44(%a1)           | io_Offset: right after the bootblock
        jsr     -456(%a6)               | DoIO

        move.l  %a4,%a1
        move.w  #9,28(%a1)              | TD_MOTOR
        clr.l   36(%a1)                 | off
        jsr     -456(%a6)

        jmp     (%a5)                   | never comes back

fail:   moveq   #-1,%d0
        rts

        .balign 4
prog_bytes:
        .long   0                       | patched by build.py
