---
name: agent-collaboration-setup
description: Install, adopt, configure, validate, repair, upgrade, or remove ACS global services and project Management Roots, including local Harness MCP entries and remote web connection setup.
---

# Agent Collaboration Setup

This is the P2 setup Skill contract. Runtime installation packages activate it
after the global installer, project-adoption service and connection validators
pass their Gates. The current source checkout also exposes a guarded local
dependency setup and readiness report. The installer establishes a private
owner Authority, registers a clean committed project Source when supplied, and
reports the remaining MCP client checks.

Canonical mechanisms: release digest verification, local install preview and
apply, project setup CLI, read_profile, list_projects, list_connections and
load_project. The release signature profile is admitted separately when
published and verified.

1. Inspect the current global ACS installation, configured Harnesses, project
   target and requested local or web access.
2. Download the selected release from the authorized distribution source and
   verify its signature or published digest.
3. On the Linux Runtime host, install or upgrade the local ACS dependencies and
   Skills; initialize the Runtime authority and bind scoped credentials through
   a reviewed operator profile before reporting the MCP service ready.
4. Detect Codex and OpenCode on their admitted client hosts and configure their
   MCP connections to the same Runtime. Treat other Harnesses as separate
   admitted profiles.
5. Adopt the project once. Preserve or create project_id, Management Root,
   manifest, AGENTS managed block, Routes, knowledge and SourceBindings.
6. Validate that AGENTS and the manifest carry the same Project identity.
7. Configure the selected remote HTTPS or private-Tunnel MCP profile. For the
   single-user private Tunnel, retain the owner's existing ACS Grant and bind
   a local stdio process. For remote HTTPS, configure OAuth metadata. Present
   current SaaS account and authorization actions to the user.
8. Validate read_profile, list_projects and load_project from each admitted
   client type.
9. Record created or changed files, service state, endpoint identity, credential
   references, rollback data and remaining user action.

Normal project work proceeds through the installed AGENTS context, runtime
Skills and MCP tools. Setup is invoked again for installation maintenance,
project adoption, connection changes, validation, repair, upgrade or removal.
