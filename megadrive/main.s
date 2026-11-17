| MEGA JAMS - FM bass + FM electric-piano arpeggio + FM pads + sampled drums
| YM2612: ch1 bass (centre), ch2 arp (ping-pongs left/right), ch3-5 pad chord
| (left/centre/right), ch6 = DAC: kick + snare samples streamed by a small Z80
| program. PSG noise: hi-hat.
| Visuals: a parallax landscape on plane B (mountains, hills and a perspective
| ground, each line scrolled at its own speed); sky colour bars painted by a
| per-line interrupt (H-int) writing the backdrop colour; shadow/highlight mode
| with orb sprites that light the scene up on every kick; text + meters on plane A.
| build: python3 build.py  (generates gen.s, assembles, links mega.bin)

        .equ VDP_DATA, 0xC00000
        .equ VDP_CTRL, 0xC00004
        .equ PSG,      0xC00011
        .equ YM_A0,    0xA04000
        .equ YM_D0,    0xA04001
        .equ YM_A1,    0xA04002
        .equ YM_D1,    0xA04003

        .equ RAM,     0xFF0000
        .equ fcnt,    RAM+0           | byte: frame within the 16th
        .equ pend,    RAM+2           | 4 bytes: bass, arp, drum, pad
        .equ meter,   RAM+6           | 4 bytes: bass, arp, drums, pads
        .equ panflag, RAM+11          | byte: arp left/right toggle
        .equ flash,   RAM+10          | byte: kick flash 7..0
        .equ phase,   RAM+12          | word: wave phase
        .equ drift,   RAM+14          | word: stripe drift
        .equ songptr, RAM+16          | long
        .equ dptr,    RAM+20          | long: hi-hat sequence (0 = idle)
        .equ skyscroll, RAM+28        | byte: sky bar offset (read by H-int)
        .equ fcount,  RAM+30          | word: frame counter
        .equ hsbuf,   RAM+0x100       | 224 words: next frame's plane B line scroll
        .equ acc,     RAM+0x300       | 224 words: per-line scroll positions (1/16 px)
        .equ spbuf,   RAM+0x500       | 6 sprites x 4 words, ready for the VDP
        .equ NSPRITES, 6
        .equ Z80_TRIGGER, 0xA01FF0    | Z80 RAM: sample id to play
        .equ FRAMES_PER_TICK, 7       | 60 Hz / 7 = 16ths at ~128 bpm

        .include "gen_equ.s"

        .text
| ---------------------------------------------------------------- vectors
        .org 0
        .long 0x00FFFE00, start
        .rept 26
        .long fault
        .endr
        .long hblank                  | 28: level 4
        .long fault                   | 29
        .long vblank                  | 30: level 6
        .rept 33
        .long fault
        .endr

        .org 0x100
        .include "gen_header.s"

| ---------------------------------------------------------------- setup
        .org 0x200
start:
        move.w  #0x2700,%sr
        move.b  0xA10001,%d0          | TMSS: say "SEGA" on newer consoles
        andi.b  #0x0F,%d0
        beq.s   1f
        move.l  #0x53454741,0xA14000
1:      tst.w   VDP_CTRL

        lea     vdp_regs,%a0
        moveq   #VDP_REG_COUNT-1,%d7
2:      move.w  (%a0)+,VDP_CTRL
        dbra    %d7,2b

        lea     RAM,%a0               | clear our variables
        move.w  #0x17F,%d7
3:      clr.l   (%a0)+
        dbra    %d7,3b

        move.l  #0x40000000,VDP_CTRL  | clear all 64K of VRAM
        move.w  #0x7FFF,%d7
4:      move.w  #0,VDP_DATA
        dbra    %d7,4b
        move.l  #0x40000010,VDP_CTRL  | clear vertical scroll
        moveq   #39,%d7
5:      move.w  #0,VDP_DATA
        dbra    %d7,5b

        lea     tiles,%a0             | tiles, maps, palette
        move.w  #TILE_WORDS-1,%d7
        move.l  #0x40000000,%d0
        bsr     load
        lea     plane_a,%a0
        move.w  #64*32-1,%d7
        move.l  #CMD_PLANE_A,%d0
        bsr     load
        lea     plane_b,%a0
        move.w  #64*32-1,%d7
        move.l  #CMD_PLANE_B,%d0
        bsr     load
        lea     palette,%a0
        moveq   #63,%d7
        move.l  #0xC0000000,%d0
        bsr     load

        move.w  #0x100,0xA11100       | take the Z80 bus (we drive the YM directly)
        move.w  #0x100,0xA11200       | and release the YM2612 from reset
