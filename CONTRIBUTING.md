# Contributing

Contributions are welcome.

## Boundary to preserve

The most important architectural rule is that this repository contains a **setup-only Skill**.

Do not move normal collaboration behavior back into `SKILL.md`.

Runtime collaboration belongs in the project files installed by the Skill, primarily:

- `AGENTS.md`
- `.agents/protocol/`
- `.agents/coordination/`
- `.agents/knowledge/`

## Compatibility rule

Do not add a harness-specific behavior to the protocol core merely because one harness supports it.

Model the capability generically first, then add an optional adapter or compatibility route.

## Changes

Before opening a pull request:

```bash
python3 scripts/validate_skill.py
python3 -m unittest discover -s tests -v
```

When scaffold semantics change:

1. update `VERSION`;
2. update `CHANGELOG.md`;
3. update managed templates;
4. add/adjust tests;
5. document upgrade impact in `references/UPGRADE-POLICY.md` when necessary.

## Pull request expectations

Explain:
- the problem;
- why it belongs in setup rather than runtime (or vice versa);
- compatibility impact;
- migration/upgrade impact;
- tests performed.
