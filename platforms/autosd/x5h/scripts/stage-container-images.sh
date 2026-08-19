#!/bin/sh
# Stage the Open AD Kit arm64 container images from the companion host onto
# the board's btrfs container store.
#
# Why staged rather than pulled on the board: multi-gigabyte pulls from the
# board route through the companion's tailnet, so a network flake becomes a
# failed board session. Staging keeps the transfer on the bench LAN
# (192.168.0.0/24) and makes the bytes reproducible, because every image is
# addressed by digest rather than by tag.
#
# The list (../components/images.txt) is two columns: the reference the board
# should carry after the load, and the digest-pinned reference to read the
# bytes from. The first column is used VERBATIM as the loaded name -- this
# script does not synthesise localhost/<name>:latest any more, because the
# unit files and awf-oak-x5h.env name these images by their registry
# references and every unit sets Pull=never, so the loaded name and the env
# file have to match exactly. See the long note at the top of images.txt.
#
# skopeo needs XDG_RUNTIME_DIR exported (export XDG_RUNTIME_DIR=/run/user/$(id -u)).
# Without it, it fails looking for auth.json and reports something that reads
# like an authentication or network failure.
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

while read -r load_ref pull_ref; do
    case "$load_ref" in ''|\#*) continue ;; esac
    # Compressed size of each arm64 layer, one "digest size" pair per
    # line. This under-reports the on-disk footprint (layers are stored
    # uncompressed), so the gate below applies an expansion factor rather
    # than comparing raw bytes to free space and quietly overfilling the
    # LUN. See the factor's derivation just above `need=`.
    layers=$(skopeo inspect --override-arch arm64 --override-os linux \
            --format '{{range .LayersData}}{{.Digest}} {{.Size}}
{{end}}' "docker://$pull_ref" 2>/dev/null)
    sz=$(printf '%s\n' "$layers" | awk 'NF==2 {s+=$2} END {print s+0}')
    [ "$sz" -gt 0 ] 2>/dev/null || fail "inspect_failed:$load_ref" "X5H_IMAGE_AUDIT_FAIL"
    echo "image=$load_ref compressed_bytes=$sz"
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
# staging run, so it under-called the real cost by 3212432011 B -- 26% low, on
# a store of 20400025600 B. The gate still passed that day, but only because
# the store was nearly empty: it held one unrelated image (464 MB as
# `podman images` reports it, localhost/x5h-ort:1.1.0) and nothing else,
# 477 MB used in total. The margin 2.5x implied afterwards -- 10238071435 B
# still free -- was fiction; the real figure was 7025639424 B, and a second
# stage sized on the projection would have filled the partition. All byte
# figures in this block are exact and decimal; the `df -h` view of the same
# store reads 19G/13G/6.6G in binary units. 3.4x is the measurement rounded
# up to two significant figures, so the gate stays conservative rather than
# exact.
#
# Written as *17/5 to keep this in integer arithmetic (the shell has no
# floats) and multiply before dividing so the truncation is at most 1 byte.
# Re-derive it, do not nudge it, if the image set changes materially: the
# ratio is a property of how well these particular layers compress, and
# btrfs on /dev/sdc3 stores them uncompressed.
#
# RE-DERIVED for the two mrm-demo images that replaced those six, and
# deliberately NOT lowered to match. Measured 2026-08-18: compressed
# 1609201424 + 2309091529 = 3918292953 B, on-disk delta by df
# 12132388864 B, ratio 3.096x. The gate keeps the larger of the two
# measurements so it stays conservative for both image sets; 3.4x projects
# 13.3 GB for this pair, which is an over-estimate of 1.2 GB and not a
# number to spend, but the alternative is a gate that only just fits.
#
# KNOWN BLIND SPOT, so an operator is not surprised by it: the audit gives no
# credit for images the board already holds. Re-running --audit against a
# board that is already fully staged compares the whole projected cost
# against the free space that remains AFTER staging, and fails. That is a
# false negative on a healthy board, not a reason to stage again.
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
while read -r load_ref pull_ref; do
    case "$load_ref" in ''|\#*) continue ;; esac
    # The load reference is a registry name with slashes and a colon, which
    # cannot be a filename; flatten it for the archive only. The name that
    # matters -- the tag baked into the archive, and so the name podman
    # gives the image -- is $load_ref itself, unmodified.
    arc="$WORK/$(printf '%s' "$load_ref" | tr '/:' '__').tar"
    skopeo copy --override-arch arm64 --override-os linux \
        "docker://$pull_ref" "oci-archive:$arc:$load_ref" \
        || fail "copy:$load_ref" "X5H_IMAGE_STAGE_FAIL"
    # Stream rather than scp-then-load: the board's /var/tmp is not sized
    # for a second full copy of every image.
    ssh -o BatchMode=yes "$BOARD" "podman load" < "$arc" \
        || fail "load:$load_ref" "X5H_IMAGE_STAGE_FAIL"
    echo "staged=$load_ref"
done < "$LIST"

# Verify BY NAME, and deliberately not by digest. `skopeo copy` into an
# oci-archive rewrites a Docker schema-2 manifest to OCI media types, so the
# digest podman reports differs from the registry digest pinned in the list
# (measured: sha256:d161659c… becomes sha256:11f418e1… ). A digest comparison
# here would fail on every correctly staged board; content identity is
# established by the layer diff_ids instead, per the note in images.txt.
# What this check IS worth: the loaded name is what every unit's Pull=never
# resolves against, so a name that did not land is a stack that will not
# start.
board_images=$(ssh -o BatchMode=yes "$BOARD" \
        "podman images --format '{{.Repository}}:{{.Tag}}'") \
    || fail "verify" "X5H_IMAGE_STAGE_FAIL"
while read -r load_ref pull_ref; do
    case "$load_ref" in ''|\#*) continue ;; esac
    printf '%s\n' "$board_images" | grep -qxF "$load_ref" \
        || fail "not_loaded:$load_ref" "X5H_IMAGE_STAGE_FAIL"
done < "$LIST"
printf '%s\n' "$board_images"
echo "X5H_IMAGE_STAGE_PASS"
