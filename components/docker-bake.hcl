// Docker Bake configuration for Open AD Kit images
// This file defines build targets for all images

group "default" {
  targets = [
    "common",
    "component",
    "universe-all"
  ]
}

group "common" {
  targets = [
    "common-base",
    "common-base-cuda",
    "common-devel",
    "common-devel-cuda"
  ]
}

group "component" {
  targets = [
    "sensing-perception",
    "sensing-perception-cuda",
    "localization-mapping",
    "planning-control",
    "vehicle-system",
    "api",
    "visualizer",
    "simulator",
  ]
}

group "universe-all" {
  targets = [
    "universe",
    "universe-cuda"
  ]
}

// For docker/metadata-action
target "docker-metadata-action-common-base" {}
target "docker-metadata-action-common-base-cuda" {}
target "docker-metadata-action-common-devel" {}
target "docker-metadata-action-common-devel-cuda" {}
target "docker-metadata-action-sensing-perception" {}
target "docker-metadata-action-sensing-perception-cuda" {}
target "docker-metadata-action-localization-mapping" {}
target "docker-metadata-action-planning-control" {}
target "docker-metadata-action-vehicle-system" {}
target "docker-metadata-action-api" {}
target "docker-metadata-action-visualizer" {}
target "docker-metadata-action-simulator" {}
target "docker-metadata-action-universe" {}
target "docker-metadata-action-universe-cuda" {}

target "common-base" {
  inherits = ["docker-metadata-action-common-base"]
  dockerfile = "components/common/Dockerfile"
  target = "common-base"
}

target "common-base-cuda" {
  inherits = ["docker-metadata-action-common-base-cuda"]
  dockerfile = "components/common/Dockerfile"
  target = "common-base-cuda"
}

target "common-devel" {
  inherits = ["docker-metadata-action-common-devel"]
  dockerfile = "components/common/Dockerfile"
  target = "common-devel"
}

target "common-devel-cuda" {
  inherits = ["docker-metadata-action-common-devel-cuda"]
  dockerfile = "components/common/Dockerfile"
  target = "common-devel-cuda"
}

target "sensing-perception" {
  inherits = ["docker-metadata-action-sensing-perception"]
  dockerfile = "components/sensing-perception/Dockerfile"
  target = "sensing-perception"
}

target "sensing-perception-cuda" {
  inherits = ["docker-metadata-action-sensing-perception-cuda"]
  dockerfile = "components/sensing-perception/Dockerfile.cuda"
  target = "sensing-perception-cuda"
}

target "localization-mapping" {
  inherits = ["docker-metadata-action-localization-mapping"]
  dockerfile = "components/localization-mapping/Dockerfile"
  target = "localization-mapping"
}

target "planning-control" {
  inherits = ["docker-metadata-action-planning-control"]
  dockerfile = "components/planning-control/Dockerfile"
  target = "planning-control"
}

target "api" {
  inherits = ["docker-metadata-action-api"]
  dockerfile = "components/api/Dockerfile"
  target = "api"
}

target "vehicle-system" {
  inherits = ["docker-metadata-action-vehicle-system"]
  dockerfile = "components/vehicle-system/Dockerfile"
  target = "vehicle-system"
}

target "visualizer" {
  inherits = ["docker-metadata-action-visualizer"]
  dockerfile = "components/visualizer/Dockerfile"
  target = "visualizer"
}

target "simulator" {
  inherits = ["docker-metadata-action-simulator"]
  dockerfile = "components/simulator/Dockerfile"
  target = "simulator"
}

target "universe" {
  inherits = ["docker-metadata-action-universe"]
  dockerfile = "components/universe/Dockerfile"
  target = "universe"
}

target "universe-cuda" {
  inherits = ["docker-metadata-action-universe-cuda"]
  dockerfile = "components/universe/Dockerfile.cuda"
  target = "universe-cuda"
}
