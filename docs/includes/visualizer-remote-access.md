## Access the Visualizer

Open your browser and navigate to:

```text
https://localhost:6080/vnc.html
```

Use the default password **`openadkit`**. The connection uses a self-signed certificate; dismiss the browser privacy warning to continue.

!!! tip "Remote Access"
    The visualizer runs under `network_mode: host`, so `ports:` is ignored and the loopback bind (`127.0.0.1:6080`) lives in the visualizer entrypoint. To reach noVNC from another machine, either forward the port over SSH:

    ```bash
    ssh -L 8080:localhost:6080 <user>@<host>
    # then open https://localhost:8080/vnc.html
    ```

    or put a TLS-terminating reverse proxy in front of `127.0.0.1:6080` and set a strong `REMOTE_PASSWORD` in `base.env`. Editing `docker-compose.yaml` to add a `ports:` mapping has no effect under host networking.