6:      btst    #0,0xA11100
        bne.s   6b

        move.b  #0x9F,PSG             | PSG silent
        move.b  #0xBF,PSG
        move.b  #0xDF,PSG
        move.b  #0xFF,PSG

        | Start the Z80 FIRST: its reset line also resets the YM2612,
        | so the FM patches must be written after this.
        lea     z80_blob,%a0          | Z80 RAM: sample player + samples
        lea     0xA00000,%a1
        move.w  #Z80_BLOB_LEN-1,%d7
9:      move.b  (%a0)+,(%a1)+
        dbra    %d7,9b
        move.w  #0,0xA11200           | reset the Z80 (and the YM) ...
        move.w  #0,0xA11100           | ... give it the bus ...
        moveq   #31,%d7
10:     dbra    %d7,10b
        move.w  #0x100,0xA11200       | ... and let it run

        move.w  #0x100,0xA11100       | pause it again while we set up the YM
11:     btst    #0,0xA11100
        bne.s   11b
        lea     ym_init,%a0           | FM patches: (part, reg, value) ... 0xFF
7:      move.b  (%a0)+,%d2
        cmpi.b  #0xFF,%d2
        beq.s   8f
        move.b  (%a0)+,%d0
        move.b  (%a0)+,%d1
        bsr     ym_write
        bra.s   7b
8:      bsr     ym_latch_dac
        move.w  #0,0xA11100           | Z80 runs the sample player from here on

        move.l  #song,songptr
        move.w  #0x2000,%sr           | interrupts on: vblank drives everything
main:   stop    #0x2000
        bra.s   main

| copy d7+1 words from a0 to the VDP address in d0
load:   move.l  %d0,VDP_CTRL
1:      move.w  (%a0)+,VDP_DATA
        dbra    %d7,1b
        rts

| YM2612 write: d0 = register, d1 = value, d2 = part (0/1)
ym_write:
1:      btst    #7,YM_A0
        bne.s   1b
        tst.b   %d2
        bne.s   2f
        move.b  %d0,YM_A0
        nop
        move.b  %d1,YM_D0
        rts
2:      move.b  %d0,YM_A1
        nop
        move.b  %d1,YM_D1
        rts

| leave the YM address latch on $2A so the Z80's writes go to the DAC
ym_latch_dac:
1:      btst    #7,YM_A0
        bne.s   1b
        move.b  #0x2A,YM_A0
        rts

fault:  bra.s   fault
| H-int, at the end of every visible line: choose the sky colour for the next line by
| pointing the backdrop register at one of the 16 ramp colours in palette 2. One
| register write (no palette write mid-line, so no CRAM dots), and SR goes to $2700
| first so V-int can never cut in while the VDP control port is in use.
hblank:
        move.w  #0x2700,%sr
        move.l  %d0,-(%sp)
        moveq   #0,%d0
        move.b  0xC00008,%d0          | the VDP's line counter
        add.b   skyscroll,%d0
        move.l  %a0,-(%sp)
        lea     skyidx,%a0
        move.b  (%a0,%d0.w),%d0
        movea.l (%sp)+,%a0
        ori.w   #0x8720,%d0           | register 7 = palette 2, colour 0..15
        move.w  %d0,VDP_CTRL
        move.l  (%sp)+,%d0
        rte

vblank:
        movem.l %d0-%d7/%a0-%a6,-(%sp)
        bsr     vdp_out               | 1. everything that touches the VDP, H-int masked
        move.w  #0x2300,%sr           | 2. let the sky interrupt run again
        bsr     music                 |    (music + maths only touch RAM and the YM)
        bsr     compute
        movem.l (%sp)+,%d0-%d7/%a0-%a6
        rte

| ---------------------------------------------------------------- music
music:
        move.w  #0x100,0xA11100       | pause the Z80 while we talk to the YM
1:      btst    #0,0xA11100
        bne.s   1b
        bsr     music_body
        bsr     ym_latch_dac
        move.w  #0,0xA11100
        rts

music_body:
        moveq   #0,%d2
        move.b  fcnt,%d0
        bne     frame_other

        move.l  songptr,%a0           | frame 0: fetch the row, key off
        move.b  (%a0)+,pend
        move.b  (%a0)+,pend+1
        move.b  (%a0)+,pend+2
        move.b  (%a0)+,pend+3
        cmpa.l  #song_end,%a0
        bne.s   1f
        lea     song,%a0              | loop
