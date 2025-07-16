group "default" {
  targets = [
    "visualizer",
    "scenario-simulator"
  ]
}

// For docker/metadata-action
target "docker-metadata-action-visualizer" {}
target "docker-metadata-action-scenario-simulator" {}

target "visualizer" {
  inherits = ["docker-metadata-action-visualizer"]
  context = "."
  dockerfile = "tools/visualizer/Dockerfile"
  target = "visualizer"
}

target "scenario-simulator" {
  inherits = ["docker-metadata-action-scenario-simulator"]
  context = "."
  dockerfile = "tools/scenario-simulator/Dockerfile"
  target = "scenario-simulator"
}
