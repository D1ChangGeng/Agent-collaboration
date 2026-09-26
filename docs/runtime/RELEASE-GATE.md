# v1.0.0 release gate

This is the engineering release checklist for the frozen candidate. It keeps
source, CI, package, product review and publication state as separate facts.

## Frozen candidate

- Candidate branch: `codex/p2-v1-release`
- Target release: `v1.0.0`
- License: Sustainable Use License 1.0
- Publication order: product-owner approval → merge to `main` → annotated tag → GitHub Release → asset download and install readback.

## Automated preflight

Run from the candidate checkout:

```text
uv run --frozen python scripts/release_preflight.py --json
```

The preflight requires a clean pushed candidate, public repository visibility,
successful CI for the exact commit, matching open PR, absent `v1.0.0` tag and
Release, selected license text, and reproducible package manifest identity.

## Evidence already available

- Local setup, Runtime, Project registration, MCP, Team and WorkItem checks on
  Linux `1302-1`.
- Codex and OpenCode MCP SDK handshakes with 36 discovered tools.
- CI matrix for Python 3.9, 3.11 and 3.12, Runtime tests, Gate tooling tests
  and package assembly.
- Source-bound ZIP/TAR assets with SHA-256 manifest.

## Product review boundary

The formal P2 Control Parity record, current-candidate independent review,
ChatGPT private Tunnel journey and product-owner decision remain separate from
this automated preflight. Historical or fixture evidence is retained with its
original source and expiry and cannot be promoted by this document.

## Final owner action

When the product owner has reviewed the preflight and current P2 evidence,
record the release approval. The release operator then performs the publication
sequence and reads back the merged commit, tag, Release assets and installation
identity.
