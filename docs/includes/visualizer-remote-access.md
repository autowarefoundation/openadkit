## Open the Visualizer

Open `http://localhost:6080/vnc.html` and sign in with the default password
**`openadkit`**. Set your own
`REMOTE_PASSWORD` in `~/.config/openadkit/<deployment>.env`.

For a remote host, forward the port over SSH and open
`http://localhost:8080/vnc.html` locally:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```
