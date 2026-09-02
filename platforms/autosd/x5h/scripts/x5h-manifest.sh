#!/bin/sh
# Print this board's normalized configuration manifest: key<TAB>value, sorted.
# Consumed by x5h-parity.sh on the companion. Everything that should be
# identical on both boards appears here; the few keys allowed to differ are
# listed in x5h-parity.sh.
#
# stdout carries the manifest and NOTHING else, so the terminal marker goes to
# stderr. A marker printed on stdout would be captured into the manifest file
# and read back as a key/value line, corrupting the data this script exists to
# produce. Grade this script by its stderr marker, not by its exit code:
#   X5H_MANIFEST_OK                  the manifest on stdout is complete
#   X5H_MANIFEST_FAIL reason=<slug>  nothing at all was written to stdout
# Reasons: mktemp mktemp_dir cmdline systemctl no_units no_disks readlink
#   sgdisk no_partitions sgdisk_info no_blkid boot_mount boot_empty
#   no_env_txt env_md5 md5 sort
#
# Any category that cannot be collected is FATAL. A manifest that silently lost
# a whole category (the x5h-boot mount failed, systemctl is broken, sgdisk is
# missing) is byte-for-byte indistinguishable from a complete one -- still
# well-formed, still sorted -- and two boards that lost the same category
# compare equal. Failing loudly is the only way that divergence stays visible.
set -u

out=
m=
md5err=

cleanup() {
    [ -n "$m" ] && { umount "$m" 2>/dev/null; rmdir "$m" 2>/dev/null; }
    [ -n "$out" ] && rm -f "$out"
    [ -n "$md5err" ] && rm -f "$md5err"
    return 0
}
fail() { cleanup; echo "X5H_MANIFEST_FAIL reason=$1" >&2; exit 1; }

out=$(mktemp) || { echo "X5H_MANIFEST_FAIL reason=mktemp" >&2; exit 1; }
md5err="$out.md5err"

emit() { printf '%s\t%s\n' "$1" "$2" >> "$out"; }

