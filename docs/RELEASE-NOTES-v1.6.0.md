# Agent Collaboration System v1.6.0

2026-10-14

ACS v1.6.0 reads project management context from current files on the selected
machine and lets Agents choose the source version appropriate to each WorkItem.
Project and Route registrations preserve durable identity while recording the
current location of their management documents.

## Current project files

Owner registration supports Management Roots inside Git checkouts and
authorized standalone directories. Paths use the selected machine's OS
namespace and connected account permissions.

`load_project` reads configured instructions and knowledge indexes from that
machine's current files. Its context reports the management machine/path,
observed document paths, observation times, inline content hashes, completeness
and missing context. Larger documents provide an ordinary `read_file`
follow-up.

Use `configure_project` with the current Project revision to set or replace
`management`, `instruction_paths` and `knowledge_index_paths`.
`management: null` clears the saved location. A single `load_project` call can
select `machine_id` and `management_path` for that read. Location changes
preserve Project and Root identity.

Ordinary machine files use `read_file`, `list_directory`, `glob`, `grep`,
`write_file`, `edit_file` and `apply_patch`. Each call can select a machine
and directory. OS account permissions, text and binary pagination, and the
Local, SSH and signed Node file services apply to current file access.

## Choosing a work version

An Agent chooses the source version needed by its task through an available
machine, native tool, Git or repository reader, then records the source it
actually observed. Owner `WorkItem.source_baseline` is optional: omission or
null leaves that choice open. An eligible `revise_work` can select a version,
replace it or clear it with null.

Owner Attempts can report the execution's actual source version through
authenticated execution receipts after execution. Review and acceptance record
the Agent's inspected `source_readback.commit` and `source_readback.tree` and
compare them with the exact candidate, recorded Evidence and execution
receipts. Relevant local edits and workspace state belong in the candidate's
Evidence.

Candidate consistency, Evidence integrity, Reviewer and Finalizer independence,
trusted identity, request deduplication, expected revisions and explicit
revocation govern these operations. Existing completed facts retain their
recorded source, author, identity and digests.

## Recorded Source history

`list_sources` discovers recorded Source IDs and captured views. Historical
reads select both `source_id` and `revision` through `read_source`,
`read_source_file`, `list_source_files` or `search_source_files`.
`read_diff` selects `source_id`, `base_revision` and `target_revision`.
Pagination retains the captured `view_revision` and source identity.

Shared deployments retain their configured Source, permission, version and
acceptance contracts. Historical records preserve the configuration and
reference Profile that produced them.

## Schema migration

Domain schema 1.14 has a formal migration from the known schema 1.13 identity.
It permits optional source baselines in work, Review and accepted-state records
while preserving existing source values, candidates and Evidence.

Project schema version 1 recognizes both exact checksums of the previous
schema bytes:

| Prior schema bytes | SHA-256 |
| --- | --- |
| Linux/Git source with LF line endings | `ccad2138f9ed4cddbe2e7e30ed797b4ead75d3c1359e4401997906e1233bfa3a` |
| Windows Release assets with CRLF line endings | `6fedb1731cde6224c0ec4770d7d5b18580d60554e9ef7b82739679b9bcfc0440` |

The known migration allows an optional Review request baseline and updates the
recorded schema checksum after application. An unknown schema identity requires
explicit migration review. See
[Runtime adoption](runtime/UPGRADE-CONTRACT.md#current-file-context-and-work-version-migration)
for the schema contract.

## Install or upgrade

Start with `acs_bootstrap.py` and `SHA256SUMS.txt` from the verified
[v1.6.0 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.6.0).
Use `--version v1.6.0` and the confirmed Runtime host, machine/account/home
binding, selected clients and web choice.

Existing installations use a guided upgrade for the Runtime schema and MCP
catalog transition. The Agent verifies the Bootstrap and Release digests,
previews and applies the known migration, preserves identities, configuration,
credentials, keys, explicit revocation, recorded history and rollback data,
then verifies actual services and connections. The upgrade preserves the
existing automatic update policy. New installations enable automatic
upgrades by default; future compatible releases follow the recorded policy.

After activation, reconnect Codex/OpenCode and verify `tools/list`,
`read_profile.access_mode`, `list_projects`, owner `filesystem_context` and a
representative `load_project` read of current files. Refresh setup and knowledge
Skills on separate client hosts through client maintenance. For ChatGPT,
restart the configured Tunnel/MCP process, select **Refresh** on its existing
connection in ChatGPT Plugins, and verify the refreshed tools in a new chat.

Before rolling back across a schema change, confirm application and database
compatibility and retain configuration backups. The
[getting started guide](GETTING-STARTED.md) and
[automatic upgrade guide](AUTOMATIC-UPDATES.md) provide the complete flow.

## Startup recovery and release versions

The release carries forward owner Core recovery, configured SSH and Tunnel
supervision, and Windows/WSL login recovery from v1.5.3. The Windows GUI host
runs the selected recovery process in the background; existing task migration
verifies the installation's maintainer and completes the recovery-lock handoff.
Use the verified Release helper and read back the task, services and selected
client connections as described in [startup recovery](runtime/STARTUP-RECOVERY.md).

Distribution v1.6.0, Runtime package v0.2.0 and setup Skill v0.4.0 are
independently versioned. ACHP Workspace schema remains 0.3.
The distribution retains [Sustainable Use License 1.0](../LICENSE).

## Verification scope

Release verification exercises project context from current files, standalone
registration, optional work baselines, authenticated execution receipts,
candidate Review and acceptance, migration from known schemas, shared compatibility
and setup behavior through component and PostgreSQL suites. Each installation's
active version, schema, service health and client capability are established by
its own readback after upgrade.
