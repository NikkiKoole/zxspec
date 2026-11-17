; PC SPEAKER JAMS - the groove on the PC's 1-bit speaker, as a tour of the tricks:
;   bars 1-8   TRICK 1  one square wave from PIT channel 2; drums interrupt it
;   bars 9-16  TRICK 2  fast switching between bass and arpeggio = fake polyphony
;   bars 17-33 TRICK 3  "RealSound" PWM: PIT channel 2 as a one-shot whose length is
;                       the sample value, retriggered 18643 times a second, playing a
;                       software mix (sine bass, arpeggio, 3 pad voices, drum samples)
; PIT channel 0 is reprogrammed to fire IRQ0 at 18643 Hz for all of it.
; build: python3 build.py -> pcjams.com      ESC quits (restores the timer).

bits 16
cpu 386
org 100h

%include "gen_equ.asm"

PIT_DIV     equ 64                  ; 1193182 / 64 = 18643 Hz
SUBDIV      equ 19
HOP         equ 20                  ; trick 2: updates (~1 ms each) per note before hopping                  ; tricks 1/2 update the square wave every 19 ticks (~1 kHz)
FRAME_TICKS equ 311                 ; ~60 frames per second
RINGMASK    equ 1023
FRAMES_PER_TICK equ 7

start:
        mov ax, 3                   ; 80x25 text
        int 10h
        mov ah, 1                   ; hide the cursor
        mov cx, 2000h
        int 10h
        call draw_static

        mov ax, 3508h               ; keep the old timer interrupt
        int 21h
        mov [old8], bx
        mov [old8 + 2], es
        push ds
        pop es
        mov ax, 2508h               ; install ours
        mov dx, irq0
        int 21h

        mov byte [subcnt], SUBDIV
        mov word [rowptr], song
        mov al, 0B6h                ; channel 2: square wave (mode 3), lo/hi bytes
        out 43h, al
        cli
        mov al, 36h                 ; channel 0: rate generator at 18643 Hz
        out 43h, al
        mov ax, PIT_DIV
        out 40h, al
        mov al, ah
        out 40h, al
        sti

main_loop:
        cmp byte [engine], 2        ; trick 3: keep the PWM ring topped up
        jne .frame
        call fill_ring
.frame: mov ax, [ticks]
        sub ax, [frame_at]
        cmp ax, FRAME_TICKS
        jb .key
        add word [frame_at], FRAME_TICKS
        call sequencer
        call visuals
.key:   mov ah, 1
        int 16h
        jz main_loop
        xor ah, ah
        int 16h
        cmp al, 27
        jne main_loop

quit:   cli
        mov al, 36h                 ; channel 0 back to the normal 18.2 Hz
        out 43h, al
        xor al, al
        out 40h, al
        out 40h, al
        in al, 61h                  ; speaker off
        and al, 0FCh
        out 61h, al
        push ds
        lds dx, [old8]
        mov ax, 2508h
        int 21h
        pop ds
        sti
        mov ax, 3
        int 10h
        mov ax, 4C00h
        int 21h

; ---------------------------------------------------------------- the timer interrupt
irq0:
        push ax
        push bx
        cmp byte [cs:engine], 2
        jne .square
        mov bx, [cs:rd]             ; trick 3: next PWM sample = the one-shot length
        mov al, [cs:ring + bx]
        out 42h, al
        inc bx
        and bx, RINGMASK
        mov [cs:rd], bx
        jmp .done
.square:
        dec byte [cs:subcnt]
        jnz .done
        mov byte [cs:subcnt], SUBDIV
        push ds
        push cs
        pop ds
        call update_square
        pop ds
.done:  inc word [cs:ticks]
        mov al, 20h
        out 20h, al
        pop bx
        pop ax
        iret

speaker_on:
        in al, 61h
        or al, 3
        out 61h, al
        ret
