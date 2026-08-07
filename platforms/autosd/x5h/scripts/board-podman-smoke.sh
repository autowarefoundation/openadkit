#!/bin/sh
# On-board podman smoke for AutoSD on the BSP kernel.
# Usage: board-podman-smoke.sh tmpfs
#        board-podman-smoke.sh btrfs /dev/disk/by-partlabel/autosd-store
# Phase order is a safety invariant: tmpfs (zero board mutation) must pass
# before btrfs (writes the previously-empty 32 GB UFS LUN) is attempted.
# This is enforced, not just documented: a genuine tmpfs pass stamps
# TMPFS_STAMP below, and the btrfs arm refuses to run without it.
set -x
T=/var/lib/autosd-test
TMPFS_STAMP=/run/x5h-smoke-tmpfs-passed
MODE="$1"
# Created up front, same reason as gate-guest.sh:10 -- an exported rootfs
# with no kernel package may not carry this directory, and mounting onto a
# nonexistent mountpoint should fail as a clear SMOKE_*_MOUNT_FAIL below, not
# as a confusing "mount point does not exist" with no marker at all.
mkdir -p /var/lib/containers
case "$MODE" in
tmpfs)
    # modprobe(8) is "modprobe [modulename] [module parameters...]" -- without
    # -a, only the first name is a module; the rest are parsed as parameters
    # to it (and silently ignored by a module that doesn't take them), so a
    # bare "modprobe overlay veth bridge br_netfilter" loads overlay ONLY and
    # still exits 0.
    modprobe -a overlay veth bridge br_netfilter \
        || { echo "SMOKE_${MODE}_MODPROBE_FAIL"; exit 1; }
    mount -t tmpfs -o size=8g tmpfs /var/lib/containers \
        || { echo "SMOKE_${MODE}_MOUNT_FAIL"; exit 1; }
    # Required marker, mirroring gate-guest.sh's GATE3_STORE_FS/GATE4_STORE_FS:
    # proves the podman probe below actually ran against tmpfs, not a
    # silently-failed mount that fell through to the ext4 root underneath.
    echo "SMOKE_${MODE}_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
    ;;
btrfs)
    if [ ! -f "$TMPFS_STAMP" ]; then
        echo "SMOKE_${MODE}_TMPFS_GATE_FAIL (no tmpfs pass recorded this boot; re-run 'tmpfs' first, or touch $TMPFS_STAMP to override deliberately)"
        exit 1
    fi
    DEV="$2"
    [ -b "$DEV" ] || { echo "SMOKE_${MODE}_DEV_FAIL ($DEV is not a block device)"; exit 1; }
    modprobe -a btrfs overlay veth bridge br_netfilter \
        || { echo "SMOKE_${MODE}_MODPROBE_FAIL"; exit 1; }
    mount -t btrfs "$DEV" /var/lib/containers \
        || { echo "SMOKE_${MODE}_MOUNT_FAIL"; exit 1; }
    STOREFS="$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
    echo "SMOKE_${MODE}_STORE_FS=$STOREFS"
    # Machine-enforced, not left to the operator's eyes: the gate's own
    # equivalent (qemu-gate.exp requiring GATE4_STORE_FS=btrfs before
    # judging a pass) is enforced by the harness, not just printed. -t
    # btrfs above already rejects most wrong-fstype devices at mount time,
    # but this assertion is the belt to that suspenders, and it runs
    # before any podman load: a $DEV typo onto a device carrying a real
    # filesystem (e.g. the BSP's own storage) must not silently let the
    # next podman load write to it -- directly against the plan's
    # invariant that the only storage written is the previously-empty
    # 32 GB UFS LUN.
    [ "$STOREFS" = "btrfs" ] || { echo "SMOKE_${MODE}_STORE_FS_FAIL"; exit 1; }
    ;;
*)
    echo "usage: $0 tmpfs | btrfs <blockdev>"; exit 2
    ;;
esac

