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
MODE="${1:---audit}"

fail() { echo "$2 reason=$1"; exit 1; }

[ -r "$LIST" ] || fail "no_image_list" "X5H_IMAGE_AUDIT_FAIL"

# Layer digest+size pairs across every image accumulate here so the total
# below can dedupe by digest: the five openadkit-* images share an
# identical universe-common layer prefix (and scenario-simulator-v2 shares
# part of it too), and podman's content-addressed store on the board keeps
# each layer digest once, so summing every image's bytes independently
# would multiply-count the shared bulk. Removed on every exit path.
tmp_layers=$(mktemp) || fail "tmpfile" "X5H_IMAGE_AUDIT_FAIL"
trap 'rm -f "$tmp_layers"' EXIT

while read -r name ref; do
    case "$name" in ''|\#*) continue ;; esac
    # Compressed size of each arm64 layer, one "digest size" pair per
    # line. This under-reports the on-disk footprint (layers are stored
    # uncompressed), so the gate below applies an expansion factor rather
    # than comparing raw bytes to free space and quietly overfilling the
    # LUN. See the factor's derivation just above `need=`.
    layers=$(skopeo inspect --override-arch arm64 --override-os linux \
            --format '{{range .LayersData}}{{.Digest}} {{.Size}}
{{end}}' "docker://$ref" 2>/dev/null)
    sz=$(printf '%s\n' "$layers" | awk 'NF==2 {s+=$2} END {print s+0}')
    [ "$sz" -gt 0 ] 2>/dev/null || fail "inspect_failed:$name" "X5H_IMAGE_AUDIT_FAIL"
    echo "image=$name compressed_bytes=$sz"
    printf '%s\n' "$layers" >> "$tmp_layers"
done < "$LIST"

# total_compressed_bytes is deduplicated by layer digest, not the sum of
# each image's (overlapping) total -- do not "simplify" this back to a
# per-image running sum, that is exactly the double-counting bug this
# dedup exists to fix.
total=$(sort -u "$tmp_layers" | awk 'NF==2 {s+=$2} END {print s+0}')

# 3.4x, MEASURED on this hardware -- not an estimate any more, and not a
# round number picked for comfort. The first full `--stage` run of these six
# images onto the board (2026-08-18) gave:
#
#   deduplicated compressed total   3656361314 B  (this script, --audit)
#   /var/lib/containers free before 19378974720 B (df -B1, same run)
#   /var/lib/containers free after   7025639424 B (df -B1, after the stage)
#   -> consumed                     12353335296 B, i.e. 3.378x the total
#
# The previous factor was 2.5x. It projected 9140903285 B for that same
# staging run, so it under-called the real cost by 3.2 GB -- 26% low, on a
# 19 GB LUN. The gate still passed that day, but only because the store
# started empty; the margin it reported (10.2 GB free afterwards, against
# 6.6 GB actual) was fiction, and a second stage sized on it would have
# filled the partition. 3.4x is the measurement rounded up to two
# significant figures, so the gate stays conservative rather than exact.
#
# Written as *17/5 to keep this in integer arithmetic (the shell has no
# floats) and multiply before dividing so the truncation is at most 1 byte.
# Re-derive it, do not nudge it, if the image set changes materially: the
# ratio is a property of how well these particular layers compress, and
# btrfs on /dev/sdc3 stores them uncompressed.
need=$(( total * 17 / 5 ))

# Free space on the board's container store, in bytes: /var/lib/containers
# is a dedicated ~19 GB partition (/dev/sdc3). Measured, never assumed.
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
