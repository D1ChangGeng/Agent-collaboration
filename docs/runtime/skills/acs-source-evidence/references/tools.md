# Source and evidence tool map

- list_sources reports repository/version hints, provider capabilities,
  current_readable_root and origin_hint.host/path.
- read_source reports observed repository/branch/workspace state and selected
  view identity; owner actual_source supplies the captured readback fields.
- list_files, search_files and read_file read the selected filesystem view.
- read_diff compares two explicit captured commit or workspace revisions.
- list_evidence and read_resource inspect recorded claims and exact evidence.
- Source-write tools use the optional surface actually exposed by the service.

Owner read_source, read_file, list_files and search_files can omit
source_id/revision. The service resolves a product repository Source.
primary_source_id selects the Project product hint; primary_source_root gives
the preferred repository location used to resolve its physical primary checkout.
Explicit source_root selects a configured readable current worktree.
Explicit revision selects already captured bytes.

Owner results include actual_source with provider, root, commit, tree,
view_revision and observed_at. Record its actual identity with repository,
branch and workspace observations. current_readable_root is the Core provider's
reported reading location. origin_hint.host/path remains repository guidance.
Existing Native, Git and repository MCP tools keep their own readable locations
and access contracts; the Agent can select those tools directly.

Owner load_project.source_observation refers to product source.
management_source_observation retains distinct management context. A missing
product default leaves product observation and its primary/version-hint
references null; explicit management reads remain available. Routine context
follow-ups use current views and version hints. Pagination continues at the
returned view_revision.

read_message retrieves terminal native content from Core Scope CAS. Missing
bytes use signed delivery.readback with original Dispatch and digest identity.
check_inbox prepares response references. Verified historical results keep
their cached Artifact and provenance.

Core filesystem roots, path normalization, tenant/Scope ownership, revocation,
secrets, byte bounds and digest checks remain effective. Shared mode retains
its established access/version and exact snapshot inputs. Source reading,
execution placement, Message delivery and Git synchronization have separate
observations.
