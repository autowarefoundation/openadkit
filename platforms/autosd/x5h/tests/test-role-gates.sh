#!/usr/bin/env bash
# Every unit that gates itself on the boot role must name every role it has
# to run in. The demo role runs the NPU stack and the CR52 in one boot, so
# it belongs on both the npu-gated and the cr52-gated units. systemd ORs
# repeated ConditionKernelCommandLine= lines, so a role is added by adding a
# line, never by editing the existing one.
set -u
name=test-role-gates
here=$(cd "$(dirname "$0")" && pwd)
cfg="$here/../config"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
gates() { grep -c "^ConditionKernelCommandLine=x5h\.role=$2\$" "$cfg/$1" 2>/dev/null; }
for u in var-opt-npu.mount x5h-npu.service; do
    [ -f "$cfg/$u" ] || fail "missing_$u"
    [ "$(gates "$u" npu)" = 1 ] || fail "npu_gate_lost_$u"
    [ "$(gates "$u" demo)" = 1 ] || fail "no_demo_gate_$u"
done
for u in cr52-remoteproc.service rpmsg-eth.service; do
    [ -f "$cfg/$u" ] || fail "missing_$u"
    [ "$(gates "$u" cr52)" = 1 ] || fail "cr52_gate_lost_$u"
    [ "$(gates "$u" demo)" = 1 ] || fail "no_demo_gate_$u"
done
# Units are only half of it. Every script that branches on the role has to
# name every role it must run in as well, and the first sweep for demo missed
# these: selfboot-smoke.sh failed a correct demo boot with unknown_role and
# npu-contract-smoke.sh refused the one role that exists to run the NPU. A
# board session is the worst place to find that, so the next role has to pass
# here before it can repeat it. Matched as a case arm, so a passing mention
# of demo in a comment does not satisfy this.
for s in selfboot-smoke.sh npu-contract-smoke.sh cr52-rproc-up.sh x5h-role; do
    [ -f "$here/../scripts/$s" ] || fail "missing_$s"
    grep -Eq '(^|[[:space:]|(])demo\)' "$here/../scripts/$s" || fail "no_demo_arm_$s"
done
echo "TEST_PASS $name"
