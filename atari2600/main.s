; ATARI JAMS - the groove on the 2600's TIA: two channels, 32 pitches each.
;   voice 0: bass (buzzy div-31 / 4-bit-poly modes low, pure square up top)
;   voice 1: drums (noise + a falling buzz for the kick), and between hits
;            the arpeggio from bar 9 (pure tones), the classic way to fit 3 parts in 2
; No screen memory: the kernel sets the background colour on every one of the
; 192 lines (rolling bars, brighter on the kick) and the playfield draws three
; level meters that grow from the centre.
; build: python3 build.py   (generates gen.inc, assembles atarijams.bin)

.setcpu "6502"

VSYNC  = $00
VBLANK = $01
WSYNC  = $02
COLUPF = $08
COLUBK = $09
CTRLPF = $0A
PF0    = $0D
PF1    = $0E
PF2    = $0F
AUDC0  = $15
AUDC1  = $16
AUDF0  = $17
AUDF1  = $18
AUDV0  = $19
AUDV1  = $1A
INTIM  = $0284
TIM64T = $0296

FRAMES_PER_TICK = 7             ; 60 Hz: a 16th note at ~128 bpm

.include "gen.inc"

.segment "ZEROPAGE"
fcnt:       .res 1
step:       .res 1
bar:        .res 1
root:       .res 1
groove:     .res 1
tmp:        .res 1
bass_env:   .res 1
arp_env:    .res 1
arp_cv:     .res 1
arp_fv:     .res 1
drum_type:  .res 1
drum_frame: .res 1
flash:      .res 1
scroll:     .res 1
gptr:       .res 2
meter:      .res 3              ; bass, arp, drums
seg0:       .res 8              ; PF0 / PF1 / PF2 per screen segment
seg1:       .res 8
seg2:       .res 8

.segment "CODE"
Reset:
        sei
        cld
        ldx #0
        txa
@clr:   dex                     ; clear the TIA and all 128 bytes of RAM
        txs
        pha
        bne @clr
        lda #1
        sta CTRLPF              ; reflected playfield: meters grow from the centre
        lda #15
        sta bass_env
        sta arp_env

Frame:
        lda #2                  ; ---- vertical sync
        sta VBLANK
        sta VSYNC
        sta WSYNC
        sta WSYNC
        sta WSYNC
        lda #0
        sta VSYNC
        lda #43                 ; ---- vertical blank: 37 lines of free time
        sta TIM64T
        jsr Music
        jsr Prepare
@wv:    lda INTIM
        bne @wv
        sta WSYNC
        lda #0
        sta VBLANK

        ldy #0                  ; ---- the kernel: 192 visible lines in 7 segments
        ldx #0                  ;      (background / meter / background / ...)
        lda segcol
        sta COLUPF
