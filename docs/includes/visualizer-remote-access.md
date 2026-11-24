Open the address `run` prints,
`http://localhost:6080/vnc.html?resize=remote&autoconnect=true`, and sign in
with the default password **`openadkit`**. `resize=remote` makes the desktop
follow your browser window; without it the desktop stays at 1024x768. To use your own, set `REMOTE_PASSWORD` in the host settings
file, `~/.config/openadkit/<deployment>.env`.

The visualizer listens on loopback only. For a remote host, forward the port
over SSH and open the same address on port 8080 locally:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```
