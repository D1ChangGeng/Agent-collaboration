# Owner startup and transport recovery

The selected Codex/OpenCode MCP command owns stdio startup. A stable
`acs_launcher.py --installation-root <root>` resolves the owner/machine-bound
active Release, then restores configured dependencies before executing its MCP
entry. SSH and WSL client descriptors enter the selected Runtime host first.

## Core dependencies

Recovery verifies the recorded private provider identity and the active
Release's Compose digest. It starts only that owner Compose project with
bounded readiness (`--wait`); it preserves PostgreSQL data, credentials,
Project/Root identities and Grants. Normal Runtime authentication still follows.
Startup does not adopt schema, bootstrap a new Grant or revive revoked access.
New service containers use `restart: unless-stopped`. Existing containers can
receive that policy only after their project/service ownership is read back.

Docker daemon availability is a machine prerequisite. For WSL without systemd,
Microsoft supports a per-distribution `[boot] command` such as
`/usr/sbin/service docker start`; preserve existing settings and backup before
changing this administrative option. It applies at the next distribution start.
A user-manager systemd unit cannot serve as the only recovery path when that
manager is offline. Do not stop a live distribution solely to verify startup.

## Transport supervision

Private SSH deployment records one owner-private profile containing its
allowlisted SSH target, private root/control socket and exact loopback port
forwards. Launch uses a per-profile gate and one supervisor lock. An existing
master is adopted only after process owner, control socket and configured target
and forwarding arguments match. SSH uses noninteractive authentication,
connection bounds and server-alive detection. A failed master reconnects under
monotonic bounded exponential backoff, capped at 30 seconds. Multiple Harness
starts share the same supervisor. Revoked SSH access/host-key failures remain
failures; recovery does not bypass host identity or credentials.

Secure MCP Tunnel has a separate owner-private startup profile referencing the
reviewed executable and digest, existing private Tunnel profile, PID and health
marker locations. Recovery validates the process executable, owner and profile
before adopting it. A dead client restarts with loopback admin/health endpoints,
without browser opening or credential output. Existing profile credentials stay
in their original protected storage. The Tunnel client's own polling handles
network reconnection while its process remains alive; supervision covers process
exit. Read `/healthz` and `/readyz` to distinguish process health from remote
readiness. Expired/revoked credentials require owner repair.

Local MCP startup requests web supervision independently of web readiness.
This avoids a dependency cycle when the Tunnel itself launches ACS stdio and
lets local collaboration remain available during a web outage.

## Configuration and maintenance

Bootstrap state preserves `startup.enabled` (default true), optional
`startup.ssh_profile_ref` and `startup.web_profile_ref` across activation.
The references point to private validated JSON profiles managed by the setup
Agent. Schema names are `acs-private-ssh-startup/1` and
`acs-secure-tunnel-startup/1`; the implementation in
[scripts/acs_startup.py](../../scripts/acs_startup.py) defines their exact fields.
Run the stable launcher with `--check-startup` for sanitized component readback.
Its ordinary stdio path prints no diagnostic stdout. Newly configured clients
receive a 120-second ACS initialization budget (`startup_timeout_sec=120` for
Codex, local MCP `timeout=120000` for OpenCode tool discovery). Preserve larger
owner settings and distinguish this startup budget from task/caller waiting.
An existing client needs the same reviewed connection-budget maintenance.

A released version must contain the recovery helper in its manifest. Older
versions keep their existing selection/compatibility path and need guided
maintenance before obtaining recovery. An owner-maintained private integration
entry may invoke the same reviewed helper without rewriting immutable Release
files or changing installed Runtime/overlay compatibility pins. Record its
helper digest and backup the former entry and state first.

## Verification scope

Check a missing master, repeated concurrent launches, an owned test master exit,
restart/reconnect, authentication loss, tampered paths/binaries and Core service
readiness. Use an isolated test profile and ports for fault injection; preserve
production sessions. Read actual MCP discovery and `read_profile` through the
configured entry. A configured boot command is not evidence of an actual
machine reboot. Keep host/version/channel evidence for the run that measured it.

Official references: [WSL boot settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
