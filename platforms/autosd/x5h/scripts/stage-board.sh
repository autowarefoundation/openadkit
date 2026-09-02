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
#   stage-payload --yes  rsync inputs/npu -> npu-work (MIRROR: --delete)
#   stage-stack      container images + scenario map (existing scripts)
#   print-uboot      the exact console lines to import the environment
# Destructive subcommands print their plan and stop unless --yes is given.
#
# MARKER DISCIPLINE. Every subcommand terminates with EXACTLY ONE of:
#   <PREFIX>_PASS …            the operation completed
#   <PREFIX>_FAIL reason=<slug> it did not
#   PLAN ONLY: …               a gated subcommand run without --yes
# `set -euo pipefail` plus any unchecked command would otherwise stop the run
# with no marker at all. That is ungradeable by construction, and at a console
# it is indistinguishable from a hang or a dropped link -- the worst possible
# input to "what state is the board in, and may I touch it again?". The EXIT
# trap below is the backstop that keeps that true even for a command nobody
# remembered to check. print-uboot is informational and emits no marker.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
X5H="$HERE/.."

MARKER_PREFIX=STAGE
MARKER_DONE=
CLEANUP_MNT=
mark() { if [ -z "$MARKER_DONE" ]; then MARKER_DONE=1; echo "$*"; fi; }
die() { mark "$*"; exit 1; }
on_exit() {
    local rc=$?
    if [ -n "$CLEANUP_MNT" ]; then
        sudo umount "$CLEANUP_MNT" 2>/dev/null || true
        rmdir "$CLEANUP_MNT" 2>/dev/null || true
        CLEANUP_MNT=
    fi
    if [ -z "$MARKER_DONE" ] && [ "$rc" -ne 0 ]; then
        echo "${MARKER_PREFIX}_FAIL reason=unexpected_exit rc=$rc"
    fi
}
trap on_exit EXIT

board=${1:-}; inputs=${2:-}; cmd=${3:-}; yes=${4:-}
[ -n "$board" ] && [ -n "$inputs" ] && [ -n "$cmd" ] \
    || die "STAGE_FAIL reason=usage usage=stage-board.sh_<board>_<inputs-dir>_<subcommand>_[--yes]"
vars="$X5H/boards/$board.vars"
[ -r "$vars" ] || die "STAGE_FAIL reason=no_vars_file file=$vars"
BOARD_IP= BOARD_HOSTNAME= HAS_YOCTO=
# shellcheck disable=SC1090
. "$vars"
[ -n "$BOARD_IP" ] && [ -n "$BOARD_HOSTNAME" ] && [ -n "$HAS_YOCTO" ] \
    || die "STAGE_FAIL reason=incomplete_vars file=$vars"
WORK=${X5H_STAGE_WORK:-/var/tmp/x5h-stage/$board}
mkdir -p "$WORK" || die "STAGE_FAIL reason=work_dir_unwritable dir=$WORK"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@$BOARD_IP"
CR52_ELF=actuation_x5h.elf
AUTOSD_ROOT=/dev/disk/by-partlabel/x5h-root
BOOT=/dev/disk/by-partlabel/x5h-boot
LUN2='/dev/disk/by-path/*ufs-scsi-0:0:0:2'
say() { echo "== $*"; }
# ssh reports its own transport errors as 255; anything else is the remote
# command's own status. The operator's next move differs -- retry the link, or
# go and look at the board -- so the two never share a reason slug.
need_yes() { [ "$yes" = --yes ] || { mark "PLAN ONLY: re-run with --yes to execute the above on $board ($BOARD_IP)"; exit 0; }; }

