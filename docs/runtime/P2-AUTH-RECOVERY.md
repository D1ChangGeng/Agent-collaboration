# Linux Codex authentication recovery

The current P2 profile uses the reviewed `zeo-dev` API provider. It does not
require Linux Codex OAuth login. The provider reference is a secret path only;
the harness never reads or copies the referenced secret value.

For this profile, record only the provider alias, model, HTTPS base URL, wire
API, auth command and a boolean probe result. `configured` is still blocked;
only a fresh `verified` probe can clear the authentication prerequisite. The
probe must redact response bodies and secret-like values and retain only its
exit status, observed model/provider identity, timestamp and evidence digest.

The OAuth procedure below remains applicable only when an execution profile
explicitly selects `linux_codex_auth_mode=oauth`.

Current read-only evidence on `1302-1`:

- Codex CLI: record the exact installed version in the fresh observation.
- For `api_provider`, `codex login status` is informational and must not be used
  as the readiness predicate.
- For `oauth`, record the boolean login result without collecting credentials.
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
