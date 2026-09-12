# Codex turn readback fallback review

Decision: PASS for the bounded Codex 0.153.2 App Server readback correction
committed at `9e619584e2c6632a47f837c96552ad5d18f2527f`.

The frozen archive SHA-256 is
`44abd2f9202bfb0347837a97b06509c924682fc71f942007857f1f3a9fcb3582`,
manifest SHA-256 is
`ba2b9fdb7da30e95b21282f1101a4caa39d1a71dfa8f1607b2d41ce3a7abbcca`,
and patch SHA-256 is
`6507bf89d4313baaa160d76484fb58f41ffdc351f88d1722a0c0c34ab7ab6cbe`.
Both committed LF blobs match the frozen hashes at exact base
`6b6927d77d0306286fe2011f17c776f3a356b5fa`.

Actual Codex 0.153.2 returned `-32601 / list_turns is not supported yet` from
`thread/turns/list` while the original turn could be read through
`thread/read(includeTurns=true)`. The Driver now uses that read-only fallback
only after an acknowledged turn on the same bound thread/session and only for
that exact code/message. It requires the official response's exact top-level
`{"thread"}` shape, a complete nonpaginated bounded turn/item history, and a
unique original user `clientId` and text match. Any extra top-level field,
pagination, changed thread/session/turn/content or ambiguous history remains
uncertain or rejected. Early exact `-32600` materialization remains pending;
unknown RPC errors propagate. No fallback path invokes or resumes a model turn.

Independent review first found that a top-level history cursor could otherwise
be ignored; that candidate was rejected. The corrected archive passes the
saved cursor counterexample and five extra-field cases without promoting a
terminal response. It passed Linux **101**, Windows **100 with one platform
skip**, Ruff on both systems, and an actual no-model Systemd launch/inspect/
termination with `turn/start=0` and an empty cgroup. The Reviewer also checked
the generated Codex 0.153.2 `ThreadReadResponse` schema and found its top level
contains only `thread`.

A separate, earlier private Zeo API probe made one actual Codex model turn,
received a completed turn and the exact `ACS_P1_CODEX_API_OK` assistant text,
and verified Systemd cleanup. Its evidence SHA-256 is
`931e1f36f891213531963994aee73c4d28587ba45770e80143afa6efb7bbb507`.
The current correction was tested with no model request; that historical probe
does not itself pass the integrated Codex or P1 Gate.
