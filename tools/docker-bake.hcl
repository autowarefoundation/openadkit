group "default" {
  targets = [
    "scenario-simulator",
    "carla-interface",
  ]
}

// For docker/metadata-action
target "docker-metadata-action-scenario-simulator" {}
target "docker-metadata-action-carla-interface" {}

target "scenario-simulator" {
  inherits = ["docker-metadata-action-scenario-simulator"]
  dockerfile = "tools/scenario-simulator/Dockerfile"
  target = "scenario-simulator"
}

target "carla-interface" {
  inherits = ["docker-metadata-action-carla-interface"]
  dockerfile = "tools/carla-interface/Dockerfile"
  target = "carla-interface"
}
