#!/usr/bin/env bash
# Stage one X5H board from the common image plus the inputs the image cannot
# carry. Reads the board's identity ONLY from boards/<board>.vars.
#
#   stage-board.sh <x5h1|x5h2> <inputs-dir> <subcommand> [--yes]
#
# Subcommands (run in this order in a session; each is idempotent, with ONE
# exception -- see partition-lun2 below):
#   check-inputs     every input present; Image-autosd embeds the MP-PHY blob
#   backup-keys      save authorized_keys + ssh host keys from the LIVE board
#   prepare-root     copy x5h-rootfs.ext4 -> work/<board>-root.ext4, inject
#                    hostname, /etc/x5h/board.conf, keys, rpmsg-eth, ELF
#   write-root --yes dd the prepared root to the board's x5h-root (board must
#                    NOT be running from it: yocto role or rescue netboot)
#   partition-lun2 --yes  GPT on the second LUN: yocto-boot/yocto-root/npu-work
#                    NOT IDEMPOTENT IN CONTENT. It is idempotent in shape --
#                    the same map, the same labels, the same pinned PARTUUIDs
#                    every time -- but it runs mkfs.ext4 over all three
#                    partitions, so a re-run on an already-populated board
#                    ERASES the vendor Yocto appliance (yocto-boot +
#                    yocto-root) and the whole NPU payload on npu-work.
#                    stage-payload restores the NPU payload from <inputs>/npu;
#                    NOTHING in this repository restores Yocto, and there is
#                    no in-repo recipe for it -- it has to be reinstalled by
#                    the vendor procedure. On a board with HAS_YOCTO=1 (board
#                    2) treat this as a one-time conversion step, not as a
#                    step to repeat when re-staging.
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
# trap is the backstop for that, and INT/TERM/HUP/QUIT are trapped too: bash
# enters the EXIT trap with $?=0 after an uncaught fatal signal, so EXIT alone
# would let a killed or hung-up run finish silently. print-uboot is
# informational and emits no marker.
#
# NEVER make a control-flow decision by substring-matching text a board can
# influence. Board output is data. Remote scripts signal outcomes through
# dedicated EXIT STATUS values, which the board's own file names, ls output and
# tool messages cannot forge.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
X5H="$HERE/.."

MARKER_PREFIX=STAGE
MARKER_DONE=
CLEANUP_MNT=
mark() { if [ -z "$MARKER_DONE" ]; then MARKER_DONE=1; echo "$*"; fi; }
die() { mark "$*"; exit 1; }
cleanup_mnt() {
    if [ -n "$CLEANUP_MNT" ]; then
        sudo umount "$CLEANUP_MNT" 2>/dev/null || true
        rmdir "$CLEANUP_MNT" 2>/dev/null || true
        CLEANUP_MNT=
    fi
}
on_exit() {
    local rc=$?
    cleanup_mnt
    if [ -z "$MARKER_DONE" ] && [ "$rc" -ne 0 ]; then
        echo "${MARKER_PREFIX}_FAIL reason=unexpected_exit rc=$rc"
    fi
}
on_signal() {
    local sig=$1 num=$2
    trap - EXIT INT TERM HUP QUIT
    cleanup_mnt
    mark "${MARKER_PREFIX}_FAIL reason=interrupted_by_signal signal=$sig"
    exit $(( 128 + num ))
}
trap on_exit EXIT
trap 'on_signal INT 2' INT
trap 'on_signal TERM 15' TERM
trap 'on_signal HUP 1' HUP
trap 'on_signal QUIT 3' QUIT

board=${1:-}; inputs=${2:-}; cmd=${3:-}; yes=${4:-}
[ -n "$board" ] && [ -n "$inputs" ] && [ -n "$cmd" ] \
    || die "STAGE_FAIL reason=usage usage=stage-board.sh_<board>_<inputs-dir>_<subcommand>_[--yes]"
