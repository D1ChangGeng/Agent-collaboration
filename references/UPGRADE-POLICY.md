# Upgrade Policy

## Principle

Skill updates and project protocol upgrades are intentionally separate.

Pulling a new version of this Skill must never silently rewrite projects that already use ACHP.

## Managed vs project-owned files

### Setup-managed

These may be replaced during `upgrade`:

- ACHP managed block in `AGENTS.md`
- ACHP managed block in `CLAUDE.md`
- ACHP managed block in `.gitignore`
- `.agents/README.md`
- `.agents/protocol/*`
- `.agents/coordination/roles/*`
- `.agents/coordination/templates/*`
- `.agents/knowledge/README.md`

### Project-owned

These are created if missing and then preserved during upgrades:

- `.agents/config.yaml`
- `.agents/coordination/PROJECT.md`
- `.agents/coordination/tasks/*`
- `.agents/coordination/handoffs/*`
- `.agents/knowledge/guides/*`
- `.agents/knowledge/decisions/*`
- `.agents/knowledge/observations/*`
- `.agents/knowledge/archive/*`
- `.agents/runtime/*`

## Upgrade steps

1. Preview with `--dry-run`.
2. Review version/changelog impact.
3. Run `upgrade`.
4. Validate.
5. Review Git diff.
6. Commit as a distinct protocol/setup change.
7. Relay repository sync requirements to other active clones/sessions.

## Backward compatibility

Breaking changes to:
- relay envelope schema;
- task/handoff semantics;
- knowledge location;
- repository sync contract;

must be documented before release and should include a migration strategy.

## Uninstall

Default uninstall removes only setup-managed files/blocks and preserves project-owned collaboration/knowledge data.

`--purge-data` is intentionally explicit and destructive.
