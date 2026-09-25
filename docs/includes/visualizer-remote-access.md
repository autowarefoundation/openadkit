## Open the Visualizer

Open `https://localhost:6080/vnc.html`, accept the self-signed certificate, and
sign in with the default password **`openadkit`**. Set your own
`REMOTE_PASSWORD` in `config.local.env`.

For a remote host, forward the port over SSH and open
`https://localhost:8080/vnc.html` locally:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```
