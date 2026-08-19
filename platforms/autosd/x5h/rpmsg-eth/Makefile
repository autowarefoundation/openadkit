# SPDX-License-Identifier: Apache-2.0
# Build the rpmsg-eth TAP bridge daemon. Static-linked by default so the
# same binary runs on both the BSP Yocto rootfs and the AutoSD NFS rootfs
# (matching scripts/rpmsg-ping.c); override LDFLAGS if the host toolchain
# has no static libc.
#
# The board image ships no compiler (see aib/x5h-rootfs.aib.yml), so this
# is built on a host and staged as a binary -- override CC for an aarch64
# target from an x86_64 dev host, e.g.:
#   CC=aarch64-linux-gnu-gcc make
# See ../rpmsg-dualboot.md's "rpmsg-eth: IP-over-RPMsg bridge" section for
# the full build/stage/prerequisites/smoke sequence.
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
LDFLAGS ?= -static

rpmsg-eth: rpmsg-eth.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f rpmsg-eth

.PHONY: clean
