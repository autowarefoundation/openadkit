// Development core must use the same locked sources as the components.
// Reuse upstream's Dockerfile rather than maintaining an Open AD Kit copy.
// CI pins autoware-base to a registry digest before evaluating this graph.
target "autoware-development-core-devel" {
  context    = "autoware"
  dockerfile = "docker/core.Dockerfile"
  target     = "core-devel"
  contexts = {
    autoware-base = upstream("base")
  }
  args = {
    BASE_IMAGE = "autoware-base"
    ROS_DISTRO = ROS_DISTRO
  }
}

target "_universe-common-base" {
  contexts = {
    autoware-core-devel = "target:autoware-development-core-devel"
  }
}
