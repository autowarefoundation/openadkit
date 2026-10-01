# Wraps the vendor ort-rootfs tree (NDA payload on npu-work, never in this
# repo) as an OCI image so the R3 podman path is reproducible from one
# command:  podman build -t localhost/x5h-ort-rootfs:latest \
#             -f /usr/sbin/ort-rootfs.containerfile \
#             --ignorefile /usr/sbin/ort-rootfs.containerignore /opt/npu/ort-rootfs
# The AutoSD image ships no `tar`, so `tar | podman import` is not available;
# build is the only route. The ignore file is REQUIRED: ort-rootfs/npu is the
# bind target of /opt/npu, which contains ort-rootfs itself (infinite recursion).
FROM scratch
COPY . /
CMD ["/bin/sh"]
