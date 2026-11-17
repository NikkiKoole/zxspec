; DOS JAMS - AdLib/OPL3 FM bass, EP arpeggio + echo, pads; Sound Blaster
; drum samples (DMA); VGA mode 13h plasma with palette cycling.
; OPL3 channels: 0 bass, 1 arp (ping-pong), 2-4 pads (L/C/R), 5 arp echo.
; Timing: VGA vertical retrace, 70 Hz; a 16th note = 8 frames.
; build: python3 build.py   ->  dosjams.com      ESC quits.

bits 16
cpu 386
org 100h

FRAMES_PER_TICK equ 8
OPL     equ 388h
OPL_HI  equ 38Ah
SB      equ 220h

%include "gen_equ.asm"

start:
        mov ax, 0013h               ; 320x200, 256 colours
        int 10h
        call fixed_palette
        call set_palette
        call draw_plasma
        call draw_text
        call opl_init
        call sb_init
        call prepare_samples
        mov word [songptr], song

main_loop:
        call wait_retrace
        call set_palette
        call draw_meters
        call music
        mov ah, 1                   ; ESC quits
        int 16h
        jz main_loop
        xor ah, ah
        int 16h
        cmp al, 27
        jne main_loop

quit:
        mov cl, 0
.off:   call key_off
        inc cl
        cmp cl, 9
        jne .off
        cmp byte [sb_ok], 0
        je .nosb
        mov al, 0D3h                ; speaker off
        call dsp_write
.nosb:  mov ax, 0003h               ; back to text mode
        int 10h
        mov ax, 4C00h
        int 21h

; ---------------------------------------------------------------- video
wait_retrace:
        mov dx, 3DAh
.a:     in al, dx
        test al, 8
        jnz .a
.b:     in al, dx
        test al, 8
        jz .b
        ret

; plasma pixel = sin_a[x] + sin_b[y] + sin_c[x+y] + 1  (palette 1..192)
draw_plasma:
        push es
        mov ax, 0A000h
        mov es, ax
        xor di, di
        xor dx, dx
.y:     xor cx, cx
.x:     mov bx, cx
        and bx, 255
        mov al, [sin_a + bx]
        mov bx, dx
        add al, [sin_b + bx]
        mov bx, cx
        add bx, dx
        and bx, 255
        add al, [sin_c + bx]
        inc al
        stosb
        inc cx
        cmp cx, 320
        jne .x
        inc dx
        cmp dx, 200
        jne .y
        pop es
        ret

; colours 1..192: the plasma gradient, rotated, brighter while the kick flashes
set_palette:
        mov dx, 3C8h
        mov al, 1
        out dx, al
        inc dx
        mov bl, [flash]
        shl bl, 2
        xor cx, cx
.l:     mov ax, cx
        add ax, [rot]
        cmp ax, 192
        jb .nw
        sub ax, 192
.nw:    mov si, ax
        shl si, 1
        add si, ax                  ; * 3
        add si, plasma_pal
        mov bh, 3
.c:     lodsb
        add al, bl
        cmp al, 63
        jbe .ok
        mov al, 63
.ok:    out dx, al
        dec bh
        jnz .c
        inc cx
        cmp cx, 192
        jne .l
        ret

fixed_palette:                      ; colours 248..255 for text and meters
        mov dx, 3C8h
        mov al, 248
        out dx, al
        inc dx
        mov si, text_pal
        mov cx, 8 * 3
.l:     lodsb
        out dx, al
        loop .l
        ret

; strings: row, col, colour, text..., 0 ; list ends with 0FFh
draw_text:
        mov si, strings
.s:     lodsb
        cmp al, 0FFh
        je .done
        mov dh, al
        lodsb
        mov dl, al
        lodsb
        mov bl, al
        mov ah, 2
        xor bh, bh
        int 10h
.c:     lodsb
        or al, al
        jz .s
        mov ah, 0Eh
        xor bh, bh
        int 10h
        jmp .c
.done:  ret

draw_meters:
        push es
        mov ax, 0A000h
        mov es, ax
        xor bx, bx
.m:     mov si, bx
        shl si, 1
        mov di, [meter_off + si]
        mov al, [meter + bx]
        xor ah, ah
        shl ax, 3
        mov [lit], ax
        mov al, [meter_col + bx]
        mov [colr], al
        mov bp, 6
