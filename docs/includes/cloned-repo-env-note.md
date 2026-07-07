!!! info "Environment file ordering"
    **From a cloned repository** — pass `--env-file ../base/base.env` before the deployment env file (as shown in the commands on this page). The base file provides shared defaults; the deployment file overrides them.

    **From a release bundle** — omit `--env-file ../base/base.env`; the bundle's env file already contains the merged defaults. Run: `docker compose --env-file <name>.env up -d`
