#!/usr/bin/env bash
# Stage one X5H board from the common image plus the inputs the image cannot
# carry. Reads the board's identity ONLY from boards/<board>.vars.
#
#   stage-board.sh <x5h1|x5h2> <inputs-dir> <subcommand> [--yes]
#
# Subcommands (run in this order in a session; each is idempotent):
#   check-inputs     every input present; Image-autosd embeds the MP-PHY blob
#   backup-keys      save authorized_keys + ssh host keys from the LIVE board
#   prepare-root     copy x5h-rootfs.ext4 -> work/<board>-root.ext4, inject
#                    hostname, /etc/x5h/board.conf, keys, rpmsg-eth, ELF
#   write-root --yes dd the prepared root to the board's x5h-root (board must
#                    NOT be running from it: yocto role or rescue netboot)
#   partition-lun2 --yes  GPT on the second LUN: yocto-boot/yocto-root/npu-work
#   write-boot --yes replace x5h-boot contents (kernel, both dtbs, env, role)
#   stage-payload    rsync inputs/npu -> npu-work (mounted on the board)
#   stage-stack      container images + scenario map (existing scripts)
#   print-uboot      the exact console lines to import the environment
# Flash-class subcommands print their plan and stop unless --yes is given.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
X5H="$HERE/.."
board=${1:?board}; inputs=${2:?inputs-dir}; cmd=${3:?subcommand}; yes=${4:-}
vars="$X5H/boards/$board.vars"
[ -r "$vars" ] || { echo "FATAL: no $vars"; exit 1; }
BOARD_IP= BOARD_HOSTNAME= HAS_YOCTO=
# shellcheck disable=SC1090
. "$vars"
WORK=${X5H_STAGE_WORK:-/var/tmp/x5h-stage/$board}
mkdir -p "$WORK"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@$BOARD_IP"
CR52_ELF=actuation_x5h.elf
AUTOSD_ROOT=/dev/disk/by-partlabel/x5h-root
BOOT=/dev/disk/by-partlabel/x5h-boot
LUN2='/dev/disk/by-path/*ufs-scsi-0:0:0:2'
say() { echo "== $*"; }
need_yes() { [ "$yes" = --yes ] || { echo "PLAN ONLY: re-run with --yes to execute the above on $board ($BOARD_IP)"; exit 0; }; }

check_inputs() {
    local missing=0
    for f in Image-autosd extract-ikconfig r8a78000-ironhide-uio-autosd.dtb r8a78000-ironhide-npu.dtb \
             x5h-rootfs.ext4 rpmsg-eth "$CR52_ELF" npu/ort-rootfs npu/cmemdrv.ko npu/renesas_ep_eval_latency.py; do
        [ -e "$inputs/$f" ] || { echo "MISSING $inputs/$f"; missing=1; }
    done
    [ $missing -eq 0 ] || { echo "STAGE_CHECK_FAIL reason=missing_inputs"; exit 1; }
    chmod +x "$inputs/extract-ikconfig"
    "$inputs/extract-ikconfig" "$inputs/Image-autosd" | grep -qxF 'CONFIG_EXTRA_FIRMWARE="rcar_gen5_mp_phy.bin"' \
        || { echo "STAGE_CHECK_FAIL reason=kernel_without_firmware"; exit 1; }
    file "$inputs/rpmsg-eth" | grep -q 'aarch64.*statically linked' || { echo "STAGE_CHECK_FAIL reason=rpmsg_eth_not_static_aarch64"; exit 1; }
    echo "STAGE_CHECK_PASS board=$board"
}

backup_keys() {
    say "saving ssh keys from the live board $BOARD_IP"
    $SSH 'cd / && find etc/ssh/authorized_keys.d/root etc/ssh/ssh_host_* -type f 2>/dev/null | cpio -o -H newc 2>/dev/null' > "$WORK/keys.cpio"
    [ -s "$WORK/keys.cpio" ] || { echo "STAGE_KEYS_FAIL reason=empty_archive"; exit 1; }
    cpio -it < "$WORK/keys.cpio"
    echo "STAGE_KEYS_PASS file=$WORK/keys.cpio"
}

