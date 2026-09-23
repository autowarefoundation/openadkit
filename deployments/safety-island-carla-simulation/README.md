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
- An `autoware-safety-island` checkout for the host CAN bridge and SI binary.
  The deployment, overlay, and domain-bridge live entirely in Open AD Kit.

## Start

```bash
cd ../..
./openadkit run safety-island-carla-simulation --gpu
```

Or from this directory: `./start.sh` (wraps the CLI).

Then from the Safety Island repository: `vcan0`,
`freertos-posix --control-output CAN_ONLY --dds-interface lo`, and
`demo/can_carla_bridge/bridge.py --ego-role ego_vehicle`.

The domain-bridge and sensors-only overlay are part of this deployment.
The image references in `config.env` are digest-pinned; record the Open AD Kit
commit (`git rev-parse HEAD`) alongside the Safety Island commit for a
repeatable run. The privilege-free contract test is
`python3 deployments/safety-island-carla-simulation/test_contract.py`.

Do not pass `--drive`. Do not start `carla-simulation` first and recreate
`carla-interface`. Set a goal in RViz and engage after the CAN path is live.

## Stop

```bash
./openadkit stop safety-island-carla-simulation
```
