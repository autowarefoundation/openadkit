#!/bin/sh
# Stage the MRM scenario's map onto the board.
#
# WHY THIS EXISTS AS A SCRIPT AT ALL. The map is 39 MB of binary
# (lanelet2_map.osm 3.2 MB, pointcloud_map.pcd 36 MB) that is deliberately
# NOT committed to this repository and is in neither container image. It is
# also not optional: awf-oak-autoware passes map_path:=/autoware/scenario-sim/map
# and the MRM scenario's RoadNetwork hard-codes both files by absolute
# in-container path, so without them Autoware never leaves INITIALIZING.
# Both units carry ConditionPathExists= on the two destination paths below,
# which turns a missing map into a skipped unit with one journal line -- but
# only if what is staged lands at exactly those paths, byte for byte.
#
# WHY A SIBLING OF stage-container-images.sh RATHER THAN A MODE ON IT.
# Same spirit, different job, and three concrete differences:
#   - different tooling: no skopeo, no podman, no digests. A file copy with
#     a checksum, not an image transfer.
#   - different filesystem: the images land on the board's dedicated btrfs
#     container store (/dev/sdc3, ~19 GB); the map lands under /var on the
#     root filesystem. The free-space question is a different question with
#     a different answer, and folding it into one script would mean one
#     audit reporting on two partitions.
#   - different cadence: the map is staged once and survives reboots (the
#     tmpfiles fragment declares its directory `d`, not `D`, precisely so a
#     reboot does not throw away 36 MB). Nobody should have to think about
#     12 GB of images to put it there.
#
# Modes:
#   --audit    check the source files and the board's free space; no transfer.
#   --stage    audit, then copy and verify by md5.
# Terminal marker, exactly one per run:
#   X5H_MAP_AUDIT_{PASS,FAIL}   /   X5H_MAP_STAGE_{PASS,FAIL}
#
# reason= vocabulary:
#   no_source_dir            $SRC is not a readable directory
#   no_source:<file>         a map file is missing or unreadable
#   board_unreachable_or_no_var
#                            df on the board's /var produced no number
#   insufficient_space       the map does not fit
#   mkdir                    the destination directory could not be created
#   copy:<file>              the transfer itself failed
#   checksum:<file>          the bytes on the board do not match the source
#   install:<file>           the verified temporary file could not be renamed
#   verify                   the post-stage listing could not be read
set -u

BOARD="${X5H_BOARD:-root@192.168.0.20}"
# Not in this repository, and not committable: see the header. The default is
# the CES2026 reference tree on the companion host, which is READ-ONLY here --
# this script never writes to it.
SRC="${X5H_MAP_SRC:-/home/test/youtalk/CES2026/fault_injection_v2/map}"
# The mount source of /autoware/scenario-sim/map in awf-oak-autoware and
# awf-oak-simulator, and the directory /etc/tmpfiles.d/awf-oak-x5h.conf
# creates at boot. Verified against the GENERATED [Unit] sections, not the
# source files: both units' ConditionPathExists= name
# /var/lib/awf/scenario-sim/map/{lanelet2_map.osm,pointcloud_map.pcd}.
DEST="${X5H_MAP_DEST:-/var/lib/awf/scenario-sim/map}"
MODE="${1:---audit}"
# Exactly the two files the scenario names. Not `cp -a` of the whole
# directory: the reference tree's map directory is the demo's working
# directory and may accumulate anything; the units assert on these two.
FILES="lanelet2_map.osm pointcloud_map.pcd"

fail() { echo "$2 reason=$1"; exit 1; }

[ -d "$SRC" ] || fail "no_source_dir" "X5H_MAP_AUDIT_FAIL"

need=0
for f in $FILES; do
    [ -r "$SRC/$f" ] || fail "no_source:$f" "X5H_MAP_AUDIT_FAIL"
    sz=$(wc -c < "$SRC/$f")
    echo "map_file=$f bytes=$sz"
    need=$((need + sz))
done

# No expansion factor here, unlike the image staging audit: these are plain
# files copied verbatim, so the bytes on the wire are the bytes on disk. The
# margin is one spare copy of the largest file, so a retry after a failed
# transfer still fits alongside the .part file it left behind.
margin=$(wc -c < "$SRC/pointcloud_map.pcd")
need=$((need + margin))

free=$(ssh -o BatchMode=yes "$BOARD" \
        "df -B1 --output=avail /var | tail -1" 2>/dev/null | tr -d ' ')
case "$free" in ''|*[!0-9]*) fail "board_unreachable_or_no_var" "X5H_MAP_AUDIT_FAIL" ;; esac

echo "needed_bytes=$need free_bytes=$free dest=$DEST"
[ "$need" -lt "$free" ] || fail "insufficient_space" "X5H_MAP_AUDIT_FAIL"
echo "X5H_MAP_AUDIT_PASS needed_bytes=$need free_bytes=$free"

[ "$MODE" = "--stage" ] || exit 0

# mkdir -p even though /etc/tmpfiles.d/awf-oak-x5h.conf declares this
# directory: a board flashed from an image built before that fragment existed
# does not have it, and this script is exactly what such a board runs first.
# On a current image the mkdir is a no-op.
ssh -o BatchMode=yes "$BOARD" "mkdir -p '$DEST'" || fail "mkdir" "X5H_MAP_STAGE_FAIL"

for f in $FILES; do
    # Transfer to <name>.part, verify, then rename. The rename is what makes
    # the units' ConditionPathExists= trustworthy: a half-transferred file
    # never occupies the real name, so the condition is never satisfied by
    # a truncated map. A plain scp would leave one behind on an interrupted
    # copy and the unit would start against it.
    ssh -o BatchMode=yes "$BOARD" "cat > '$DEST/$f.part'" < "$SRC/$f" \
        || fail "copy:$f" "X5H_MAP_STAGE_FAIL"
    want=$(md5sum < "$SRC/$f" | cut -d' ' -f1)
    got=$(ssh -o BatchMode=yes "$BOARD" "md5sum < '$DEST/$f.part'" 2>/dev/null | cut -d' ' -f1)
    # An unreachable board or an unreadable file leaves $got empty, which
    # cannot equal $want, so this one comparison covers both.
    [ "$want" = "$got" ] || fail "checksum:$f" "X5H_MAP_STAGE_FAIL"
    ssh -o BatchMode=yes "$BOARD" "mv '$DEST/$f.part' '$DEST/$f'" \
        || fail "install:$f" "X5H_MAP_STAGE_FAIL"
    echo "staged=$f md5=$want"
done

ssh -o BatchMode=yes "$BOARD" "ls -l '$DEST'; df -B1 --output=avail /var | tail -1" \
    || fail "verify" "X5H_MAP_STAGE_FAIL"
echo "X5H_MAP_STAGE_PASS files=2 dest=$DEST"
