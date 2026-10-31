# acs-source-evidence: tools

Use the actual exposed tools; retain returned handles instead of constructing internal routing identities.

- `list_sources`
- `read_source`
- `read_diff`
- `read_file`

Source provenance and actual file access. ACS messages carry references, not repository synchronization.

Exact arguments and observed effects come from the running tool schema. Historical input, when needed for a transition, is in [the v6 archive](legacy-v6-tools.md); it is not the current communication contract.