vars="$X5H/boards/$board.vars"
[ -r "$vars" ] || die "STAGE_FAIL reason=no_vars_file file=$vars"
BOARD_IP= BOARD_HOSTNAME= HAS_YOCTO=
# shellcheck disable=SC1090
. "$vars"
# The vars file is arbitrary shell. It is only ever meant to set the three
# BOARD_* keys, but a stray `yes=--yes` in it would disarm need_yes on every
# destructive subcommand, and MARKER_DONE=1 would suppress every marker. The
# command line is the ONLY authority for these, so re-bind them here, after the
# source, where nothing in the file can reach them.
board=${1:-}; inputs=${2:-}; cmd=${3:-}; yes=${4:-}
MARKER_DONE=; MARKER_PREFIX=STAGE; CLEANUP_MNT=
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
# Relay board output behind a gutter. Board text is data: a payload file named
# STAGE_PAYLOAD_PASS would otherwise print as a line starting with a marker and
# be counted as a second marker by any line-anchored grader. (sed reads to EOF,
# so this pipeline has no early-terminating consumer.)
relay() { printf '%s\n' "$1" | sed 's/^/| /'; }
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
    # the tone for the whole session. (find | cpio runs on the board, whose
    # non-interactive shell has no pipefail, and cpio reads to EOF regardless.)
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
    CLEANUP_MNT="$mnt"   # cleanup_mnt unmounts this on every path out, signals included
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
    # always reports readback_mismatch.
    #
    # The tail used to be `dd … | head -c $rem`. head exits at $rem, so dd took
    # a SIGPIPE and the remote pipeline returned 141 -- harmless only because
    # the board's non-interactive shell happens not to set pipefail. If it ever
    # did, a byte-perfect read-back would report STAGE_WRITE_FAIL after a
    # SUCCESSFUL dd and invite a re-write of a healthy root partition. There is
    # now no early-terminating consumer anywhere in the remote command: the tail
    # is one exact-length read via iflag=skip_bytes, and md5sum reads to EOF.
    # Only the tail gives up iflag=direct (its length is not block-aligned); the
    # bulk is still read direct, and the write used conv=fsync so the page cache
    # cannot be stale with respect to the device.
    local want got bytes full rem off readcmd raw
    raw=$(md5sum "$img") || die "STAGE_WRITE_FAIL reason=local_md5_failed"
    want=${raw:0:32}
    bytes=$(stat -c %s "$img") || die "STAGE_WRITE_FAIL reason=stat_failed"
    full=$(( bytes / 4194304 )); rem=$(( bytes % 4194304 )); off=$(( full * 4194304 ))
    readcmd="dd if=$AUTOSD_ROOT bs=4M count=$full iflag=direct status=none"
    [ "$rem" -eq 0 ] || readcmd="{ $readcmd; dd if=$AUTOSD_ROOT bs=$rem count=1 skip=$off iflag=skip_bytes status=none; }"
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
    # happened". Each step has its own EXIT STATUS, and the marker maps that
    # status to the last step that completed. The status is the signal, not the
    # LUN2_STAGE echoes -- those are for the operator to read, and board output
    # must never drive control flow.
    #
    # The three mkfs targets are by-partlabel symlinks resolved by udev after
    # the rereadpt, i.e. exactly the kind of name a stale or foreign partition
    # can also own. Each is asserted to resolve to a partition OF THE DEVICE
    # already resolved above before any of them is formatted.
    local remote out stage
    remote="set -u
sgdisk -Z $dev && echo LUN2_STAGE=zapped || exit 11
sgdisk -n1:0:+1G  -c1:yocto-boot -u1:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e11 \
       -n2:0:+8G  -c2:yocto-root -u2:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e12 \
       -n3:0:0    -c3:npu-work   -u3:7c94f5e2-9e2b-4c31-8f0a-1a2b3c4d5e13 $dev && echo LUN2_STAGE=partitioned || exit 12
