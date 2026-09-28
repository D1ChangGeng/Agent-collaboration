# Agent Collaboration System v1.1.0

This release adds a standard verified installation path for fresh machines and
controlled upgrades.

## Highlights

- Release Bootstrap downloads a selected GitHub Release and verifies
  `SHA256SUMS.txt` before extracting it.
- Embedded file manifests verify the source commit, tree and every packaged
  file before installation.
- Versioned private installation directories keep the active and previous
  release available for controlled rollback.
- Runtime setup continues from the verified Release directory, then performs
  local service setup, project registration, MCP configuration and readback.
- ZIP/TAR path safety, tamper detection, symlink protection and installer
  behavior are covered by tests and hosted CI.

## Installation

Give the public repository or Release link to Codex/OpenCode and ask the Agent
to use the versioned Release Bootstrap. The Agent reports the selected release,
archive digest, installed commit/tree, active version, previous version and
remaining user authorization steps.

The project retains Sustainable Use License 1.0.
