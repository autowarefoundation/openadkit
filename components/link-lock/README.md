# Link lock

ROS patch releases can change signatures, so a runtime that installs current
apt candidates while the tree was compiled against older ones can fail at
startup. `diagnostic_updater` 4.2.6 -> 4.2.7 changed the `Updater` constructor
and broke the Jazzy images that way.

The link lock makes the compile-time dependency set explicit. The lock file
(default `/opt/openadkit/link-lock.txt`, override with `--lock <file>`) is a
sorted list of `Package=Version` lines.

| Command | Stage | What it does |
|---|---|---|
| `lock.sh record [file]` | devel | Scans every ELF object under `/opt/autoware` (shared libraries and node executables), maps each `NEEDED` library to the ROS package that ships it under `/opt/ros/$ROS_DISTRO/lib`, writes the lock |
| `lock.sh upgrade --lock <file>` | devel | Installs the locked packages at the current apt candidates |
| `lock.sh install --lock <file>` | runtime | Installs the exact locked versions (`--allow-downgrades`) |
| `lock.sh verify [file]` | runtime | Fails the build when an installed package differs from the lock |

`align.sh` is the devel-stage procedure: record -> upgrade -> record -> rebuild
only when something moved -> write the final lock. It runs after the stage's
last dependency install so the lock reflects the tree's final environment.

The Dockerfiles re-run the align step on every build through the
`ROS_ALIGN_STAMP` build arg; its only job is to bust the layer cache. The
expensive first `colcon` pass stays cached until a linked package actually
moves.

## Coverage

Only ROS packages whose libraries the compiled tree links against are locked.
Libraries outside `/opt/ros/$ROS_DISTRO/lib`, `dlopen`-ed plugins, and
exec-only dependencies are out of scope; the release evidence cells are the
backstop for those. `record` fails when it finds no linked packages, so a bad
scan cannot silently degrade the lock to a no-op.