# Example kit fixture

What CI puts on top of `openadkit new example-kit` (validation_matrix.py
`make_example_kits`) to exercise every kit extension point against a build:
settings in `settings.env`, a parameter override in `config/autoware/`, a C++
package and the kit's own vehicle and sensor kit packages in `overlay_ws/`, a
pinned external image (`external-images.json`, merged into the kit's
`openadkit.json`), and services with a healthcheck in the Compose file of its
first deployment, `deployments/example-kit-planning-simulation/compose.yaml`.
The kit runs Planning Simulation's verify step, then `checks/dev_loop.sh`: it
changes the C++ package, builds it, restarts and sees the change (evidence
level L3).

A second deployment, `example-kit-logging-simulation`, shares the kit's files
on another base. It has no Compose file, so it runs its base's services, and
its own `settings.env` wins over the kit's. The cells validate it; they do not
run it.
