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
# coinor-libipopt-dev, libcppad-dev, liblapack-dev, libblas-dev: the brief's
# list omitted these, and modules/safety_guardian/planning/CMakeLists.txt:4
# hard-requires the "ipopt" pkg-config module (confirmed: pkg_check_modules
# fails with "ipopt ... not found" without them).
# libboost-system-dev: modules/visualization/CMakeLists.txt:9 hard-requires
# find_package(Boost 1.70 REQUIRED COMPONENTS system); also missing from
# the brief's list.
# libgstreamer*-dev, libnice-dev, libsrtp2-dev: visualization.cpp:638-639
# calls WebRTCStreamer::WebRTCStreamer()/init() with no #ifdef ENABLE_WEBRTC
# guard, but modules/visualization/src/webrtc_stream.cpp (which defines
# those symbols) is only added to the target when CMake's
# pkg_check_modules(WEBCONN ...) finds gstreamer-webrtc-1.0 and friends.
# Without these packages the link fails with "undefined reference to
# visualization::WebRTCStreamer::..." (confirmed). Confirmed pkg-config
# resolves gstreamer-webrtc-1.0 with exactly these five packages, no extra
# apt repository needed (universe is already enabled on this base image).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ninja-build pkg-config \
      libopencv-dev nlohmann-json3-dev libgtest-dev libyaml-cpp-dev \
      coinor-libipopt-dev libcppad-dev liblapack-dev libblas-dev \
      libboost-system-dev \
      libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstreamer-plugins-bad1.0-dev \
      libnice-dev libsrtp2-dev \
      python3-numpy python3-opencv \
      ros-jazzy-cv-bridge ros-jazzy-image-transport ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
# CppAD's cppad/ipopt/solve.hpp hardcodes #include <coin-or/IpIpoptApplication.hpp>,
# but this Ubuntu 24.04 image installs that header under /usr/include/coin/
# instead (confirmed). Resolve wherever it actually landed and symlink
# coin-or to it, the same workaround VisionPilot/docker/Dockerfile.cpu uses.
RUN hdr_dir="$(dirname "$(find /usr/include -name IpIpoptApplication.hpp | head -1)")" \
    && [ -n "$hdr_dir" ] \
    && ln -sf "$hdr_dir" /usr/include/coin-or
COPY ort/ /usr/share/visionpilot/onnxruntime/
RUN git clone --depth 1 --branch ${VP_REF} https://github.com/youtalk/vision_pilot.git /src
WORKDIR /src/VisionPilot/build
# app/CMakeLists.txt:75 has an unguarded
# install(DIRECTORY "${CMAKE_SOURCE_DIR}/onnxruntime/" ...): VisionPilot/onnxruntime/
# does not exist in the source tree (confirmed against the feat/x5h-carla-npu
# worktree), and cmake --install hard-fails on a missing DIRECTORY source. An
# empty placeholder satisfies the rule; the real library lives at
# ONNXRUNTIME_ROOT (outside the source tree) and is copied by hand below.
# `source` needs bash. podman's default OCI image format drops a SHELL
# instruction with no error ("SHELL is not supported for OCI image format"),
# so every RUN still executes under /bin/sh (dash), where `source` is
# "not found" (confirmed: this exact failure, exit 127). Invoking bash
# explicitly makes the step work under both OCI and docker image formats.
RUN bash -c "source /opt/ros/jazzy/setup.bash \
    && mkdir -p /src/VisionPilot/onnxruntime \
    && cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DONNXRUNTIME_ROOT=/usr/share/visionpilot/onnxruntime \
         -DGPU=OFF -DENABLE_ROS2_INTERFACE=ON -DBUILD_TESTING=OFF .. \
    && ninja generate_config VisionPilot \
    && cmake --install . --prefix /opt/vp-install"

FROM docker.io/library/ros:jazzy-ros-base
ENV DEBIAN_FRONTEND=noninteractive
# Package name suffix confirmed against ros:jazzy-ros-base on arm64
# (apt-cache search): it's 406t64, not the brief's 4.6t64.
# coinor-libipopt-dev, liblapack3, libblas3, libcppad-lib1456.0t64,
# libboost-system1.83.0, and the gstreamer/nice/srtp runtime libs: the
# runtime-linked half of the ipopt/CppAD/Boost/WebRTC packages added to the
# builder stage above, matching VisionPilot/docker/Dockerfile.cpu's runtime
# list.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libopencv-core406t64 libopencv-imgproc406t64 libopencv-imgcodecs406t64 libopencv-highgui406t64 libopencv-videoio406t64 libopencv-calib3d406t64 \
      libyaml-cpp0.8 ros-jazzy-cv-bridge ros-jazzy-image-transport ros-jazzy-rmw-cyclonedds-cpp \
      coinor-libipopt-dev liblapack3 libblas3 libcppad-lib1456.0t64 libboost-system1.83.0 \
      libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libgstreamer-plugins-bad1.0-0 \
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-nice \
      libnice10 libsrtp2-1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/share/visionpilot/onnxruntime /usr/share/visionpilot/onnxruntime
COPY --from=builder /opt/vp-install/ /usr/
# The CARLA rig's homography replaces the OpenLane example H.yaml.
COPY --from=builder /src/Simulation/CARLA/ROS2/config/H_carla.yaml /usr/share/visionpilot/config/H.yaml
COPY --from=builder /src/Simulation/CARLA/ROS2/config/homography_C_matrix.yaml /usr/share/visionpilot/config/homography_C_matrix.yaml
ENV LD_LIBRARY_PATH=/opt/ros/jazzy/lib:/usr/share/visionpilot/onnxruntime/lib RMW_IMPLEMENTATION=rmw_cyclonedds_cpp QT_QPA_PLATFORM=offscreen
WORKDIR /usr/share/visionpilot
ENTRYPOINT ["/usr/bin/VisionPilot"]
