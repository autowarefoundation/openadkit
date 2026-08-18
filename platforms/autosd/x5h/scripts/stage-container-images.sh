#!/bin/sh
# Stage the Open AD Kit arm64 component images from the companion host onto
# the board's btrfs container store.
#
# Why staged rather than pulled on the board: multi-gigabyte pulls from the
# board route through the companion's tailnet, so a network flake becomes a
# failed board session. Staging keeps the transfer on the bench LAN
# (192.168.0.0/24) and makes the bytes reproducible, because every image is
# addressed by digest rather than by tag.
#
# Modes:
#   --audit    inspect sizes only; no transfer. Gates on free space.
#   --stage    audit, then copy to OCI layouts and load onto the board.
# Terminal marker, exactly one per run:
#   X5H_IMAGE_AUDIT_{PASS,FAIL}   /   X5H_IMAGE_STAGE_{PASS,FAIL}
set -u

BOARD="${X5H_BOARD:-root@192.168.0.20}"
LIST="${X5H_IMAGE_LIST:-$(dirname "$0")/../components/images.txt}"
WORK="${X5H_STAGE_DIR:-/var/tmp/x5h-oci}"
# Free space on the board's container store, in bytes. The store is the
# 32 GB UFS LUN mounted at /var/lib/containers (board-podman-smoke.sh
# btrfs arm). Measured, never assumed.
MODE="${1:---audit}"

fail() { echo "$2 reason=$1"; exit 1; }

[ -r "$LIST" ] || fail "no_image_list" "X5H_IMAGE_AUDIT_FAIL"

total=0
while read -r name ref; do
    case "$name" in ''|\#*) continue ;; esac
    # Sum the compressed layer sizes of the arm64 manifest. This
    # under-reports the on-disk footprint (layers are stored uncompressed),
    # so the gate below applies a 2.5x expansion factor rather than
    # comparing raw bytes to free space and quietly overfilling the LUN.
    sz=$(skopeo inspect --override-arch arm64 --override-os linux \
            --format '{{range .LayersData}}{{.Size}}
{{end}}' "docker://$ref" 2>/dev/null \
         | awk '{s+=$1} END {print s+0}')
    [ "$sz" -gt 0 ] 2>/dev/null || fail "inspect_failed:$name" "X5H_IMAGE_AUDIT_FAIL"
    echo "image=$name compressed_bytes=$sz"
    total=$((total + sz))
done < "$LIST"

need=$(( total * 5 / 2 ))
free=$(ssh -o BatchMode=yes "$BOARD" \
        "df -B1 --output=avail /var/lib/containers | tail -1" 2>/dev/null | tr -d ' ')
case "$free" in ''|*[!0-9]*) fail "board_unreachable_or_no_store" "X5H_IMAGE_AUDIT_FAIL" ;; esac

echo "total_compressed_bytes=$total estimated_on_disk_bytes=$need free_bytes=$free"
[ "$need" -lt "$free" ] || fail "insufficient_space" "X5H_IMAGE_AUDIT_FAIL"
echo "X5H_IMAGE_AUDIT_PASS total_bytes=$need free_bytes=$free"

[ "$MODE" = "--stage" ] || exit 0

mkdir -p "$WORK" || fail "workdir" "X5H_IMAGE_STAGE_FAIL"
while read -r name ref; do
    case "$name" in ''|\#*) continue ;; esac
    skopeo copy --override-arch arm64 --override-os linux \
        "docker://$ref" "oci-archive:$WORK/$name.tar:localhost/$name:latest" \
        || fail "copy:$name" "X5H_IMAGE_STAGE_FAIL"
    # Stream rather than scp-then-load: the board's /var/tmp is not sized
    # for a second full copy of every image.
    ssh -o BatchMode=yes "$BOARD" "podman load" < "$WORK/$name.tar" \
        || fail "load:$name" "X5H_IMAGE_STAGE_FAIL"
    echo "staged=$name"
done < "$LIST"

ssh -o BatchMode=yes "$BOARD" "podman images --format '{{.Repository}}:{{.Tag}}'" \
    || fail "verify" "X5H_IMAGE_STAGE_FAIL"
echo "X5H_IMAGE_STAGE_PASS"