check_inputs() {
    local missing=0 f cfg ftype needle
    for f in Image-autosd extract-ikconfig r8a78000-ironhide-uio-autosd.dtb r8a78000-ironhide-npu.dtb \
             x5h-rootfs.ext4 rpmsg-eth "$CR52_ELF" npu/ort-rootfs npu/cmemdrv.ko npu/renesas_ep_eval_latency.py; do
        [ -e "$inputs/$f" ] || { echo "MISSING $inputs/$f"; missing=1; }
    done
    [ $missing -eq 0 ] || die "STAGE_CHECK_FAIL reason=missing_inputs"
    chmod +x "$inputs/extract-ikconfig" || die "STAGE_CHECK_FAIL reason=extract_ikconfig_not_executable"
    # Capture, then match on the string. The old `extract-ikconfig … | grep -qxF`
    # let grep exit at the match, the producer take a SIGPIPE, and pipefail turn
    # a PRESENT firmware line into kernel_without_firmware -- a false FAIL on
    # the very invariant this gate exists to protect. A kernel config is much
    # larger than the 64 KB pipe buffer, so that was not theoretical.
    cfg=$("$inputs/extract-ikconfig" "$inputs/Image-autosd") || die "STAGE_CHECK_FAIL reason=extract_ikconfig_failed"
    needle=$'\n''CONFIG_EXTRA_FIRMWARE="rcar_gen5_mp_phy.bin"'$'\n'
    case $'\n'"$cfg"$'\n' in
        *"$needle"*) ;;
        *) die "STAGE_CHECK_FAIL reason=kernel_without_firmware" ;;
    esac
    ftype=$(file "$inputs/rpmsg-eth") || die "STAGE_CHECK_FAIL reason=file_probe_failed"
    case "$ftype" in
        *aarch64*"statically linked"*) ;;
        *) die "STAGE_CHECK_FAIL reason=rpmsg_eth_not_static_aarch64" ;;
    esac
    mark "STAGE_CHECK_PASS board=$board"
}

backup_keys() {
    local rc=0
    say "saving ssh keys from the live board $BOARD_IP"
    # First board-touching subcommand of a session, so the one most likely to
    # meet a dead or unreachable board. A marker-less failure here would set
    # the tone for the whole session.
    $SSH 'cd / && find etc/ssh/authorized_keys.d/root etc/ssh/ssh_host_* -type f 2>/dev/null | cpio -o -H newc 2>/dev/null' > "$WORK/keys.cpio" || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_KEYS_FAIL reason=board_unreachable rc=255"
    [ "$rc" -eq 0 ] || die "STAGE_KEYS_FAIL reason=remote_key_archive_failed rc=$rc"
    [ -s "$WORK/keys.cpio" ] || die "STAGE_KEYS_FAIL reason=empty_archive"
    cpio -it < "$WORK/keys.cpio" || die "STAGE_KEYS_FAIL reason=unreadable_archive"
    mark "STAGE_KEYS_PASS file=$WORK/keys.cpio"
}

prepare_root() {
    # These steps run on the companion, not a board, so `set -e` alone would at
    # least stop them honestly. They still get markers: a run that dies after
    # the cp but before the installs leaves a NON-EMPTY image, and write_root's
    # only precondition is `[ -s "$img" ]` -- so a half-populated root would
    # sail through and get dd'd onto the board. The marker is what stops an
    # operator reading a silent stop as a transient glitch and carrying on.
    local img="$WORK/$board-root.ext4" mnt
    [ -s "$WORK/keys.cpio" ] || die "STAGE_ROOT_FAIL reason=run_backup_keys_first"
    cp --reflink=auto "$inputs/x5h-rootfs.ext4" "$img" || die "STAGE_ROOT_FAIL reason=image_copy_failed"
    mnt=$(mktemp -d) || die "STAGE_ROOT_FAIL reason=mktemp_failed"
    sudo mount -o loop "$img" "$mnt" || { rmdir "$mnt" 2>/dev/null || true; die "STAGE_ROOT_FAIL reason=loop_mount_failed"; }
    CLEANUP_MNT="$mnt"   # on_exit unmounts this on every path out
    printf '%s\n' "$BOARD_HOSTNAME" | sudo tee "$mnt/etc/hostname" >/dev/null \
        || die "STAGE_ROOT_FAIL reason=hostname_write_failed"
    printf 'BOARD_HOSTNAME=%s\nHAS_YOCTO=%s\n' "$BOARD_HOSTNAME" "$HAS_YOCTO" | sudo tee "$mnt/etc/x5h/board.conf" >/dev/null \
        || die "STAGE_ROOT_FAIL reason=board_conf_write_failed"
    (cd "$mnt" && sudo cpio -idmu < "$WORK/keys.cpio") || die "STAGE_ROOT_FAIL reason=key_restore_failed"
    sudo install -D -m 0755 "$inputs/rpmsg-eth" "$mnt/var/usrlocal/bin/rpmsg-eth" \
        || die "STAGE_ROOT_FAIL reason=rpmsg_eth_install_failed"   # /usr/local -> ../var/usrlocal on this rootfs
    sudo install -D -m 0644 "$inputs/$CR52_ELF" "$mnt/lib/firmware/$CR52_ELF" \
        || die "STAGE_ROOT_FAIL reason=cr52_elf_install_failed"
    printf 'CR52_FIRMWARE=%s\n' "$CR52_ELF" | sudo tee "$mnt/etc/default/cr52-remoteproc" >/dev/null \
        || die "STAGE_ROOT_FAIL reason=cr52_default_write_failed"
    sudo test -f "$mnt/etc/systemd/system/multi-user.target.wants/sshd.service" || die "STAGE_ROOT_FAIL reason=sshd_not_enabled_in_image"
    sudo test -f "$mnt/etc/systemd/system/multi-user.target.wants/x5h-npu.service" || die "STAGE_ROOT_FAIL reason=npu_unit_not_enabled_in_image"
    sudo umount "$mnt" || die "STAGE_ROOT_FAIL reason=umount_failed"
    CLEANUP_MNT=
    rmdir "$mnt" 2>/dev/null || true
    mark "STAGE_ROOT_PASS image=$img"
}

