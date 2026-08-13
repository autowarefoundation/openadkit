# SPDX-License-Identifier: Apache-2.0
# Build the rpmsg-eth TAP bridge daemon. Static-linked by default so the
# same binary runs on both the BSP Yocto rootfs and the AutoSD NFS rootfs
# (matching scripts/rpmsg-ping.c); override LDFLAGS if the host toolchain
# has no static libc.
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
LDFLAGS ?= -static

rpmsg-eth: rpmsg-eth.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f rpmsg-eth

.PHONY: clean
