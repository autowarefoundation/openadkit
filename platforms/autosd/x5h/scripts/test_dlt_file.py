"""Unit tests for dlt_file.py. Run: python3 -m pytest -q test_dlt_file.py

The records are built here byte by byte, in the layout the S-CORE datarouter
sends (score_logging 0.2.4, dlt_headers.h: HTYP = UEH | WEID | WTMS | version 1,
length and timestamp big endian, verbose arguments little endian), behind the
storage header that record_dlt.py writes.
"""
import struct

import pytest

import dlt_file as d


def arg_str(s):
    raw = s.encode() + b"\0"
    return struct.pack("<IH", 0x200, len(raw)) + raw


def arg_uint32(v):
    return struct.pack("<II", 0x43, v)


def dlt_record(app, ctx, level, args, tmsp, recv, ecu=b"X5H\0"):
    """One file record: storage header, standard header, extended header, args."""
    payload = b"".join(args)
    ext = struct.pack("<BB4s4s", (level << 4) | 1, len(args),
                      app.encode().ljust(4, b"\0"), ctx.encode().ljust(4, b"\0"))
    std = struct.pack(">BBH", 0x35, 7, 4 + 4 + 4 + len(ext) + len(payload))
    std += ecu + struct.pack(">I", round(tmsp * 10000))
    sec = int(recv)
    storage = struct.pack("<4sIi4s", b"DLT\x01", sec, round((recv - sec) * 1e6), ecu)
    return storage + std + ext + payload


VP_LINE = dlt_record("VP", "VP", 2, [arg_str("frame deadline failed, alive notifications stopped")],
                     tmsp=1234.5678, recv=1789432101.25)
LM_LINE = dlt_record("LM", "LM", 4, [arg_str("Completed the request for PG"), arg_str("MainPG"),
                                     arg_str("to State"), arg_str("fallback_run_target"),
                                     arg_str("in"), arg_uint32(12), arg_str("ms")],
                     tmsp=1234.9, recv=1789432101.5)


def test_reads_the_datarouter_layout():
    a, b = d.read_dlt(VP_LINE + LM_LINE)
    assert (a.ecu, a.app, a.ctx, a.level) == ("X5H", "VP", "VP", 2)
    assert a.text == "frame deadline failed, alive notifications stopped"
    assert a.tmsp == pytest.approx(1234.5678)
    assert a.recv == pytest.approx(1789432101.25)
    assert b.text == "Completed the request for PG MainPG to State fallback_run_target in 12 ms"
    assert d.LEVELS[b.level] == "INFO"


def test_decodes_every_argument_type_the_datarouter_sends():
    payload = (struct.pack("<Ib", 0x21, -5) + struct.pack("<IQ", 0x44, 2**40)
               + struct.pack("<IB", 0x11, 1) + struct.pack("<Id", 0x84, 0.25)
               + struct.pack("<IH", 0x400, 2) + b"\xab\xcd")
    assert d.decode_args(payload, 5) == "-5 1099511627776 true 0.25 abcd"


def test_decodes_big_endian_arguments():
    payload = struct.pack(">II", 0x43, 7) + struct.pack(">IH", 0x200, 3) + b"ok\0"
    assert d.decode_args(payload, 2, big_endian=True) == "7 ok"


def test_an_unknown_argument_type_is_marked_and_the_stream_goes_on():
    # 0x1043: an unsigned 32-bit argument with the FIXP bit, which this reader
    # does not decode.
    odd = dlt_record("LM", "LM", 4, [struct.pack("<I", 0x1043) + b"\0" * 4, arg_str("lost")],
                     tmsp=1.0, recv=1789432101.0)
    msgs = d.read_dlt(odd + VP_LINE)
    assert msgs[0].text == "<type 0x1043>"
    assert msgs[1].app == "VP"


def test_a_record_cut_short_at_the_end_is_dropped():
    assert len(d.read_dlt(VP_LINE + LM_LINE[:-3])) == 1


def test_a_broken_record_in_the_middle_is_refused():
    with pytest.raises(d.DltError) as e:
        d.read_dlt(VP_LINE + b"XXXX" + LM_LINE[4:])
    assert e.value.reason == "bad_storage_header"


def test_a_string_that_is_not_utf8_still_decodes():
    raw = b"bad \xff\xfe\0"
    rec = dlt_record("VP", "VP", 4, [struct.pack("<IH", 0x200, len(raw)) + raw],
                     tmsp=1.0, recv=1789432101.0)
    assert d.read_dlt(rec)[0].text.startswith("bad ")


def test_the_command_line_prints_one_line_per_message(tmp_path, capsys):
    p = tmp_path / "dlt.dlt"
    p.write_bytes(VP_LINE + LM_LINE)
    assert d.main([str(p)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ("1789432101.250 1234.5678 X5H VP VP ERROR "
                        "frame deadline failed, alive notifications stopped")
    assert len(lines) == 2