prepare_root() {
    local img="$WORK/$board-root.ext4" mnt
    [ -s "$WORK/keys.cpio" ] || { echo "STAGE_ROOT_FAIL reason=run_backup_keys_first"; exit 1; }
    cp --reflink=auto "$inputs/x5h-rootfs.ext4" "$img"
    mnt=$(mktemp -d)
    sudo mount -o loop "$img" "$mnt"
    trap 'sudo umount "$mnt" 2>/dev/null || true; rmdir "$mnt" 2>/dev/null || true' EXIT
    printf '%s\n' "$BOARD_HOSTNAME" | sudo tee "$mnt/etc/hostname" >/dev/null
    printf 'BOARD_HOSTNAME=%s\nHAS_YOCTO=%s\n' "$BOARD_HOSTNAME" "$HAS_YOCTO" | sudo tee "$mnt/etc/x5h/board.conf" >/dev/null
    (cd "$mnt" && sudo cpio -idmu < "$WORK/keys.cpio")
    sudo install -D -m 0755 "$inputs/rpmsg-eth" "$mnt/var/usrlocal/bin/rpmsg-eth"   # /usr/local -> ../var/usrlocal on this rootfs
    sudo install -D -m 0644 "$inputs/$CR52_ELF" "$mnt/lib/firmware/$CR52_ELF"
    printf 'CR52_FIRMWARE=%s\n' "$CR52_ELF" | sudo tee "$mnt/etc/default/cr52-remoteproc" >/dev/null
    sudo test -f "$mnt/etc/systemd/system/multi-user.target.wants/sshd.service" || { echo "STAGE_ROOT_FAIL reason=sshd_not_enabled_in_image"; exit 1; }
    sudo test -f "$mnt/etc/systemd/system/multi-user.target.wants/x5h-npu.service" || { echo "STAGE_ROOT_FAIL reason=npu_unit_not_enabled_in_image"; exit 1; }
    sudo umount "$mnt"; rmdir "$mnt"; trap - EXIT
    echo "STAGE_ROOT_PASS image=$img"
}

write_root() {
    local img="$WORK/$board-root.ext4"
    [ -s "$img" ] || { echo "STAGE_WRITE_FAIL reason=run_prepare_root_first"; exit 1; }
    say "PLAN: dd $img -> $BOARD_IP:$AUTOSD_ROOT (the board must not be running from x5h-root)"
    $SSH "findmnt -n -o SOURCE / ; readlink -f $AUTOSD_ROOT"
    need_yes
    # The partlabel symlink must resolve to a real block device before dd runs.
    # readlink -f prints the path even when nothing is there, so without this
    # the running-from-target test below passes, dd creates a regular FILE at
    # that path, and the read-back reads back that very file: a false PASS that
    # wrote nothing to the disk.
    $SSH "test -b $AUTOSD_ROOT" || { echo "STAGE_WRITE_FAIL reason=target_not_block_device"; exit 1; }
    local rootsrc; rootsrc=$($SSH 'findmnt -n -o SOURCE /')
    [ "$rootsrc" != "$($SSH "readlink -f $AUTOSD_ROOT")" ] || { echo "STAGE_WRITE_FAIL reason=board_running_from_target"; exit 1; }
    $SSH "dd of=$AUTOSD_ROOT bs=4M conv=fsync status=none" < "$img"
    # Read back exactly the image's byte length. A plain count of size/4194304
    # truncates every image that is not a whole multiple of 4 MiB and then
    # always reports readback_mismatch, so read the whole 4 MiB blocks and, if
    # there is a remainder, one more aligned block trimmed to the tail length
    # (the extra block keeps iflag=direct's alignment requirement satisfied).
    local want got bytes full rem readcmd
    want=$(md5sum "$img" | cut -c1-32)
    bytes=$(stat -c %s "$img"); full=$(( bytes / 4194304 )); rem=$(( bytes % 4194304 ))
    readcmd="dd if=$AUTOSD_ROOT bs=4M count=$full iflag=direct status=none"
    [ "$rem" -eq 0 ] || readcmd="{ $readcmd; dd if=$AUTOSD_ROOT bs=4M skip=$full count=1 iflag=direct status=none 2>/dev/null | head -c $rem; }"
    got=$($SSH "$readcmd | md5sum" | cut -c1-32)
    [ "$want" = "$got" ] || { echo "STAGE_WRITE_FAIL reason=readback_mismatch want=$want got=$got"; exit 1; }
    echo "STAGE_WRITE_PASS md5=$got"
}

