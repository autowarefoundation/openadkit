// Docker Bake configuration for Open AD Kit images.
//
// Local builds: every target resolves cross-references via `target:` within one
// build graph.
//
// CI: each bake-group builds in its own job; build-all-images.yaml overrides
// cross-stage contexts via `set: *.contexts.<name>=docker-image://...` so that
// cross-group references resolve to already-pushed GHCR tags. Tags themselves
// are supplied by docker/metadata-action via the docker-metadata-action-*
// targets, not by this file.

// Default ROS distro for local builds. Tracks the documented default distro
// (docs/macros.py DEFAULT_DISTRO / the published `<target>` alias), which is Humble for
// v2.0. CI never relies on this default — build-all-images.yaml sets ROS_DISTRO
// explicitly per matrix entry. Flip to "jazzy" together with the docs default
// when Jazzy-primary lands (v2.1).
variable "ROS_DISTRO" {
  default = "humble"
}

// Pin for upstream Autoware images. A concrete release tag (e.g. "1.2.3") is
// the production default, set via a repo Variable in CI. Empty string yields
// the upstream "plain" <name>-<distro> multi-arch manifest — handy for local
// experiments, but NOT what CI should run with.
variable "UPSTREAM_TAG" {
  default = ""
}
variable "UPSTREAM_REPO" {
  default = "ghcr.io/autowarefoundation/autoware"
}

// Local builds resolve cross-stage refs within one graph. CI overrides each
// context via `set: *.contexts.<name>=docker-image://...` in build-all-images.yaml.
function "ctx" {
  params = [name]
  result = "target:${name}"
}

// Resolves an upstream Autoware image reference. UPSTREAM_TAG="" yields the
// plain <name>-<distro> multi-arch tag; non-empty yields <name>-<distro>-<tag>.
function "upstream" {
  params = [name]
  result = "docker-image://${UPSTREAM_REPO}:${name}-${ROS_DISTRO}${UPSTREAM_TAG == "" ? "" : "-${UPSTREAM_TAG}"}"
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
    "/tmp/autoware/src/universe/external/trt_batched_nms",
    "/tmp/autoware/src/universe/external/bevdet_vendor",
    "/tmp/autoware/src/universe/external/cuda_blackboard",
    "/tmp/autoware/src/universe/external/negotiated",
    "/tmp/autoware/src/universe/autoware_universe/perception",
    "/tmp/autoware/src/universe/autoware_universe/sensing",
    "/tmp/autoware/src/sensor_component",
  ])
}

group "default" {
  targets = ["universe-common", "component"]
}

group "universe-common" {
  targets = ["universe-common-devel", "universe-common"]
}

group "component" {
  targets = [
    "sensing-perception", "sensing-perception-cuda", "localization-mapping",
    "planning-control", "vehicle-system", "api", "visualizer", "simulator",
    "carla-interface",
  ]
}

// For docker/metadata-action (tags injected by the workflow).
target "docker-metadata-action-universe-common-devel" {}
target "docker-metadata-action-universe-common" {}
target "docker-metadata-action-sensing-perception" {}
target "docker-metadata-action-sensing-perception-cuda" {}
target "docker-metadata-action-localization-mapping" {}
target "docker-metadata-action-planning-control" {}
target "docker-metadata-action-vehicle-system" {}
target "docker-metadata-action-api" {}
target "docker-metadata-action-visualizer" {}
target "docker-metadata-action-simulator" {}
target "docker-metadata-action-carla-interface" {}

// Common base for both universe-common stages. The Dockerfile has FROM lines
// for both ${CORE_DEVEL_IMAGE} (devel stage) and ${CORE_IMAGE} (runtime
// stage), so BuildKit needs both ARGs and both contexts resolved at parse
// time regardless of which target stage is being built — mirrors upstream's
// `_universe-base` / `_universe-cuda-base` inheritable pattern.
target "_universe-common-base" {
  dockerfile = "components/universe-common/Dockerfile"
  contexts = {
    autoware-core-devel = upstream("core-devel")
    autoware-core       = upstream("core")
  }
  args = {
    CORE_DEVEL_IMAGE = "autoware-core-devel"
    CORE_IMAGE       = "autoware-core"
    ROS_DISTRO       = ROS_DISTRO
  }
}

target "universe-common-devel" {
  inherits = ["_universe-common-base", "docker-metadata-action-universe-common-devel"]
  target   = "universe-common-devel"
}

target "universe-common" {
  inherits = ["_universe-common-base", "docker-metadata-action-universe-common"]
  target   = "universe-common"
  contexts = {
    universe-common-devel = ctx("universe-common-devel")
  }
}

target "_component-base" {
  contexts = {
    universe-common-devel = ctx("universe-common-devel")
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

target "planning-control" {
  inherits   = ["_component-base", "docker-metadata-action-planning-control"]
  dockerfile = "components/planning-control/Dockerfile"
  target     = "planning-control"
}

target "vehicle-system" {
  inherits   = ["_component-base", "docker-metadata-action-vehicle-system"]
  dockerfile = "components/vehicle-system/Dockerfile"
  target     = "vehicle-system"
}

target "api" {
  inherits   = ["_component-base", "docker-metadata-action-api"]
  dockerfile = "components/api/Dockerfile"
  target     = "api"
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
  }
}

target "carla-interface" {
  inherits = ["docker-metadata-action-carla-interface"]
  dockerfile = "components/carla-interface/Dockerfile"
  target = "carla-interface"
}
