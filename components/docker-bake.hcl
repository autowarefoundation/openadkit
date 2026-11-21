// Docker Bake configuration for Open AD Kit images.
//
// Local builds: every target resolves cross-references via `target:` within one
// build graph.
//
// CI: each bake-group builds in its own job; build-all-images.yaml overrides
// cross-stage contexts via `set: *.contexts.<name>=docker-image://...` so that
// cross-group references resolve to already-pushed GHCR tags. CI also sets
// LOCAL_IMAGE="" so only docker-metadata-action tags are published.

// Default ROS distro for local builds, openadkit.json defaultRosDistro. CI sets
// ROS_DISTRO per matrix entry.
variable "ROS_DISTRO" {
  default = "humble"
}

// Upstream Autoware release the images build on, the tag in
// .github/autoware.ref (e.g. "2.0.0"); required.
variable "UPSTREAM_TAG" {
  default = ""
}
// ROS snapshot (snapshots.ros.org) each distro's upstream images were built
// from, for UPSTREAM_TAG 2.0.0. Change both together: the builds fail when the
// snapshot does not match the upstream images (components/shared/ros-snapshot).
variable "ROS_SNAPSHOT_HUMBLE" {
  default = "2026-10-12"
}
variable "ROS_SNAPSHOT_JAZZY" {
  default = "2026-10-05"
}
function "ros_snapshot" {
  params = []
  result = ROS_DISTRO == "jazzy" ? ROS_SNAPSHOT_JAZZY : ROS_SNAPSHOT_HUMBLE
}
variable "UPSTREAM_REPO" {
  default = "ghcr.io/autowarefoundation/autoware"
}

// Local tag prefix. Empty string disables local tags so CI metadata-action is
// the sole tag source.
variable "LOCAL_IMAGE" {
  default = "ghcr.io/autowarefoundation/openadkit"
}

// Local builds resolve cross-stage refs within one graph. CI overrides each
// context via `set: *.contexts.<name>=docker-image://...` in build-all-images.yaml.
function "ctx" {
  params = [name]
  result = "target:${name}"
}

// The upstream Autoware release image <name>-<distro>-<UPSTREAM_TAG>.
function "upstream" {
  params = [name]
  result = "docker-image://${UPSTREAM_REPO}:${name}-${ROS_DISTRO}-${UPSTREAM_TAG}"
}

// Architecture segment for local tags, taken from the bake host platform so a
// local `--load` build is immediately visible to repository-mode `./openadkit`
// (which looks up <target>-<arch>-<ros-distro>) without --set overrides.
function "local_arch" {
  params = []
  result = BAKE_LOCAL_PLATFORM == "linux/arm64" ? "arm64" : "amd64"
}

// Local tag: :<target>-<arch>-<ros_distro>, the one the CLI runs from a source
// checkout.
function "local_tags" {
  params = [name]
  result = LOCAL_IMAGE == "" ? [] : ["${LOCAL_IMAGE}:${name}-${local_arch()}-${ROS_DISTRO}"]
}

// Single source of truth for the sensing-perception `--base-paths` package
// list. Both the CPU and CUDA sensing Dockerfiles consume this via the
// COLCON_BASE_PATHS arg so a drift cannot silently diverge the two images.
function "sensing_base_paths" {
  params = []
  result = join(" ", [
    "/tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_perception_launch",
    "/tmp/autoware/src/launcher/autoware_launch/tier4_universe_launch/tier4_sensing_launch",
    "/tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_description",
    "/tmp/autoware/src/launcher/autoware_launch/sensor_kit/carla_sensor_kit_launch/carla_sensor_kit_launch",
    "/tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/common_sensor_launch",
    "/tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/sample_sensor_kit_description",
    "/tmp/autoware/src/launcher/autoware_launch/sensor_kit/sample_sensor_kit_launch/sample_sensor_kit_launch",
    "/tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description",
    "/tmp/autoware/src/universe/external/bevdet_vendor",
    // Globs match the CUDA packages both in universe and in core/cuda.
    "/tmp/autoware/src/*/*/cuda_blackboard",
    "/tmp/autoware/src/*/*/negotiated",
    "/tmp/autoware/src/*/*/*/autoware_cuda_utils",
    "/tmp/autoware/src/*/*/*/autoware_tensorrt_common",
    "/tmp/autoware/src/universe/autoware_universe/perception",
    "/tmp/autoware/src/universe/autoware_universe/sensing",
    "/tmp/autoware/src/sensor_component",
  ])
}

