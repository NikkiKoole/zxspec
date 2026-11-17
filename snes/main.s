; SNES JAMS - sampled bass, arp and pads + drum samples, with hardware echo
;
; The SPC700 (sound CPU) runs a 22-byte relay: we hand it (DSP register,
; value) pairs through the APU ports and it writes them to the S-DSP. All
; music logic lives here on the 65816, driven by the 60 Hz NMI.
; Voices: 0 bass, 1 arp (ping-pongs L/R), 2-4 pad chord (L/C/R),
;         5 kick, 6 snare, 7 hi-hat. Echo on arp, pads and snare.
; Visuals: HDMA backdrop gradient that scrolls and flashes on the kick,
;          text + level meters on BG1.
; build: python3 build.py

.p816
.smart +

; ---- direct page variables
fcnt      = $20
pend      = $21       ; 4 bytes: bass, arp, drum, pad
meter     = $25       ; 4 bytes: bass, arp, pads, drums
flash     = $29
scroll    = $2a       ; word
songptr   = $2c       ; word
counter   = $2e       ; APU port handshake counter
panflag   = $2f
nmi_flag  = $30
echo_wait = $31
dsp_val   = $32
kon_mask  = $33
koff_mask = $34
gptr      = $36       ; word: gradient table pointer
hdma_tab  = $0400     ; 224 lines x 5 bytes + end marker

FRAMES_PER_TICK = 7

.include "gen_data.inc"

.segment "CODE"

Reset:
        sei
        clc
        xce                     ; native mode
        rep #$38                ; 16-bit A/X/Y, binary mode
        ldx #$1fff
        txs
        lda #$0000
        tcd                     ; direct page = $0000
        sep #$20
        lda #$80
        sta $2100               ; force blank
        stz $4200               ; no NMI yet
        stz $420c               ; no HDMA yet

        ldx #$0000              ; clear our variables
@clr:   stz $00,x
        inx
        cpx #$0100
        bne @clr

        ; ---- PPU setup
        stz $2101
        stz $2102
        stz $2103
        stz $2105               ; mode 0
        stz $2106
        lda #$04
        sta $2107               ; BG1 map at VRAM word $0400
        stz $2108
        stz $2109
        stz $210a
        stz $210b               ; BG1 tiles at VRAM word $0000
        stz $210c
        ldx #$000d              ; all scroll registers = 0 (written twice)
@scr:   stz $2100,x
        stz $2100,x
        inx
        cpx #$0015
        bne @scr
        stz $2123
        stz $2124
        stz $2125
        stz $2126
        stz $2127
        stz $2128
        stz $2129
        stz $212a
        stz $212b
        lda #$01
        sta $212c               ; BG1 on the main screen
        stz $212d
        stz $212e
        stz $212f
        stz $2130
        stz $2131
        stz $2133

        lda #$80                ; VRAM: increment after the high byte
        sta $2115
        rep #$20
        stz $2116               ; tiles at word $0000
        ldx #$0000
@tiles: lda tiles,x
        sta $2118
        inx
        inx
        cpx #TILE_BYTES
        bne @tiles
        lda #$0400              ; tilemap at word $0400
        sta $2116
        ldx #$0000
@map:   lda tilemap,x
        sta $2118
        inx
        inx
        cpx #$0800
        bne @map
        sep #$20

        stz $2121               ; palette
        ldx #$0000
@pal:   lda palette,x
        sta $2122
        inx
        cpx #$0040
        bne @pal

        ; ---- HDMA backdrop gradient table (count, CGADD, CGADD, lo, hi)
        ldx #$0000
@ht:    lda #$01
        sta hdma_tab,x
        stz hdma_tab+1,x
        stz hdma_tab+2,x
        stz hdma_tab+3,x
        stz hdma_tab+4,x
        rep #$20
        txa
        clc
        adc #$0005
        tax
        sep #$20
        cpx #224*5
        bne @ht
        stz hdma_tab,x          ; end of table
        lda #$03                ; mode 3: $2121, $2121, $2122, $2122
        sta $4300
        lda #$21
        sta $4301
        ldx #hdma_tab
        stx $4302
        stz $4304

        ; ---- sound
        jsr upload_spc
        jsr dsp_init

        jsr gradient
        lda #$01
        sta $420c               ; HDMA channel 0 on
        lda #$0f
        sta $2100               ; screen on, full brightness
        lda #$80
        sta $4200               ; NMI on

main:   wai
        lda nmi_flag
        beq main
        stz nmi_flag
        jsr echo_fade_in
        jsr music
        jsr gradient
        bra main