speaker_off:
        in al, 61h
        and al, 0FCh
        out 61h, al
        ret
set_div:                            ; ax = PIT divisor for channel 2
        out 42h, al
        mov al, ah
        out 42h, al
        ret

; tricks 1 and 2, ~1000 times a second: which single pitch does the speaker play now?
update_square:
        push cx
        cmp byte [drum_t], 0
        je .nodrum
        dec byte [drum_t]
        cmp byte [drum_type], 1
        jne .noise
        xor bh, bh                  ; kick: walk down the sweep table
        mov bl, [drum_t]
        add bx, bx
        mov ax, [kick_sweep + bx]
        call set_div
        call speaker_on
        jmp .ret
.noise: mov ax, [lfsr]              ; snare / hat: a new random pitch every update
        shr ax, 1
        jnc .nx
        xor ax, 0B400h
.nx:    mov [lfsr], ax
        cmp byte [drum_type], 2
        jne .hat
        and ax, 1FFh
        add ax, 60
        jmp .nset
.hat:   and ax, 1Fh
        add ax, 10
.nset:  call set_div
        call speaker_on
        jmp .ret
.nodrum:
        cmp byte [engine], 1
        jne .one
        inc byte [alt]              ; trick 2: alternate bass / arpeggio, ~20 ms each so
        cmp byte [alt], HOP * 2     ; every note gets whole cycles (shorter hops smear
        jb .hop                     ; the pitch: a low bass cycle alone is ~12 ms)
        mov byte [alt], 0
.hop:   cmp byte [alt], HOP
        jb .one
        cmp byte [arp_on], 0
        je .one
        mov ax, [arp_div]
        call set_div
        call speaker_on
        jmp .ret
.one:   cmp byte [bass_on], 0
        je .off
        mov ax, [bass_div]
        call set_div
        call speaker_on
        jmp .ret
.off:   call speaker_off
.ret:   pop cx
        ret

; ---------------------------------------------------------------- trick 3: the mixer
fill_ring:
.more:  mov ax, [wr]
        sub ax, [rd]
        and ax, RINGMASK
        cmp ax, 900
        jae .full
        call mix_one
        mov bx, [wr]
        mov [ring + bx], al
        inc bx
        and bx, RINGMASK
        mov [wr], bx
        jmp .more
.full:  ret

; one sample -> al = PWM length 1..63
mix_one:
        xor dx, dx                  ; dx = the sum
        mov ax, [bass_ph]           ; sine bass
        add ax, [bass_inc]
        mov [bass_ph], ax
        mov bl, ah
        xor bh, bh
        mov al, [sine + bx]
        mov cl, [bass_vol]
        imul cl
        add dx, ax
        mov ax, [arp_ph]            ; arpeggio: triangle
        add ax, [arp_inc]
        mov [arp_ph], ax
        mov bl, ah
        xor bh, bh
        mov al, [tri + bx]
        mov cl, [arp_vol]
        imul cl
        sar ax, 1
        add dx, ax
        mov si, 0                   ; three pad voices: soft saws
.pad:   mov ax, [pad_ph + si]
        add ax, [pad_inc + si]
        mov [pad_ph + si], ax
        mov bl, ah
        xor bh, bh
        mov al, [saw + bx]
        mov cl, [pad_vol]
        imul cl
        sar ax, 2
        add dx, ax
        add si, 2
        cmp si, 6
        jb .pad
        mov si, [smp_left]          ; drum sample
        or si, si
        jz .nos
        dec word [smp_left]
        mov bx, [smp_ptr]
        mov al, [bx]
        inc word [smp_ptr]
        cbw
        mov cl, 4
        shl ax, cl
        add dx, ax
.nos:   mov ax, dx                  ; scale to 6 bits around the middle
        sar ax, 7
        add ax, 32
        cmp ax, 1
        jge .lo
        mov ax, 1
.lo:    cmp ax, 63
        jle .hi
        mov ax, 63