// Single source of truth for the planning `--base-paths` package list, shared
// by the CPU and CUDA planning Dockerfiles like sensing_base_paths above. The
// CUDA and TensorRT helpers are what autoware_diffusion_planner depends on.
function "planning_base_paths" {
  params = []
  result = join(" ", [
    "/tmp/autoware/src/launcher/autoware_launch/vehicle/sample_vehicle_launch/sample_vehicle_description",
    "/tmp/autoware/src/universe/autoware_universe/planning",
    "/tmp/autoware/src/*/*/*/autoware_cuda_utils",
    "/tmp/autoware/src/*/*/*/autoware_tensorrt_common",
    "/tmp/autoware/src/universe/autoware_universe/perception/autoware_tensorrt_plugins",
  ])
}

group "default" {
  targets = ["common", "component"]
}

// Named apart from the universe-common target: Bake resolves a name to the
// group first, which would build the devel image with every universe-common.
group "common" {
  targets = ["universe-common-devel", "universe-common"]
}

group "component" {
  targets = [
    "sensing-perception", "sensing-perception-cuda", "localization-mapping",
    "planning", "planning-cuda", "control", "vehicle-system",
    "visualizer", "simulator",
  ]
}

group "planning-simulation" {
  targets = [
    "universe-common", "localization-mapping", "planning", "control",
    "vehicle-system", "visualizer", "simulator",
  ]
}

// Local compose tags live on these stubs so image targets can inherit them
// without overriding CI metadata-action tags. LOCAL_IMAGE="" leaves the stub
// untagged; the workflow bake file then supplies the push tags.
target "docker-metadata-action-universe-common-devel" { tags = local_tags("universe-common-devel") }
target "docker-metadata-action-universe-common" { tags = local_tags("universe-common") }
target "docker-metadata-action-sensing-perception" { tags = local_tags("sensing-perception") }
target "docker-metadata-action-sensing-perception-cuda" { tags = local_tags("sensing-perception-cuda") }
target "docker-metadata-action-localization-mapping" { tags = local_tags("localization-mapping") }
target "docker-metadata-action-planning" { tags = local_tags("planning") }
target "docker-metadata-action-planning-cuda" { tags = local_tags("planning-cuda") }
target "docker-metadata-action-control" { tags = local_tags("control") }
target "docker-metadata-action-vehicle-system" { tags = local_tags("vehicle-system") }
target "docker-metadata-action-visualizer" { tags = local_tags("visualizer") }
target "docker-metadata-action-simulator" { tags = local_tags("simulator") }

// Common base for the universe-common stages. The Dockerfile has FROM lines
// for both ${CORE_DEVEL_IMAGE} (build stage) and ${BASE_IMAGE} (runtime
// stage), so BuildKit needs both ARGs and both contexts resolved at parse
// time regardless of which target stage is being built. The runtime starts
// from the lean base and copies the compiled core/common tree from the build
// stage; inheriting upstream core would retain its development files in final
// layers.
target "_universe-common-base" {
  dockerfile = "components/universe-common/Dockerfile"
  contexts = {
    autoware-core-devel = upstream("core-devel")
    autoware-base       = upstream("base")
  }
  args = {
    CORE_DEVEL_IMAGE = "autoware-core-devel"
    BASE_IMAGE       = "autoware-base"
    ROS_DISTRO       = ROS_DISTRO
    ROS_SNAPSHOT     = ros_snapshot()
  }
}

// The devel image without its per-build security refresh. It is not
// published; components compile on it so their builds stay cached.
target "universe-common-build" {
  inherits = ["_universe-common-base"]
  target   = "universe-common-build"
}