blockdev --rereadpt $dev && echo LUN2_STAGE=rereadpt || exit 13
sleep 2
for L in yocto-boot yocto-root npu-work; do
    P=\$(readlink -f /dev/disk/by-partlabel/\$L) || exit 18
    case \"\$P\" in
        \"$dev\"[0-9]*|\"$dev\"p[0-9]*) ;;
        *) echo \"LUN2_BADLABEL \$L -> \$P (not a partition of $dev)\"; exit 18 ;;
    esac
    [ -b \"\$P\" ] || exit 18
done
echo LUN2_STAGE=labels_verified
mkfs.ext4 -q -F -L yocto-boot /dev/disk/by-partlabel/yocto-boot && echo LUN2_STAGE=mkfs_yocto_boot || exit 14
mkfs.ext4 -q -F -L yocto-root /dev/disk/by-partlabel/yocto-root && echo LUN2_STAGE=mkfs_yocto_root || exit 15
mkfs.ext4 -q -F -L npu-work   /dev/disk/by-partlabel/npu-work && echo LUN2_STAGE=mkfs_npu_work || exit 16
sgdisk -p $dev && echo LUN2_STAGE=done || exit 17"
    rc=0; out=$($SSH "$remote" 2>&1) || rc=$?
    relay "$out"
    if [ "$rc" -ne 0 ]; then
        case "$rc" in
            11) stage=nothing ;;
            12) stage=zapped ;;
            13) stage=partitioned ;;
            18) stage=rereadpt_labels_unverified ;;
            14) stage=labels_verified ;;
            15) stage=mkfs_yocto_boot ;;
            16) stage=mkfs_yocto_root ;;
            17) stage=mkfs_npu_work ;;
            *)  stage=unknown ;;
        esac
        [ "$rc" -ne 255 ] || die "STAGE_LUN2_FAIL reason=transport_lost rc=255 completed=indeterminate"
        [ "$rc" -ne 18 ] || die "STAGE_LUN2_FAIL reason=partlabel_not_on_target_device rc=18 completed=$stage"
        die "STAGE_LUN2_FAIL reason=partitioning_failed rc=$rc completed=$stage"
    fi
    mark "STAGE_LUN2_PASS"
}