1:      move.l  %a0,songptr
        lea     keyoffs,%a2           | (event byte offset, key code) pairs
        moveq   #4,%d6
2:      moveq   #0,%d3
        move.b  (%a2)+,%d3
        move.b  (%a2)+,%d1
        lea     pend,%a0
        tst.b   (%a0,%d3.w)
        beq.s   3f
        moveq   #0x28,%d0
        bsr     ym_write
3:      dbra    %d6,2b
        bra     effects

frame_other:
        cmpi.b  #1,%d0
        bne     effects
        moveq   #0,%d3                | frame 1: key on new notes
        move.b  pend,%d3
        cmpi.b  #2,%d3
        bcs.s   4f
        moveq   #0,%d4
        bsr     note_on
        move.b  #20,meter
4:      moveq   #0,%d3
        move.b  pend+1,%d3
        cmpi.b  #2,%d3
        bcs.s   5f
        eori.b  #1,panflag            | arp ping-pongs between the speakers
        move.b  #0x80,%d1
        tst.b   panflag
        bne.s   6f
        move.b  #0x40,%d1
6:      move.b  #0xB5,%d0
        bsr     ym_write
        moveq   #1,%d4
        bsr     note_on
        move.b  #20,meter+1
5:      moveq   #0,%d3
        move.b  pend+3,%d3
        cmpi.b  #2,%d3
        bcs.s   7f
        subq.w  #2,%d3                | pad chord: 3 notes from chordtab
        move.w  %d3,%d0
        add.w   %d3,%d3
        add.w   %d0,%d3
        lea     chordtab,%a3
        adda.w  %d3,%a3
        moveq   #0,%d3
        move.b  (%a3)+,%d3
        moveq   #2,%d4
        bsr     note_on
        moveq   #0,%d3
        move.b  (%a3)+,%d3
        moveq   #4,%d4
        bsr     note_on
        moveq   #0,%d3
        move.b  (%a3)+,%d3
        moveq   #5,%d4
        bsr     note_on
        move.b  #20,meter+3
7:      move.b  pend+2,%d3
        beq.s   effects
        move.b  #20,meter+2
        cmpi.b  #3,%d3
        bne.s   8f
        move.l  #hat_seq,dptr         | hi-hat: PSG noise
        bra.s   effects
8:      move.b  %d3,Z80_TRIGGER       | kick/snare: sample on the DAC
        cmpi.b  #1,%d3
        bne.s   effects
        move.b  #7,flash              | kick: flash the screen

effects:
        move.l  dptr,%a1              | hi-hat sequence: one entry per frame
        cmpa.l  #0,%a1                |  word: 0xFFFE = end
        beq.s   9f                    |  byte: PSG noise control (0 = none)
        move.w  (%a1)+,%d5            |  byte: PSG attenuation (0xFF = none)
        cmpi.w  #0xFFFE,%d5
        bne.s   10f
        clr.l   dptr
        bra.s   9f
10:     move.b  (%a1)+,%d1
        beq.s   11f
        move.b  %d1,PSG
11:     move.b  (%a1)+,%d1
        cmpi.b  #0xFF,%d1
        beq.s   12f
        ori.b   #0xF0,%d1
        move.b  %d1,PSG
12:     move.l  %a1,dptr
9:
        lea     meter,%a0             | meters fall back
        moveq   #3,%d7
13:     tst.b   (%a0)
        beq.s   14f
        subq.b  #1,(%a0)
14:     addq.l  #1,%a0
        dbra    %d7,13b

        addq.b  #1,fcnt
        cmpi.b  #FRAMES_PER_TICK,fcnt
        bne.s   15f
        clr.b   fcnt
15:     rts

keyoffs: .byte 0,0, 1,1, 3,2, 3,4, 3,5     | bass ch1, arp ch2, pads ch3-5
        .balign 2

| d3 = MIDI note, d4 = YM key code (0-2 = ch1-3, 4-6 = ch4-6)
note_on:
        lea     freqtab,%a0
        add.w   %d3,%d3
        move.w  (%a0,%d3.w),%d5
        move.w  %d4,%d2
        lsr.w   #2,%d2                | part 0 / 1
        move.w  %d4,%d6
        andi.w  #3,%d6                | channel within the part
        move.w  %d5,%d1
        lsr.w   #8,%d1
        move.b  #0xA4,%d0
        add.b   %d6,%d0
        bsr     ym_write
        move.b  %d5,%d1
        move.b  #0xA0,%d0
        add.b   %d6,%d0
        bsr     ym_write
        moveq   #0,%d2
        moveq   #0x28,%d0
        move.b  #0xF0,%d1
        or.b    %d4,%d1
        bra     ym_write