write_root() {
    local img="$WORK/$board-root.ext4" rc=0
    [ -s "$img" ] || die "STAGE_WRITE_FAIL reason=run_prepare_root_first"
    say "PLAN: dd $img -> $BOARD_IP:$AUTOSD_ROOT (the board must not be running from x5h-root)"
    $SSH "findmnt -n -o SOURCE / ; readlink -f $AUTOSD_ROOT" || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_WRITE_FAIL reason=board_unreachable rc=255"
    [ "$rc" -eq 0 ] || die "STAGE_WRITE_FAIL reason=plan_probe_failed rc=$rc"
    need_yes
    # The partlabel symlink must resolve to a real block device before dd runs.
    # readlink -f prints the path even when nothing is there, so without this
    # the running-from-target test below passes, dd creates a regular FILE at
    # that path, and the read-back reads back that very file: a false PASS that
    # wrote nothing to the disk.
    rc=0; $SSH "test -b $AUTOSD_ROOT" || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_WRITE_FAIL reason=board_unreachable rc=255"
    [ "$rc" -eq 0 ] || die "STAGE_WRITE_FAIL reason=target_not_block_device"
    local rootsrc target
    rootsrc=$($SSH 'findmnt -n -o SOURCE /') || die "STAGE_WRITE_FAIL reason=rootsrc_probe_failed rc=$?"
    target=$($SSH "readlink -f $AUTOSD_ROOT") || die "STAGE_WRITE_FAIL reason=target_probe_failed rc=$?"
    [ "$rootsrc" != "$target" ] || die "STAGE_WRITE_FAIL reason=board_running_from_target"
    # A failed dd leaves the board's root partition in an unknown state, so the
    # operator must be told which kind of failure it was: a lost link says retry
    # the transport, a dd error says go and look at the board before writing
    # anything else to it.
    rc=0; $SSH "dd of=$AUTOSD_ROOT bs=4M conv=fsync status=none" < "$img" || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_WRITE_FAIL reason=dd_transport_lost rc=255 target_state=unknown_partial_write"
    [ "$rc" -eq 0 ] || die "STAGE_WRITE_FAIL reason=dd_failed rc=$rc target_state=unknown_partial_write"
    # Read back exactly the image's byte length. A plain count of size/4194304
    # truncates every image that is not a whole multiple of 4 MiB and then
    # always reports readback_mismatch, so read the whole 4 MiB blocks and, if
    # there is a remainder, one more aligned block trimmed to the tail length
    # (the extra block keeps iflag=direct's alignment requirement satisfied).
    local want got bytes full rem readcmd raw
    raw=$(md5sum "$img") || die "STAGE_WRITE_FAIL reason=local_md5_failed"
    want=${raw:0:32}
    bytes=$(stat -c %s "$img") || die "STAGE_WRITE_FAIL reason=stat_failed"
    full=$(( bytes / 4194304 )); rem=$(( bytes % 4194304 ))
    readcmd="dd if=$AUTOSD_ROOT bs=4M count=$full iflag=direct status=none"
    [ "$rem" -eq 0 ] || readcmd="{ $readcmd; dd if=$AUTOSD_ROOT bs=4M skip=$full count=1 iflag=direct status=none 2>/dev/null | head -c $rem; }"
    raw=$($SSH "$readcmd | md5sum") || die "STAGE_WRITE_FAIL reason=readback_failed rc=$? target_state=written_unverified"
    got=${raw:0:32}
    [ "$want" = "$got" ] || die "STAGE_WRITE_FAIL reason=readback_mismatch want=$want got=$got"
    mark "STAGE_WRITE_PASS md5=$got"
}