; ---------------------------------------------------------------- NMI
NMI:
        rep #$30
        pha
        phx
        phy
        sep #$20
        lda $4210               ; acknowledge
        ; meters -> BG1 tilemap
        ldy #$0000
@m:     rep #$20
        lda meter_addr,y        ; meter_addr: 4 words, meter_pal: 4 words
        sta $2116
        lda meter_pal,y
        sta $40                 ; tile word for a lit cell
        tya
        lsr a
        tax
        sep #$20
        lda meter,x
        sta $42                 ; level 0..20
        ldx #$0000
@c:     rep #$20
        lda #$0000
        sep #$20
        txa
        cmp $42
        rep #$20
        lda #$0000
        bcs @off
        lda $40
@off:   sta $2118
        sep #$20
        inx
        cpx #20
        bne @c
        iny
        iny
        cpy #8
        bne @m
        lda #$01
        sta nmi_flag
        rep #$30
        ply
        plx
        pla
        rti

EmptyHandler:
        rti

; ---------------------------------------------------------------- APU
; Upload the SPC700 relay + sample directory + BRR samples (ARAM $0200..)
; with the IPL ROM's block protocol, then start it at $0200.
.a8
.i16
upload_spc:
@w1:    lda $2140
        cmp #$aa
        bne @w1
@w2:    lda $2141
        cmp #$bb
        bne @w2
        stz $2142               ; destination $0200
        lda #$02
        sta $2143
        lda #$01
        sta $2141               ; "transfer a block"
        lda #$cc
        sta $2140
@w3:    cmp $2140
        bne @w3
        ldx #$0000
@byte:  lda aram_blob,x
        sta $2141
        txa
        sta $2140
@w4:    cmp $2140
        bne @w4
        inx
        cpx #ARAM_LEN
        bne @byte
        stz $2142               ; now jump to $0200
        lda #$02
        sta $2143
        stz $2141               ; 0 = execute
        txa
        inc a
        bne @nz
        inc a
@nz:    sta $2140
@w5:    cmp $2140
        bne @w5
        sta counter
        ldx #$0800              ; give the relay a moment to start
@d:     dex
        bne @d
        rts

; write dsp_val to S-DSP register A (via the relay)
.a8
.i16
dsp_write:
        sta $2141
        lda dsp_val
        sta $2142
        inc counter
        lda counter
        sta $2140
@w:     cmp $2140
        bne @w
        rts

; table of (register, value) pairs, terminated by $ff
.a8
.i16
dsp_init:
        ldx #$0000
@l:     lda dsp_init_tab,x
        cmp #$ff
        beq @done
        pha
        lda dsp_init_tab+1,x
        sta dsp_val
        pla
        jsr dsp_write
        inx
        inx
        bra @l
@done:  rts

; echo starts silent; after its buffer has been flushed, fade it in
.a8
.i16
echo_fade_in:
        lda echo_wait
        cmp #30
        beq @done
        inc echo_wait
        cmp #29
        bne @done
        lda #ECHO_FEEDBACK
        sta dsp_val
        lda #$0d                ; EFB
        jsr dsp_write
        lda #ECHO_VOLUME
        sta dsp_val
        lda #$2c                ; EVOLL
        jsr dsp_write
        lda #$3c                ; EVOLR
        jsr dsp_write
@done:  rts

; ---------------------------------------------------------------- music
.a8
.i16
music:
        lda fcnt
        beq @frame0
        jmp @other

@frame0:                        ; fetch the row, key off retriggered voices
        ldx songptr
        lda song,x
        sta pend
        lda song+1,x
        sta pend+1
        lda song+2,x
        sta pend+2
        lda song+3,x
        sta pend+3
        inx
        inx
        inx
        inx
        cpx #SONG_BYTES
        bne @nowrap
        ldx #$0000
@nowrap:
        stx songptr
        stz koff_mask
        lda pend
        beq @k1
        lda #$01
        tsb koff_mask
@k1:    lda pend+1
        beq @k2
        lda #$02
        tsb koff_mask
@k2:    lda pend+3
        beq @k3
        lda #$1c
        tsb koff_mask
@k3:    lda koff_mask
        beq @fx
        sta dsp_val
        lda #$5c                ; KOFF
        jsr dsp_write
@fx:    jmp effects

@other: cmp #$01
        beq @frame1
        jmp effects

@frame1:                        ; key on the new notes
        stz kon_mask
        stz dsp_val
        lda #$5c                ; KOFF = 0 (or nothing could key on)
        jsr dsp_write

        lda pend                ; bass: voice 0
        cmp #$02
        bcc @nob
        jsr note_index
        lda bass_pitch,x
        sta dsp_val
        lda #$02
        jsr dsp_write
        lda bass_pitch+1,x
        sta dsp_val
        lda #$03
        jsr dsp_write
        lda #$01
        tsb kon_mask
        lda #20
        sta meter

