#!/bin/sh
# SIL twin of scripts/x5h-score-vp.sh: the same container boundary, the
# libscore_vp.so stand-in instead of VisionPilot. tests/test-x5h-score-exec.sh
# keeps the two boundaries equal.
rm -f "$SCORE_VP_READY_FILE"
mkdir -p /run/score-sil
exec /usr/bin/systemd-cat -t sil-vp /usr/bin/podman run --rm --replace --name sil-vp \
    --network=host --ipc=host --cgroups=split --log-driver=passthrough \
    -v /tmp:/tmp -v /run/score-sil:/run/score-sil \
    -e IDENTIFIER -e LCM_ALIVE_INTERFACE_PATH -e SCORE_VP_FRAME_MAX_MS -e SCORE_VP_READY_FILE \
    -e MW_LOG_CONFIG_FILE=/opt/score/sil/logging.json -e LD_LIBRARY_PATH=/opt/score/lib \
    -v /var/tmp/score-sil:/opt/score:ro \
    --entrypoint /opt/score/bin/vp_standin localhost/score-sil:latest
