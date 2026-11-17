| AMIGA JAMS - the groove on Paula: 4 x 8-bit sample channels, hard stereo.
| The instruments are SAMPLED FM (rendered in build.py after the Mega Drive
| patches), the way Amiga musicians sampled other machines.
|   ch0 (L) bass   ch1 (R) drums   ch2 (R) e-piano arp   ch3 (L) pad chords
| Loaded into chip RAM by boot.s; position independent (PC- or A3/A4-relative).
| Takes over the machine: no OS, copper bars + one bitplane of text/meters,
| music stepped from the vertical blank (PAL 50 Hz, a 16th = 6 frames).

        .include "gen_equ.s"

        .equ FRAMES_PER_TICK, 6
        | variables (offsets from A3)
        .equ V_FCNT,    0
        .equ V_SONG,    2       | long: byte offset into the song
        .equ V_PEND,    6       | 4 bytes: bass, arp, drum, pad
        .equ V_METER,   10      | 4 bytes: bass, arp, pads, drums
        .equ V_FLASH,   14
        .equ V_SCROLL,  16
        .equ V_STARTED, 18      | channels started last tick (switch them to silence)

        .text
start:
        lea     start(%pc),%a4          | image base
        lea     vars(%pc),%a3
        movea.l 0x4,%a6
        jsr     -132(%a6)               | Forbid: the OS stops here
        lea     0xdff000,%a5
        move.w  #0x7fff,0x9a(%a5)       | INTENA: everything off
        move.w  #0x7fff,0x9c(%a5)       | INTREQ: clear
        move.w  #0x7fff,0x96(%a5)       | DMACON: everything off
        move.w  #0x00ff,0x9e(%a5)       | ADKCON: no audio modulation

        lea     copper(%pc),%a0         | bitplane pointer into the copper list
        lea     screen(%pc),%a1
        move.l  %a1,%d0
        move.w  %d0,6(%a0)
        swap    %d0
        move.w  %d0,2(%a0)
        move.l  %a0,0x80(%a5)           | COP1LC
        move.w  %d0,0x88(%a5)           | COPJMP1

        move.w  #0x1200,0x100(%a5)      | BPLCON0: one bitplane, colour on
        clr.w   0x102(%a5)
        clr.w   0x104(%a5)
        clr.w   0x108(%a5)              | BPL1MOD
        move.w  #0x0038,0x92(%a5)       | DDFSTRT  \ 320 pixels, lowres
        move.w  #0x00d0,0x94(%a5)       | DDFSTOP  /
        move.w  #0x2c81,0x8e(%a5)       | DIWSTRT  \ 320 x 256 PAL window
        move.w  #0x2cc1,0x90(%a5)       | DIWSTOP  /
        move.w  #0x8380,0x96(%a5)       | DMA on: master, bitplanes, copper

mainloop:
1:      move.w  0x1e(%a5),%d0           | wait for the vertical blank
        btst    #5,%d0
        beq.s   1b
        move.w  #0x0020,0x9c(%a5)
        bsr     music
        bsr     bars
        bsr     meters
        bra.s   mainloop

| ---------------------------------------------------------------- music
music:
        tst.w   V_FCNT(%a3)
        bne     m_other

        move.l  V_SONG(%a3),%d0         | fetch this 16th's row
        lea     song(%pc),%a0
        adda.l  %d0,%a0
        move.b  (%a0)+,V_PEND(%a3)
        move.b  (%a0)+,V_PEND+1(%a3)
        move.b  (%a0)+,V_PEND+2(%a3)
        move.b  (%a0)+,V_PEND+3(%a3)
        addq.l  #4,%d0
        cmp.l   #SONG_BYTES,%d0
        bne.s   1f
        moveq   #0,%d0
1:      move.l  %d0,V_SONG(%a3)
        moveq   #0,%d7                  | DMA bits of the channels we (re)start

        moveq   #0,%d0                  | bass: channel 0, left
        move.b  V_PEND(%a3),%d0
        cmp.b   #2,%d0
        bcs.s   2f
        lea     per_bass(%pc),%a0
        add.w   %d0,%d0
        move.w  (%a0,%d0.w),%d1
        moveq   #0,%d2
        moveq   #SMP_BASS,%d3
        moveq   #64,%d4
        bsr     setchan
        bset    #0,%d7
        move.b  #20,V_METER(%a3)

2:      moveq   #0,%d0                  | arp: channel 2, right
        move.b  V_PEND+1(%a3),%d0
        cmp.b   #2,%d0
        bcs.s   3f
        lea     per_arp(%pc),%a0
        add.w   %d0,%d0
        move.w  (%a0,%d0.w),%d1
        moveq   #2,%d2
        moveq   #SMP_EP,%d3
        moveq   #ARP_VOL,%d4
        bsr     setchan
        bset    #2,%d7
        move.b  #20,V_METER+1(%a3)

3:      moveq   #0,%d0                  | pads: channel 3, left (a sampled chord)
        move.b  V_PEND+3(%a3),%d0
        beq.s   5f
        cmp.b   #1,%d0
        bne.s   4f
        clr.w   0xd8(%a5)               | release: AUD3VOL = 0
        bra.s   5f
