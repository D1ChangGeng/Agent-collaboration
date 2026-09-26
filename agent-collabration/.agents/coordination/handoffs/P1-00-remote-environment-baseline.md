# P1-00 Remote Environment Baseline — Read-only Evidence

- Observed at: 2026-09-10 (Asia/Shanghai)
- Scope: read-only endpoint, repository, Git, permissions, tool/runtime inventory
- Target label: `1302-1`
- SSH method: `ssh -o BatchMode=yes -o ConnectTimeout=...`
- Remote mutation: none

## Endpoint and SSH

- SSH config resolves `1302-1` to user `changgeng`, host `10.108.25.251`, port `22`.
- BatchMode SSH succeeded.
- Remote host: `yue-Precision-3680`.
- Identity: `uid=1005(changgeng) gid=1005(changgeng)`; groups include `sudo`, `docker`.
- OS/kernel: Ubuntu host, Linux `6.11.0-17-generic`, x86_64.
- Home: `/home/changgeng`.
- Every SSH probe emitted: `Warning: remote port forwarding failed for listen port 7890`. Command execution still succeeded. Treat forwarding capability as unresolved/risk.

## Requested repository path

- Requested path: `/home/changgeng/Agent-collaboration`.
- Direct stat/access result: **missing**; no repository or permissions can be established at that exact path.
- Actual similarly named path: `/home/changgeng/Agent-collabration` (double `r`).
- Actual path mode/owner: `775`, `changgeng:changgeng`; user has `rwx`.
- This spelling mismatch is a source-binding risk. Do not silently treat the actual path as the requested path.

## Git state at actual path

Observed in `/home/changgeng/Agent-collabration`:

- Top-level: `/home/changgeng/Agent-collabration`
- Branch: `main`
- HEAD: `8033d306dbc50f26ee49d5591f871fc73e684a27`
- HEAD tree: `b91afcc04ce11356b69c512dc61d0828da2119ed`
- Working tree summary: `## main...origin/main` (no additional dirty entries observed)
- Remote fetch/push: `https://github.com/D1ChangGeng/Agent-collaboration.git`
- Upstream: `origin/main`
- Ahead/behind: `0/0`
- `git ls-remote --heads origin` returned `8033d306dbc50f26ee49d5591f871fc73e684a27 refs/heads/main`.
- No push or mutation was performed.

## Permissions

- `/home/changgeng`: `rwx` for `changgeng`.
- Actual `/home/changgeng/Agent-collabration`: `rwx` for `changgeng`.
- Requested `/home/changgeng/Agent-collaboration`: absent, therefore permission state is not applicable (report as missing, not denied).

## Toolchain

Default non-login PATH observation:

- `/usr/bin/node`: v18.19.1
- `/usr/bin/npm`: 9.2.0
- `pnpm`, `codex`, `opencode`, `temporal`, `psql`, `pg_isready`: not found in default PATH

With explicit PATH prefix `/home/changgeng/.nvm/versions/node/v24.11.1/bin:/home/changgeng/.opencode/bin`:

- Node: v24.11.1
- npm: 11.6.2
- pnpm: 10.30.2
- Codex CLI: `codex-cli 0.153.2`
- OpenCode: `1.18.29`
- Git: 2.43.0
- Docker: 29.1.2

## Temporal and PostgreSQL observations

- No host `temporal`/Temporal CLI or `psql`/pg_isready binary found.
- Local TCP probes: 127.0.0.1:5432 open; 7233 open; 7234 and 8233 closed/filtered.
- Running containers include:
  - `alpha-temporal-1291`: `temporalio/auto-setup:1.29.1`, Up 2 days, 127.0.0.1:7333 -> 7233.
  - `alpha-temporal`: `temporalio/auto-setup:1.29.0`, Up 2 days, **unhealthy**, 127.0.0.1:7233 -> 7233.
  - `alpha-temporal-postgres`: `postgres:16`, healthy.
  - Other PostgreSQL containers observed: `b1proof-pg`, `alpha-postgres-test`, `alpha-postgres`, and unrelated `finsight-postgres:15-alpine`.
- Temporal CLI/SDK version and service-level health contract were not directly measured. Container image tags are the available version evidence.

## Runtime/process observations

- User services include research API/web/worker.
- Running process inventory includes Temporal server, PostgreSQL, OpenCode, Codex app-server, and Node 24 workloads.
- This proves process/container presence only; it does not establish P1 Driver conformance, Harness session binding, or cross-machine delivery support.

## Unknowns and risks

1. Exact intended source path is unresolved because the requested single-r path is absent and the existing repo uses double `r`.
2. SSH port-forward listen 7890 is unavailable/conflicted; end-to-end transport capability is not established.
3. Default PATH selects Node 18 and hides Node 24/pnpm/Codex/OpenCode; commands must use explicit PATH or absolute paths.
4. Two Temporal auto-setup containers exist; the 1.29.0 instance is unhealthy while 1.29.1 is running. Active provider/namespace/endpoint is not established.
5. Host PostgreSQL/Temporal CLIs are absent; database/provider versions are inferred only from running container image tags.
6. No direct evidence yet for Node enrollment, Runtime Driver lifecycle, Message/Receipt, Lease/Fencing, or P1/P2 acceptance.

## Commands used (bounded, read-only)

- `ssh -G 1302-1`
- SSH endpoint identity probe (`hostname`, `id`, `uname`, `pwd`)
- Bounded remote `stat`, `test`, `git rev-parse`, `git status`, `git remote`, `git ls-remote`
- Bounded command/path version probes
- `systemctl --user` service listing
- `pgrep`, `/proc/*` executable/cmdline reads
- `docker ps`, `docker inspect`
- Local TCP connect checks to 5432/7233/7234/8233

No remote file, process, service, container, Git ref, or configuration was changed.

