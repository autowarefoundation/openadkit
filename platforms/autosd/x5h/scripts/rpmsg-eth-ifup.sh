#!/bin/sh
# ExecStartPre helper for rpmsg-eth.service (installed at
# /usr/local/sbin/rpmsg-eth-ifup.sh -- see config/rpmsg-eth.service for the
# full install path). Creates tap0 and brings it up with the frozen link
# parameters for the CR52 bridge: address 172.16.52.1/24 and, critically,
# MTU 462.
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
set -u

ip tuntap add dev tap0 mode tap 2>/dev/null || true
ip addr replace 172.16.52.1/24 dev tap0
ip link set tap0 mtu 462 up
