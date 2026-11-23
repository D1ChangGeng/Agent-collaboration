# ACS v2.3.2

ACS v2.3.2 consolidates Porpita native attachment and conversation-history
runtime support, Porpita Desktop UI SPEC verification crosswalks, and `Validate ACS`
CI repairs on top of v2.3.1.

## What Changed Since v2.3.1

- **Porpita Native Delivery & Newest-First Message Paging**:
  - Added `runtime/native_attachment_delivery.py`, durable native source link
    and artifact recovery updates across `runtime/artifacts.py`,
    `runtime/communication.py`, `runtime/communication_dispatch.py`,
    `runtime/communication_native_link_storage.py`, `runtime/delivery.py`,
    `runtime/orca_receiver_backend.py`, `runtime/receiver.py`, and
    `runtime/receiver_delivery.py`.
  - Added optional `order=oldest|newest` cursor-fenced paging on
    `GET /api/communication/v1/projects/{project_id}/messages`
    (`runtime/communication_http.py`, `runtime/communication_client_service.py`),
    preserving the default `oldest` cursor namespace for existing clients.
  - Added unit and PostgreSQL regression coverage in
    `runtime_tests/test_communication_http_queries.py`,
    `runtime_tests/test_delivery_selection_timezone.py`,
    `runtime_tests/test_native_attachment_host_delivery_pg.py`, and
    `runtime_tests/test_native_attachment_host_port.py`.
- **Porpita Desktop UI SPEC & Crosswalk Archive**:
  - Archived `docs/client/porpita-ui-spec/` (M1–M5 iterations, design evidence,
    coverage closure), updated `docs/client/ORCA-FIRST.zh-CN.md` crosswalks,
    and added client HTTP/SSH/P1 contracts and portable E2E suite baselines.
- **`Validate ACS` CI Repairs**:
  - Updated `.github/workflows/validate.yml` (`runtime` job) to checkout full
    git history (`fetch-depth: 0`) required by
    `runtime_tests/test_message_attachment_packet.py`.
  - Updated `runtime_tests/test_mcp_component_fixture.py` to pass explicit
    `"limit": 500` when listing the `runtime/` tree (>100 entries).
  - Updated `runtime_tests/test_native_source_links.py` to create the POSIX
    `DriverJournal` parent folder with mode `0o700` for `KernelClaim`.
  - Added `runtime_tests/test_communication_http_queries.py` and
    `runtime_tests/test_native_attachment_host_delivery_pg.py` to the
    PostgreSQL CI integration run.

## Compatibility & Upgrade Notes

- Core/Project Schema remains `2` and the MCP tool catalog remains `12`.
- Upgrading from v2.3.1 requires no database migration; existing host/account
  bindings, credentials, Harnesses, and journals are preserved.
