#!/bin/sh
# x5h QEMU gate, guest side — rebuilt-kernel (6.1.102-autosd) edition.
# Emits GATE[1-7]_* markers on stdout (serial). Never exits nonzero mid-way —
# every assertion reports a marker and GATE_DONE always prints; the host
# side judges markers.
# vs the BSP-mimic edition: GATE2 now EXPECTS the ext4 store to hold
# capability xattrs (EXT4_FS_SECURITY=y is the point of the rebuild); GATE5
# (netavark "none" driver) is retired — 60-nftables.conf is injected at
# image-prep time so nftables is the configuration under test; GATE6
# (nftables port publish + outbound SNAT) and GATE7 (SELinux permissive)
# are new. Gate numbers are stable identifiers, not a sequence: 5 is
# deliberately not reused.
#
# There is deliberately NO `set -o pipefail` in this file, and its absence
# is load-bearing. The `... | grep -q ...` guards below (captest_cap_ok's
# getcap check, the curl polls) want a pipeline's status to be the LAST
# command's. Under pipefail an early-exiting `grep -q` SIGPIPEs its
# producer, so the guard returns 141 precisely when it MATCHES -- a guard
# that fails only when it passes. That bug shipped once already on this
# branch (stage-rebuilt-kernel.sh, fixed in db855a4). Do not "harden" this
# script by adding pipefail without rewriting every pipeline first.
T=/var/lib/autosd-test
mkdir -p /var/lib/containers

echo GATE1_LOGIN_OK
# Runtime assertion of the kernelrelease half of the one-build-two-images
# invariant (GATE1_CCVER below is the toolchain half): build-bsp-kernel.sh
# already asserts kernelrelease is exactly 6.1.102-autosd at BUILD time, but
# nothing before this line proves the guest actually BOOTED that release.
# The board netboots the same release from the same build -- the gate log
# recording it here is what makes "the gate proved the board's kernel
# lineage" a checkable claim, not just an assumption carried over from the
# build step.
echo "GATE1_KVER=$(uname -r)"
# Toolchain-pin runtime assertion. The wedge that motivated the pin is
# invisible to this gate (no real silicon), so the one thing CI can prove
# is that the booted kernel WAS built by the pinned compiler -- a silently
# un-pinned build becomes a red gate here, not a board hang later.
CCVER="$(cat /proc/version)"
echo "GATE1_CCVER=$CCVER"
case "$CCVER" in
    *"Arm GNU Toolchain 13.2.rel1"*) echo GATE1_CCVER_OK ;;
    *) echo GATE1_CCVER_FAIL ;;
esac
echo "GATE1_SYSTEMD_STATE=$(systemctl is-system-running 2>/dev/null)"
systemctl --failed --no-legend 2>/dev/null | head -20
# The rebuilt kernel ships these as modules (=m, exactly as the BSP kernel
# does); the retired mimic kernel had them built in. The injected module
# tree + host-side depmod make modprobe work here; a failure is a staging
# bug and every later gate would fail confusingly without this loud marker
# (the judge fails the run on it).
if ! modprobe -a overlay veth bridge br_netfilter btrfs nf_tables; then
    echo GATE1_MODPROBE_FAIL
fi

# Discover the just-loaded captest tag and confirm the security.capability
# xattr survives into a running container. Not hardcoded: podman load's tag
# normalization differs between hosts (dev host: localhost/...; this guest:
# docker.io/library/...). Sets $CAPTEST as a side effect; returns failure
# (printing nothing) if the tag can't be found or getcap doesn't confirm.
captest_cap_ok() {
    CAPTEST="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 captest)"
    [ -n "$CAPTEST" ] && podman run --rm "$CAPTEST" getcap /usr/bin/ping | grep -q cap_net_raw
}

# --- GATE2: default store on the ext4 root — EXPECTED TO PASS now. A load
# that "succeeds" but silently drops the xattr still fails captest_cap_ok,
# so this cannot false-pass (the cycle-5/6 lesson, kept).
echo "GATE2_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g2.log 2>&1 && captest_cap_ok; then
    echo GATE2_EXT4_OK
else
    echo GATE2_EXT4_FAIL
    tail -5 /tmp/g2.log
fi
podman rmi -af >/dev/null 2>&1

# --- GATE3: tmpfs store (unchanged from the mimic edition) ---
mount -t tmpfs -o size=2g tmpfs /var/lib/containers
# Required by the host: proves the probe ran against tmpfs, not a silently-
# failed mount falling through to the ext4 root. tail -1 picks the topmost
# mount if findmnt reports a stack.
echo "GATE3_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g3.log 2>&1 && captest_cap_ok; then
    echo GATE3_TMPFS_OK
else
    echo GATE3_FAIL; tail -5 /tmp/g3.log
fi
podman rmi -af >/dev/null 2>&1
umount /var/lib/containers

