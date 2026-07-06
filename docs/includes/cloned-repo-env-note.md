!!! warning "Cloned repository"
    If running from a cloned repository rather than a release bundle, prepend `--env-file ../base/base.env` to **every** `docker compose` command on this page. Release bundles merge both env files into one; from a clone you need both so shared variables such as `ROS_DOMAIN_ID` and `REMOTE_PASSWORD` resolve.
