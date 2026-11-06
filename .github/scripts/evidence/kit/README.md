# Example kit fixture

What CI puts on top of `openadkit new custom-kit` (validation_matrix.py
`make_example_kits`) to exercise every kit extension point against a build:
a value in `config.env`, a parameter override in `config/autoware/`, a C++
package in `overlay_ws/`, a pinned artifact (`artifacts.json`, merged into the
kit's `openadkit.json`), and services with a healthcheck in
`docker-compose.yaml`. The kit runs Planning Simulation's verify step.