target "universe-common-devel" {
  inherits = ["_universe-common-base", "docker-metadata-action-universe-common-devel"]
  target   = "universe-common-devel"
  contexts = {
    universe-common-build = ctx("universe-common-build")
  }
}

target "universe-common" {
  inherits = ["_universe-common-base", "docker-metadata-action-universe-common"]
  target   = "universe-common"
  contexts = {
    universe-common-build = ctx("universe-common-build")
  }
}

// Components compile in the universe-common-devel context: the build stage
// locally, the published devel image or CI's internal build image in CI.
target "_component-base" {
  contexts = {
    universe-common-devel = ctx("universe-common-build")
    universe-common       = ctx("universe-common")
  }
  args = {
    UNIVERSE_COMMON_DEVEL_IMAGE = "universe-common-devel"
    UNIVERSE_COMMON_IMAGE       = "universe-common"
    ROS_DISTRO                  = ROS_DISTRO
  }
}

target "sensing-perception" {
  inherits   = ["_component-base", "docker-metadata-action-sensing-perception"]
  dockerfile = "components/sensing-perception/Dockerfile"
  target     = "sensing-perception"
  args = {
    COLCON_BASE_PATHS = sensing_base_paths()
  }
}

target "localization-mapping" {
  inherits   = ["_component-base", "docker-metadata-action-localization-mapping"]
  dockerfile = "components/localization-mapping/Dockerfile"
  target     = "localization-mapping"
}

target "planning" {
  inherits   = ["_component-base", "docker-metadata-action-planning"]
  dockerfile = "components/planning/Dockerfile"
  target     = "planning"
  args = {
    COLCON_BASE_PATHS = planning_base_paths()
  }
}

target "control" {
  inherits   = ["_component-base", "docker-metadata-action-control"]
  dockerfile = "components/control/Dockerfile"
  target     = "control"
}

target "vehicle-system" {
  inherits   = ["_component-base", "docker-metadata-action-vehicle-system"]
  dockerfile = "components/vehicle-system/Dockerfile"
  target     = "vehicle-system"
}

target "visualizer" {
  inherits   = ["_component-base", "docker-metadata-action-visualizer"]
  dockerfile = "components/visualizer/Dockerfile"
  target     = "visualizer"
}

target "simulator" {
  inherits   = ["_component-base", "docker-metadata-action-simulator"]
  dockerfile = "components/simulator/Dockerfile"
  target     = "simulator"
}

target "sensing-perception-cuda" {
  inherits   = ["_component-base", "docker-metadata-action-sensing-perception-cuda"]
  dockerfile = "components/sensing-perception/Dockerfile.cuda"
  target     = "sensing-perception-cuda"
  contexts = {
    autoware-base-cuda-runtime = upstream("base-cuda-runtime")
    autoware-base-cuda-devel   = upstream("base-cuda-devel")
  }
  args = {
    BASE_CUDA_RUNTIME_IMAGE = "autoware-base-cuda-runtime"
    BASE_CUDA_DEVEL_IMAGE   = "autoware-base-cuda-devel"
    COLCON_BASE_PATHS       = sensing_base_paths()
    ROS_SNAPSHOT            = ros_snapshot()
  }
}

target "planning-cuda" {
  inherits   = ["_component-base", "docker-metadata-action-planning-cuda"]
  dockerfile = "components/planning/Dockerfile.cuda"
  target     = "planning-cuda"
  contexts = {
    autoware-base-cuda-runtime = upstream("base-cuda-runtime")
    autoware-base-cuda-devel   = upstream("base-cuda-devel")
  }
  args = {
    BASE_CUDA_RUNTIME_IMAGE = "autoware-base-cuda-runtime"
    BASE_CUDA_DEVEL_IMAGE   = "autoware-base-cuda-devel"
    COLCON_BASE_PATHS       = planning_base_paths()
    ROS_SNAPSHOT            = ros_snapshot()
  }
}