.hi:    ret

; ---------------------------------------------------------------- the song
sequencer:
        cmp byte [fcnt], 0
        jne .frame
        mov si, [rowptr]
        mov al, [si + 3]            ; which trick is this bar? (stored per row)
        cmp al, [engine]
        je .same
        call switch_engine
.same:  mov al, [si]                ; bass
        cmp al, 2
        jb .brel
        xor ah, ah
        mov bx, ax
        add bx, bx
        mov dx, [divtab + bx]
        mov [bass_div], dx
        mov dx, [inctab + bx]
        mov [bass_inc], dx
        mov byte [bass_on], 1
        mov byte [bass_vol], 15
        mov byte [meter], 30
        jmp .arp
.brel:  cmp al, 1
        jne .arp
        mov byte [bass_on], 0
.arp:   mov al, [si + 1]
        cmp al, 2
        jb .drum
        xor ah, ah
        mov bx, ax
        add bx, bx
        mov dx, [divtab + bx]
        mov [arp_div], dx
        mov dx, [inctab + bx]
        mov [arp_inc], dx
        mov byte [arp_on], 1
        mov byte [arp_vol], 12
        mov byte [arp_life], 10
        mov byte [meter + 1], 30
.drum:  mov al, [si + 2]
        or al, al
        jz .pad
        cli
        mov [drum_type], al
        mov byte [drum_t], DRUM_UPDATES
        cmp al, 3
        jne .dlen
        mov byte [drum_t], 15       ; a hat is shorter
.dlen:  sti
        xor ah, ah
        dec ax
        mov bx, ax
        add bx, bx
        mov dx, [smp_start + bx]
        mov [smp_ptr], dx
        mov dx, [smp_len + bx]
        mov [smp_left], dx
        mov byte [meter + 3], 30
        cmp al, 0
        jne .pad
        mov byte [flash], 8
.pad:   mov al, [si + 4]            ; pad chord (trick 3 only)
        cmp al, 1
        jb .next
        jne .chord
        mov byte [pad_target], 0
        jmp .next
.chord: sub al, 2
        mov ah, 3
        mul ah
        mov bx, ax
        mov di, 0
.pc:    mov al, [chordtab + bx]
        xor ah, ah
        push bx
        mov bx, ax
        add bx, bx
        mov dx, [inctab + bx]
        pop bx
        mov [pad_inc + di], dx
        inc bx
        add di, 2
        cmp di, 6
        jb .pc
        mov byte [pad_target], 7
        mov byte [meter + 2], 30
.next:  add si, ROW_BYTES
        cmp si, song_end
        jb .sv
        mov si, song
.sv:    mov [rowptr], si
.frame: inc byte [fcnt]             ; ---- every frame: envelopes
        cmp byte [fcnt], FRAMES_PER_TICK
        jb .env
        mov byte [fcnt], 0
.env:   cmp byte [bass_on], 0
        jne .bv
        shr byte [bass_vol], 1      ; release: halve each frame (no click)
        jmp .av
.bv:    cmp byte [bass_vol], 9
        jbe .av
        dec byte [bass_vol]
.av:    cmp byte [arp_vol], 0
        je .al
        dec byte [arp_vol]
.al:    cmp byte [arp_life], 0
        je .aoff
        dec byte [arp_life]
        jmp .pv
.aoff:  mov byte [arp_on], 0
.pv:    mov al, [pad_vol]
        cmp al, [pad_target]
        je .m
        jb .pup
        dec byte [pad_vol]
        jmp .m
.pup:   inc byte [pad_vol]
.m:     mov bx, 0
.md:    cmp byte [meter + bx], 0
        je .mz
        dec byte [meter + bx]
.mz:    inc bx
        cmp bx, 4
        jb .md
        cmp byte [flash], 0
        je .f
        dec byte [flash]
.f:     ret

