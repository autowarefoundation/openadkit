// Override file for the upstream Autoware docker/docker-bake.hcl. It starts the
// base image from the riscv64 ROS 2 build instead of ros:jazzy-ros-base, which
// has no riscv64 variant.
target "base" {
  contexts = {
    "ros:jazzy-ros-base" = "docker-image://openadkit-riscv64/ros:jazzy-ros-base"
  }
}
