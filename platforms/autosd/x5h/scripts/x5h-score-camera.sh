#!/bin/sh
# Started by the S-CORE launch manager as component "camera" (CES 2027 demo
# role): decodes the compressed bench camera into the raw topic VisionPilot
# reads. Same exec chain as x5h-score-vp.sh. bash exec's the node binary
# itself, not `ros2 run`, so the node is PID 1 and handles the SIGTERM that
# podman forwards; a PID 1 without a handler drops it.
#
# Board-verified notes, copied from the former Quadlet unit. They explain
# the -r out:=/x5h/main_cam/image remap and the -p in_transport/out_transport
# parameters below.
#
# The output topic is deliberately NOT the bench's own camera topic name.
# CARLA still publishes the raw 3.69 MB topic on domain 1, and if VisionPilot
# subscribed to that name it would match the bench publisher as well as this
# one and pull the raw stream across the LAN again, which is the whole defect
# gate D5 was blocked on. DDS only sends to matched subscribers, so a distinct
# local name leaves the raw topic on the bench host with no subscriber at all.
# vision_pilot_ros2.conf must name the same topic.
#
# republish takes its transports as PARAMETERS in Jazzy, not as positional
# arguments. Passed positionally they are silently ignored: the node comes up
# with in_transport=raw and an empty out_transport, logs nothing wrong, and
# publishes no output at all.
exec /usr/bin/systemd-cat -t x5h-camera /usr/bin/podman run --rm --replace --name x5h-image-republish \
    --network=host --cgroups=split --log-driver=passthrough \
    -v /etc/containers/systemd/cyclonedds-x5h-demo.xml:/etc/x5h/cyclonedds.xml:ro,z \
    -e ROS_DOMAIN_ID=1 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI=file:///etc/x5h/cyclonedds.xml \
    --entrypoint /bin/bash localhost/x5h-image-republish:latest \
    -c 'source /opt/ros/jazzy/setup.bash && exec /opt/ros/jazzy/lib/image_transport/republish --ros-args -p in_transport:=compressed -p out_transport:=raw -r in/compressed:=/carla/hero/main_cam/image/compressed -r out:=/x5h/main_cam/image'