# Clear the transient store's runroot before any podman call. This is not
# hygiene, it is required on the board: AutoSD ships
# /usr/share/containers/storage.conf with transient_store = true, so the
# storage database lives in the runroot (/run/containers/storage) rather
# than under the graphroot. podman-clean-transient.service runs at boot,
# long before this script mounts anything, and at that moment
# /var/lib/containers is still the NFS root -- where overlay is refused
# outright ("'overlay' is not supported over nfs"). The unit fails, but it
# has already written db.sql + overlay/ into the runroot recording that
# verdict, and every later podman invocation in the same boot reuses it --
# so podman keeps reporting the store as NFS even once a tmpfs or btrfs
# store IS mounted over /var/lib/containers and stat -f confirms it. That
# reproduced exactly on the board: SMOKE_tmpfs_STORE_FS=tmpfs immediately
# followed by SMOKE_tmpfs_LOAD_FAIL with the nfs message, while the same
# load against a fresh --root/--runroot pair succeeded. Removing this
# directory is safe by construction -- it is transient state on /run that
# containers/storage recreates on demand -- and it is also wanted BETWEEN
# phases, since each phase mounts a different store underneath a database
# that would otherwise still describe the previous one.
# The QEMU gate cannot catch this: its root is ext4 on /dev/vda, so the
# boot-time unit succeeds there and leaves healthy state behind.
rm -rf /run/containers/storage

# From here on, record failures in FAIL instead of exiting immediately, so
# every run reaches exactly one terminal marker -- SMOKE_<mode>_PASS or
# SMOKE_<mode>_FAIL -- and the tmpfs cleanup below always runs.
FAIL=
podman load -i "$T/captest-docker.tar" || { echo "SMOKE_${MODE}_LOAD_FAIL"; FAIL=1; }
# The loaded tag CANNOT be hardcoded as localhost/x5h-captest:latest: podman's
# `load` image-tag normalization differs across podman builds/versions -- the
# QEMU gate's guest podman produces docker.io/library/x5h-captest:latest
# instead, and a hardcoded run against a nonexistent local tag falls through
# to trying to pull from a registry literally named "localhost". Discover it
# the same way $BB is discovered below, and guard the empty capture the same
# way, so a discovery failure can't reach `podman run --rm "" getcap ...`.
CAPTEST=
if [ -z "$FAIL" ]; then
    CAPTEST="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 captest)"
    [ -n "$CAPTEST" ] || { echo "SMOKE_${MODE}_LOAD_FAIL"; FAIL=1; }
fi
if [ -z "$FAIL" ]; then
    podman run --rm "$CAPTEST" getcap /usr/bin/ping | grep cap_net_raw \
        || { echo "SMOKE_${MODE}_CAPS_FAIL"; FAIL=1; }
fi
if [ -z "$FAIL" ]; then
    podman load -i "$T/busybox-oci.tar" || { echo "SMOKE_${MODE}_BUSYBOX_LOAD_FAIL"; FAIL=1; }
fi
BB=
if [ -z "$FAIL" ]; then
    BB="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 busybox)"
    [ -n "$BB" ] || { echo "SMOKE_${MODE}_BUSYBOX_LOAD_FAIL"; FAIL=1; }
fi
if [ -z "$FAIL" ]; then
    podman run -d --name web -p 8080:80 "$BB" \
        sh -c 'echo ok > /tmp/index.html && exec httpd -f -p 80 -h /tmp'
    # Port-published attempt: INFORMATIONAL ONLY, must never set FAIL. This
    # is GATE5's first attempt, and the green gate run's own timeline proved
    # it dead under firewall_driver=none (what 50-x5h.conf ships): the
    # port-published container started with veth0 forwarding, the poll ran
    # ~78s with zero successful curls, and only the direct-container-IP
    # fallback below succeeded. netavark's "none" driver is a no-op for
    # setup_port_forward -- no DNAT rule is ever installed, so
    # 127.0.0.1:8080 is unreachable by construction, not by anything wrong
    # with this store or this board. Kept anyway so a future
    # firewall_driver change that makes it viable again shows up here.
    # Poll rather than a fixed sleep, same reason gate-guest.sh polls: a
    # short fixed window would misreport a merely-slow start as broken, and
    # the board is slower than the CI runner the gate ran on.
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
    [ -n "$ok" ] && echo "SMOKE_${MODE}_NET_PORT_OK"
    # The path the gate actually proved: host -> container by the
    # container's own bridge IP, the same `podman inspect` form
    # gate-guest.sh's GATE5 fallback uses (docker-compat .IPAddress can
    # come back empty under netavark; the .Networks range form does not).
    # THIS is the check that sets FAIL, not the port-published attempt
    # above -- a prior round wrongly made the port-published attempt
    # decisive, which would have failed SMOKE_tmpfs on every board run
    # regardless of store health, and because tmpfs gates btrfs via the
    # stamp interlock, would have blocked the btrfs phase too.
    IP="$(podman inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web 2>/dev/null)"
    ok=""
    i=0
    while [ "$i" -lt 30 ]; do
        if [ -n "$IP" ] && curl -fsS --max-time 5 "http://$IP/" 2>/dev/null | grep -q ok; then
            ok=1
            break
        fi
        i=$((i + 1))
        sleep 2
    done
    if [ -n "$ok" ]; then
        echo "SMOKE_${MODE}_NET_OK"
    else
        echo "SMOKE_${MODE}_NET_FAIL (try firewall none / direct container IP, as in the QEMU gate -- both the port-published and the direct-container-IP path were already tried automatically above and both failed, so look at podman0/veth state and podman logs next)"
        FAIL=1
    fi
    podman rm -f web >/dev/null 2>&1