4:      subq.w  #2,%d0
        move.w  %d0,%d3
        add.w   #SMP_PAD0,%d3
        move.w  #PAD_PER,%d1
        moveq   #3,%d2
        moveq   #PAD_VOL,%d4
        bsr     setchan
        bset    #3,%d7
        move.b  #20,V_METER+2(%a3)

5:      moveq   #0,%d0                  | drums: channel 1, right
        move.b  V_PEND+2(%a3),%d0
        beq.s   7f
        move.w  %d0,%d3
        add.w   #SMP_KICK-1,%d3
        lea     drum_vol-1(%pc),%a0
        moveq   #0,%d4
        move.b  (%a0,%d0.w),%d4
        move.w  #DRUM_PER,%d1
        moveq   #1,%d2
        bsr     setchan
        bset    #1,%d7
        move.b  #20,V_METER+3(%a3)
        cmp.b   #1,%d0
        bne.s   7f
        move.w  #7,V_FLASH(%a3)         | kick: flash the bars

7:      tst.w   %d7                     | restart those channels' DMA
        beq.s   9f
        move.w  %d7,0x96(%a5)           | off ...
        move.w  #600,%d0
8:      dbra    %d0,8b                  | ... long enough for Paula to notice ...
        move.w  %d7,%d0
        or.w    #0x8000,%d0
        move.w  %d0,0x96(%a5)           | ... and on: they start from the top
9:      move.w  %d7,V_STARTED(%a3)
        bra.s   effects

m_other:
        cmp.w   #1,V_FCNT(%a3)          | one frame later: once each new sample has
        bne.s   effects                 | finished, play silence instead of looping it
        move.w  V_STARTED(%a3),%d7
        lea     silence(%pc),%a0
        move.l  %a0,%d1
        lea     0xa0(%a5),%a1
        moveq   #3,%d6
10:     btst    #0,%d7
        beq.s   11f
        move.l  %d1,(%a1)               | AUDxLC
        move.w  #1,4(%a1)               | AUDxLEN (words)
11:     lsr.w   #1,%d7
        lea     16(%a1),%a1
        dbra    %d6,10b

effects:
        lea     V_METER(%a3),%a0        | meters fall back
        moveq   #3,%d6
12:     tst.b   (%a0)
        beq.s   13f
        subq.b  #1,(%a0)
13:     addq.l  #1,%a0
        dbra    %d6,12b
        addq.w  #1,V_FCNT(%a3)
        cmp.w   #FRAMES_PER_TICK,V_FCNT(%a3)
        bne.s   14f
        clr.w   V_FCNT(%a3)
14:     rts

| d2 = channel, d3 = sample index, d1 = period, d4 = volume
setchan:
        lea     0xa0(%a5),%a0
        move.w  %d2,%d5
        lsl.w   #4,%d5
        adda.w  %d5,%a0
        lea     smp_tab(%pc),%a1        | per sample: long offset from start, word length in words
        move.w  %d3,%d5
        mulu    #6,%d5
        adda.w  %d5,%a1
        move.l  (%a1)+,%d5
        add.l   %a4,%d5
        move.l  %d5,(%a0)               | AUDxLC
        move.w  (%a1),4(%a0)            | AUDxLEN
        move.w  %d1,6(%a0)              | AUDxPER
        move.w  %d4,8(%a0)              | AUDxVOL
        rts

| ---------------------------------------------------------------- visuals
| COLOR00 on every line from a scrolling gradient; brighter while the kick flashes
bars:
        lea     copper(%pc),%a0
        lea     bar_offs(%pc),%a1
        lea     gradtab(%pc),%a2
        move.w  V_FLASH(%a3),%d0
        lsl.w   #8,%d0
        add.w   %d0,%d0                 | level * 512 bytes
        adda.w  %d0,%a2
        move.w  V_SCROLL(%a3),%d1
        move.w  #255,%d7
1:      move.w  %d1,%d2
        and.w   #255,%d2
        add.w   %d2,%d2
        move.w  (%a2,%d2.w),%d3
        move.w  (%a1)+,%d4
        move.w  %d3,(%a0,%d4.w)
        addq.w  #1,%d1
        dbra    %d7,1b
        addq.w  #1,V_SCROLL(%a3)
        tst.w   V_FLASH(%a3)
        beq.s   2f
        subq.w  #1,V_FLASH(%a3)
2:      rts

meters:
        lea     screen(%pc),%a0
        lea     meter_offs(%pc),%a1
        lea     V_METER(%a3),%a2
        moveq   #3,%d6
1:      move.w  (%a1)+,%d0
        lea     (%a0,%d0.w),%a6
        moveq   #0,%d1
        move.b  (%a2)+,%d1
        moveq   #5,%d5                  | 6 lines tall
2:      moveq   #0,%d2
3:      cmp.w   %d1,%d2
        scs     %d3                     | lit while column < level
        move.b  %d3,(%a6,%d2.w)
        addq.w  #1,%d2
        cmp.w   #20,%d2
        bne.s   3b
        lea     40(%a6),%a6
        dbra    %d5,2b
        dbra    %d6,1b
        rts

        .balign 4
vars:   .space  32
silence:
        .long   0
drum_vol:
        .byte   KICK_VOL, SNARE_VOL, HAT_VOL
        .balign 2

        .include "gen_data.s"
