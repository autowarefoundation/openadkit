#!/usr/bin/env bash
# Stand-in for x5h-si-link: prints the wall clock at each SIGUSR1. bash runs
# the trap after the current sleep, so the time is late by at most 10 ms.
trap 'echo "SIL_STUB_FAULT at=$(date +%s.%N)"' USR1
while :; do sleep 0.01; done