# --- GATE4: btrfs store on the blank second disk (unchanged) ---
mkfs.btrfs -f /dev/vdb >/dev/null 2>&1
mount /dev/vdb /var/lib/containers
echo "GATE4_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g4.log 2>&1 && captest_cap_ok; then
    echo GATE4_BTRFS_OK
else
    echo GATE4_FAIL; tail -5 /tmp/g4.log
fi

# --- GATE6: netavark nftables — published port AND outbound SNAT (store
# stays btrfs from GATE4). 60-nftables.conf overrides 50-x5h.conf's
# firewall_driver="none", so podman/netavark run the nftables driver here;
# the port-published path — a structural no-op under "none" — is DECISIVE.
podman load -i "$T/busybox-oci.tar" >/dev/null 2>&1
BB="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 busybox)"
podman run -d --name web -p 8080:80 "$BB" \
    sh -c 'echo ok > /tmp/index.html && exec httpd -f -p 80 -h /tmp' >/tmp/g6.log 2>&1
# Poll, not a fixed sleep: under TCG conmon/crun/httpd startup routinely
# takes longer than a few seconds.
ok=""
i=0
while [ "$i" -lt 30 ]; do
    if curl -fsS --max-time 5 http://127.0.0.1:8080/ 2>/dev/null | grep -q ok; then
        ok=1
        break
    fi
    i=$((i + 1))
    sleep 2
done
if [ -n "$ok" ]; then
    echo GATE6_NFT_PORT_OK
else
    echo GATE6_NFT_PORT_FAIL
    tail -5 /tmp/g6.log
    nft list ruleset 2>&1 | head -30
fi
# Outbound SNAT: the CI workflow runs an HTTP listener on the runner's
# 127.0.0.1:8099; slirp maps guest-side 10.0.2.2:8099 onto it. busybox wget
# from a FRESH container exercises container -> podman0 -> masquerade ->
# guest eth0. Under "none" no masquerade rule was ever installed, so this
# is the first time container->external is genuinely tested (the survey
# table's honest-networking gap, final-review I5).
ok=""
i=0
while [ "$i" -lt 5 ]; do
    # -T 10: bound the per-attempt cost in code, not just in the inactivity-
    # budget comment's arithmetic. This is precisely the failure this probe
    # exists to catch (masquerade rule missing -> SYN black-holed), and an
    # unanswered SYN otherwise blocks for the kernel's syn-retry ceiling
    # (~127s), silently eating the qemu-gate.exp inactivity budget instead
    # of failing fast.
    if podman run --rm "$BB" wget -T 10 -q -O /dev/null http://10.0.2.2:8099/ 2>/dev/null; then
        ok=1
        break
    fi
    i=$((i + 1))
    sleep 2
done
if [ -n "$ok" ]; then
    echo GATE6_SNAT_OK
else
    echo GATE6_SNAT_FAIL
    nft list ruleset 2>&1 | head -30
fi
podman rm -f web >/dev/null 2>&1

# --- GATE7: SELinux compiled in and permissive (enforcing=0 on cmdline).
# Reads the selinuxfs enforce flag directly instead of getenforce so the
# marker cannot depend on which utility package made it into the image.
if [ -f /sys/fs/selinux/enforce ]; then
    e="$(cat /sys/fs/selinux/enforce)"
    if [ "$e" = "0" ]; then
        echo GATE7_SELINUX_PERMISSIVE_OK
    else
        echo "GATE7_SELINUX_ENFORCE=$e"
    fi
else
    echo GATE7_SELINUX_ABSENT
fi
# selinux-bools.service FAILED on the BSP kernel (no SELinux — observed in
# gate cycle 3, recorded as a survey answer). With SELinux present and
# permissive it must now come up clean; systemctl is-failed exits 0 only
# when the unit is in the failed state -- but it ALSO exits nonzero when
# the unit does not exist at all, the same as when it is loaded and
# healthy, so is-failed alone cannot tell "OK" from "dropped from the
# image". GATE7_SELINUX_BOOLS_OK is a required marker, and a required
# marker that can pass on a missing unit is a false-PASS shape. LoadState
# disambiguates: it reads "not-found" for a unit systemd never heard of,
# and something else (e.g. "loaded") for one it has -- so OK now requires
# both "the unit exists" and "is-failed says it isn't failed".
LOADSTATE="$(systemctl show -p LoadState --value selinux-bools.service 2>/dev/null)"
if [ "$LOADSTATE" = "not-found" ]; then
    echo "GATE7_SELINUX_BOOLS_ABSENT (LoadState=not-found -- unit missing from this image)"
elif systemctl is-failed selinux-bools.service >/dev/null 2>&1; then
    echo GATE7_SELINUX_BOOLS_FAILED
    systemctl status selinux-bools.service --no-pager 2>&1 | head -10
else
    echo GATE7_SELINUX_BOOLS_OK
fi

echo GATE_DONE