switch_engine:                      ; al = 0 / 1 / 2
        cli
        mov [engine], al
        cmp al, 2
        jne .square
        mov al, 90h                 ; channel 2: one-shot (mode 0), low byte only
        out 43h, al
        mov al, 32
        out 42h, al
        mov bx, [rd]                ; ring: half a buffer of silence to start
        add bx, 512
        and bx, RINGMASK
        mov [wr], bx
        mov cx, 1024
        mov di, ring
.fill:  mov byte [di], 32
        inc di
        loop .fill
        call speaker_on
        jmp .done
.square:
        mov al, 0B6h                ; channel 2: square wave again
        out 43h, al
        call speaker_off
.done:  sti
        mov byte [trick_dirty], 1
        ret

; ---------------------------------------------------------------- the screen (text mode)
put_str:                            ; ds:si = row, col, attr, text..., 0 ; ends with 0FFh
        push es
        mov ax, 0B800h
        mov es, ax
.s:     lodsb
        cmp al, 0FFh
        je .d
        mov bl, 160
        mul bl
        mov di, ax
        lodsb
        xor ah, ah
        add ax, ax
        add di, ax
        lodsb
        mov ah, al
.c:     lodsb
        or al, al
        jz .s
        stosw
        jmp .c
.d:     pop es
        ret

draw_static:
        mov si, static_text
        call put_str
        ret

visuals:
        push es
        mov ax, 0B800h
        mov es, ax
        mov bx, 0                   ; meters: 4 rows of up to 30 blocks
.mr:    mov al, bl
        mov ah, 160
        mul ah
        add ax, METER_ROW * 160 + METER_COL * 2
        mov di, ax
        mov cl, [meter + bx]
        mov ch, 0
        mov ah, [meter_attr + bx]
.mc:    cmp ch, cl
        mov al, 0DBh
        jb .lit
        mov al, 0FAh
.lit:   stosw
        inc ch
        cmp ch, 30
        jb .mc
        inc bx
        cmp bx, 4
        jb .mr
        cmp byte [trick_dirty], 0   ; the trick description, when it changes
        je .fl
        mov byte [trick_dirty], 0
        mov al, [engine]
        xor ah, ah
        mov bx, ax
        add bx, bx
        mov si, [trick_text + bx]
        pop es
        call put_str
        push es
        mov ax, 0B800h
        mov es, ax
.fl:    mov al, [flash]             ; the "speaker cone": a box that pulses on the kick
        mov ah, 08h
        or al, al
        jz .box
        mov ah, 0Fh
.box:   mov di, CONE_ROW * 160 + CONE_COL * 2
        mov cx, 5
.br:    push cx
        push di
        mov cx, 12
        mov al, 0B1h
        rep stosw
        pop di
        pop cx
        add di, 160
        loop .br
        pop es
        ret

; ---------------------------------------------------------------- data
old8:       dd 0
ticks:      dw 0
frame_at:   dw 0
subcnt:     db 0
engine:     db 0
trick_dirty: db 1
fcnt:       db 0
rowptr:     dw 0
alt:        db 0
lfsr:       dw 0ACE1h
bass_on:    db 0
bass_div:   dw 0
bass_inc:   dw 0
bass_ph:    dw 0
bass_vol:   db 0
arp_on:     db 0
arp_life:   db 0
arp_div:    dw 0
arp_inc:    dw 0
arp_ph:     dw 0
arp_vol:    db 0
pad_inc:    dw 0, 0, 0
pad_ph:     dw 0, 0, 0
pad_vol:    db 0
pad_target: db 0
drum_type:  db 0
drum_t:     db 0
smp_ptr:    dw 0
smp_left:   dw 0
meter:      db 0, 0, 0, 0
flash:      db 0
rd:         dw 0
wr:         dw 0
meter_attr: db 0Ah, 0Dh, 06h, 0Eh

%include "gen_data.asm"

ring:       times 1024 db 32