# md5() runs inside command substitutions nested in pipelines, so it cannot set
# a shell flag the parent would see. It drops a sentinel file instead, checked
# once at the end: a hash that could not be taken must not pass as data.
md5() {
    h=$(md5sum "$1" 2>/dev/null | cut -c1-32)
    if [ ${#h} -eq 32 ]; then
        printf '%s' "$h"
    else
        printf 'MD5FAIL'
        : > "$md5err"
    fi
}

emit kernel "$(uname -r)"
emit hostname "$(hostname)"
cmdline=$(tr ' ' '\n' < /proc/cmdline | grep -v '^ip=' | grep -v '^x5h\.role=' | tr '\n' ' ' | sed 's/ $//')
[ -n "$cmdline" ] || fail cmdline
emit cmdline "$cmdline"

for dir in /etc/systemd/system /etc/containers /etc/modprobe.d /etc/modules-load.d /etc/udev/rules.d \
           /etc/ssh/sshd_config.d /etc/systemd/system.conf.d /etc/x5h \
           /etc/systemd/system-preset /etc/ssh/authorized_keys.d /etc/NetworkManager/conf.d /etc/tmpfiles.d; do
    [ -d "$dir" ] || continue
    find "$dir" -type f | sort | while read -r f; do emit "file.$f" "$(md5 "$f")"; done
done
for f in /etc/hostname /usr/sbin/x5h-* /usr/sbin/*rpmsg* /usr/sbin/cr52-* /usr/sbin/npu-* /usr/sbin/selfboot-* /usr/sbin/ort-rootfs.* /usr/local/bin/rpmsg-eth /etc/ssh/ssh_host_*_key.pub; do
    [ -f "$f" ] && emit "file.$f" "$(md5 "$f")"
done

# Capture systemctl on its own line: piping into awk would hand $? to awk and
# a broken systemctl would look like a board with no units.
#
# 'sshd*' is in the pattern list because sshd is the one unit that governs
# remote access to the board, and the enablement of the unit is a different
# fact from the content of its drop-in (which the /etc/ssh/sshd_config.d scan
# above covers). Without it, a board whose sshd was disabled by hand mid
# session still passes parity, and the authorized_keys.d exemption in
# x5h-parity.sh would leave root SSH the least covered surface of the check.
unitfiles=$(systemctl list-unit-files --no-legend --no-pager 'x5h-*' 'cr52-*' 'rpmsg-*' 'sshd*' 'awf-oak-*' 'var-*.mount') || fail systemctl
units=$(printf '%s\n' "$unitfiles" | awk '{print $1}')
[ -n "$units" ] || fail no_units
for u in $units; do
    emit "unit.$u" "$(systemctl is-enabled "$u" 2>/dev/null || echo unknown)"
done

# The partition scan must not run inside a pipeline: fail() in a subshell would
# only kill the subshell and the manifest would come out short but "clean".
disks=$(ls /dev/disk/by-path/ | grep 'ufs-scsi-0:0:0:[12]$' | sort)
[ -n "$disks" ] || fail no_disks
i=0
for disk in $disks; do
    dev=$(readlink -f "/dev/disk/by-path/$disk") || fail readlink
    ptab=$(sgdisk -p "$dev") || fail sgdisk
    nums=$(printf '%s\n' "$ptab" | awk '/^ *[0-9]+ /{print $1}')
    [ -n "$nums" ] || fail no_partitions
    for n in $nums; do
        info=$(sgdisk -i "$n" "$dev") || fail sgdisk
        label=$(printf '%s\n' "$info" | sed -n "s/^Partition name: '\(.*\)'/\1/p")
        size=$(printf '%s\n' "$info" | sed -n 's/^Partition size: [0-9]* sectors (\(.*\))/\1/p')
        uuid=$(printf '%s\n' "$info" | sed -n 's/^Partition unique GUID: //p' | tr 'A-F' 'a-f')
        [ -n "$uuid" ] || fail sgdisk_info
        emit "part.$i.$n" "$label:$size:$uuid"
    done
    i=$((i + 1))
done

# Emit an fs.* key for every label unconditionally, "absent" when the partition
# does not exist. A missing key would vanish symmetrically if blkid broke.
command -v blkid >/dev/null 2>&1 || fail no_blkid
for lbl in yocto-boot yocto-root npu-work; do
    p=$(blkid -t PARTLABEL="$lbl" -o device 2>/dev/null | head -1)
    if [ -n "$p" ]; then
        t=$(blkid -s TYPE -o value "$p" 2>/dev/null)
        emit "fs.$lbl" "${t:-none}"
    else
        emit "fs.$lbl" absent
    fi
done

m=$(mktemp -d) || fail mktemp_dir
mount -o ro /dev/disk/by-partlabel/x5h-boot "$m" || fail boot_mount
nboot=0
for f in "$m"/*; do
    [ -f "$f" ] || continue
    emit "boot.$(basename "$f")" "$(md5 "$f")"
    nboot=$((nboot + 1))
done
[ "$nboot" -gt 0 ] || fail boot_empty

# env.md5 -- the md5 of the NORMALIZED rendered U-Boot environment.
#
# boot.x5h-env.txt (the raw md5) is allow-listed in x5h-parity.sh because the
# rendered env legitimately differs per board, which left the highest-
# consequence per-board artifact in this tree with zero parity coverage: the
# env carries `pd_ignore_unused clk_ignore_unused` (omitting them wedges the SoC
# with no oops, no panic, no watchdog), the pinned root=PARTUUID= values and the
# per-role kernel/dtb load addresses.
#
# uboot/x5h-env.tmpl has exactly three placeholders -- @BOARD_IP@ (twice),
# @BOARD_HOSTNAME@ and @YOCTO_HOSTNAME@ -- and every one of them sits inside an
# `ip=` word, in the client-address field and the hostname field:
#   ip=<client>:<server>:<gw>:<netmask>:<hostname>:<device>:<autoconf>
# So normalizing means blanking those two fields of every `ip=` word and
# nothing else. Substitute, never delete the line: deleting bootargs_common or
# bootargs_yocto would throw away clk_ignore_unused and the PARTUUIDs, which is
# precisely the content this key exists to protect. Gateway, netmask, device
# and autoconf stay in the hash, as does the whole rest of every line.
[ -f "$m/x5h-env.txt" ] || fail no_env_txt
envmd5=$(sed 's/\(ip=\)[^: ]*\(:[^: ]*:[^: ]*:[^: ]*:\)[^: ]*\(:\)/\1@IP@\2@HOST@\3/g' "$m/x5h-env.txt" | md5sum | cut -c1-32)
[ ${#envmd5} -eq 32 ] || fail env_md5
emit env.md5 "$envmd5"

umount "$m" && rmdir "$m" && m=

[ -e "$md5err" ] && fail md5

sort "$out" || fail sort
cleanup
echo "X5H_MANIFEST_OK" >&2