partition_lun2() {
    # The LUN2 glob must resolve to exactly ONE device before anything
    # destructive runs: unquoted, a multi-match word-splits into sgdisk -Z and
    # would zap every match. Resolve it here, then use the concrete path below
    # so the glob never reaches the destructive command at all.
    local matches dev line rc=0
    local -a mlist=()
    matches=$($SSH "ls -1d $LUN2 2>/dev/null") || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_LUN2_FAIL reason=board_unreachable rc=255"
    while IFS= read -r line; do
        if [ -n "$line" ]; then mlist+=("$line"); fi
    done <<<"$matches"
    case "${#mlist[@]}" in
        1) ;;
        0) die "STAGE_LUN2_FAIL reason=no_lun2_device glob=$LUN2" ;;
        *) die "STAGE_LUN2_FAIL reason=ambiguous_lun2_device count=${#mlist[@]}" ;;
    esac
    dev=$($SSH "readlink -f ${mlist[0]}") || die "STAGE_LUN2_FAIL reason=lun2_readlink_failed rc=$?"
    rc=0; $SSH "test -b $dev" || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_LUN2_FAIL reason=board_unreachable rc=255"
    [ "$rc" -eq 0 ] || die "STAGE_LUN2_FAIL reason=lun2_not_block_device dev=$dev"
    say "PLAN: GPT on $dev (via ${mlist[0]}) : yocto-boot 1G / yocto-root 8G / npu-work rest, PARTUUIDs ...5e11/12/13 -- DESTROYS current contents"
    $SSH "sgdisk -p $dev" || die "STAGE_LUN2_FAIL reason=sgdisk_probe_failed rc=$?"
    need_yes
    # A compound remote command, so a PARTIAL failure is the likely one, and
    # "GPT zapped but no filesystems" needs a different recovery from "nothing
    # happened". Each step announces itself, and the marker reports the last
    # step that completed.
    local remote out stage
    remote="set -u
sgdisk -Z $dev && echo LUN2_STAGE=zapped || exit 11
sgdisk -n1:0:+1G  -c1:yocto-boot -u1:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e11 \
       -n2:0:+8G  -c2:yocto-root -u2:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e12 \
       -n3:0:0    -c3:npu-work   -u3:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e13 $dev && echo LUN2_STAGE=partitioned || exit 12
blockdev --rereadpt $dev && echo LUN2_STAGE=rereadpt || exit 13
sleep 2
mkfs.ext4 -q -F -L yocto-boot /dev/disk/by-partlabel/yocto-boot && echo LUN2_STAGE=mkfs_yocto_boot || exit 14
mkfs.ext4 -q -F -L yocto-root /dev/disk/by-partlabel/yocto-root && echo LUN2_STAGE=mkfs_yocto_root || exit 15
mkfs.ext4 -q -F -L npu-work   /dev/disk/by-partlabel/npu-work && echo LUN2_STAGE=mkfs_npu_work || exit 16
sgdisk -p $dev && echo LUN2_STAGE=done || exit 17"
    rc=0; out=$($SSH "$remote" 2>&1) || rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -ne 0 ]; then
        case "$out" in
            *LUN2_STAGE=*) stage=${out##*LUN2_STAGE=}; stage=${stage%%$'\n'*} ;;
            *) stage=nothing ;;
        esac
        [ "$rc" -ne 255 ] || die "STAGE_LUN2_FAIL reason=transport_lost rc=255 completed=$stage"
        die "STAGE_LUN2_FAIL reason=partitioning_failed rc=$rc completed=$stage"
    fi
    mark "STAGE_LUN2_PASS"
}

