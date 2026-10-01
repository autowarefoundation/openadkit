#!/bin/sh
# Started by the S-CORE launch manager as component "visionpilot" (CES 2027
# demo role, platforms/autosd/x5h/score/config/demo). This script is the
# podman command line and nothing else: the launch manager passes at most 20
# arguments and only the environment variables its configuration names.
#
# exec twice: systemd-cat exec's podman, so the PID the launch manager
# watches is podman's, and podman's signal proxy carries the launch
# manager's SIGTERM to VisionPilot. systemd-cat gives the container output
# one tagged journal stream (journalctl -t x5h-vp); passthrough hands the
# container that stream, so no line is printed twice.
#
# The ready file goes first: a file left by the previous run would tell the
# launch manager that VisionPilot is ready before it is.
#
# The host PID namespace (pid=host): mw::log writes the client's own PID into
# the datarouter's shared memory, and the datarouter drops a client whose PID
# is not the peer PID it sees on the socket. In a private PID namespace the
# client would write 1.
#
# Board-verified notes, copied from the former Quadlet unit. A comment cannot
# sit between the continued lines of one command, so each is introduced by
# the option it explains.
#
# -v .../arc_prog_npus:/npu/hostapp/binary/arc_prog_npus:ro
# The ARC programs the NPU driver loads to power the engine on. /opt/npu ships
# one set at hostapp/binary/arc_prog_npus, and it is NOT the set this image's
# Renesas runtime was built against: all twelve l1c*.bin differ by content.
# With the wrong set the driver never reaches "Set programs and power on",
# every inference returns RenesasBackendExecute failed, and VisionPilot dies
# in its own offload gate with no mention of ARC programs at all. The matching
# set is the one inside the vendor ORT rootfs, which is why npu-check-autosd.sh
# passes on the same board, same artifacts and same devices while this failed.
# Board-confirmed on board 2, 2026-09-18: with this line VisionPilot reaches
# 12.9 ms NPU latency and 43 fps; without it, it restart-loops.
#
# -v /opt/npu/perf/merged:/home/youtalk/src/openadkit/x5h-work/npu/merged:ro
# The NNX artifacts were compiled on a workstation and manifest.json records
# the absolute path they were written to, which exists on no board. The
# Renesas backend opens that exact path and dies with "fopen: No such file or
# directory" followed by an Ort::Exception. Mapping the board's copy onto the
# recorded path makes it resolve without editing vendor artifacts. Board-
# confirmed on BOTH boards 2026-09-18. If the artifacts are ever recompiled,
# check manifest.json and move this line with them.
#
# -e LD_LIBRARY_PATH=...
# The image's own LD_LIBRARY_PATH is
# /opt/ros/jazzy/lib:/usr/share/visionpilot/onnxruntime/lib, which omits the
# architecture subdirectory where libddsc.so.0 lives. The entrypoint is
# /usr/bin/VisionPilot directly, so nothing sources /opt/ros/jazzy/setup.bash
# to add it. Without this line rmw_cyclonedds_cpp fails to load and the
# container exits 1 immediately with "libddsc.so.0: cannot open shared object
# file", restart-looping forever. Board-confirmed on BOTH boards 2026-09-18.
rm -f "$SCORE_VP_READY_FILE"
mkdir -p /run/score
exec /usr/bin/systemd-cat -t x5h-vp /usr/bin/podman run --rm --replace --name x5h-vp \
    --network=host --ipc=host --pid=host --cgroups=split --log-driver=passthrough --privileged \
    -v /tmp:/tmp -v /run/score:/run/score \
    -e IDENTIFIER -e LCM_ALIVE_INTERFACE_PATH -e SCORE_VP_FRAME_MAX_MS -e SCORE_VP_READY_FILE \
    -e SCORE_VP_LIB=/opt/score/lib/libscore_vp.so \
    -e MW_LOG_CONFIG_FILE=/etc/score/vp-logging.json \
    -v /usr/local/score/lib/libscore_vp.so:/opt/score/lib/libscore_vp.so:ro \
    -v /etc/score/vp-logging.json:/etc/score/vp-logging.json:ro \
    --device /dev/uio2:/dev/npuc0 --device /dev/uio3:/dev/npuc1 \
    --device /dev/cmem0 --device /dev/cmem_other0 --device /dev/cmem_other1 \
    --device /dev/cmem_other2 --device /dev/cmem_other3 \
    -v /opt/npu:/npu \
    -v /opt/npu/ort-rootfs/usr/local/lib/python3.11/site-packages/onnxruntime/nnac_portable_env/binary/arc_prog_npus:/npu/hostapp/binary/arc_prog_npus:ro \
    -v /opt/npu/perf/merged:/home/youtalk/src/openadkit/x5h-work/npu/merged:ro \
    -v /etc/containers/systemd/vision_pilot.conf:/usr/share/visionpilot/config/vision_pilot.conf:ro,z \
    -v /etc/containers/systemd/vision_pilot_ros2.conf:/usr/share/visionpilot/config/vision_pilot_ros2.conf:ro,z \
    -v /etc/containers/systemd/cyclonedds-x5h-demo.xml:/etc/x5h/cyclonedds.xml:ro,z \
    -e ROS_DOMAIN_ID=1 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI=file:///etc/x5h/cyclonedds.xml -e QT_QPA_PLATFORM=offscreen \
    -e LD_LIBRARY_PATH=/opt/ros/jazzy/lib/aarch64-linux-gnu:/opt/ros/jazzy/lib:/usr/share/visionpilot/onnxruntime/lib \
    localhost/x5h-visionpilot:latest --no-window