@line:  sta WSYNC               ; every write lands before the beam reaches it:
        lda (gptr),y            ;   COLUBK ~cycle 11, PF0 18, PF1 25, PF2 32
        sta COLUBK
        lda seg0,x
        sta PF0
        lda seg1,x
        sta PF1
        lda seg2,x
        sta PF2
        iny
        tya
        cmp segend,x
        bne @line
        inx                     ; next segment (its colour is set in the right border,
        lda segcol,x            ;  where this segment's playfield is already blank)
        sta COLUPF
        cpx #7
        bne @line

        lda #2                  ; ---- overscan
        sta VBLANK
        lda #0
        sta PF0
        sta PF1
        sta PF2
        lda #35
        sta TIM64T
@wo:    lda INTIM
        bne @wo
        jmp Frame

; ---------------------------------------------------------------- music
Music:
        lda fcnt
        bne @env
        jsr Tick
@env:   ldx bass_env            ; voice 0: the bass's volume envelope
        lda bass_env_tab,x
        sta AUDV0
        cpx #15
        bcs @v1
        inc bass_env
@v1:    lda drum_type           ; voice 1: a drum while one is sounding ...
        beq @arp
        sec
        sbc #1
        asl
        asl
        asl
        clc
        adc drum_frame          ; (type-1)*8 + frame
        tax
        lda drum_c,x
        sta AUDC1
        lda drum_f,x
        sta AUDF1
        lda drum_v,x
        sta AUDV1
        inc drum_frame
        lda drum_frame
        cmp #8
        bne @tick
        lda #0
        sta drum_type
        beq @tick
@arp:   lda arp_cv              ; ... otherwise the arpeggio note
        sta AUDC1
        lda arp_fv
        sta AUDF1
        ldx arp_env
        lda arp_env_tab,x
        sta AUDV1
        cpx #15
        bcs @tick
        inc arp_env
@tick:  inc fcnt
        lda fcnt
        cmp #FRAMES_PER_TICK
        bne @done
        lda #0
        sta fcnt
@done:  rts

Tick:
        ldx bar
        lda barinfo,x           ; groove << 4 | root, or $FF for the silent bar
        cmp #$FF
        bne @play
        jmp @adv
@play:  sta tmp
        and #$0F
        sta root
        lda tmp
        lsr
        lsr
        lsr
        lsr
        sta groove

        cpx #LAST_BAR           ; ---- bass
        bne @bnorm
        lda step
        bne @nobass
        ldy root
        lda bass_lo_c,y
        sta AUDC0
        lda bass_lo_f,y
        sta AUDF0
        lda #0
        sta bass_env
        lda #20
        sta meter
        bne @nobass
@bnorm: lda step
        and #1
        bne @rel
        ldy root
        lda step
        and #2                  ; every other eighth jumps up an octave
        bne @hi
        lda bass_lo_c,y
        sta AUDC0
        lda bass_lo_f,y
        sta AUDF0
        jmp @bon
@hi:    lda bass_hi_c,y
        sta AUDC0
        lda bass_hi_f,y
        sta AUDF0
@bon:   lda #0
        sta bass_env
        lda #20
        sta meter
        bne @nobass
@rel:   lda #15                 ; staccato: off on the in-between 16ths
        sta bass_env
@nobass:
        cpx #ARP_FROM_BAR       ; ---- arpeggio
        bcc @noarp
        lda step
        and #1
        bne @noarp
        cpx #LAST_BAR
        bne @arpn
        lda step
        bne @noarp
        lda #3                  ; last bar: one long octave
        bne @arps
@arpn:  lda step
        lsr
        tay
        lda arp_shape,y
@arps:  sta tmp
        lda root
        asl
        asl
        clc
        adc tmp
        tay
        lda arp_c,y
        sta arp_cv
        lda arp_f,y
        sta arp_fv
        lda #0
        sta arp_env
        lda #20
        sta meter+1
@noarp:
        lda groove              ; ---- drums
        asl
        asl
        asl
        asl
        clc
        adc step
        tay
        lda grooves,y
        beq @adv
        sta drum_type
        lda #0
        sta drum_frame
        lda #20
        sta meter+2
        lda drum_type
        cmp #1
        bne @adv
        lda #7
        sta flash

@adv:   inc step                ; ---- next 16th
        lda step
        cmp #16
        bne @r
        lda #0
        sta step
        inc bar
        lda bar
        cmp #LOOP_BARS
        bne @r
        lda #0
        sta bar
@r:     rts

; ---------------------------------------------------------------- visuals
Prepare:
        lda scroll              ; background: a scrolling gradient, bright on the kick
        sta gptr
        lda #>gradtab
        ldx flash
        beq @g
        lda #>gradtab_hot
        dec flash
@g:     sta gptr+1
        inc scroll
        ldx #0                  ; meters -> playfield bytes of segments 1, 3, 5
@m:     ldy meter,x
        txa
        asl
        sta tmp
        inc tmp                 ; segment = 2 * meter + 1
        lda pfm0,y
        ldy tmp
        sta seg0,y
        ldy meter,x
        lda pfm1,y
        ldy tmp
        sta seg1,y
        ldy meter,x
        lda pfm2,y
        ldy tmp
        sta seg2,y
        lda meter,x
        beq @z
        dec meter,x
@z:     inx
        cpx #3
        bne @m
        rts

.segment "VECTORS"
        .word Reset, Reset, Reset
