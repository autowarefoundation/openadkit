#!/usr/bin/env bash
# Build the two pinned test images for the x5h gate and board smoke.
# Usage: make-test-images.sh <outdir>   (needs docker with arm64 support + skopeo)
set -euo pipefail
OUT="$(mkdir -p "$1" && cd "$1" && pwd)"

# 1. busybox: tiny runtime + httpd for the networking assertion. ECR public
#    mirror avoids docker.io anonymous rate limits.
skopeo copy --override-arch arm64 --override-os linux \
  docker://public.ecr.aws/docker/library/busybox:1.36 \
  "oci-archive:$OUT/busybox-oci.tar:busybox:1.36"

# 2. captest: guaranteed to carry a security.capability xattr in its top layer.
tmp="$(mktemp -d)"
cat > "$tmp/Containerfile" <<'EOF'
FROM quay.io/fedora/fedora:42
RUN dnf -y install libcap iputils && \
    setcap cap_net_raw+ep /usr/bin/ping && \
    getcap /usr/bin/ping && \
    dnf clean all
EOF
docker build --platform linux/arm64 -f "$tmp/Containerfile" -t x5h-captest:latest "$tmp"
docker save x5h-captest:latest -o "$OUT/captest-docker.tar"
rm -rf "$tmp"

# 3. Verify the archive really contains a security.capability PAX record.
python3 - "$OUT/captest-docker.tar" <<'EOF'
import sys, tarfile
found = False
with tarfile.open(sys.argv[1]) as outer:
    for m in outer.getmembers():
        if not (m.name.endswith(("layer.tar", ".tar")) or "blobs/" in m.name):
            continue
        f = outer.extractfile(m)
        if f is None:
            continue
        try:
            with tarfile.open(fileobj=f) as inner:
                for im in inner:
                    if "SCHILY.xattr.security.capability" in (im.pax_headers or {}):
                        print(f"capability xattr on: {im.name}")
                        found = True
        except tarfile.TarError:
            continue
sys.exit(0 if found else "FATAL: no security.capability xattr in any layer")
EOF
echo "OK: $OUT"