| ---------------------------------------------------------------- visuals
| Part 1, during V-blank with H-int masked: push last frame's prepared data.
vdp_out:
        move.w  #0x8F04,VDP_CTRL      | line scroll: plane B words only (step 4)
        move.l  #CMD_HSCROLL_B,VDP_CTRL
        lea     hsbuf,%a0
        move.w  #223,%d7
1:      move.w  (%a0)+,VDP_DATA
        dbra    %d7,1b
        move.w  #0x8F02,VDP_CTRL

        move.l  #CMD_SPRITES,VDP_CTRL | sprites
        lea     spbuf,%a0
        moveq   #NSPRITES*4-1,%d7
2:      move.w  (%a0)+,VDP_DATA
        dbra    %d7,2b

        moveq   #0,%d0                | the sky ramp (palette 2), brighter on the kick
        move.b  flash,%d0
        lsl.w   #5,%d0                | 16 colours = 32 bytes per level
        lea     skypals,%a0
        adda.w  %d0,%a0
        move.l  #0xC0400000,VDP_CTRL  | CRAM colour 32
        moveq   #7,%d7
6:      move.l  (%a0)+,VDP_DATA
        dbra    %d7,6b
        addq.b  #1,skyscroll

        lea     meter,%a2             | meters on plane A
        lea     meter_cmds,%a3
        lea     meter_tiles,%a4
        moveq   #3,%d6
3:      move.l  (%a3)+,VDP_CTRL
        move.w  (%a4)+,%d4
        moveq   #0,%d5
        move.b  (%a2)+,%d5
        moveq   #0,%d3
        moveq   #19,%d7
4:      move.w  %d4,%d1
        cmp.w   %d5,%d3
        blt.s   5f
        moveq   #0,%d1
5:      move.w  %d1,VDP_DATA
        addq.w  #1,%d3
        dbra    %d7,4b
        dbra    %d6,3b
        rts

| Part 2, interrupts allowed: work out next frame in RAM.
compute:
        lea     speedtab,%a0          | parallax: every line moves at its own speed
        lea     acc,%a1
        lea     hsbuf,%a2
        move.w  #223,%d7
1:      move.w  (%a0)+,%d0
        add.w   %d0,(%a1)
        move.w  (%a1)+,%d1
        lsr.w   #4,%d1                | 1/16 px -> px (wraps at 4096 = 8 x 512: seamless)
        neg.w   %d1
        move.w  %d1,(%a2)+
        dbra    %d7,1b

        lea     spbuf,%a0             | orbs: shown while the kick flash lasts, rising as it fades
        lea     orbs,%a1
        moveq   #0,%d2
        move.b  flash,%d2
        moveq   #4,%d6
        moveq   #1,%d5                | link to the next sprite
2:      move.w  (%a1)+,%d0            | x
        move.w  (%a1)+,%d1            | y
        tst.w   %d2
        beq.s   3f
        add.w   #128,%d1
        add.w   %d2,%d1
        add.w   %d2,%d1
        bra.s   4f
3:      moveq   #0,%d1                | hidden (above the screen)
4:      move.w  %d1,(%a0)+
        move.w  %d5,%d3
        ori.w   #0x0F00,%d3           | 4x4 tiles
        move.w  %d3,(%a0)+
        move.w  #SPRITE_ATTR,(%a0)+
        add.w   #128,%d0
        move.w  %d0,(%a0)+
        addq.w  #1,%d5
        dbra    %d6,2b
        move.w  moon+2,%d1            | the moon: always there, bobbing gently
        add.w   #128,%d1
        move.w  fcount,%d0
        lsr.w   #4,%d0
        andi.w  #3,%d0
        add.w   %d0,%d1
        move.w  %d1,(%a0)+
        move.w  #0x0F00,(%a0)+        | last sprite: link 0
        move.w  #SPRITE_ATTR,(%a0)+
        move.w  moon,%d0
        add.w   #128,%d0
        move.w  %d0,(%a0)+

        addq.w  #1,fcount
        tst.b   flash
        beq.s   5f
        subq.b  #1,flash
5:      rts

| ---------------------------------------------------------------- data
        .balign 2
        .include "gen_data.s"
rom_end:
