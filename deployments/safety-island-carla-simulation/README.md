# Safety Island CARLA simulation

CARLA 0.9.16 plus Autoware, with Safety Island as the controller. Actuation
is classic CAN from `autoware-safety-island`, not
`autoware_carla_interface.apply_control()`. Autoware's trajectory follower
stays running so Auto/Engage works.

**Safety Island guide:** that repository's
`documentation/user_guide/can_carla_closed_loop.rst`.

## Prerequisites

- Same as [CARLA Simulation](../carla-simulation/README.md) (amd64, NVIDIA
  Docker runtime, UDP buffers)
- `SAFETY_ISLAND_REPO` — absolute path to an `autoware-safety-island`
  checkout that contains `demo/carla-closed-loop/`

## Start

```bash
export SAFETY_ISLAND_REPO=/path/to/autoware-safety-island
./start.sh
```

Then from the Safety Island repository: `vcan0`, domain-bridge,
`freertos-posix --control-output CAN_ONLY`, and
`demo/can_carla_bridge/bridge.py --role ego_vehicle`.

Do not pass `--drive`. Do not start `carla-simulation` first and recreate
`carla-interface`. Set a goal in RViz and engage after the CAN path is live.
`start.sh` pins Humble `*-amd64-humble` images so RViz and Auto match the
layout CLI would inject.

## Stop

```bash
./start.sh --down
```
