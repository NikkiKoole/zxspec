; NES JAMS - triangle bass, pulse arpeggio + pulse "echo", DMC kick sample,
; noise snare/hat. Music and visuals run in the 60 Hz NMI.
; Visuals: text + level meters, backdrop flash and a little screen shake
; on every kick.
; build: python3 build.py

.include "gen_data.inc"

; ---- zero page
.segment "ZEROPAGE"
fcnt:     .res 1
pend:     .res 4          ; bass, arp, drum, echo
arp_t:    .res 1          ; frames since the arp note (envelope position)
echo_t:   .res 1
meter:    .res 4          ; bass, arp, echo, drums
flash:    .res 1
songptr:  .res 2
nptr:     .res 2          ; noise sequence pointer (hi byte 0 = idle)
tmp:      .res 1

FRAMES_PER_TICK = 7

.segment "HEADER"
        .byte "NES", $1a
        .byte 1                 ; 16 KB PRG
        .byte 1                 ; 8 KB CHR
        .byte $01               ; vertical mirroring, mapper 0
        .byte $00
        .res 8, 0

.segment "CODE"
Reset:
        sei
        cld
        ldx #$ff
        txs
        inx
        stx $2000               ; NMI off
        stx $2001               ; rendering off
        stx $4010               ; DMC IRQ off
        lda #$40
        sta $4017               ; APU frame IRQ off
        bit $2002
@vb1:   bit $2002               ; wait for the PPU to warm up
        bpl @vb1
        txa
@ram:   sta $0000,x
        sta $0100,x
        sta $0200,x
        sta $0300,x
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        inx
        bne @ram
@vb2:   bit $2002
        bpl @vb2

        lda #$3f                ; palette
        sta $2006
        lda #$00
        sta $2006
        ldx #0
@pal:   lda palette,x
        sta $2007
        inx
        cpx #16
        bne @pal

        lda #$20                ; nametable 0 + attributes (1024 bytes)
        sta $2006
        lda #$00
        sta $2006
        lda #<nametable
        sta songptr
        lda #>nametable
        sta songptr+1
        ldx #4
        ldy #0
@nt:    lda (songptr),y
        sta $2007
        iny
        bne @nt
        inc songptr+1
        dex
        bne @nt

        ; ---- APU
        lda #$0f
        sta $4015               ; pulse 1+2, triangle, noise
        lda #$08
        sta $4001               ; sweep units off
        sta $4005
        lda #$30
        sta $4000               ; pulses silent (constant volume 0)
        sta $4004
        sta $400c               ; noise silent
        lda #$80
        sta $4008               ; triangle silent
        lda #DMC_RATE
        sta $4010
        lda #$40
        sta $4011               ; DMC output level: middle
        lda #<((dmc_kick - $c000) / 64)
        sta $4012
        lda #DMC_LEN_REG
        sta $4013
        lda #15
        sta arp_t
        sta echo_t

        lda #<song
        sta songptr
        lda #>song
        sta songptr+1

@vb3:   bit $2002
        bpl @vb3
        lda #0
        sta $2005
        sta $2005
        lda #%10000000          ; NMI on, BG from pattern table 0
        sta $2000
        lda #%00001010          ; show background (incl. left column)
        sta $2001
forever:
        jmp forever

; ---------------------------------------------------------------- NMI
NMI:
        pha
        txa
        pha
        tya
        pha

        ldx #0                  ; level meters
@m:     bit $2002
        lda meter_hi,x
        sta $2006
        lda meter_lo,x
        sta $2006
        lda meter,x
        sta tmp
        ldy #0
@c:     lda #0
        cpy tmp
        bcs @off
        lda #1                  ; block tile
@off:   sta $2007
        iny
        cpy #20
        bne @c
        inx
        cpx #4
        bne @m

        bit $2002               ; backdrop colour flashes on the kick
        lda #$3f
        sta $2006
        lda #$00
        sta $2006
        ldx flash
        lda flashtab,x
        sta $2007

        lda shaketab,x          ; ... and the screen shakes a little
        sta $2005
        lda #0
        sta $2005
        lda #%10000000
        sta $2000

        lda flash
        beq @nf
        dec flash