write_boot() {
    local d="$WORK/boot" f keep=""
    rm -rf "$d" || die "STAGE_BOOT_FAIL reason=work_dir_cleanup_failed dir=$d"
    mkdir -p "$d" || die "STAGE_BOOT_FAIL reason=work_dir_unwritable dir=$d"
    cp "$inputs/Image-autosd" "$inputs/r8a78000-ironhide-uio-autosd.dtb" "$inputs/r8a78000-ironhide-npu.dtb" "$d/" \
        || die "STAGE_BOOT_FAIL reason=input_copy_failed"
    bash "$X5H/uboot/render-env.sh" "$vars" > "$d/x5h-env.txt" || die "STAGE_BOOT_FAIL reason=render_env_failed"
    printf 'role=npu\n' > "$d/x5h-role.txt" || die "STAGE_BOOT_FAIL reason=role_file_write_failed"
    for f in "$d"/*; do
        [ -s "$f" ] || die "STAGE_BOOT_FAIL reason=empty_staged_file file=${f##*/}"
        keep="$keep ${f##*/}"
    done
    keep=${keep# }
    say "PLAN: replace the contents of $BOOT on $board ($BOARD_IP) with these files, staged in $d:"
    (cd "$d" && ls -l) || die "STAGE_BOOT_FAIL reason=staging_listing_failed"
    say "PLAN: they are extracted over the partition FIRST (cpio -idmu overwrites in place) and verified"
    say "PLAN: present; only then is every OTHER regular file on $BOOT deleted -- Image-yocto and stale"
    say "PLAN: env files included. The partition is therefore never empty at any instant."
    need_yes
    # One remote script, not an && chain: extract, verify, then delete the
    # stale files, and umount on every path out. It accumulates a single reason
    # and prints ONE marker at the end -- the loops below can each detect more
    # than one problem, and "exactly one marker" has to hold remotely too.
    local remote out rc=0
    remote=$(cat <<REMOTE
set -u
keep="$keep"
freason=; fdetail=
m=\$(mktemp -d) || { echo "STAGE_BOOT_FAIL reason=remote_mktemp_failed"; exit 1; }
mount $BOOT "\$m" || { echo "STAGE_BOOT_FAIL reason=boot_mount_failed"; rmdir "\$m" 2>/dev/null; exit 1; }
# cpio runs in a subshell so this shell never holds \$m as its cwd, which would
# make the umount below fail.
(cd "\$m" && cpio -idmu) || freason=cpio_extract_failed
if [ -z "\$freason" ]; then
    for f in \$keep; do
        if [ ! -s "\$m/\$f" ]; then freason=missing_after_extract; fdetail=" file=\$f"; break; fi
    done
fi
if [ -z "\$freason" ]; then
    for p in "\$m"/*; do
        [ -f "\$p" ] || continue
        b=\${p##*/}
        case " \$keep " in *" \$b "*) continue ;; esac
        if rm -f "\$p"; then :; else freason=stale_removal_failed; fdetail=" file=\$b"; break; fi
    done
fi
sync
ls -l "\$m"
if umount "\$m"; then :; elif [ -z "\$freason" ]; then freason=boot_umount_failed; fi
rmdir "\$m" 2>/dev/null || true
if [ -n "\$freason" ]; then echo "STAGE_BOOT_FAIL reason=\$freason\$fdetail"; exit 1; fi
exit 0
REMOTE
)
    out=$($SSH "$remote" < <(cd "$d" && find . -type f | cpio -o -H newc 2>/dev/null) 2>&1) || rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -ne 0 ]; then
        # `case`, not `grep -q`: grep -q exits at the match, printf can then
        # take a SIGPIPE, and pipefail would report the pipeline as failed --
        # emitting a redundant SECOND marker after the remote's own.
        case "$out" in
            *"STAGE_BOOT_FAIL "*) MARKER_DONE=1 ;;   # the remote emitted the one marker
            *) if [ "$rc" -eq 255 ]; then
                   mark "STAGE_BOOT_FAIL reason=transport_lost rc=255 boot_state=unknown"
               else
                   mark "STAGE_BOOT_FAIL reason=remote_update_failed rc=$rc"
               fi ;;
        esac
        exit 1
    fi
    mark "STAGE_BOOT_PASS role=npu"
}

