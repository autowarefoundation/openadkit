#!/bin/sh
# SIL twin of scripts/x5h-score-camera.sh. The trap gives PID 1 a SIGTERM
# handler; it runs within one second because sleep 1 returns first.
exec /usr/bin/systemd-cat -t sil-camera /usr/bin/podman run --rm --replace --name sil-camera \
    --network=host --cgroups=split --log-driver=passthrough --pull=never \
    --entrypoint /bin/sh localhost/score-sil:latest \
    -c 'trap "exit 0" TERM; while :; do sleep 1; done'
