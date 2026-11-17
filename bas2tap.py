#!/usr/bin/env python3
"""Tiny ZX Spectrum BASIC -> .tap converter.

Conventions for the source file:
  * Keywords are UPPERCASE, variable names are lowercase (so "note" never
    gets mistaken for the TO keyword).
  * Spaces outside strings / REMs are dropped (the Spectrum re-inserts them
    when listing).
Usage: python3 bas2tap.py prog.bas out.tap [NAME] [autostart-line]
"""
import math
import re
import sys

KEYWORDS = [
    "RND", "INKEY$", "PI", "FN", "POINT", "SCREEN$", "ATTR", "AT", "TAB",
    "VAL$", "CODE", "VAL", "LEN", "SIN", "COS", "TAN", "ASN", "ACS", "ATN",
    "LN", "EXP", "INT", "SQR", "SGN", "ABS", "PEEK", "IN", "USR", "STR$",
    "CHR$", "NOT", "BIN", "OR", "AND", "<=", ">=", "<>", "LINE", "THEN",
    "TO", "STEP", "DEF FN", "CAT", "FORMAT", "MOVE", "ERASE", "OPEN #",
    "CLOSE #", "MERGE", "VERIFY", "BEEP", "CIRCLE", "INK", "PAPER", "FLASH",
    "BRIGHT", "INVERSE", "OVER", "OUT", "LPRINT", "LLIST", "STOP", "READ",
    "DATA", "RESTORE", "NEW", "BORDER", "CONTINUE", "DIM", "REM", "FOR",
    "GO TO", "GO SUB", "INPUT", "LOAD", "LIST", "LET", "PAUSE", "NEXT",
    "POKE", "PRINT", "PLOT", "RUN", "SAVE", "RANDOMIZE", "IF", "CLS", "DRAW",
    "CLEAR", "RETURN", "COPY",
]
TOKENS = {kw.replace(" ", ""): 0xA5 + i for i, kw in enumerate(KEYWORDS)}
BY_LENGTH = sorted(TOKENS, key=len, reverse=True)
REM = TOKENS["REM"]
NUM_RE = re.compile(r"\d*\.?\d+|\d+\.")


def encode_number(v):
    """Spectrum 5-byte floating point form."""
    if v == int(v) and 0 <= v < 65536:
        v = int(v)
        return bytes([0, 0, v & 0xFF, v >> 8, 0])
    if v == 0:
        return bytes(5)
    e = math.floor(math.log2(v)) + 1
    m = round(v / 2 ** e * 2 ** 32)
    if m >= 2 ** 32:
        m //= 2
        e += 1
    m &= 0x7FFFFFFF  # top bit is the sign bit (positive)
    return bytes([e + 128]) + m.to_bytes(4, "big")


def tokenize_line(text):
    out = bytearray()
    i = 0
    in_string = False
    prev = ""
    while i < len(text):
        c = text[i]
        if in_string:
            out.append(ord(c))
            in_string = c != '"'
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(ord(c))
            i += 1
            continue
        if c == " ":
            i += 1
            continue
        if c.isupper() or c in "<>":
            rest = text[i:].replace(" ", "")
            for kw in BY_LENGTH:
                if rest.startswith(kw):
                    out.append(TOKENS[kw])
                    # consume len(kw) non-space chars from the original text
                    n = 0
                    while n < len(kw):
                        if text[i] != " ":
                            n += 1
                        i += 1
                    if TOKENS[kw] == REM:
                        out += text[i:].lstrip(" ").encode("ascii")
                        return bytes(out)
                    prev = kw
                    break
            else:
                out.append(ord(c))
                prev = c
                i += 1
            continue
        if (c.isdigit() or c == ".") and not (prev.isalnum() and prev.islower() or prev.isdigit()):
            m = NUM_RE.match(text, i)
            if m:
                s = m.group(0)
                out += s.encode("ascii") + b"\x0e" + encode_number(float(s))
                i = m.end()
                prev = "0"
                continue
        out.append(ord(c))
        prev = c
        i += 1
    return bytes(out)


def tokenize_program(source):
    prog = bytearray()
    for raw in source.splitlines():
        raw = raw.rstrip()
        if not raw.strip():
            continue
        m = re.match(r"\s*(\d+)\s?(.*)$", raw)
        if not m:
            raise SystemExit(f"line without number: {raw!r}")
        num, body = int(m.group(1)), m.group(2)
        data = tokenize_line(body) + b"\x0d"
        prog += num.to_bytes(2, "big") + len(data).to_bytes(2, "little") + data
    return bytes(prog)


def tap_block(flag, payload):
    block = bytes([flag]) + payload
    chk = 0
    for b in block:
        chk ^= b
    block += bytes([chk])
    return len(block).to_bytes(2, "little") + block


def make_tap(prog, name, autostart):
    header = (bytes([0]) + name.ljust(10)[:10].encode("ascii")
              + len(prog).to_bytes(2, "little")
              + autostart.to_bytes(2, "little")
              + len(prog).to_bytes(2, "little"))
    return tap_block(0x00, header) + tap_block(0xFF, prog)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else "program"
    auto = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    prog = tokenize_program(open(src).read())
    open(dst, "wb").write(make_tap(prog, name, auto))
    print(f"{dst}: {len(prog)} bytes of BASIC")
