# ACS v2.0.3

Long-lived sender entries now refresh receiving settings from their original
trusted configuration file. Previously an entry could load a new Endpoint
registration while retaining an older receiver generation in memory. The
receiver correctly rejected that mixed configuration before Native invocation,
but an old maintenance process could still claim a new queued message.

`ConfiguredRemoteEndpoint` now invalidates its cached adapter when its trusted
receiving settings change. The loader accepts only the same configured subject,
access mode, DSN and credential reference; changed identity/storage or a removed
endpoint requires reconnection. Querying status still cannot prepare a service
or invoke a model. Receiver signature/generation checks remain unchanged.

Use the verified Release Bootstrap for the existing owner installation and the
normal signed deployment update for a separate receiver. No database migration
is required from v2.0.2. Preserve existing keys, credentials and Journals.
During this first upgrade from older code, reconnect older ACS maintenance
entries after activation; processes already executing the old implementation
cannot gain the new refresh behavior. Source checkouts and non-ACS processes
remain independently managed. The physical-host reboot exclusion is retained.

Component tests cover cache invalidation, private-file reload, identity/DSN/
credential/removal refusal and side-effect-free status reads. Actual warm-client
communication and deployment observations are recorded separately in the
verification evidence, with untested scopes left explicit.
