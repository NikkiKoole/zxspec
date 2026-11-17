; C64 JAMS - bass + arpeggio + drums on the SID, with raster bars
; build: python3 build.py   (generates song.asm, then runs acme)

!cpu 6510
!to "c64jams.prg", cbm

SID   = $d400
ptr   = $fb             ; song pointer (zero page)
dptr  = $fd             ; drum sequence pointer (zero page)
FRAMES_PER_TICK = 6     ; 50 Hz / 6 = one 16th note at 125 bpm

; draw a 20-char level meter
!macro meter .addr, .m {
        ldy #0
-       lda #$a0                ; solid block
        cpy .m
        bcc +
        lda #$20                ; space
+       sta .addr,y
        iny
        cpy #20
        bne -
}

; ---- BASIC stub: 10 SYS 2061
* = $0801
        !word basic_end, 10
        !byte $9e
        !text "2061"
        !byte 0
basic_end:
        !word 0

; ---- setup
* = $080d
start:
        sei
        lda #$7f                ; no CIA interrupts: we sync to the raster ourselves
        sta $dc0d
        lda $dc0d
        lda #0
        sta $d020
        sta $d021

        ldx #0                  ; copy screen text + colours
-       lda screen,x
        sta $0400,x
        lda screen+$100,x
        sta $0500,x
        lda screen+$200,x
        sta $0600,x
        lda screen+$300,x
        sta $0700,x
        lda colours,x
        sta $d800,x
        lda colours+$100,x
        sta $d900,x
        lda colours+$200,x
        sta $da00,x
        lda colours+$300,x
        sta $db00,x
        inx
        bne -

        ldx #$18                ; silence the SID
        lda #0
-       sta SID,x
        dex
        bpl -
        lda #$09                ; voice 1 (bass): pulse, A0 D9 S10 R4
        sta SID+5
        lda #$a4
        sta SID+6
        lda #$28                ; voice 2 (arp): triangle, soft A2 D8 S6 R6
        sta SID+12
        lda #$66
        sta SID+13
        lda #$09                ; voice 3 (drums): A0 D9 S0 R0
        sta SID+19
        lda #$00
        sta SID+20
        lda #$08                ; voice 3 pulse width 50% (snare body)
        sta SID+17
        lda #$a1                ; resonance 10, voice 1 through the filter
        sta SID+23
        lda #$1f                ; low-pass, volume 15
        sta SID+24

        lda #<song
        sta ptr
        lda #>song
        sta ptr+1
        lda #0
        sta dptr+1

; ---- main loop: one pass per frame
mainloop:
        lda #16                 ; top border: raster bars
        jsr waitline
        ldx #34
        jsr bars

        jsr play                ; music + meters while the screen is drawn
        +meter $0400 + 12*40 + 12, meter
        +meter $0400 + 14*40 + 12, meter+1
        +meter $0400 + 16*40 + 12, meter+2
        ldx flash               ; kick drum flashes the background
        lda flashtab,x
        sta $d021
        lda flash
        beq +
        dec flash
+       inc scroll

        lda #251                ; bottom border: raster bars
        jsr waitline
        ldx #48
        jsr bars
        jmp mainloop

; wait for raster line A (0-255)
waitline:
        sta target
-       lda $d011
        bmi -
        lda $d012
        cmp target
        bne -
        rts

; colour the border for X raster lines
bars:
        ldy scroll
-       lda $d012
--      cmp $d012
        beq --
        lda bartab,y
        sta $d020
        iny
        dex
        bne -
        lda #0
        sta $d020
        rts

; ---- music driver, called once per frame
; song rows: 3 bytes per 16th (bass, arp, drum)
;   voices 1/2: 0 = hold, 1 = release, 2+ = note number (MIDI)
;   voice 3:    0 = none, 1 = kick, 2 = snare, 3 = hi-hat
play:
        lda fcnt
        bne frame_other

        ; frame 0: fetch the row, gate off voices that get a new event
        ldy #0
        lda (ptr),y
        sta pend
        iny
        lda (ptr),y
        sta pend+1
        iny
        lda (ptr),y
        sta pend+2
        lda pend
        beq +
        lda #$40
        sta SID+4
+       lda pend+1
        beq +
        lda #$10
        sta SID+11
+       clc
        lda ptr
        adc #3
        sta ptr
        bcc +
        inc ptr+1
+       lda ptr
        cmp #<song_end
        bne effects
        lda ptr+1
        cmp #>song_end
        bne effects
        lda #<song              ; loop the song
        sta ptr
        lda #>song
        sta ptr+1
        jmp effects

frame_other:
        cmp #1
        bne effects
        ; frame 1: start the new notes
        ldx pend
        cpx #2
        bcc +
        lda freqlo,x
        sta SID+0
        lda freqhi,x
        sta SID+1
        lda #$41                ; pulse + gate
        sta SID+4
        lda #$90                ; open the filter: "squelch"
        sta cutoff
        lda #20
        sta meter
+       ldx pend+1
        cpx #2
        bcc +
        lda freqlo,x
        sta SID+7
        lda freqhi,x
        sta SID+8
        lda #$11                ; triangle + gate
        sta SID+11
        lda #20
        sta meter+1
+       ldx pend+2
        beq effects
        lda drumlo-1,x
        sta dptr
        lda drumhi-1,x
        sta dptr+1
        lda #20
        sta meter+2
        cpx #1
        bne effects
        lda #4
        sta flash

effects:
        lda dptr+1              ; step the drum sequence: (control, freq hi) per frame
        beq nodrum
        ldy #0
        lda (dptr),y
        bne +
        sta dptr+1
        beq nodrum
+       sta SID+18
        iny
        lda (dptr),y
        sta SID+15
        clc
        lda dptr
        adc #2
        sta dptr
        bcc nodrum
        inc dptr+1
nodrum:
        lda cutoff              ; filter closes after each bass note
        cmp #$20
        bcc +
        sec
        sbc #5
        sta cutoff
+       lda cutoff
        sta SID+22

        clc                     ; slow pulse-width sweep on the bass
        lda pw
        adc #$18
        sta pw
        sta SID+2
        lda pw+1
        adc #0
        and #$0f
        sta pw+1
        sta SID+3

        ldx #2                  ; meters fall back
-       lda meter,x
        beq +
        dec meter,x
+       dex
        bpl -

        inc fcnt
        lda fcnt
        cmp #FRAMES_PER_TICK
        bne +
        lda #0
        sta fcnt
+       rts

; ---- variables
fcnt:   !byte 0
pend:   !byte 0, 0, 0
cutoff: !byte 0
pw:     !word $0800
meter:  !byte 0, 0, 0
flash:  !byte 0
scroll: !byte 0
target: !byte 0
flashtab: !byte 0, 11, 11, 12, 12

; ---- drum sequences: (control register, frequency hi) per frame, 0 ends
drumlo: !byte <kick, <snare, <hat
drumhi: !byte >kick, >snare, >hat
kick:   !byte $11,$28, $11,$18, $11,$10, $11,$0b, $11,$08, $11,$06, $11,$05, $10,$04, 0
snare:  !byte $81,$30, $41,$0c, $81,$28, $81,$24, $80,$20, 0
hat:    !byte $81,$f8, $80,$f8, 0

!source "song.asm"
