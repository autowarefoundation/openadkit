# VisionPilot for the X5H board: ROS 2 camera input, Renesas execution
# provider, Release build. arm64 only.
#   components/demo/prepare-vp-context.sh <overlay> /tmp/vp-ctx
#   podman build --platform linux/arm64 -f components/demo/visionpilot-x5h.containerfile \
#     --build-arg VP_REF=feat/x5h-carla-npu -t localhost/x5h-visionpilot:latest /tmp/vp-ctx
# The context carries only ort/ (vendor library + headers). The source is
# cloned from youtalk/vision_pilot at VP_REF. The apt list mirrors
# VisionPilot/docker/Dockerfile.cpu on that branch, minus the stock ORT tarball.
FROM docker.io/library/ros:jazzy-ros-base AS builder
ARG VP_REF=feat/x5h-carla-npu
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ninja-build pkg-config \
      libopencv-dev nlohmann-json3-dev libgtest-dev libyaml-cpp-dev \
      python3-numpy python3-opencv \
      ros-jazzy-cv-bridge ros-jazzy-image-transport ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
COPY ort/ /usr/share/visionpilot/onnxruntime/
RUN git clone --depth 1 --branch ${VP_REF} https://github.com/youtalk/vision_pilot.git /src
WORKDIR /src/VisionPilot/build
SHELL ["/bin/bash", "-c"]
# app/CMakeLists.txt:75 has an unguarded
# install(DIRECTORY "${CMAKE_SOURCE_DIR}/onnxruntime/" ...): VisionPilot/onnxruntime/
# does not exist in the source tree (confirmed against the feat/x5h-carla-npu
# worktree), and cmake --install hard-fails on a missing DIRECTORY source. An
# empty placeholder satisfies the rule; the real library lives at
# ONNXRUNTIME_ROOT (outside the source tree) and is copied by hand below.
RUN source /opt/ros/jazzy/setup.bash \
    && mkdir -p /src/VisionPilot/onnxruntime \
    && cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DONNXRUNTIME_ROOT=/usr/share/visionpilot/onnxruntime \
         -DGPU=OFF -DENABLE_ROS2_INTERFACE=ON -DBUILD_TESTING=OFF .. \
    && ninja generate_config VisionPilot \
    && cmake --install . --prefix /opt/vp-install

FROM docker.io/library/ros:jazzy-ros-base
ENV DEBIAN_FRONTEND=noninteractive
# Package name suffix confirmed against ros:jazzy-ros-base on arm64
# (apt-cache search): it's 406t64, not the brief's 4.6t64.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libopencv-core406t64 libopencv-imgproc406t64 libopencv-imgcodecs406t64 libopencv-highgui406t64 libopencv-videoio406t64 libopencv-calib3d406t64 \
      libyaml-cpp0.8 ros-jazzy-cv-bridge ros-jazzy-image-transport ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/share/visionpilot/onnxruntime /usr/share/visionpilot/onnxruntime
COPY --from=builder /opt/vp-install/ /usr/
# The CARLA rig's homography replaces the OpenLane example H.yaml.
COPY --from=builder /src/Simulation/CARLA/ROS2/config/H_carla.yaml /usr/share/visionpilot/config/H.yaml
COPY --from=builder /src/Simulation/CARLA/ROS2/config/homography_C_matrix.yaml /usr/share/visionpilot/config/homography_C_matrix.yaml
ENV LD_LIBRARY_PATH=/opt/ros/jazzy/lib:/usr/share/visionpilot/onnxruntime/lib RMW_IMPLEMENTATION=rmw_cyclonedds_cpp QT_QPA_PLATFORM=offscreen
WORKDIR /usr/share/visionpilot
ENTRYPOINT ["/usr/bin/VisionPilot"]