fi

# tmpfs is the zero-mutation phase: leave the board as found so a later btrfs
# run doesn't stack its mount on top of a still-mounted tmpfs store. A failed
# unmount does not change the podman/network verdict above (SMOKE_*_PASS
# still reports that truthfully), but it DOES withhold the interlock stamp
# below: the stamp's job is to promise "the board was left clean," and a
# stuck tmpfs mount breaks that promise even when podman itself worked.
UMOUNT_OK=
if [ "$MODE" = "tmpfs" ]; then
    # Retry rather than deciding on the first attempt: `podman rm -f` returns
    # as soon as the container is killed, but conmon/crun exit and podman's
    # own container-cleanup run asynchronously after it, and until they are
    # done something still holds the store. Observed on the board as a single
    # "umount: /var/lib/containers: target is busy" immediately after an
    # otherwise clean SMOKE_tmpfs_PASS -- a plain retry seconds later
    # succeeded with no sub-mounts and no containers left, so this is a race
    # with teardown, not a leak. Deciding on the first attempt withheld the
    # interlock stamp and blocked the btrfs phase for no real reason. A
    # genuinely stuck mount still fails: it just takes ~20 s to say so.
    i=0
    while [ "$i" -lt 10 ]; do
        if umount /var/lib/containers 2>/dev/null; then
            UMOUNT_OK=1
            break
        fi
        i=$((i + 1))
        sleep 2
    done
    if [ -z "$UMOUNT_OK" ]; then
        umount /var/lib/containers
        echo "SMOKE_${MODE}_UMOUNT_WARN (stale tmpfs mount may remain over the ext4 root; tmpfs-pass stamp withheld)"
    fi
fi

if [ -n "$FAIL" ]; then
    echo "SMOKE_${MODE}_FAIL"
    exit 1
fi

# Only a genuine, complete tmpfs pass AND a clean unmount unlock the btrfs
# arm -- and the write itself is verified, not assumed. There is no set -e
# in this script, so an unguarded ": > $TMPFS_STAMP" whose write silently
# failed (e.g. permission, or /run not actually mounted) would still fall
# through to SMOKE_tmpfs_PASS below, leaving the operator staring at a
# pass while the btrfs arm mysteriously refuses with TMPFS_GATE_FAIL. The
# findmnt check is the same upgrade SMOKE_*_STORE_FS already got: it
# confirms the stamp is landing on the boot-scoped tmpfs /run actually is
# (see the Board bring-up section on why that scoping matters), not
# silently on whatever /run happens to resolve to.
if [ "$MODE" = "tmpfs" ] && [ -n "$UMOUNT_OK" ]; then
    STAMPFS="$(findmnt -no FSTYPE --target /run | tail -1)"
    if [ "$STAMPFS" = "tmpfs" ]; then
        : > "$TMPFS_STAMP" || { echo "SMOKE_${MODE}_STAMP_WRITE_FAIL"; FAIL=1; }
    else
        echo "SMOKE_${MODE}_STAMP_WRITE_FAIL (/run is $STAMPFS, not tmpfs -- refusing a stamp that would not be boot-scoped)"
        FAIL=1
    fi
fi

if [ -n "$FAIL" ]; then
    echo "SMOKE_${MODE}_FAIL"
    exit 1
fi
echo "SMOKE_${MODE}_PASS"
