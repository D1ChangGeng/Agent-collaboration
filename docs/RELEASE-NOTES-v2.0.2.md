# ACS v2.0.2

This patch corrects natural-message input handling. Tool JSON is bounded by its
UTF-8 encoding. Earlier versions counted non-ASCII characters after JSON ASCII
escaping, so a valid Chinese or emoji message could fail before reaching the
declared 32 KiB UTF-8 message limit. The corrected entry accepts and retains
those original messages; oversized content and envelopes still fail.

Authorized callers receive a field and corrective guidance for missing
required arguments, wrong JSON types, enum choices and declared size/range
bounds. Message-content failures identify `content`. Unknown fields and raw
submitted values are not echoed. Hidden tools, invalid credentials and private
backend failures retain their authorization/redaction boundaries. The existing
MCP result version and natural-message/reply semantics are unchanged.

The PostgreSQL regressions cover corrected sends, exact Unicode readback,
boundary rejection, no failed-send side effects and guidance visibility. An
opt-in real-model scenario exercises lost Receiver acknowledgements and
continuation from a replacement sender context. Its actual result and support
scope are recorded in the accompanying verification evidence; defining a test
does not qualify that capability.

Use the verified release Bootstrap to update an existing v2 installation.
No database migration is required from v2.0.1. Preserve the existing owner,
Node/Runtime/Slot identities, credentials and Journals. A separately provisioned
receiving node uses its normal signed deployment update and service readback.
The previously agreed physical-host reboot exclusion remains in effect.
