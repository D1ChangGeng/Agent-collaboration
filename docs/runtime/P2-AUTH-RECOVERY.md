# Linux Codex authentication recovery

Current read-only evidence on `1302-1`:

- Codex CLI: `0.153.2`.
- `codex login status`: exit 1, logged in = false.
- Device authorization HTTP 403: reported by the task, not repeated by this
  harness.
- No credential material was read or copied.

Do not retry device authorization as part of an automated P2 run. Authentication
requires the user to perform normal OAuth interactively:

1. Start a persistent tmux session on Linux and invoke normal `codex login`.
2. Read the localhost callback port and authorization URL shown by that command.
3. From Windows, open an SSH local-forward tunnel to the exact Linux callback:
   `ssh -N -L <windows-port>:127.0.0.1:<linux-callback-port> 1302-1`.
4. The user opens the displayed authorization URL in their Browser and completes
   authentication. Credentials and callback query values must not be pasted into
   the runbook, evidence bundle or chat.
5. Keep the tunnel until the Linux command reports completion, then close only
   that tunnel.
6. Run `codex login status` on Linux in a fresh process and record only the
   boolean result, CLI version, timestamp and evidence SHA.

Browser interaction and account authorization are human actions. The harness
does not launch the Browser, approve OAuth or consume login tokens. Until the
fresh status is true, Codex P2 scenarios remain `NOT_RUN`.