.line:  push di
        mov cx, [lit]
        mov al, [colr]
        rep stosb
        mov cx, 160
        sub cx, [lit]
        xor al, al
        rep stosb
        pop di
        add di, 320
        dec bp
        jnz .line
        inc bx
        cmp bx, METERS
        jne .m
        pop es
        ret

; ---------------------------------------------------------------- OPL3
; al = register, ah = value
opl_write:
        push ax
        push cx
        push dx
        mov dx, OPL
        jmp opl_common
opl_write_hi:
        push ax
        push cx
        push dx
        mov dx, OPL_HI
opl_common:
        out dx, al
        mov cx, 6
.d1:    in al, dx
        loop .d1
        inc dx
        mov al, ah
        out dx, al
        dec dx
        mov cx, 36
.d2:    in al, dx
        loop .d2
        pop dx
        pop cx
        pop ax
        ret

opl_init:
        mov ax, 0105h               ; OPL3 mode on (bank 1, reg 5)
        call opl_write_hi
        mov al, 20h                 ; clear both banks
.clr:   xor ah, ah
        call opl_write
        call opl_write_hi
        inc al
        cmp al, 0F6h
        jne .clr
        mov si, opl_init_tab        ; (register, value) pairs, ends with 0FFh
.l:     lodsb
        cmp al, 0FFh
        je .done
        mov ah, [si]
        inc si
        call opl_write
        jmp .l
.done:  ret

; al = MIDI note, cl = channel 0..8
key_on:
        push ax
        push bx
        xor bh, bh
        mov bl, al
        mov ah, [fn_lo + bx]
        mov al, 0A0h
        add al, cl
        call opl_write
        mov ah, [fn_hi + bx]
        or ah, 20h
        mov al, 0B0h
        add al, cl
        call opl_write
        mov bl, cl
        mov [b0_shadow + bx], ah
        pop bx
        pop ax
        ret

; cl = channel
key_off:
        push ax
        push bx
        xor bh, bh
        mov bl, cl
        mov ah, [b0_shadow + bx]
        and ah, 0DFh
        mov al, 0B0h
        add al, cl
        call opl_write
        pop bx
        pop ax
        ret

; ---------------------------------------------------------------- Sound Blaster
dsp_write:                          ; al = byte
        push dx
        push ax
        mov dx, SB + 0Ch
.w:     in al, dx
        test al, 80h
        jnz .w
        pop ax
        out dx, al
        pop dx
        ret

sb_init:
        mov dx, SB + 6              ; reset the DSP
        mov al, 1
        out dx, al
        mov cx, 100
.d:     in al, dx
        loop .d
        xor al, al
        out dx, al
        mov dx, SB + 0Eh
        mov cx, 0FFFFh
.w:     in al, dx
        test al, 80h
        jnz .rd
        loop .w
        ret                         ; no Sound Blaster: drums stay silent
.rd:    mov dx, SB + 0Ah
        in al, dx
        cmp al, 0AAh
        jne .no
        mov byte [sb_ok], 1
        mov al, 0D1h                ; speaker on
        call dsp_write
        mov al, 40h                 ; sample rate (time constant)
        call dsp_write
        mov al, SB_TIME_CONSTANT
        call dsp_write
.no:    ret

; Copy each sample to a buffer that doesn't cross a 64 KB DMA page.
prepare_samples:
        xor bx, bx
.s:     mov si, bx
        shl si, 1
        mov di, bx
        shl di, 13                  ; 8 KB area per sample
        add di, dma_area
        mov ax, ds
        shl ax, 4
        add ax, di                  ; physical address, low 16 bits
        mov cx, [sample_len + si]
        dec cx
        add ax, cx
        jnc .fits
        add di, 4096                ; crossed a page: move past the boundary
.fits:  mov [sample_off + si], di
        mov cx, [sample_len + si]
        push si
        mov si, [sample_src + si]
        rep movsb
        pop si
        inc bx
        cmp bx, 3
        jne .s
        ret

