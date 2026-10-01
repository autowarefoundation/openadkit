#!/bin/sh
# SIL twin of the demo si_fault component: latch the fault on the stub.
exec /usr/bin/systemctl kill -s USR1 score-sil-stub.service
