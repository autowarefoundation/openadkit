#!/bin/sh
# SIL twin of scripts/x5h-score-camera.sh. The trap gives PID 1 a SIGTERM
# handler; wait returns as soon as the signal arrives, so it stops at once,
# like the real camera node.
exec /usr/bin/systemd-cat -t sil-camera /usr/bin/podman run --rm --replace --name sil-camera \
    --network=host --cgroups=split --log-driver=passthrough --pull=never \
    --entrypoint /bin/sh localhost/score-sil:latest \
    -c 'trap "exit 0" TERM; while :; do sleep 1 & wait $!; done'