stage_payload() {
    # rsync --delete MIRRORS: anything under /var/opt/npu on the board that is
    # absent from $inputs/npu/ is removed. That directory holds vendor material
    # and NPU calibration artifacts, several of which exist in exactly one
    # place, and the documented workflow (Task 9) fills $inputs/npu/ by copying
    # FROM that same board -- so a narrowed inbound copy followed by this
    # command deletes the only remaining full set. Plan, then gate, then act.
    local rsh="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    local dry ntotal ndel nsend rc=0
    [ -d "$inputs/npu" ] || die "STAGE_PAYLOAD_FAIL reason=no_npu_inputs dir=$inputs/npu"
    [ -n "$(ls -A "$inputs/npu")" ] || die "STAGE_PAYLOAD_FAIL reason=empty_npu_inputs dir=$inputs/npu"
    $SSH 'mkdir -p /var/opt/npu && { mountpoint -q /var/opt/npu || mount /dev/disk/by-partlabel/npu-work /var/opt/npu; }' \
        || die "STAGE_PAYLOAD_FAIL reason=npu_work_mount_failed rc=$?"
    say "PLAN: mirror $inputs/npu/ -> $board ($BOARD_IP):/var/opt/npu/ with rsync --delete"
    say "PLAN: --delete means EVERY path under /var/opt/npu ON THE BOARD that is absent from"
    say "PLAN: $inputs/npu/ is REMOVED. Confirm the inputs directory is the FULL set, not a"
    say "PLAN: narrowed copy, before approving."
    dry=$(rsync -a --delete --dry-run --itemize-changes -e "$rsh" "$inputs/npu/" "root@$BOARD_IP:/var/opt/npu/") \
        || die "STAGE_PAYLOAD_FAIL reason=dry_run_failed rc=$?"
    ntotal=$(printf '%s\n' "$dry" | grep -c . || true)
    ndel=$(printf '%s\n' "$dry" | grep -c '^\*deleting' || true)
    nsend=$(( ntotal - ndel ))
    say "PLAN: dry run: $ndel path(s) would be DELETED from the board, $nsend would be sent."
    if [ "$ndel" -gt 0 ]; then
        printf '%s\n' "$dry" | grep '^\*deleting' | head -50 || true   # head closing the pipe must not trip pipefail
        [ "$ndel" -le 50 ] || say "PLAN: ... and $(( ndel - 50 )) further deletions not listed above"
    fi
    need_yes
    rsync -a --delete --info=progress2 -e "$rsh" "$inputs/npu/" "root@$BOARD_IP:/var/opt/npu/" \
        || die "STAGE_PAYLOAD_FAIL reason=rsync_failed rc=$?"
    # The listing and the vermagic line are printed either way -- that vermagic
    # is what an operator checks against the running kernel. cmemdrv.ko is the
    # out-of-tree module the whole npu role depends on, so a mirror that lacks
    # it is an explicit failure, not a silent one.
    local verify
    rc=0
    verify=$($SSH 'ls /var/opt/npu; if [ -f /var/opt/npu/cmemdrv.ko ]; then modinfo -F vermagic /var/opt/npu/cmemdrv.ko; else echo "NO_CMEMDRV /var/opt/npu/cmemdrv.ko is not present"; fi' 2>&1) || rc=$?
    printf '%s\n' "$verify"
    [ "$rc" -eq 0 ] || die "STAGE_PAYLOAD_FAIL reason=verify_failed rc=$rc"
    # The sentinel is a fixed token, not the path: a path-shaped sentinel has to
    # be kept in sync with the literal above and silently stops matching if
    # either side is reworded. Matched with `case`, not a `grep -q` pipeline,
    # for the SIGPIPE reason given in write_boot.
    case "$verify" in
        *NO_CMEMDRV*) die "STAGE_PAYLOAD_FAIL reason=no_cmemdrv" ;;
    esac
    mark "STAGE_PAYLOAD_PASS"
}

stage_stack() {
    # The two delegated scripts print their own X5H_IMAGE_* / X5H_MAP_* markers;
    # these are the STAGE_* markers for the subcommand as a whole.
    X5H_BOARD="root@$BOARD_IP" sh "$HERE/stage-container-images.sh" --stage \
        || die "STAGE_STACK_FAIL reason=container_images_failed rc=$?"
    X5H_BOARD="root@$BOARD_IP" sh "$HERE/stage-scenario-map.sh" --stage \
        || die "STAGE_STACK_FAIL reason=scenario_map_failed rc=$?"
    mark "STAGE_STACK_PASS"
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
    check-inputs)   MARKER_PREFIX=STAGE_CHECK;   check_inputs ;;
    backup-keys)    MARKER_PREFIX=STAGE_KEYS;    backup_keys ;;
    prepare-root)   MARKER_PREFIX=STAGE_ROOT;    prepare_root ;;
    write-root)     MARKER_PREFIX=STAGE_WRITE;   write_root ;;
    partition-lun2) MARKER_PREFIX=STAGE_LUN2;    partition_lun2 ;;
    write-boot)     MARKER_PREFIX=STAGE_BOOT;    write_boot ;;
    stage-payload)  MARKER_PREFIX=STAGE_PAYLOAD; stage_payload ;;
    stage-stack)    MARKER_PREFIX=STAGE_STACK;   stage_stack ;;
    print-uboot)    MARKER_DONE=1;               print_uboot ;;
    *) die "STAGE_FAIL reason=unknown_subcommand cmd=$cmd" ;;
esac
