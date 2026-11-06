# ROS snapshot

The upstream Autoware images ship binaries compiled against the ROS packages of
one ROS sync, but `packages.ros.org` only serves the latest sync. A stage that
installs from it can run those binaries, and ours, against versions they were
never compiled with. `diagnostic_updater` 4.2.6 -> 4.2.7 changed the `Updater`
constructor and broke the Jazzy images that way.

`ros-snapshot.sh <date> --check` points the ROS apt source at that date's
snapshot on `snapshots.ros.org` and fails when an installed ROS package is newer
than the snapshot's. The universe-common and CUDA stages run it before any apt
step, devel and runtime alike; the component images inherit the source.

The upstream images are layered, and their layers can come from different ROS
syncs: `base` from an older one, `core-devel` installed later from the live
repository. The packages core added over `base` are what it was compiled
against, so the universe-common build stage passes the base image's dpkg
database and also fails unless each of those is exactly the snapshot's version.
Every stage therefore installs the ROS versions upstream core was built with, and
a snapshot from before or after that build cannot build. The images carry the
date as the `org.opencontainers.image.ros-snapshot` label, and the release notes
and BOM name it per distro.

The snapshot is signed by the vendored `ros-snapshots.asc` (ROS Snapshot
builder, `4B63CF8FDE49746E98FA01DDAD19BAB3CBF125EA`). Ubuntu sources stay
live: Ubuntu updates keep the ABI of a release stable, and security fixes keep
flowing.

## Changing the snapshot

The dates live in `components/docker-bake.hcl` (`ROS_SNAPSHOT_HUMBLE`,
`ROS_SNAPSHOT_JAZZY`) and belong to `UPSTREAM_TAG`; change them together. It is
the last snapshot listed on `snapshots.ros.org/<distro>/` before the release's
`core-devel` image was built; confirm that the check passes:

```bash
image=ghcr.io/autowarefoundation/autoware
base=$(docker create "$image:base-jazzy-<tag>")
docker cp "$base:/var/lib/dpkg" base-dpkg && docker rm "$base"
docker run --rm -e ROS_DISTRO=jazzy -v "$PWD/components/shared/ros-snapshot:/s:ro" \
  -v "$PWD/base-dpkg:/base-dpkg:ro" --entrypoint bash "$image:core-devel-jazzy-<tag>" \
  -c 'bash /s/ros-snapshot.sh <YYYY-MM-DD> --check /base-dpkg'
```

The key expires on 2027-06-01. Replace `ros-snapshots.asc` with the extended
key from `keyserver.ubuntu.com` before then.

## Linked libraries

Without a lock, the runtime images rely on the rosdep exec dependencies for
every package the compiled tree links against, as upstream Autoware does.
`../check-linked-libs.sh` proves it at the end of each runtime stage: it runs
`ldd` on every library and `ldd -r` on every executable under `/opt/autoware`,
and fails the build on a missing library or an undefined symbol. This also
covers the images CI evidence cannot run (GPU, CARLA). `dlopen`-ed plugins,
Python modules, and launch-time packages are left to the release evidence.