write_boot() {
    local d="$WORK/boot" ar="$WORK/boot.cpio" arerr="$WORK/boot.cpio.err"
    local f keep="" manifest="" line
    rm -rf "$d" || die "STAGE_BOOT_FAIL reason=work_dir_cleanup_failed dir=$d"
    mkdir -p "$d" || die "STAGE_BOOT_FAIL reason=work_dir_unwritable dir=$d"
    cp "$inputs/Image-autosd" "$inputs/r8a78000-ironhide-uio-autosd.dtb" "$inputs/r8a78000-ironhide-npu.dtb" "$d/" \
        || die "STAGE_BOOT_FAIL reason=input_copy_failed"
    bash "$X5H/uboot/render-env.sh" "$vars" > "$d/x5h-env.txt" || die "STAGE_BOOT_FAIL reason=render_env_failed"
    printf 'role=npu\n' > "$d/x5h-role.txt" || die "STAGE_BOOT_FAIL reason=role_file_write_failed"
    for f in "$d"/*; do
        [ -s "$f" ] || die "STAGE_BOOT_FAIL reason=empty_staged_file file=${f##*/}"
        case "${f##*/}" in *[:[:space:]]*) die "STAGE_BOOT_FAIL reason=unsafe_staged_filename file=${f##*/}" ;; esac
        line=$(md5sum "$f") || die "STAGE_BOOT_FAIL reason=local_md5_failed file=${f##*/}"
        manifest="$manifest ${f##*/}:${line%% *}"
        keep="$keep ${f##*/}"
    done
    manifest=${manifest# }; keep=${keep# }
    # Build the archive to a FILE, not a process substitution. A process
    # substitution's exit status is discarded by construction, so a producer
    # that failed and emitted a well-formed but INCOMPLETE archive used to be
    # invisible here -- and on an already-staged partition (the idempotent
    # re-run this header advertises) the remote presence check then passed
    # against last month's files and reported STAGE_BOOT_PASS having written
    # nothing. Content, not presence, is what the remote verifies now.
    rm -f "$ar" "$arerr"
    ( cd "$d" && find . -type f | cpio -o -H newc ) > "$ar" 2>"$arerr" \
        || { cat "$arerr" >&2; die "STAGE_BOOT_FAIL reason=archive_build_failed"; }
    [ -s "$ar" ] || die "STAGE_BOOT_FAIL reason=archive_empty"
    say "PLAN: replace the contents of $BOOT on $board ($BOARD_IP) with these files, staged in $d:"
    (cd "$d" && ls -l) || die "STAGE_BOOT_FAIL reason=staging_listing_failed"
    say "PLAN: they are extracted over the partition FIRST (cpio -idmu overwrites in place), then each"
    say "PLAN: file's md5 is verified against the staged copy; only once ALL match is every OTHER"
    say "PLAN: regular file on $BOOT deleted -- Image-yocto and stale env files included."
    say "PLAN: The partition is therefore never empty at any instant."
    need_yes
    # The remote signals failure through EXIT STATUS 40 and carries its reason
    # on a per-run NONCE channel. It must not print a bare STAGE_BOOT_FAIL: that
    # line would be indistinguishable from a boot file named STAGE_BOOT_FAIL in
    # the ls output, and guttering board text (relay) would strip it of marker
    # status. The nonce is generated here, per run, so nothing already on the
    # board can occupy that channel.
    local remote out rc=0 nonce line mline=""
    nonce="MK${RANDOM}${RANDOM}${RANDOM}$$"
    remote=$(cat <<REMOTE
set -u
nonce="$nonce"
keep="$keep"
manifest="$manifest"
freason=; fdetail=
m=\$(mktemp -d) || { echo "\$nonce reason=remote_mktemp_failed"; exit 40; }
mount $BOOT "\$m" || { echo "\$nonce reason=boot_mount_failed"; rmdir "\$m" 2>/dev/null; exit 40; }
# cpio runs in a subshell so this shell never holds \$m as its cwd, which would
# make the umount below fail.
(cd "\$m" && cpio -idmu) || { freason=cpio_extract_failed; fdetail=" boot_state=unverified_possibly_partial"; }
if [ -z "\$freason" ]; then
    for e in \$manifest; do
        n=\${e%%:*}; w=\${e#*:}
        g=\$(md5sum "\$m/\$n" 2>/dev/null) || { freason=content_unreadable; fdetail=" file=\$n boot_state=unverified_possibly_partial"; break; }
        g=\${g%% *}
        if [ "\$g" != "\$w" ]; then freason=content_mismatch; fdetail=" file=\$n want=\$w got=\$g boot_state=stale_or_partial"; break; fi
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
if [ -n "\$freason" ]; then echo "\$nonce reason=\$freason\$fdetail"; exit 40; fi
exit 0
REMOTE
)
    out=$($SSH "$remote" < "$ar" 2>&1) || rc=$?
    # Split the nonce channel out of the board's own output, then gutter the rest.
    while IFS= read -r line; do
        case "$line" in
            "$nonce "*) if [ -z "$mline" ]; then mline=${line#"$nonce" }; fi ;;
            *) printf '| %s\n' "$line" ;;
        esac
    done <<<"$out"
    case "$rc" in
        0)   mark "STAGE_BOOT_PASS role=npu" ;;
        40)  mark "STAGE_BOOT_FAIL ${mline:-reason=remote_failed_without_reason}"; exit 1 ;;
        255) mark "STAGE_BOOT_FAIL reason=transport_lost rc=255 boot_state=unknown"; exit 1 ;;
        *)   mark "STAGE_BOOT_FAIL reason=remote_update_failed rc=$rc boot_state=unknown"; exit 1 ;;
    esac
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
    $SSH 'mkdir -p /var/opt/npu && { mountpoint -q /var/opt/npu || mount /dev/disk/by-partlabel/npu-work /var/opt/npu; }' || rc=$?
    [ "$rc" -ne 255 ] || die "STAGE_PAYLOAD_FAIL reason=board_unreachable rc=255"
    [ "$rc" -eq 0 ] || die "STAGE_PAYLOAD_FAIL reason=npu_work_mount_failed rc=$rc"
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
    #
    # Presence is reported by EXIT STATUS 20, not by a sentinel string mixed
    # into ls output: a payload file named NO_CMEMDRV_notes.txt used to produce
    # a false no_cmemdrv while cmemdrv.ko was present.
    local verify
    rc=0
    verify=$($SSH 'ls /var/opt/npu; if [ -f /var/opt/npu/cmemdrv.ko ]; then modinfo -F vermagic /var/opt/npu/cmemdrv.ko; else echo "cmemdrv.ko is not present"; exit 20; fi' 2>&1) || rc=$?
    relay "$verify"
    case "$rc" in
        0)   ;;
        20)  die "STAGE_PAYLOAD_FAIL reason=no_cmemdrv" ;;
        255) die "STAGE_PAYLOAD_FAIL reason=board_unreachable rc=255" ;;
        *)   die "STAGE_PAYLOAD_FAIL reason=verify_failed rc=$rc" ;;
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
