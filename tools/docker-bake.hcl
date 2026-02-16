group "default" {
  targets = [
    "scenario-simulator",
  ]
}

// For docker/metadata-action
target "docker-metadata-action-scenario-simulator" {}

target "visualizer" {
  inherits = ["docker-metadata-action-visualizer"]
  dockerfile = "tools/visualizer/Dockerfile"
  target = "visualizer"
}

target "scenario-simulator" {
  inherits = ["docker-metadata-action-scenario-simulator"]
  dockerfile = "tools/scenario-simulator/Dockerfile"
  target = "scenario-simulator"
}