partition_lun2() {
    # The LUN2 glob must resolve to exactly ONE device before anything
    # destructive runs: unquoted, a multi-match word-splits into sgdisk -Z and
    # would zap every match. Resolve it here, then use the concrete path below
    # so the glob never reaches the destructive command at all.
    local matches n dev
    matches=$($SSH "ls -1d $LUN2 2>/dev/null" || true)
    n=$(printf '%s\n' "$matches" | grep -c . || true)
    case "$n" in
        1) ;;
        0) echo "STAGE_LUN2_FAIL reason=no_lun2_device glob=$LUN2"; exit 1 ;;
        *) echo "STAGE_LUN2_FAIL reason=ambiguous_lun2_device count=$n"; exit 1 ;;
    esac
    dev=$($SSH "readlink -f $matches")
    $SSH "test -b $dev" || { echo "STAGE_LUN2_FAIL reason=lun2_not_block_device dev=$dev"; exit 1; }
    say "PLAN: GPT on $dev (via $matches) : yocto-boot 1G / yocto-root 8G / npu-work rest, PARTUUIDs ...5e11/12/13 -- DESTROYS current contents"
    $SSH "sgdisk -p $dev"
    need_yes
    $SSH "sgdisk -Z $dev && \
      sgdisk -n1:0:+1G  -c1:yocto-boot -u1:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e11 \
             -n2:0:+8G  -c2:yocto-root -u2:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e12 \
             -n3:0:0    -c3:npu-work   -u3:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e13 $dev && blockdev --rereadpt $dev && sleep 2 && \
      mkfs.ext4 -q -F -L yocto-boot /dev/disk/by-partlabel/yocto-boot && \
      mkfs.ext4 -q -F -L yocto-root /dev/disk/by-partlabel/yocto-root && \
      mkfs.ext4 -q -F -L npu-work   /dev/disk/by-partlabel/npu-work && sgdisk -p $dev"
    echo "STAGE_LUN2_PASS"
}