@nob:   lda pend+1              ; arp: voice 1, ping-pong panning
        cmp #$02
        bcc @noa
        jsr note_index
        lda arp_pitch,x
        sta dsp_val
        lda #$12
        jsr dsp_write
        lda arp_pitch+1,x
        sta dsp_val
        lda #$13
        jsr dsp_write
        lda panflag
        eor #$01
        sta panflag
        beq @left
        lda #ARP_NEAR
        sta dsp_val
        lda #$11                ; VOLR loud
        jsr dsp_write
        lda #ARP_FAR
        sta dsp_val
        lda #$10
        jsr dsp_write
        bra @panned
@left:  lda #ARP_NEAR
        sta dsp_val
        lda #$10                ; VOLL loud
        jsr dsp_write
        lda #ARP_FAR
        sta dsp_val
        lda #$11
        jsr dsp_write
@panned:
        lda #$02
        tsb kon_mask
        lda #20
        sta meter+1

@noa:   lda pend+3              ; pads: voices 2-4
        cmp #$02
        bcc @nop
        sec
        sbc #$02
        sta $3c
        asl a
        clc
        adc $3c                 ; chord * 3
        rep #$20
        and #$00ff
        tay
        sep #$20
        lda #$22                ; voice 2 pitch registers
        sta $3e
@pv:    lda chordtab,y
        jsr note_index
        lda pad_pitch,x
        sta dsp_val
        lda $3e
        jsr dsp_write
        lda pad_pitch+1,x
        sta dsp_val
        lda $3e
        inc a
        jsr dsp_write
        iny
        lda $3e
        clc
        adc #$10
        sta $3e
        cmp #$52
        bne @pv
        lda #$1c
        tsb kon_mask
        lda #20
        sta meter+2

@nop:   lda pend+2              ; drums: voices 5-7
        beq @kon
        cmp #$01
        bne @nk
        lda #$20
        tsb kon_mask
        lda #7
        sta flash
        bra @drum
@nk:    cmp #$02
        bne @nh
        lda #$40
        tsb kon_mask
        bra @drum
@nh:    lda #$80
        tsb kon_mask
@drum:  lda #20
        sta meter+3

@kon:   lda kon_mask
        beq effects
        sta dsp_val
        lda #$4c                ; KON
        jsr dsp_write

effects:
        ldx #$0000              ; meters fall back
@md:    lda meter,x
        beq @mz
        dec meter,x
@mz:    inx
        cpx #4
        bne @md
        inc fcnt
        lda fcnt
        cmp #FRAMES_PER_TICK
        bne @done
        stz fcnt
@done:  rts

; A = MIDI note -> X = note * 2 (index into a pitch table)
.a8
.i16
note_index:
        rep #$20
        and #$00ff
        asl a
        tax
        sep #$20
        rts

; ---------------------------------------------------------------- visuals
; fill the HDMA table: scrolling gradient, brighter while the kick flashes
.a8
.i16
gradient:
        rep #$30
        lda flash
        and #$00ff
        xba
        asl a                   ; level * 512 bytes
        clc
        adc #gradtab
        sta gptr
        lda scroll
        and #$00ff
        asl a
        tay
        ldx #$0000
@l:     lda (gptr),y
        sta hdma_tab+3,x
        tya
        clc
        adc #$0002
        and #$01fe
        tay
        txa
        clc
        adc #$0005
        tax
        cpx #224*5
        bne @l
        inc scroll
        sep #$20
        lda flash
        beq @f
        dec flash
@f:     rts

; ---------------------------------------------------------------- header
.segment "HEADER"
        .byte "SNES JAMS            "  ; 21 bytes
        .byte $20                      ; LoROM
        .byte $00                      ; ROM only
        .byte $05                      ; 32 KB
        .byte $00                      ; no SRAM
        .byte $01                      ; North America
        .byte $00                      ; licensee
        .byte $00                      ; version
        .word $ffff, $0000             ; checksum complement, checksum (patched)

.segment "VECTORS"
        .word 0, 0
        .word EmptyHandler      ; COP
        .word EmptyHandler      ; BRK
        .word EmptyHandler      ; ABORT
        .word NMI               ; NMI
        .word 0
        .word EmptyHandler      ; IRQ
        .word 0, 0
        .word EmptyHandler      ; COP (emulation)
        .word 0
        .word EmptyHandler      ; ABORT
        .word EmptyHandler      ; NMI
        .word Reset             ; RESET
        .word EmptyHandler      ; IRQ/BRK
