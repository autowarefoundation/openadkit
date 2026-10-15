#!/usr/bin/env python3
"""Read a DLT file as the bench recorder writes it, and print it as text.

  dlt_file.py <file.dlt>

record_dlt.py (vision_pilot, Simulation/CARLA/ROS2/si) writes every DLT message
that the board's S-CORE datarouter sends behind a DLT storage header, which
holds the bench clock at arrival. The same file opens in dlt-viewer. This
module is the reader the demo reel composer uses, and its command line is how
gate SG5 searches the stream.

It decodes what the datarouter sends: verbose log messages with string,
integer, float, bool and raw arguments, in either byte order. Any other
argument type ends the decoding of that one message with a <type 0x...>
marker, so one odd message never hides the rest of the stream.

Output: one line per message,
  <bench arrival s> <board monotonic s> <ecu> <app> <ctx> <level> <text>
"""

import struct
import sys
from dataclasses import dataclass

STORAGE = struct.Struct("<4sIi4s")
PATTERN = b"DLT\x01"
# Standard header type bits (HTYP).
UEH, MSBF, WEID, WSID, WTMS = 0x01, 0x02, 0x04, 0x08, 0x10
# Verbose argument type info bits. SCOD (bits 15-17) only names a string's
# coding, so it is accepted; any other bit is a type this reader does not know.
BOOL, SINT, UINT, FLOA, STRG, RAWD = 0x10, 0x20, 0x40, 0x80, 0x200, 0x400
KNOWN = 0x0F | BOOL | SINT | UINT | FLOA | STRG | RAWD | 0x38000
LEVELS = {1: "FATAL", 2: "ERROR", 3: "WARN", 4: "INFO", 5: "DEBUG", 6: "VERBOSE"}
_INT = {1: "b", 2: "h", 3: "i", 4: "q"}
_FLOAT = {3: "f", 4: "d"}


class DltError(Exception):
    """A refusal with a slug, like the composer's ReelError."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason} {detail}".strip())
        self.reason = reason


@dataclass
class DltMsg:
    recv: float          # bench clock at arrival, from the storage header
    tmsp: float | None   # board CLOCK_MONOTONIC at the log call, in seconds
    ecu: str
    app: str
    ctx: str
    level: int           # DLT MTIN, see LEVELS; 0 when the message has no extended header
    text: str


def _id(raw):
    return raw.rstrip(b"\0").decode("ascii", "replace")


def decode_args(payload, noar, big_endian=False):
    """The verbose arguments of one message, joined by spaces as dlt-viewer shows them."""
    e = ">" if big_endian else "<"
    out, i = [], 0
    try:
        for _ in range(noar):
            (ti,) = struct.unpack_from(e + "I", payload, i)
            i += 4
            tyle = ti & 0x0F
            if ti & ~KNOWN:
                out.append(f"<type 0x{ti:x}>")
                break
            if ti & (STRG | RAWD):
                (n,) = struct.unpack_from(e + "H", payload, i)
                raw = payload[i + 2:i + 2 + n]
                if len(raw) < n:
                    raise struct.error("argument runs past the message")
                i += 2 + n
                out.append(raw.rstrip(b"\0").decode("utf-8", "replace") if ti & STRG else raw.hex())
            elif ti & BOOL:
                out.append("true" if payload[i] else "false")
                i += 1
            elif ti & (SINT | UINT) and tyle in _INT:
                fmt = e + (_INT[tyle].upper() if ti & UINT else _INT[tyle])
                (v,) = struct.unpack_from(fmt, payload, i)
                i += struct.calcsize(fmt)
                out.append(str(v))
            elif ti & FLOA and tyle in _FLOAT:
                fmt = e + _FLOAT[tyle]
                (v,) = struct.unpack_from(fmt, payload, i)
                i += struct.calcsize(fmt)
                out.append(f"{v:g}")
            else:
                out.append(f"<type 0x{ti:x}>")
                break
    except (struct.error, IndexError):
        out.append("<truncated>")
    return " ".join(out)


def parse_message(msg, recv):
    """One DLT message, from its standard header on, as a DltMsg."""
    try:
        htyp = msg[0]
        k = 4
        ecu = ""
        if htyp & WEID:
            ecu = _id(msg[k:k + 4])
            k += 4
        if htyp & WSID:
            k += 4
        tmsp = None
        if htyp & WTMS:
            tmsp = struct.unpack_from(">I", msg, k)[0] * 1e-4
            k += 4
        if not htyp & UEH:
            return DltMsg(recv, tmsp, ecu, "", "", 0, "<non-verbose>")
        msin, noar, apid, ctid = struct.unpack_from("<BB4s4s", msg, k)
        k += 10
    except (struct.error, IndexError) as exc:
        raise DltError("bad_message", str(exc)) from exc
    text = decode_args(msg[k:], noar, bool(htyp & MSBF)) if msin & 1 else "<non-verbose>"
    return DltMsg(recv, tmsp, ecu, _id(apid), _id(ctid), (msin >> 4) & 0x0F, text)


def read_dlt(data):
    """Every complete record of a DLT file, in file order.

    A record cut short at the end of the file is dropped: record-demo.sh stops
    the recorder with a signal, and half a message is not evidence. A broken
    record anywhere else is a refusal, because nothing after it can be found.
    """
    out, i = [], 0
    while len(data) - i >= STORAGE.size + 4:
        pattern, sec, usec, _ecu = STORAGE.unpack_from(data, i)
        if pattern != PATTERN:
            raise DltError("bad_storage_header", f"offset {i}")
        j = i + STORAGE.size
        (n,) = struct.unpack_from(">H", data, j + 2)
        if n < 4:
            raise DltError("bad_length", f"offset {j}")
        if j + n > len(data):
            break
        out.append(parse_message(data[j:j + n], sec + usec * 1e-6))
        i = j + n
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: dlt_file.py <file.dlt>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], "rb") as f:
            msgs = read_dlt(f.read())
    except (OSError, DltError) as exc:
        print(f"DLT_FILE_FAIL {exc}", file=sys.stderr)
        return 1
    for m in msgs:
        tmsp = "-" if m.tmsp is None else f"{m.tmsp:.4f}"
        print(f"{m.recv:.3f} {tmsp} {m.ecu or '-'} {m.app or '-'} {m.ctx or '-'} "
              f"{LEVELS.get(m.level, '-')} {m.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
