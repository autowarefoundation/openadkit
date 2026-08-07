#!/bin/sh
# On-board podman smoke for AutoSD, running on either the BSP kernel or the
# rebuilt 6.1.102-autosd kernel (see the REBUILT detection below).
# Usage: board-podman-smoke.sh tmpfs
#        board-podman-smoke.sh ext4loop
#        board-podman-smoke.sh btrfs /dev/disk/by-partlabel/autosd-store
# Phase order is a safety invariant: tmpfs (zero board mutation) must pass
# before btrfs (writes the previously-empty 32 GB UFS LUN) is attempted;
# ext4loop is also zero-mutation (backing file on /run tmpfs) and runs
# between them on the rebuilt kernel. This is enforced, not just
# documented: a genuine tmpfs pass stamps TMPFS_STAMP below, and the btrfs
# arm refuses to run without it. The tmpfs->btrfs interlock stamp is
# unchanged by ext4loop.
#
# Tracing only. No `set -e` (failures are recorded in FAIL below so every run
# reaches exactly one terminal SMOKE_<mode>_{PASS,FAIL} marker), and no
# `set -o pipefail` -- the latter absence is load-bearing, not an oversight.
# The `| grep -q ok` curl polls, the `| grep cap_net_raw` getcap check and
# the `| tail -1` findmnt reads all want a pipeline's status to be the LAST
# command's. Under pipefail an early-exiting `grep -q` SIGPIPEs curl, so the
# guard returns 141 precisely when it MATCHES -- a guard that fails only when
# it passes. That bug shipped once already on this branch
# (stage-rebuilt-kernel.sh, fixed in db855a4). Do not add pipefail here
# without rewriting every pipeline first.
set -x
T=/var/lib/autosd-test
# Overridable for the off-board stub harness only; on the board the /run
# default is what the btrfs interlock keys on.
TMPFS_STAMP="${X5H_TMPFS_STAMP:-/run/x5h-smoke-tmpfs-passed}"
MODE="$1"
# Rebuilt-kernel detection: 6.1.102-autosd carries EXT4_FS_SECURITY and
# NF_TABLES, so the published-port path must work (decisive below) and the
# outbound-SNAT probe runs. On the BSP kernel both stay as before.
case "$(uname -r)" in
*-autosd*) REBUILT=1 ;;
*) REBUILT= ;;
esac
# Created up front, same reason as gate-guest.sh -- an exported rootfs
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
ext4loop)
    # Zero-persistent-mutation proof of EXT4_FS_SECURITY on the rebuilt
    # kernel: the store lives on an ext4 image file in /run (tmpfs), so
    # nothing on UFS or the NFS root is written. Expected PASS only on
    # 6.1.102-autosd; on the BSP kernel this reproduces the GATE2-class
    # capability failure by design. loop is =m on both kernels.
    modprobe -a loop overlay veth bridge br_netfilter \
        || { echo "SMOKE_${MODE}_MODPROBE_FAIL"; exit 1; }
    IMG=/run/x5h-ext4-store.img
    rm -f "$IMG"
    truncate -s 2G "$IMG" || { echo "SMOKE_${MODE}_IMG_FAIL"; exit 1; }
    mkfs.ext4 -q "$IMG" || { echo "SMOKE_${MODE}_MKFS_FAIL"; exit 1; }
    mount -o loop "$IMG" /var/lib/containers \
        || { echo "SMOKE_${MODE}_MOUNT_FAIL"; exit 1; }
    STOREFS="$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
    echo "SMOKE_${MODE}_STORE_FS=$STOREFS"
    # Unmount before exiting even on this early-exit path: no podman
    # container has run yet at this point, so there is no async-teardown
    # race to retry against, but a wrong-fstype loop mount left over
    # /var/lib/containers here would otherwise be this script's only exit
    # path with no cleanup attempt at all.
    [ "$STOREFS" = "ext4" ] || { echo "SMOKE_${MODE}_STORE_FS_FAIL"; umount /var/lib/containers 2>/dev/null; exit 1; }
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
    # 32 GB UFS LUN. Also unmount before exiting here, same as the
    # ext4loop arm's equivalent guard: no podman container has run yet at
    # this point, so there is no async-teardown race to retry against, but
    # a wrong-fstype mount left live over /var/lib/containers would
    # otherwise be this arm's only exit path with no cleanup attempt at
    # all -- and this is the arm that touches the real 32 GB UFS LUN, so
    # leaving it mounted is worse here than anywhere else in this script.
    [ "$STOREFS" = "btrfs" ] || { echo "SMOKE_${MODE}_STORE_FS_FAIL"; umount /var/lib/containers 2>/dev/null; exit 1; }
    ;;
