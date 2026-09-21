#!/usr/bin/env bash
# The boot role decides two separate things, and this test guards both.
#
# The platform layer -- the NPU mount and bring-up, the CR52 remoteproc, the
# rpmsg-eth link -- belongs to every role that boots the derived device tree.
# demo and dev both do, so each of those units must name both. Repeated
# conditions of one type are ANDed by systemd, so each role line needs a pipe
# right after the equals sign to become a triggering condition: the unit then
# runs when at least one triggering condition matches and every regular
# (non-triggering) condition still applies.
#
# The application layer is the opposite: the MRM component stack and the CES
# demo stack each bind domain 1 and domain 2 and each runs its own
# domain_bridge, so exactly one of them may own a boot. The MRM units are
# gated to dev alone and carry no [Install] section, because Quadlet writes
# the default.target.wants symlink itself for any .container that has one and
# the unit would then come up on every dev boot unbidden.
set -u
name=test-role-gates
here=$(cd "$(dirname "$0")" && pwd)
cfg="$here/../config"
comp="$here/../components"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
gates() { grep -c "^ConditionKernelCommandLine=|x5h\.role=$2\$" "$1" 2>/dev/null; }

# --- the platform layer: both AD Kit roles, both triggering ----------------
for u in var-opt-npu.mount x5h-npu.service cr52-remoteproc.service rpmsg-eth.service; do
    [ -f "$cfg/$u" ] || fail "missing_$u"
    for role in demo dev; do
        [ "$(gates "$cfg/$u" "$role")" = 1 ] || fail "no_${role}_gate_$u"
    done
done

# --- the application layer: MRM gated to dev, and never auto-started -------
for u in "$comp"/awf-oak-*.container; do
    [ -f "$u" ] || fail missing_awf_oak_units
    b=$(basename "$u")
    [ "$(grep -c '^ConditionKernelCommandLine=x5h\.role=dev$' "$u")" = 1 ] || fail "no_dev_gate_$b"
    grep -q '^\[Install\]' "$u" && fail "install_section_$b"
done

# --- the retired roles must not come back anywhere ------------------------
# cr52 and npu were roles until the three-role split. A unit still naming one
# would be permanently skipped, which systemd reports as a SUCCESSFUL start
# job, so the failure is silent by construction and has to be caught here.
while IFS= read -r f; do
    grep -Eq '^ConditionKernelCommandLine=\|?x5h\.role=(cr52|npu)$' "$f" \
        && fail "retired_role_gate_$(basename "$f")"
done < <(find "$cfg" "$comp" -type f)

# --- the pipe rule --------------------------------------------------------
# Any unit with more than one x5h.role= line, piped or not, must have the pipe
# on every one of them: a plain (non-triggering) line ANDed alongside another
# role line makes the pair unsatisfiable, which is exactly the regression this
# test exists to catch. A single plain role line is fine and deliberate (see
# the awf-oak-*.container units), so only files with more than one are checked.
# Both sweeps recurse: the CES demo stack's units live in components/demo/.
while IFS= read -r f; do
    plain=$(grep -c '^ConditionKernelCommandLine=x5h\.role=' "$f")
    piped=$(grep -c '^ConditionKernelCommandLine=|x5h\.role=' "$f")
    [ $((plain + piped)) -gt 1 ] || continue
    [ "$plain" -eq 0 ] || fail "role_condition_not_triggering_$(basename "$f")"
done < <(find "$cfg" "$comp" -type f)

# --- the scripts that branch on the role ----------------------------------
# Units are only half of it. Every script that branches on the role has to
# name every role it must run in as well, and the first sweep for demo missed
# these: selfboot-smoke.sh failed a correct demo boot with unknown_role and
# npu-contract-smoke.sh refused the one role that exists to run the NPU. A
# board session is the worst place to find that, so a new role has to pass
# here before it can repeat it. Matched as a case arm, so a passing mention in
# a comment does not satisfy it. The role may head its own arm (`demo)`) or
# share one (`demo|dev)`), so both spellings count.
for s in selfboot-smoke.sh npu-contract-smoke.sh cr52-rproc-up.sh x5h-role demo-role-smoke.sh; do
    [ -f "$here/../scripts/$s" ] || fail "missing_$s"
    for role in demo dev; do
        grep -Eq "(^|[[:space:]|(])${role}[|)]" "$here/../scripts/$s" || fail "no_${role}_arm_$s"
    done
done
echo "TEST_PASS $name"