@nf:
        jsr music

        pla
        tay
        pla
        tax
        pla
IRQ:    rti

; ---------------------------------------------------------------- music
music:
        lda fcnt
        beq @frame0
        jmp @other

@frame0:                        ; fetch this 16th's row
        ldy #0
        lda (songptr),y
        sta pend
        iny
        lda (songptr),y
        sta pend+1
        iny
        lda (songptr),y
        sta pend+2
        iny
        lda (songptr),y
        sta pend+3
        clc
        lda songptr
        adc #4
        sta songptr
        bcc @nc
        inc songptr+1
@nc:    lda songptr
        cmp #<song_end
        bne @nw
        lda songptr+1
        cmp #>song_end
        bne @nw
        lda #<song
        sta songptr
        lda #>song
        sta songptr+1
@nw:    lda pend                ; bass event: silence the triangle first
        beq @fx
        lda #$80
        sta $4008
        lda #$08
        sta $400b
@fx:    jmp effects

@other: cmp #1
        beq @frame1
        jmp effects

@frame1:
        ldx pend                ; bass on the triangle
        cpx #2
        bcc @nb
        lda #$ff
        sta $4008
        lda tri_lo,x
        sta $400a
        lda tri_hi,x
        ora #$08
        sta $400b
        lda #20
        sta meter
@nb:    ldx pend+1              ; arp on pulse 1
        cpx #2
        bcc @na
        lda pul_lo,x
        sta $4002
        lda pul_hi,x
        ora #$08
        sta $4003
        lda #0
        sta arp_t
        lda #20
        sta meter+1
@na:    ldx pend+3              ; echo on pulse 2
        cpx #2
        bcc @ne
        lda pul_lo,x
        sta $4006
        lda pul_hi,x
        ora #$08
        sta $4007
        lda #0
        sta echo_t
        lda #20
        sta meter+2
@ne:    lda pend+2              ; drums
        beq effects
        cmp #1
        bne @nk
        lda #$0f                ; kick: restart the DMC sample
        sta $4015
        lda #$1f
        sta $4015
        lda #7
        sta flash
        bne @dm
@nk:    cmp #2
        bne @nh
        lda #<snare_seq
        sta nptr
        lda #>snare_seq
        sta nptr+1
        bne @dm
@nh:    lda #<hat_seq
        sta nptr
        lda #>hat_seq
        sta nptr+1
@dm:    lda #20
        sta meter+3

effects:
        ldx arp_t               ; pulse envelopes (software, per frame)
        lda arp_env,x
        ora #$70                ; 25% duty, constant volume
        sta $4000
        cpx #15
        bcs @a
        inc arp_t
@a:     ldx echo_t
        lda echo_env,x
        ora #$30                ; 12.5% duty
        sta $4004
        cpx #15
        bcs @e
        inc echo_t
@e:
        lda nptr+1              ; noise drum: (volume, period) per frame
        beq @nn
        ldy #0
        lda (nptr),y
        cmp #$ff
        bne @play
        lda #$30
        sta $400c
        lda #0
        sta nptr+1
        beq @nn
@play:  ora #$30
        sta $400c
        iny
        lda (nptr),y
        sta $400e
        lda #$08
        sta $400f
        clc
        lda nptr
        adc #2
        sta nptr
        bcc @nn
        inc nptr+1
@nn:
        ldx #3                  ; meters fall back
@md:    lda meter,x
        beq @mz
        dec meter,x
@mz:    dex
        bpl @md

        inc fcnt
        lda fcnt
        cmp #FRAMES_PER_TICK
        bne @done
        lda #0
        sta fcnt
@done:  rts

.segment "VECTORS"
        .word NMI, Reset, IRQ
