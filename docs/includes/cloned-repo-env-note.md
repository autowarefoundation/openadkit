!!! info "Environment file ordering"
    Commands on this page pass `--env-file ../base/base.env` before the deployment env file. The base file provides shared defaults; the deployment file overrides them. Release bundles merge both into one file so they use a single `--env-file`.