write_boot() {
    local d="$WORK/boot" f keep=""
    rm -rf "$d"; mkdir -p "$d"
    cp "$inputs/Image-autosd" "$inputs/r8a78000-ironhide-uio-autosd.dtb" "$inputs/r8a78000-ironhide-npu.dtb" "$d/"
    bash "$X5H/uboot/render-env.sh" "$vars" > "$d/x5h-env.txt"
    printf 'role=npu\n' > "$d/x5h-role.txt"
    for f in "$d"/*; do
        [ -s "$f" ] || { echo "STAGE_BOOT_FAIL reason=empty_staged_file file=${f##*/}"; exit 1; }
        keep="$keep ${f##*/}"
    done
    keep=${keep# }
    say "PLAN: replace the contents of $BOOT on $board ($BOARD_IP) with these files, staged in $d:"
    (cd "$d" && ls -l)
    say "PLAN: they are extracted over the partition FIRST (cpio -idmu overwrites in place) and verified"
    say "PLAN: present; only then is every OTHER regular file on $BOOT deleted -- Image-yocto and stale"
    say "PLAN: env files included. The partition is therefore never empty at any instant."
    need_yes
    # One remote script, not an && chain: extract, verify, then delete the
    # stale files, and umount on every path out.
    local remote out rc=0
    remote=$(cat <<REMOTE
set -u
keep="$keep"
m=\$(mktemp -d) || { echo "STAGE_BOOT_FAIL reason=remote_mktemp_failed"; exit 1; }
mount $BOOT "\$m" || { echo "STAGE_BOOT_FAIL reason=boot_mount_failed"; rmdir "\$m" 2>/dev/null; exit 1; }
rc=0
# cpio runs in a subshell so this shell never holds \$m as its cwd, which would
# make the umount below fail.
(cd "\$m" && cpio -idmu) || { echo "STAGE_BOOT_FAIL reason=cpio_extract_failed"; rc=1; }
if [ \$rc -eq 0 ]; then
    for f in \$keep; do
        [ -s "\$m/\$f" ] || { echo "STAGE_BOOT_FAIL reason=missing_after_extract file=\$f"; rc=1; }
    done
fi
if [ \$rc -eq 0 ]; then
    for p in "\$m"/*; do
        [ -f "\$p" ] || continue
        b=\${p##*/}
        case " \$keep " in *" \$b "*) continue ;; esac
        rm -f "\$p" || { echo "STAGE_BOOT_FAIL reason=stale_removal_failed file=\$b"; rc=1; }
    done
fi
sync
ls -l "\$m"
umount "\$m" || { echo "STAGE_BOOT_FAIL reason=boot_umount_failed"; rc=1; }
rmdir "\$m" 2>/dev/null || true
exit \$rc
REMOTE
)
    out=$($SSH "$remote" < <(cd "$d" && find . -type f | cpio -o -H newc 2>/dev/null) 2>&1) || rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -ne 0 ]; then
        printf '%s\n' "$out" | grep -q '^STAGE_BOOT_FAIL ' || echo "STAGE_BOOT_FAIL reason=remote_update_failed rc=$rc"
        exit 1
    fi
    echo "STAGE_BOOT_PASS role=npu"
}

stage_payload() {
    $SSH 'mkdir -p /var/opt/npu && mountpoint -q /var/opt/npu || mount /dev/disk/by-partlabel/npu-work /var/opt/npu'
    rsync -a --delete --info=progress2 -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" "$inputs/npu/" "root@$BOARD_IP:/var/opt/npu/"
    $SSH 'ls /var/opt/npu; test -f /var/opt/npu/cmemdrv.ko && modinfo -F vermagic /var/opt/npu/cmemdrv.ko'
    echo "STAGE_PAYLOAD_PASS"
}

stage_stack() {
    X5H_BOARD="root@$BOARD_IP" sh "$HERE/stage-container-images.sh" --stage
    X5H_BOARD="root@$BOARD_IP" sh "$HERE/stage-scenario-map.sh" --stage
}

print_uboot() {
    cat <<EOF
# On the U-Boot console of $board (deliver by typing these short lines; the env file itself is imported, never typed):
setenv bootcmd_yocto_nfs "\${bootcmd_yocto}"
ufs init
scsi rescan
ext4load scsi 2:1 \${loadaddr} x5h-role.txt     # if this fails try scsi 1:1 and use that LU below
ext4load scsi 2:1 \${loadaddr} x5h-env.txt
env import -t \${loadaddr} \${filesize}
saveenv
printenv bootcmd role
boot
EOF
}

case "$cmd" in
    check-inputs) check_inputs ;;
    backup-keys) backup_keys ;;
    prepare-root) prepare_root ;;
    write-root) write_root ;;
    partition-lun2) partition_lun2 ;;
    write-boot) write_boot ;;
    stage-payload) stage_payload ;;
    stage-stack) stage_stack ;;
    print-uboot) print_uboot ;;
    *) echo "unknown subcommand $cmd" >&2; exit 2 ;;
esac
