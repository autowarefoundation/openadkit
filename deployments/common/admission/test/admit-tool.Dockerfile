# syntax=docker/dockerfile:1
# Dedicated deploy-time admission tool image (ADMIT_TOOL_IMAGE).
#
# It builds ONLY manifest_admit, from autoware_core's common/autoware_component_interface_admission,
# on a minimal ROS base. deploy_check.sh runs THIS image — never an image under test — so the
# admission binary is always trusted, independent of the (possibly third-party) images it inspects.
#
# Build:
#   docker build -t autoware-admit-tool:jazzy -f admit-tool.Dockerfile .
#
# CORE_REPO / CORE_REF exist so a not-yet-merged branch can be tested without editing this file:
#   docker build -t autoware-admit-tool:jazzy -f admit-tool.Dockerfile \
#     --build-arg CORE_REPO=https://github.com/<owner>/autoware_core.git \
#     --build-arg CORE_REF=<branch> .
#
# This image carries NO spec manifest, so it runs the version-only admission rule. A tool image that
# carries one at /opt/autoware/interface_manifest.json additionally enforces spec-QoS conformance;
# see admit-tool-entrypoint.sh, and run_self_test.sh, which derives such a variant from this image.
FROM ros:jazzy-ros-base

# autoware_cmake (for autoware_package()) and nlohmann_json are the package's only build
# dependencies; BUILD_TESTING is off below, so its ament_lint / gtest test dependencies are not
# needed here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    nlohmann-json3-dev \
    python3-colcon-common-extensions \
    ros-jazzy-autoware-cmake \
    && rm -rf /var/lib/apt/lists/*

ARG CORE_REPO=https://github.com/autowarefoundation/autoware_core.git
ARG CORE_REF=main
RUN mkdir -p /ws/src \
    && git clone --depth 1 --branch "${CORE_REF}" "${CORE_REPO}" /tmp/core \
    && if [ ! -d /tmp/core/common/autoware_component_interface_admission ]; then \
        echo "admit-tool: autoware_component_interface_admission is not present in ${CORE_REPO}@${CORE_REF}; pass --build-arg CORE_REPO/CORE_REF pointing at a checkout that carries it" >&2; \
        exit 1; \
    fi \
    && cp -r /tmp/core/common/autoware_component_interface_admission /ws/src/ \
    && rm -rf /tmp/core

WORKDIR /ws
RUN . /opt/ros/jazzy/setup.sh \
    && colcon build --packages-select autoware_component_interface_admission \
        --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

COPY admit-tool-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
