#!/bin/sh
# x5h QEMU gate, guest side. Emits GATE[1-5]_* markers on stdout (serial).
# Answers survey §7: selinux=0 boot / podman xattr / tmpfs store / btrfs store /
# netavark without nftables. Never exits nonzero mid-way — every assertion
# reports a marker and GATE_DONE always prints; the host side judges markers.
T=/var/lib/autosd-test
# Created up front so the very first GATE2_STORE_FS read below (which runs
# before podman has touched anything) doesn't hit a nonexistent path and
# come back empty; GATE3/GATE4 mount over this same directory later.
mkdir -p /var/lib/containers

echo GATE1_LOGIN_OK
echo "GATE1_SYSTEMD_STATE=$(systemctl is-system-running 2>/dev/null)"
systemctl --failed --no-legend 2>/dev/null | head -20

# Discover the just-loaded captest image tag and confirm the
# security.capability xattr survived by reading it back inside a running
# container. The tag CANNOT be hardcoded as "localhost/x5h-captest:latest":
# podman's `load` image-tag normalization differs between the dev host Task 4
# was reviewed on (which produced that exact tag) and this guest's podman
# (which produces "docker.io/library/x5h-captest:latest" instead) -- the same
# reason the busybox path below already discovers its tag rather than
# hardcoding it. Sets $CAPTEST as a side effect (this script has no other use
# for local variable scoping, matching every other global in this file) and
# returns failure -- printing nothing -- if the tag can't be found or getcap
# doesn't confirm the capability; callers decide which marker that maps to,
# since GATE2's mapping differs from GATE3/GATE4's.
captest_cap_ok() {
    CAPTEST="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 captest)"
    [ -n "$CAPTEST" ] && podman run --rm "$CAPTEST" getcap /usr/bin/ping | grep -q cap_net_raw
}

# --- GATE2: default store on the ext4 root (EXT4_FS_SECURITY absent) ---
# GATE2_STORE_FS is informational only: it records which filesystem the
# verdict below was actually measured against (no mount is performed here,
# so this should read "ext4" -- the root export's own filesystem). `tail -1`
# because findmnt --target lists the whole mount stack (oldest first) when
# the mountpoint has been covered by a later mount -- see GATE3/GATE4 below.
echo "GATE2_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g2.log 2>&1; then
    # `load` succeeding is necessary but not sufficient: a load that silently
    # drops the xattr (rather than failing outright) would exit 0 here too,
    # so UNEXPECTED_PASS requires the same run+getcap confirmation GATE3/
    # GATE4 use, not load's exit status alone.
    if captest_cap_ok; then
        echo GATE2_EXT4_UNEXPECTED_PASS
    else
        # load reported success, but the capability isn't actually readable
        # in a running container (or the tag couldn't even be found). This is
        # still the expected constraint manifesting -- ext4 without
        # EXT4_FS_SECURITY can't carry the xattr -- just discovered silently
        # via the runtime probe instead of a loud load-time error, so it is
        # the same finding as GATE2_EXT4_FAIL_OK, not a genuine pass.
        echo GATE2_EXT4_FAIL_OK
        tail -5 /tmp/g2.log
    fi
else
    if grep -qiE 'operation not supported|not supported|ENOTSUP' /tmp/g2.log; then
        echo GATE2_EXT4_FAIL_OK
    else
        echo GATE2_EXT4_FAIL_OTHER
    fi
    tail -5 /tmp/g2.log
fi
podman rmi -af >/dev/null 2>&1

# --- GATE3: tmpfs store (TMPFS_XATTR=y on BSP kernel too) ---
mount -t tmpfs -o size=2g tmpfs /var/lib/containers
# GATE3_STORE_FS is required by the host: it proves the podman probe below
# actually ran against tmpfs, not a silently-failed mount that fell through
# to whatever was mounted at /var/lib/containers before (i.e. the ext4 root).
# `tail -1` picks the effective (most-recently-mounted, topmost) filesystem
# if the mount above failed and findmnt reports a stack instead of one line.
echo "GATE3_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g3.log 2>&1 && captest_cap_ok; then
    echo GATE3_TMPFS_OK
else
    echo GATE3_FAIL; tail -5 /tmp/g3.log
fi
podman rmi -af >/dev/null 2>&1
umount /var/lib/containers

# --- GATE4: btrfs store on the blank second disk ---
mkfs.btrfs -f /dev/vdb >/dev/null 2>&1
mount /dev/vdb /var/lib/containers
# GATE4_STORE_FS is required by the host for the same reason as GATE3's: it
# proves the probe ran against btrfs, not a leftover/fallback mount. `tail -1`
# for the same reason as GATE3's -- pick the effective top-of-stack mount.
echo "GATE4_STORE_FS=$(findmnt -no FSTYPE --target /var/lib/containers | tail -1)"
if podman load -i "$T/captest-docker.tar" >/tmp/g4.log 2>&1 && captest_cap_ok; then
    echo GATE4_BTRFS_OK
else
    echo GATE4_FAIL; tail -5 /tmp/g4.log
fi

# --- GATE5: container networking without NF_TABLES (store stays btrfs) ---
podman load -i "$T/busybox-oci.tar" >/dev/null 2>&1
BB="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 busybox)"
podman run -d --name web -p 8080:80 "$BB" \
    sh -c 'echo ok > /tmp/index.html && exec httpd -f -p 80 -h /tmp' >/tmp/g5.log 2>&1
# Poll instead of a single fixed sleep: under TCG, conmon/crun/httpd startup
# routinely takes longer than a few seconds, and a too-short window here
# would misreport a working iptables path as broken.
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
    echo GATE5_IPTABLES_OK
else
    tail -5 /tmp/g5.log
    # Fallback: no usable iptables backend -> firewall none + direct container IP.
    printf '[network]\nfirewall_driver = "none"\n' > /etc/containers/containers.conf.d/99-gate-fallback.conf
    podman rm -f web >/dev/null 2>&1
    podman run -d --name web "$BB" \
        sh -c 'echo ok > /tmp/index.html && exec httpd -f -p 80 -h /tmp' >/dev/null 2>&1
    ok=""
    i=0
    while [ "$i" -lt 30 ]; do
        IP="$(podman inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web 2>/dev/null)"
        if [ -n "$IP" ] && curl -fsS --max-time 5 "http://$IP/" 2>/dev/null | grep -q ok; then
            ok=1
            break
        fi
        i=$((i + 1))
        sleep 2
    done
    if [ -n "$ok" ]; then
        echo GATE5_NONE_OK
    else
        echo GATE5_FAIL
    fi
fi
podman rm -f web >/dev/null 2>&1
# The board's NFS root is persistent (Task 8 copies this script there): don't
# leave the fallback drop-in behind shadowing Task 2's 50-x5h.conf forever.
# Which path was taken is already recorded by the GATE5_* marker above.
rm -f /etc/containers/containers.conf.d/99-gate-fallback.conf

echo GATE_DONE
