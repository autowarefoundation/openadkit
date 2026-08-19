# Updating the CR52 realtime firmware from Linux

The realtime core does not load its payload from Linux. As described in
[rpmsg-dualboot.md](rpmsg-dualboot.md), the payload is flashed into a boot
slot and started by the boot firmware before Linux exists; on this SoC
remoteproc's `.load` and `.stop` are no-ops. So "update the CR52 firmware"
means "change what is in that slot", and until now that meant putting the
board into its serial download mode and running the vendor flash tool —
a procedure that needs physical access to the board.

That slot is a region of a UFS logical unit. Linux can write it directly.
This document is the procedure for doing that; combined with the fact that
a plain `reboot` cold-resets the SoC (see [selfboot.md](selfboot.md)), it
makes realtime firmware updates a fully remote operation.

> **Numbers live elsewhere.** The slot's device, offset, extent and the
> certificate parameters come from the vendor SDK and are not reproduced
> in this repository. Take them from the vendor SDK and your site's own
> record of this work; the procedure below is written to be followed with
> those values to hand.

## Before you write anything

**Stage the vendor restore path first.** Have the vendor flash tool, its
restore configuration and the original payload present and hash-verified
*before* the first write. If a write leaves the boot firmware unable to
start the realtime core, that tooling and physical access to the board are
the way back. It was not needed during validation, but it is the only
recovery route, so it is not optional.

Keep an operator at the board for the first write on any new board or
after any change to the slot geometry.

## 1. Locate the slot, read-only

Decode the vendor's update image (an SREC) into a flat binary, then find
where that binary already lives on the board's storage by comparing bytes.
Nothing is written in this phase.

```python
# S3 records only; addresses are absolute load addresses
def decode(srec, out):
    segs = []
    for line in open(srec):
        line = line.strip()
        if not line.startswith('S3'):
            continue
        count = int(line[2:4], 16)
        addr = int(line[4:12], 16)
        segs.append((addr, bytes.fromhex(line[12:12 + 2 * (count - 5)])))
    segs.sort()
    start, end = segs[0][0], max(a + len(p) for a, p in segs)
    img = bytearray(b'\xff' * (end - start))
    for a, p in segs:
        img[a - start:a - start + len(p)] = p
    open(out, 'wb').write(img)
```

Stage a short prefix of the decoded image onto the board, then compare it
against each candidate device at the documented offset. Express the offset
in 4 KiB units — these LUNs use 4096-byte logical sectors:

```sh
# skip = <offset> / 4096
for d in /dev/disk/by-path/platform-*ufs*; do
  case $d in *-part*) continue ;; esac
  dd if=$d bs=4096 skip=<skip> count=16 2>/dev/null \
    | cmp -s - /var/tmp/slot-prefix.bin && echo "HIT $d"
done
```

**Exactly one device must hit.** Before believing it, cross-check: read the
same offset on another controller and confirm it differs. A useful sanity
signal is that the first bytes of a Cortex-R52 image are an exception
vector table — a run of identical `ldr pc, [pc, #…]` instructions — so a
hit should look like code, not like filesystem data.

If nothing hits, do not widen the write blindly. Dump the candidate
devices and search for the prefix offline to find the true offset, or stop
and keep using the vendor tool.

## 2. Capture a pristine baseline

Read the **whole slot extent** — not just the payload length — to a file
and keep it off-board:

```sh
dd if=<dev> bs=4096 skip=<skip> count=<extent-sectors> of=/var/tmp/slot-orig.bin
```

This is what you restore to, and it is strictly better than restoring the
decoded payload: the payload is shorter than the extent, and the bytes
past its end are not necessarily what a zero-fill would produce. On this
board they are erased flash (`0xff`), so a restore that zero-filled the
tail would not return the region to how it was found.

Confirm the baseline's leading bytes equal the decoded current payload
before trusting it.

## 3. Write

```sh
dd if=<new-payload> of=<dev> bs=4096 seek=<skip> conv=notrunc,fsync
blockdev --flushbufs <dev>
dd if=<dev> bs=4096 skip=<skip> count=<extent-sectors> iflag=direct 2>/dev/null \
  | head -c <payload-bytes> | cmp - <new-payload> && echo WRITE_VERIFIED
```

Three details matter:

- **Erase the extent first** when the new payload is shorter than the old
  one, so no tail of the previous image survives inside the region the
  boot firmware loads.
- **`oflag=direct` only works on sector-aligned transfers.** A payload
  whose length is not a multiple of 4096 will fail with O_DIRECT on its
  final partial block. Write buffered with `conv=fsync` instead.
- **`blockdev --flushbufs` before reading back.** Without it the
  verification read can be served from the page cache, in which case it
  confirms nothing about what reached the media. Read back with
  `iflag=direct`.

## 4. Restart the realtime core and verify

```sh
reboot
```

That is the whole reset step. The reboot is a PSCI `SYSTEM_RESET` which
the firmware implements as a cold reset, so the realtime core restarts and
the boot firmware re-loads the slot. Watch the realtime console: a working
RPMsg payload reprints its OpenAMP banner ending in `creating remoteproc
virtio`.

Then confirm the round trip from Linux:

```sh
sh /usr/local/bin/rpmsg-smoke.sh -f rpmsg-echo-cr52.elf -s rpmsg-client-sample -n 100
```

Expect `RPMSG_SMOKE_PASS`. The discriminating kernel line is

```
virtio_rpmsg_bus virtio0: creating channel rpmsg-client-sample addr 0x400
```

If the slot content is not an RPMsg payload, that line never appears and
the smoke ends in `RPMSG_SMOKE_FAIL … reason=service_timeout`. Note that
remoteproc will still report the processor "up" and will still log
"Booting fw image" — it is describing the ELF Linux staged, not what the
core is executing. Only the channel announce and the round trip are
evidence.

## Validating the write path on a board

Prove the mechanism before relying on it, in three steps:

1. **Write the current payload over itself.** Byte-identical, so the
   content risk is zero, and a passing smoke afterwards proves the write
   path and the read-back verification work.
2. **Write a different, known-bootable payload.** The expected result is
   that the realtime console stays silent and the smoke fails with
   `service_timeout`. That failure is the evidence the write took effect —
   a successful swap that changed nothing would prove nothing. Linux must
   still boot normally; a slot the realtime core cannot use does not stop
   the application cores.
3. **Restore the pristine baseline** and confirm the smoke passes again.

This was run on 2026-08-07. All three steps passed, across three reboots,
and the vendor restore path was never needed. No certificate regeneration
was required for either payload — the boot firmware accepted both a
payload written by the vendor tool and one written directly from Linux. If
a future board or SDK version rejects a directly-written payload, expect
the failure at boot firmware stage, recover with the vendor tool, and
treat certificate generation as the next thing to investigate.

## Related

- [CR52 dual boot + RPMsg](rpmsg-dualboot.md) — what the payload does and
  why Linux cannot load it.
- [UFS self-boot](selfboot.md) — the reset semantics this relies on, and
  why the board comes back by itself afterwards.
