# The board's decoder for the demo camera stream. arm64 only.
#   podman build -f components/demo/image-republish-x5h.containerfile \
#     -t localhost/x5h-image-republish:latest components/demo
#
# The bench host publishes the CARLA camera as JPEG rather than raw, because
# 1280x720 bgra8 is 3.69 MB per sample and 297 Mbit/s at 10 Hz, which this
# board cannot reassemble (gate D5, 2026-09-18: rx_drop in the tens of
# thousands with rx_errs=0, and VisionPilot at zero frames). Something on the
# board has to turn the compressed topic back into sensor_msgs/Image, and
# VisionPilot subscribes to a plain Image with no image_transport of its own.
#
# The base image already carries image_transport's `republish`, so all that is
# missing is the plugin that knows how to decompress. Nothing else is added
# and VisionPilot's own image is untouched.
FROM localhost/x5h-visionpilot:latest
ENV DEBIAN_FRONTEND=noninteractive
# Acquire::Check-Date=false: this board has no working RTC (RTC time reads
# 2000-01-03) and no NTP, so its clock sits about a month behind and apt
# rejects every Release file as "not valid yet". This stops apt judging the
# clock; it does not change it.
RUN apt-get -o Acquire::Check-Date=false -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends ros-jazzy-compressed-image-transport \
    && rm -rf /var/lib/apt/lists/*
# The base image's entrypoint is /usr/bin/VisionPilot. This image runs a ROS
# node instead, so clear it rather than fight it from every caller.
ENTRYPOINT []
