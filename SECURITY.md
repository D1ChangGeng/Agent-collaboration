# Security Policy

## Scope

This project writes collaboration scaffolding into repositories and may create Skill symlinks/copies in user configuration directories.

## Safety requirements

- Never store credentials, session tokens, SSH keys, API keys, or private remote-access secrets in `.agents/`.
- Never use destructive Git reset/clean operations as part of setup.
- Never overwrite unrelated content in `AGENTS.md`, `CLAUDE.md`, or `.gitignore`.
- Never claim a cross-session message was delivered without runtime evidence.
- Never commit local capability observations from `.agents/runtime/` as universal project truth.
- Treat symbolic links carefully and never follow arbitrary project symlinks when deleting managed files.

## Reporting

Open a private security advisory in the GitHub repository when available. Avoid posting active credential exposure in a public issue.
