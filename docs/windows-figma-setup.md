# Windows — one-time Figma MCP bridge for claude-yolo / WSL2

`claude-yolo` (and any AI Agent session running inside WSL2 or Docker) needs
to reach the Figma Dev Mode MCP server, which Figma Desktop binds to
**Windows' `127.0.0.1:3845`**. That loopback isn't reachable from inside
WSL2 or a Docker container without a one-time `netsh portproxy` rule that
republishes the port on `0.0.0.0`, plus a firewall allow rule.

This setup applies to **Windows + WSL2** — running `claude` or `claude-yolo`
from a WSL2 shell (the only supported Windows configuration; see the README).

## Prerequisites

- Figma Desktop running, with Dev Mode MCP server enabled (Figma →
  Preferences → "Enable local MCP Server").
- Docker Desktop installed.
- **WSL2** with a Linux distro (Ubuntu recommended).

## Apply the bridge (one time, as Administrator)

Open **PowerShell as Administrator** and run:

```powershell
netsh interface portproxy add v4tov4 listenport=3845 listenaddress=0.0.0.0 connectport=3845 connectaddress=127.0.0.1
netsh advfirewall firewall add rule name="Figma MCP" dir=in action=allow protocol=TCP localport=3845
```

The portproxy survives reboots; you only run it once per machine.

## Verify

From a WSL2 shell:

```bash
curl -sf "http://$(ip route | awk '/default/{print $3; exit}'):3845/sse" | head -1
```

You should see a streaming-response header, not a connection error.

Inside `claude-yolo` (after launching), the same check uses
`host.docker.internal`:

```bash
curl -sf http://host.docker.internal:3845/sse | head -1
```

## Undo

```powershell
netsh interface portproxy delete v4tov4 listenport=3845 listenaddress=0.0.0.0
netsh advfirewall firewall delete rule name="Figma MCP"
```

## Notes

- If you change Figma's MCP port from the default `3845`, replace both
  occurrences of `3845` above with your port.
- WSL2 has an alternative path — `[wsl2] networkingMode=mirrored` in
  `%USERPROFILE%\.wslconfig` — which makes the bridge unnecessary for WSL2
  use but does not help the claude-yolo (Docker) case. The `netsh portproxy`
  bridge above covers both.
