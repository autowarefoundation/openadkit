#!/bin/sh
# Print this board's normalized configuration manifest: key<TAB>value, sorted.
# Consumed by x5h-parity.sh on the companion. Everything that should be
# identical on both boards appears here; the few keys allowed to differ are
# listed in x5h-parity.sh.
set -u
out=$(mktemp)
emit() { printf '%s\t%s\n' "$1" "$2" >> "$out"; }
md5() { md5sum "$1" 2>/dev/null | cut -c1-32; }
emit kernel "$(uname -r)"
emit hostname "$(hostname)"
emit cmdline "$(tr ' ' '\n' < /proc/cmdline | grep -v '^ip=' | grep -v '^x5h\.role=' | tr '\n' ' ' | sed 's/ $//')"
for dir in /etc/systemd/system /etc/containers /etc/modprobe.d /etc/modules-load.d /etc/udev/rules.d \
           /etc/ssh/sshd_config.d /etc/systemd/system.conf.d /etc/x5h; do
    [ -d "$dir" ] || continue
    find "$dir" -type f | sort | while read -r f; do emit "file.$f" "$(md5 "$f")"; done
done
for f in /etc/hostname /usr/sbin/x5h-* /usr/sbin/*rpmsg* /usr/sbin/cr52-* /usr/sbin/npu-* /usr/sbin/ort-rootfs.* /usr/local/bin/rpmsg-eth /etc/ssh/ssh_host_*_key.pub; do
    [ -f "$f" ] && emit "file.$f" "$(md5 "$f")"
done
for u in $(systemctl list-unit-files --no-legend --no-pager 'x5h-*' 'cr52-*' 'rpmsg-*' 'awf-oak-*' 'var-*.mount' 2>/dev/null | awk '{print $1}'); do
    emit "unit.$u" "$(systemctl is-enabled "$u" 2>/dev/null || echo unknown)"
done
i=0
for disk in $(ls /dev/disk/by-path/ | grep 'ufs-scsi-0:0:0:[12]$' | sort); do
    dev=$(readlink -f "/dev/disk/by-path/$disk")
    sgdisk -p "$dev" 2>/dev/null | awk -v i=$i '/^ *[0-9]+ /{print "part."i"."$1}' | while read -r key; do
        n=${key##*.}
        label=$(sgdisk -i "$n" "$dev" | sed -n "s/^Partition name: '\(.*\)'/\1/p")
        size=$(sgdisk -i "$n" "$dev" | sed -n 's/^Partition size: [0-9]* sectors (\(.*\))/\1/p')
        uuid=$(sgdisk -i "$n" "$dev" | sed -n 's/^Partition unique GUID: //p' | tr 'A-F' 'a-f')
        emit "$key" "$label:$size:$uuid"
    done
    i=$((i + 1))
done
for lbl in yocto-boot yocto-root npu-work; do
    p=$(blkid -t PARTLABEL="$lbl" -o device 2>/dev/null | head -1)
    [ -n "$p" ] && emit "fs.$lbl" "$(blkid -s TYPE -o value "$p" 2>/dev/null || echo none)"
done
m=$(mktemp -d)
if mount -o ro /dev/disk/by-partlabel/x5h-boot "$m" 2>/dev/null; then
    for f in "$m"/*; do [ -f "$f" ] && emit "boot.$(basename "$f")" "$(md5 "$f")"; done
    umount "$m"
fi
rmdir "$m"
sort "$out"; rm -f "$out"
