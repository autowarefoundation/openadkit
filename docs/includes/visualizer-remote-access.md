Open `http://localhost:6080/vnc.html` and sign in with the default password
**`openadkit`**. To use your own, set `REMOTE_PASSWORD` in the host settings
file, `~/.config/openadkit/<deployment>.env`.

The visualizer listens on loopback only. For a remote host, forward the port
over SSH and open `http://localhost:8080/vnc.html` locally:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```