*)
    echo "usage: $0 tmpfs | ext4loop | btrfs <blockdev>"; exit 2
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
    # Port-published attempt. On the BSP kernel this stays INFORMATIONAL
    # ONLY and must never set FAIL: this is GATE5's first attempt, and the
    # green gate run's own timeline proved it dead under
    # firewall_driver=none (what 50-x5h.conf ships) -- the port-published
    # container started with veth0 forwarding, the poll ran ~78s with zero
    # successful curls, and only the direct-container-IP fallback below
    # succeeded. netavark's "none" driver is a no-op for setup_port_forward
    # -- no DNAT rule is ever installed, so 127.0.0.1:8080 is unreachable by
    # construction, not by anything wrong with this store or this board.
    # On the rebuilt kernel it is the opposite: 60-nftables.conf switches
    # netavark to the nftables driver, which DOES install the DNAT rule, so
    # a dead published port there is a real regression and this check is
    # decisive (see the REBUILT branch below).
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
    if [ -n "$ok" ]; then
        echo "SMOKE_${MODE}_NET_PORT_OK"
    elif [ -n "$REBUILT" ]; then
        # Under 60-nftables.conf the nftables driver must install the DNAT
        # rule; a dead published port on the rebuilt kernel is a real
        # failure, not the "none"-driver structural no-op it is on BSP.
        echo "SMOKE_${MODE}_NET_PORT_FAIL"
        FAIL=1
    fi
    # The path the gate actually proved on the BSP kernel: host -> container
    # by the container's own bridge IP, the same `podman inspect` form
    # gate-guest.sh's GATE5 fallback uses (docker-compat .IPAddress can
    # come back empty under netavark; the .Networks range form does not).
    # On the BSP kernel THIS is the check that sets FAIL, not the
    # port-published attempt above -- a prior round wrongly made the
    # port-published attempt decisive there, which would have failed
    # SMOKE_tmpfs on every board run regardless of store health, and
    # because tmpfs gates btrfs via the stamp interlock, would have blocked
    # the btrfs phase too. On the rebuilt kernel this remains a second,
    # independent confirmation and can also set FAIL.
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
    if [ -n "$REBUILT" ]; then
        # Container -> external: busybox wget to the host PC across the
        # board LAN from a FRESH container (needs netavark's masquerade
        # rule). Operator first runs on the host:
        #   python3 -m http.server 8099 --bind 192.168.0.1
        # Override the target with SMOKE_EXT_URL; SMOKE_EXT_URL=skip
        # records an explicit skip instead of a failure.
        EXT_URL="${SMOKE_EXT_URL:-http://192.168.0.1:8099/}"
        if [ "$EXT_URL" = "skip" ]; then
            echo "SMOKE_${MODE}_SNAT_SKIPPED"
        else
            ok=""
            i=0
            while [ "$i" -lt 5 ]; do
                # -T 10: bound the per-attempt cost in code, not just in the
                # loop's own arithmetic. This is precisely the failure this
                # probe exists to catch (masquerade rule missing -> SYN
                # black-holed), and an unanswered SYN otherwise blocks for
                # the kernel's syn-retry ceiling (~127s per attempt), turning
                # this 5-attempt loop into ~10 minutes of silence at a
                # serial console with a human waiting, instead of ~50s.
                if podman run --rm "$BB" wget -T 10 -q -O /dev/null "$EXT_URL" 2>/dev/null; then
                    ok=1
                    break
                fi
                i=$((i + 1))
                sleep 2
            done
            if [ -n "$ok" ]; then
                echo "SMOKE_${MODE}_SNAT_OK"
            else
                echo "SMOKE_${MODE}_SNAT_FAIL"
                FAIL=1
            fi
        fi
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

# ext4loop has the same async-teardown race as tmpfs above (podman rm -f
# returns before conmon/crun finish releasing the store), so it gets the
# same retry loop -- and a leaked loop mount over the ext4-on-tmpfs image is
# worse to leave behind than a leaked tmpfs mount, since it also pins the
# backing file's tmpfs memory even after the file itself is unlinked. tmpfs
# above only withholds its interlock stamp on a failed unmount; ext4loop has
# no stamp to withhold, so its failed-unmount case instead sets FAIL
# directly -- the run terminates as SMOKE_ext4loop_FAIL, not a bare WARN
# that still reaches PASS. rm -f runs ONLY after a confirmed clean unmount:
# deleting the backing file while the loop device may still be attached
# would drop the file's directory entry (hiding the leak from a later
# `ls /run`) while the mount and its tmpfs memory stay live underneath.
if [ "$MODE" = "ext4loop" ]; then
    EXT4LOOP_UMOUNT_OK=
    i=0
    while [ "$i" -lt 10 ]; do
        if umount /var/lib/containers 2>/dev/null; then
            EXT4LOOP_UMOUNT_OK=1
            break
        fi
        i=$((i + 1))
        sleep 2
    done
    if [ -z "$EXT4LOOP_UMOUNT_OK" ]; then
        umount /var/lib/containers
        echo "SMOKE_${MODE}_UMOUNT_WARN (stale loop mount may remain over the ext4 root)"
        FAIL=1
    else
        rm -f /run/x5h-ext4-store.img
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
