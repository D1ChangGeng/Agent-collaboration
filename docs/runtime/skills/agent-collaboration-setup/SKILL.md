---
name: agent-collaboration-setup
description: Install, adopt, configure, validate, repair, upgrade, or remove ACS global services and project Management Roots, including local Harness MCP entries and remote web connection setup.
---

# Agent Collaboration Setup

This is the P2 setup Skill contract. Runtime installation packages activate it
after the global installer, project-adoption service and connection validators
pass their Gates.

Canonical mechanisms: signed release installer, project setup CLI, read_profile,
list_projects, list_connections, load_project.

1. Inspect the current global ACS installation, configured Harnesses, project
   target and requested local or web access.
2. Download the selected release from the authorized distribution source and
   verify its signature or published digest.
3. Install or upgrade one global ACS service, CLI, local Node and MCP entry.
4. Detect Codex, Claude Code and OpenCode and configure their global MCP
   connection to the same installation.
5. Adopt the project once. Preserve or create project_id, Management Root,
   manifest, AGENTS managed block, Routes, knowledge and SourceBindings.
6. Validate that AGENTS and the manifest carry the same Project identity.
7. Configure the selected remote HTTPS or secure-Tunnel MCP path and OAuth
   metadata. Present the exact SaaS callback and consent steps to the user.
8. Validate read_profile, list_projects and load_project from each admitted
   client type.
9. Record created or changed files, service state, endpoint identity, credential
   references, rollback data and remaining user action.

Normal project work proceeds through the installed AGENTS context, runtime
Skills and MCP tools. Setup is invoked again for installation maintenance,
project adoption, connection changes, validation, repair, upgrade or removal.