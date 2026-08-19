#!/bin/sh
# Stage 0 rehearsal on the companion host: run the Open AD Kit component
# stack (amd64) against autoware-safety-island's freertos-posix actuation
# runtime across a link clamped to the board's MTU, and measure what the
# real Autoware topic set costs.
#
# Why a veth pair in a network namespace, rather than pointing both sides at
# one interface on this host: two processes on the same host bound to the
# same interface exchange DDS traffic without the frame ever crossing a
# link, so the MTU would never bind and the measurement would be a fiction.
# The namespace forces every byte through a real 462-byte-MTU device, and
# the addresses are the board's own (172.16.52.1/.2) so
# cyclonedds-x5h.xml is used unmodified here and on the board.
#
# What this rig does NOT cover, stated so nobody over-reads a PASS:
#   - RPMsg per-message overhead and mailbox latency. A veth is faster than
#     the real link, so the measured budget is a LOWER bound on cost.
#   - The static-peer SPDP path on the CR52 side (proven separately in M6).
#   - arm64. Stage 1 on the board is the arm64 test.
#
# Requires sudo for the namespace and veth setup: --setup and --teardown are
# the only privileged modes and are meant to be run as separate,
# human-authorised invocations.
set -u

NS="${X5H_NS:-x5h-si}"
HOST_IF="${X5H_HOST_IF:-si0}"
NS_IF="${X5H_NS_IF:-si1}"
MTU=462                      # frozen; see scripts/rpmsg-eth-ifup.sh
HOST_ADDR=172.16.52.1/24
NS_ADDR=172.16.52.2/24
DUR="${X5H_MEASURE_SECONDS:-60}"

fail() { echo "X5H_REHEARSAL_FAIL reason=$1"; exit 1; }

case "${1:---measure}" in
--setup)
    # Privileged. Idempotent: every command tolerates a rig left behind by
    # an interrupted previous run.
    ip netns add "$NS" 2>/dev/null || true
    ip link add "$HOST_IF" mtu "$MTU" type veth peer name "$NS_IF" mtu "$MTU" 2>/dev/null || true
    ip link set "$NS_IF" netns "$NS" 2>/dev/null || true
    ip addr replace "$HOST_ADDR" dev "$HOST_IF"
    ip link set "$HOST_IF" mtu "$MTU" up
    ip netns exec "$NS" ip addr replace "$NS_ADDR" dev "$NS_IF"
    ip netns exec "$NS" ip link set "$NS_IF" mtu "$MTU" up
    ip netns exec "$NS" ip link set lo up
    # Assert the MTU actually took: a silently-1500 link would make the
    # whole measurement meaningless while every later step still passed.
    got=$(cat "/sys/class/net/$HOST_IF/mtu")
    [ "$got" = "$MTU" ] || fail "host_mtu=$got"
    got=$(ip netns exec "$NS" cat "/sys/class/net/$NS_IF/mtu")
    [ "$got" = "$MTU" ] || fail "ns_mtu=$got"
    ip netns exec "$NS" ping -c2 -W2 172.16.52.1 >/dev/null 2>&1 || fail "rig_no_ping"
    echo "X5H_RIG_PASS host_if=$HOST_IF ns=$NS mtu=$MTU"
    ;;
--teardown)
    ip link del "$HOST_IF" 2>/dev/null || true
    ip netns del "$NS" 2>/dev/null || true
    echo "X5H_RIG_TEARDOWN_OK"
    ;;
--measure)
    [ -d "/sys/class/net/$HOST_IF" ] || fail "no_rig_run_setup_first"
    # Count only domain-2 traffic: everything on this interface is domain 2
    # by construction, so interface counters are the measurement.
    # tx_* on the host end == what domain 1 pushes toward the safety
    # island, which is the direction the spec's budget estimate covers.
    tp0=$(cat "/sys/class/net/$HOST_IF/statistics/tx_packets")
    tb0=$(cat "/sys/class/net/$HOST_IF/statistics/tx_bytes")
    td0=$(cat "/sys/class/net/$HOST_IF/statistics/tx_dropped")
    sleep "$DUR"
    tp1=$(cat "/sys/class/net/$HOST_IF/statistics/tx_packets")
    tb1=$(cat "/sys/class/net/$HOST_IF/statistics/tx_bytes")
    td1=$(cat "/sys/class/net/$HOST_IF/statistics/tx_dropped")
    echo "X5H_LINK_BUDGET fragments_per_s=$(( (tp1-tp0) / DUR )) bytes_per_s=$(( (tb1-tb0) / DUR )) tx_drops=$(( td1-td0 )) window_s=$DUR"
    ;;
*)
    fail "usage"
    ;;
esac
