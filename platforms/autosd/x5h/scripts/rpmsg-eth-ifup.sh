#!/bin/sh
# ExecStartPre helper for rpmsg-eth.service (installed at
# /usr/sbin/rpmsg-eth-ifup.sh by aib/x5h-rootfs.aib.yml -- NOT
# /usr/local/sbin, which automotive-image-builder refuses to install into;
# see config/rpmsg-eth.service for that split). Creates tap0 and brings it up
# with the frozen link parameters for the CR52 bridge: address
# 172.16.52.1/24, MAC
# 02:5c:52:00:00:01, and, critically, MTU 462.
#
# MTU 462 is NOT a tuning knob: max Ethernet frame on this link is 476 bytes
# (462 payload + 14-byte Ethernet header), sized to the RPMsg payload budget
# on the CR52 side (496 bytes, leaving headroom for the RPMsg header itself).
# Bringing tap0 up at the kernel's default MTU (1500) would let the kernel
# hand the daemon frames it cannot forward whole; rpmsg-eth.c drops those
# (counted as dropped_oversize) rather than fragmenting them, so a wrong MTU
# here means silent, oversize-triggered packet loss on the link, not a
# crash. rpmsg-eth-smoke.sh asserts this MTU on the running interface so a
# regression here is caught before it reaches ping-loss territory.
#
# The MAC is also a frozen constant, not cosmetic: without setting it, tap0
# gets a kernel-random address that changes every time the persistent tap
# is recreated, making board packet captures unreproducible across a
# debugging session -- exactly the case where a stable MAC to filter on
# matters most. The FreeRTOS side resolves peers with lwIP's ARP
# (NETIF_FLAG_ETHARP) rather than a static peer table, so a wrong or
# changing MAC here does not blackhole traffic today -- but the constraint
# is still frozen and still checked (see rpmsg-eth-smoke.sh).
#
# set -u only, not -e: every command below is deliberately allowed to
# report its own failure (the `add` is idempotent-by-design, see below; the
# rest are asserted downstream by rpmsg-eth-smoke.sh) rather than aborting
# this script silently mid-sequence.
set -u

# Interface name: takes $1 (rpmsg-eth.service's ExecStartPre passes the same
# "tap0" its own ExecStart uses via -t) so the name lives in one place --
# the unit file -- instead of being hardcoded here independently of it.
# Defaults to tap0 so this script still works stand-alone/uninstalled.
IFACE="${1:-tap0}"

# 2>/dev/null || true makes this line idempotent (a persistent tap from a
# previous run already exists and 'add' would otherwise fail every restart)
# -- it is NOT meant to hide a genuine failure. A real one here (no
# /dev/net/tun, no CONFIG_TUN) always resurfaces immediately at the next
# line: 'ip addr replace' on a nonexistent interface fails loudly on its
# own, so swallowing this specific command's stderr does not hide the
# underlying problem, only this command's redundant complaint about it.
ip tuntap add dev "$IFACE" mode tap 2>/dev/null || true
ip addr replace 172.16.52.1/24 dev "$IFACE"
ip link set "$IFACE" address 02:5c:52:00:00:01
ip link set "$IFACE" mtu 462 up