; al = sample 0 kick, 1 snare, 2 hat
sb_play:
        cmp byte [sb_ok], 0
        je .ret
        pusha
        xor ah, ah
        mov si, ax
        shl si, 1
        mov dx, SB + 0Eh            ; acknowledge any finished transfer
        in al, dx
        mov ax, ds                  ; physical address -> page:offset
        mov bx, ax
        shl ax, 4
        shr bx, 12
        add ax, [sample_off + si]
        adc bx, 0
        mov cx, [sample_len + si]
        dec cx
        push ax
        mov al, 5                   ; DMA channel 1: mask
        out 0Ah, al
        xor al, al
        out 0Ch, al                 ; clear flip-flop
        mov al, 49h                 ; single transfer, memory -> SB, channel 1
        out 0Bh, al
        pop ax
        out 02h, al
        mov al, ah
        out 02h, al
        mov al, bl
        out 83h, al
        mov al, cl
        out 03h, al
        mov al, ch
        out 03h, al
        mov al, 1                   ; unmask
        out 0Ah, al
        mov al, 14h                 ; 8-bit single-cycle DMA output
        call dsp_write
        mov al, cl
        call dsp_write
        mov al, ch
        call dsp_write
        popa
.ret:   ret

; ---------------------------------------------------------------- music
music:
        cmp byte [fcnt], 0
        jne .other
        mov si, [songptr]           ; frame 0: fetch the row, key off
        mov di, pend
        mov cx, ROW_BYTES
        rep movsb
        cmp si, song_end
        jne .nw
        mov si, song
.nw:    mov [songptr], si
        cmp byte [pend], 0
        je .k1
        mov cl, 0
        call key_off
.k1:    cmp byte [pend + 1], 0
        je .k2
        mov cl, 1
        call key_off
.k2:    cmp byte [pend + 3], 0
        je .k3
        mov cl, 2
        call key_off
        mov cl, 3
        call key_off
        mov cl, 4
        call key_off
.k3:    cmp byte [pend + 4], 0
        je .fx_j
        mov cl, 5
        call key_off
.fx_j:  jmp .fx

.other: cmp byte [fcnt], 1
        jne .fx_j
        mov al, [pend]              ; bass
        cmp al, 2
        jb .nb
        mov cl, 0
        call key_on
        mov byte [meter], 20
.nb:    mov al, [pend + 1]          ; arp: ping-pong left/right
        cmp al, 2
        jb .na
        xor byte [panflag], 1
        mov ah, 10h
        jz .pl
        mov ah, 20h
.pl:    or ah, ARP_C0
        mov al, 0C1h
        call opl_write
        mov al, [pend + 1]
        mov cl, 1
        call key_on
        mov byte [meter + 1], 20
.na:    mov al, [pend + 3]          ; pads: chord on channels 2-4
        cmp al, 2
        jb .np
        sub al, 2
        xor ah, ah
        mov bx, ax
        shl bx, 1
        add bx, ax
        mov al, [chordtab + bx]
        mov cl, 2
        call key_on
        mov al, [chordtab + bx + 1]
        mov cl, 3
        call key_on
        mov al, [chordtab + bx + 2]
        mov cl, 4
        call key_on
        mov byte [meter + 2], 20
.np:    mov al, [pend + 4]          ; echo: opposite side to the arp
        cmp al, 2
        jb .ne
        mov ah, 20h
        test byte [panflag], 1
        jz .pe
        mov ah, 10h
.pe:    or ah, ARP_C0
        mov al, 0C5h
        call opl_write
        mov al, [pend + 4]
        mov cl, 5
        call key_on
        mov byte [meter + 3], 20
.ne:    mov al, [pend + 2]          ; drums: Sound Blaster samples
        or al, al
        jz .fx
        dec al
        call sb_play
        mov byte [meter + 4], 20
        or al, al
        jnz .fx
        mov byte [flash], 7

.fx:    xor bx, bx                  ; meters fall back
.md:    cmp byte [meter + bx], 0
        je .mz
        dec byte [meter + bx]
.mz:    inc bx
        cmp bx, METERS
        jne .md
        cmp byte [flash], 0
        je .nf
        dec byte [flash]
.nf:    inc word [rot]
        cmp word [rot], 192
        jne .nr
        mov word [rot], 0
.nr:    inc byte [fcnt]
        cmp byte [fcnt], FRAMES_PER_TICK
        jne .done
        mov byte [fcnt], 0
.done:  ret

; ---------------------------------------------------------------- data
fcnt:       db 0
pend:       times ROW_BYTES db 0
meter:      times METERS db 0
flash:      db 0
panflag:    db 0
sb_ok:      db 0
rot:        dw 0
songptr:    dw 0
lit:        dw 0
colr:       db 0
b0_shadow:  times 9 db 0
sample_off: dw 0, 0, 0

%include "gen_data.asm"

align 16
dma_area:                           ; 3 x 8 KB, filled at start-up (not in the file)
