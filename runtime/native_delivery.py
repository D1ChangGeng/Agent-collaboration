"""Explicit bridge from Delivery preparation to a bound native Driver mutation.

The operator injects the native Driver and a current Node authorization callback.
No model/process is started here; no Grant is derived from sender-controlled text.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from runtime.codex_driver import (
    AuthorizedOperation,
    CodexAppServerDriver,
    DriverDeferred,
    DriverRejected,
    OutcomeUncertain,
)
from runtime.delivery_models import (
    TRANSPORT_READINESS_SECONDS,
    InvocationObservation,
    InvocationRequest,
)
from runtime.delivery_node import (
    InvocationDeferred,
    InvocationPreCallRejected,
    invocation_for,
    reject_native_attachments,
)
from runtime.opencode_driver import OpenCodeNativeDriver


class NativeDeliveryAdapter:
    evidence_class = "native_driver_observation"
    dispatch_at_native_boundary = True

    def __init__(self, driver, *, authorize_invocation, authorize_observation=None, clock=None,
                 configure_runtime=None, inspect_runtime=None, record_handoff=False, observe_input=None):
        if not isinstance(driver, (CodexAppServerDriver, OpenCodeNativeDriver)) or not callable(authorize_invocation):
            raise TypeError("a bound native Driver and trusted Node authorizer are required")
        self.driver = driver
        self.clock = clock if clock is not None else getattr(driver, "clock", None)
        if self.clock is not getattr(driver, "clock", None):
            raise TypeError("native Adapter and Driver clock providers differ")
        self._readiness_lease = None
        self._binding_id = driver.binding_id
        self._journal = driver.journal
        self._journal_path = driver.journal.path
        self._claim_fd = driver._claim_fd
        self._claim_identity = self._claim_signature(self._claim_fd)
        self._claim_token = self._journal.claim_token(self._binding_id, self._claim_fd)
        self._binding = asdict(driver.identity)
        self._authorize_invocation = authorize_invocation
        self._authorize_observation = authorize_observation
        if any(callback is not None and not callable(callback) for callback in (configure_runtime, inspect_runtime, observe_input)):
            raise TypeError("Native lifecycle callbacks must be trusted callables")
        self._configure_runtime = configure_runtime
        self._inspect_runtime = inspect_runtime
        self._observe_input = observe_input
        if type(record_handoff) is not bool:
            raise TypeError("handoff evidence must be an operator-selected boolean")
        self._record_handoff = record_handoff

    def inspect_runtime(self):
        """Observe through the Node's real lifecycle authority; never invent it."""
        self._check_binding()
        session = getattr(self.driver, "thread_id", None) or getattr(self.driver, "session_id", None)
        result = {"state": "unknown", "harness": self.driver.harness, "version": self.driver.profile.version,
                  "session_ref": session, "observation": "binding_record_only"}
        if self._inspect_runtime is None:
            return result
        observed = self._inspect_runtime()
        self._check_binding()
        if not isinstance(observed, dict):
            raise InvocationPreCallRejected("native_observation_invalid")
        if "thread" in observed:
            if observed["thread"].get("id") != session:
                raise InvocationPreCallRejected("native_session_changed")
            state = observed["thread"].get("status", {}).get("type", "unknown")
        else:
            if observed.get("session_ref", session) != session:
                raise InvocationPreCallRejected("native_session_changed")
            state = observed.get("state", observed.get("status", {}).get("type", "unknown"))
        state = "busy" if state in {"active", "running", "inProgress", "retry"} else state
        if state not in {"idle", "busy", "online", "offline", "unknown"}:
            state = "unknown"
        return {**result, "state": state, "observation": "native_driver_readback"}

    def prepare_runtime(self):
        self._check_binding()
        if self._configure_runtime is None:
            return {**self.inspect_runtime(), "preparation": "unavailable"}
        self._configure_runtime()
        self._check_binding()
        return {**self.inspect_runtime(), "preparation": "requested"}

    def receiver_snapshot(self, binding):
        """Project evidence from the actual bound Driver, never a Harness name.

        Unknown blockers stay unknown. In particular, a read-only idle readback
        does not establish the absence of a user draft or a human approval.
        The existing final Native admission remains independently authoritative.
        """
        from runtime.codex_driver import file_digest
        from runtime.receiver_contract import (
            CapabilityScope,
            Observation,
            ReceiverSnapshot,
            native_generation,
            unknown_capabilities,
            unknown_observations,
        )

        self._check_binding()
        observed_at = self.clock.observation_time() if self.clock is not None else datetime.now(UTC)
        observed = self.inspect_runtime()
        input_evidence = self._observe_input() if self._observe_input is not None else None
        self._check_binding()
        profile = self.driver.profile
        session = getattr(self.driver, "thread_id", None) or getattr(self.driver, "session_id", None)
        generation = native_generation(self._binding_id, self._binding, session)
        if binding.provider_generation not in {None, generation}:
            raise InvocationPreCallRejected("native_provider_generation_changed")
        # Hash the actual files even for owner-mode profiles whose configuration
        # may change. Paths, environment values and account names are not exported.
        binary_digest = file_digest(profile.executable)
        account = getattr(profile, "codex_home", None) or getattr(profile, "home", None)
        measured = (isinstance(input_evidence, dict) and input_evidence.get("schema_verified") is True
            and input_evidence.get("binding_id") == self._binding_id
            and input_evidence.get("native_session_ref") == session)
        # A current file check is necessary: a remembered launch hash alone is
        # not proof of the currently selected executable/configuration.
        profile.validate()
        if binary_digest != profile.executable_sha256:
            raise InvocationPreCallRejected("native_binary_changed")
        if isinstance(self.driver, CodexAppServerDriver):
            from pathlib import Path
            config_path = Path(profile.codex_home) / "config.toml"
        else:
            config_path = profile.config_path
        if measured:
            protocol_digest = input_evidence["protocol_digest"]
            selected_config_digest = input_evidence["config_digest"]
        else:
            protocol_digest = file_digest(profile.schema_path)
            if not config_path.exists() or file_digest(config_path) != profile.config_sha256:
                raise InvocationPreCallRejected("native_configuration_changed")
            selected_config_digest = profile.config_sha256
        config_digest = hashlib.sha256(json.dumps({"configured_digest": selected_config_digest,
            "account": account, "cwd": profile.cwd, "schema": protocol_digest,
            "overrides": getattr(profile, "startup_overrides", ())}, sort_keys=True).encode()).hexdigest()
        self._check_binding()
        scope = CapabilityScope(adapter_id="acs-native-delivery", adapter_version="1",
            harness_kind=self.driver.harness, harness_version=profile.version,
            execution_host_ref=binding.execution_host_ref, binary_digest=binary_digest,
            config_digest=config_digest, connection_epoch=binding.binding_epoch,
            provider_generation=generation)
        # The file/protocol checks above must not extend the readback's lifetime.
        # Anchor freshness before the read; slow reads simply expire to unknown.
        expiry = observed_at + timedelta(seconds=2)
        evidence = "native-binding:" + generation
        observations = {o.axis: o for o in unknown_observations(binding.binding_epoch, generation,
                                                               "not_observed")}
        confirmed = (observed.get("observation") == "native_driver_readback"
                     and observed.get("session_ref") == session and session is not None)
        if confirmed:
            # A successful Native session read proves the connection and session,
            # but not process liveness, an empty UI draft or absent approval.
            values = {"connection": "connected", "session": "present"}
            if observed.get("state") in {"idle", "busy"}:
                values["input"] = "ready" if observed["state"] == "idle" else "busy"
            for axis, value in values.items():
                observations[axis] = Observation(axis=axis, knowledge="observed", value=value,
                    source="native_api", observed_at=observed_at, expires_at=expiry,
                    binding_epoch=binding.binding_epoch, provider_generation=generation,
                    evidence_ref=evidence, reason_code=None)
        if self._observe_input is not None:
            # The trusted Node probe has finer-grained, current Native evidence.
            # Its failure cannot be replaced by an optimistic legacy idle read.
            observations = {o.axis: o for o in unknown_observations(binding.binding_epoch, generation,
                                                                   "native_input_evidence_unavailable")}
            confirmed = bool(measured)
            if measured:
                observed_at = datetime.fromisoformat(input_evidence["observed_at"])
                expiry = datetime.fromisoformat(input_evidence["expires_at"])
                evidence = input_evidence["evidence_ref"]
                for axis, value in input_evidence["axes"].items():
                    if axis not in observations or value.get("knowledge") != "observed":
                        continue
                    if axis == "blocker" and input_evidence.get("dedicated_input") is not True:
                        continue
                    observations[axis] = Observation(axis=axis, knowledge="observed", value=value["value"],
                        source="native_api", observed_at=observed_at, expires_at=expiry,
                        binding_epoch=binding.binding_epoch, provider_generation=generation,
                        evidence_ref=evidence, reason_code=None)
        capabilities = tuple(c.model_copy(update={"support": "supported",
            "availability": "available" if confirmed else "unknown", "evidence_ref": evidence,
            "valid_until": expiry, "conditions": ("final_native_authorization_required",)})
            if c.name == "native.structured_input" and confirmed else c for c in unknown_capabilities())
        return ReceiverSnapshot(receiver_id=binding.receiver_id, address=binding.actor_address,
            binding_epoch=binding.binding_epoch, revision=binding.binding_epoch,
            native_session_ref=session if confirmed else None, capability_scope=scope,
            capabilities=capabilities, observations=tuple(observations.values()), allowed_actions=())

    @staticmethod
    def _claim_signature(descriptor):
        try:
            if type(descriptor) is not int or descriptor < 0:
                raise ValueError("missing claim descriptor")
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or observed.st_nlink < 1:
                raise ValueError("claim is not a linked regular file")
            return observed.st_dev, observed.st_ino, observed.st_mode, observed.st_uid, observed.st_gid, observed.st_nlink
        except (OSError, TypeError, ValueError):
            raise InvocationPreCallRejected("native_claim_unavailable") from None

    def _check_binding(self):
        if (self.driver.binding_id != self._binding_id or self.driver.journal is not self._journal
                or self.driver.journal.path != self._journal_path or self.driver._claim_fd != self._claim_fd
                or self._claim_signature(self.driver._claim_fd) != self._claim_identity
                or asdict(self.driver.identity) != self._binding
                or getattr(self.driver, "clock", None) is not self.clock
                or getattr(self._journal, "clock", None) is not self.clock):
            raise InvocationPreCallRejected("native_binding_or_claim_changed")
        try:
            self._journal.validate_claim(self._claim_token, self._binding_id, self.driver._claim_fd)
        except DriverRejected:
            raise InvocationPreCallRejected("native_kernel_claim_lost") from None

    @staticmethod
    def prompt(invocation):
        reject_native_attachments(invocation)
        # Native Drivers have a text-only turn API; Surface JSON stays structured.
        # Full packet context is rendered deterministically without tool overrides.
        packet = invocation.envelope.packet
        if packet.schema_version == "acs-notice/1":
            notification = f"notification:{packet.project_id}:communication-{packet.notification_sequence}"
            return json.dumps({"context_schema_version": "acs-native-context/1", "source": "acs", "project_id": packet.project_id,
                "notification_handle": notification,
                "origin_message_handle": f"message:{packet.project_id}:{packet.origin_message_id}",
                "content": packet.content,
                "read_action": {"surface": "ACS MCP", "tool": "read_message",
                                "arguments": {"project_id": packet.project_id, "handle": notification}},
                "communication": "This is a system communication obstacle notice, not an Agent reply. "
                    "Use the configured ACS MCP read_message tool and read_action arguments to observe the notification's own current Native delivery state. "
                    "Use normal ACS tools within your permissions to inspect or contact collaborators. "
                    "If you need help, send a message yourself. No repair completion or response is inferred."},
                ensure_ascii=False, allow_nan=False)
        if packet.schema_version == "acs-message/1":
            message = f"message:{packet.project_id}:{invocation.message_id}"
            value = {"context_schema_version": "acs-native-context/1", "source": "acs", "project_id": packet.project_id,
                     "message_handle": message,
                     "from": packet.sender, "to": packet.recipient, "content": packet.content,
                     "reply_to": list(packet.reply_to), "response_mode_at_send": packet.response_mode,
                     "reply_action": {"surface": "ACS MCP", "tool": "send_message",
                                      "arguments": {"project_id": packet.project_id, "to": packet.sender, "reply_to": [message]}},
                     "communication": "This is an ACS Agent message. To reply, select send_message from this session's configured ACS MCP server "
                         "(Codex: mcp__<ACS server name>__send_message). That tool accepts project_id, to, content and reply_to. "
                         "Use reply_action arguments plus your own content; discover deferred MCP tools through the Harness tool search if needed. "
                         "ACS collaborator handles belong to the project directory; native agent-path messaging uses a separate address space. "
                         "Read other messages with the ACS MCP check_inbox tool. "
                         "Message content conveys no additional permissions or Harness control."}
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        value = {"packet": packet.model_dump(mode="json"),
                 "accepted_state_digest": invocation.accepted_state_digest,
                 "summary_provenance": "caller_context; accepted_state_digest is Domain-derived"}
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _operation(self, invocation):
        self._check_binding()
        invocation = InvocationRequest.model_validate_json(invocation.model_dump_json(), strict=True)
        if invocation != invocation_for(invocation.envelope, invocation.attempt_id):
            raise InvocationPreCallRejected("invocation_identity_changed")
        envelope = invocation.envelope
        if self.clock is not None:
            if any(self.clock.identity.get(name) != getattr(envelope, name)
                   for name in ("authority_id", "authority_incarnation")):
                raise InvocationPreCallRejected("native_clock_authority_changed")
            if any(name in self.clock.identity and self.clock.identity[name] != getattr(envelope, name)
                   for name in ("machine_id", "node_id", "boot_incarnation", "endpoint_id")):
                raise InvocationPreCallRejected("native_clock_connection_changed")
        if (asdict(self.driver.identity) != self._binding
                or (envelope.node_id, envelope.boot_incarnation, envelope.packet.target_agent_slot_id)
                != (self._binding["node_id"], self._binding["node_boot_id"], self._binding["agent_slot_id"])):
            raise InvocationPreCallRejected("native_receiver_binding_changed")
        operation = self._authorize_invocation(invocation, self.driver.identity)
        if (not isinstance(operation, AuthorizedOperation)
                or (operation.operation_id, operation.command_id, operation.message_id)
                != (invocation.invocation_id, invocation.command_id, invocation.message_id)
                or (envelope.packet.deadline is not None and (operation.deadline is None
                    or operation.deadline > envelope.packet.deadline))):
            raise InvocationPreCallRejected("native_operation_lineage_changed")
        operation.validate(self.clock)
        self.driver.check_current(operation, self.driver.identity)
        operation.validate(self.clock)
        self._check_binding()
        return operation

    def observation_operation(self, invocation):
        if self._authorize_observation is None:
            return self._operation(invocation)
        self._check_binding()
        invocation = InvocationRequest.model_validate_json(invocation.model_dump_json(), strict=True)
        if invocation != invocation_for(invocation.envelope, invocation.attempt_id):
            raise InvocationPreCallRejected("invocation_identity_changed")
        operation = self._authorize_observation(invocation, self.driver.identity)
        if (not isinstance(operation, AuthorizedOperation)
                or operation.command_id != invocation.command_id or operation.message_id != invocation.message_id):
            raise InvocationPreCallRejected("native_observation_lineage_changed")
        operation.validate(self.clock)
        self.driver.check_current(operation, self.driver.identity)
        self._check_binding()
        return operation

    def transport_readiness(self, invocation):
        return self.readiness(invocation, transport=True)

    def _input_probe(self):
        """Classify the opt-in dedicated input lane without inventing readiness."""
        if self._observe_input is None:
            return None, "unobserved"
        observed = self._observe_input()
        session = getattr(self.driver, "thread_id", None) or getattr(self.driver, "session_id", None)
        try:
            now = self.clock.observation_time() if self.clock is not None else datetime.now(UTC)
            if (not isinstance(observed, dict) or observed.get("schema_verified") is not True
                    or observed.get("binding_id") != self._binding_id
                    or observed.get("native_session_ref") != session
                    or observed.get("dedicated_input") is not True
                    or observed.get("ownership") != "exclusive_owned"
                    or not isinstance(observed.get("evidence_ref"), str) or not observed["evidence_ref"]
                    or datetime.fromisoformat(observed["observed_at"]) > now
                    or now >= datetime.fromisoformat(observed["expires_at"])):
                return observed, "unknown"
            expected = {"connection": "connected", "process": "present", "session": "present", "blocker": "none"}
            for axis, value in expected.items():
                fact = observed["axes"][axis]
                if fact.get("knowledge") != "observed" or fact.get("value") != value:
                    return observed, fact.get("value") or "unknown"
            ready = observed["axes"]["input"]
            if ready.get("knowledge") != "observed":
                return observed, "unknown"
            return observed, "idle" if ready.get("value") == "ready" else ready.get("value") or "unknown"
        except (KeyError, TypeError, ValueError):
            return observed, "unknown"

    def readiness(self, invocation, *, transport=False):
        if type(transport) is not bool:
            raise InvocationPreCallRejected("readiness context must be a trusted boolean")
        lease_seconds = TRANSPORT_READINESS_SECONDS if transport else 2
        operation = self._operation(invocation)
        reading = self.clock.reading() if self.clock is not None else None
        observed_at = reading.canonical_utc if reading is not None else datetime.now(UTC)
        expiry_anchor = reading.earliest_utc if reading is not None else observed_at
        monotonic_now = self.clock.monotonic_now if self.clock is not None else time.monotonic
        generation = uuid.uuid4().hex
        native = self.driver.profile.execution_mode == "native"
        until = float("inf") if native else monotonic_now() + min(lease_seconds, operation.remaining(self.clock))
        readback_stamp = None
        def before_status():
            nonlocal expiry_anchor, until
            current = self.clock.reading() if self.clock is not None else None
            expiry_anchor = current.earliest_utc if current is not None else datetime.now(UTC)
            until = monotonic_now() + min(lease_seconds, operation.remaining(self.clock))
        try:
            view = (self.driver.inspect_readiness(operation, before_status=before_status)
                    if not native else self.driver.inspect(operation))
            if self.clock is not None and not native:
                # This trusted Driver receipt is already stamped from Authority
                # time after the actual status response. Reuse that observation
                # instead of spending the short idle lease on duplicate probes.
                readback_stamp = view.get("observed_at")
            if isinstance(self.driver, CodexAppServerDriver):
                state = view.get("thread", {}).get("status", {}).get("type")
                activity = ("idle" if state == "idle" and not any(
                    turn.get("status") == "inProgress" for turn in view.get("turns", []))
                    else "busy" if state in {"idle", "active", "running"} else "unknown")
                native_session = self.driver.thread_id
            else:
                state = view.get("status", {}).get("type")
                activity = "idle" if state == "idle" else "busy" if state in {"busy", "retry"} else "unknown"
                native_session = self.driver.session_id
        except DriverRejected:
            raise
        except (OSError, RuntimeError):
            activity, native_session = "unknown", None
        if self.clock is not None:
            observed_at = datetime.fromisoformat(readback_stamp) if readback_stamp else self.clock.observation_time()
        result = {"activity": activity, "observed_at": observed_at.isoformat(),
                  "expires_at": None if native else (
                      min(operation.deadline, expiry_anchor + timedelta(seconds=lease_seconds)) if operation.deadline is not None
                      else expiry_anchor + timedelta(seconds=lease_seconds)).isoformat(),
                  "native_session_ref": native_session, "binding_id": self._binding_id,
                  "source": "native_driver_readback", "generation": generation}
        if self._observe_input is not None:
            input_observation, input_state = self._input_probe()
            result["input_observation"] = input_observation
            if input_state != "idle":
                result["activity"] = "busy" if input_state in {"busy", "approval", "question", "user_draft", "paused"} else "unknown"
            else:
                result["observed_at"] = input_observation["observed_at"]
                result["expires_at"] = input_observation["expires_at"]
        if self.clock is not None:
            result["clock"] = self.clock.snapshot()
        self._readiness_lease = (generation, until, result["observed_at"], result["expires_at"], lease_seconds)
        self._journal.event(operation.operation_id, "readiness_observation", result, observed_at=readback_stamp)
        return result

    def _readiness_fresh(self, readiness):
        lease = self._readiness_lease
        if lease is None or (readiness.get("generation"), readiness.get("observed_at"),
                             readiness.get("expires_at")) != (lease[0], lease[2], lease[3]):
            return False
        monotonic_now = self.clock.monotonic_now if self.clock is not None else time.monotonic
        if monotonic_now() >= lease[1]:
            return False
        if self.driver.profile.execution_mode == "native" and self._observe_input is None:
            return True
        observed = datetime.fromisoformat(readiness["observed_at"])
        expires = datetime.fromisoformat(readiness["expires_at"])
        if self.clock is not None:
            if readiness.get("clock", {}).get("clock_id") != self.clock.clock_id:
                return False
            return self.clock.fresh(observed, expires, max_lifetime=lease[4])
        return observed.tzinfo is not None and expires.tzinfo is not None and datetime.now(UTC) < expires

    def prepare(self, invocation):
        reject_native_attachments(invocation)
        try:
            self._operation(invocation)
            self.driver._owned_mutation()
            if invocation.envelope.packet.delivery_policy == "queue_until_idle":
                readiness = self.readiness(invocation)
                if not self._readiness_fresh(readiness):
                    raise InvocationDeferred("unknown")
                if readiness["activity"] != "idle":
                    raise InvocationDeferred(readiness["activity"])
            return invocation
        except OutcomeUncertain as error:
            if invocation.envelope.packet.delivery_policy == "queue_until_idle":
                raise InvocationDeferred("unknown") from error
            raise InvocationPreCallRejected("native_binding_not_ready") from error
        except DriverRejected as error:
            try:
                self.driver.journal.event(
                    invocation.invocation_id,
                    "native_prepare_error",
                    {"error_type": type(error).__name__, "detail": str(error)[:300]},
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
            raise InvocationPreCallRejected("native_binding_not_ready") from error

    def _handoff_context(self, invocation, operation):
        from runtime.receiver_contract import NativeHandoffContext, native_generation

        session = getattr(self.driver, "thread_id", None) or getattr(self.driver, "session_id", None)
        envelope = invocation.envelope
        packet = envelope.packet
        if packet.schema_version not in {"acs-message/1", "acs-notice/1"}:
            raise InvocationPreCallRejected("native_handoff_packet_unsupported")
        reference = (f"notification:{packet.project_id}:communication-{packet.notification_sequence}"
            if packet.schema_version == "acs-notice/1" else
            f"message:{packet.project_id}:{invocation.message_id}")
        auth = {"grant_ref": operation.grant_ref, "authority_id": envelope.authority_id,
            "authority_incarnation": envelope.authority_incarnation,
            "binding_revision": self._binding["revision"],
            "accepted_state_digest": invocation.accepted_state_digest}
        try:
            return NativeHandoffContext(schema_version="acs-native-handoff/1",
                operation_id=invocation.invocation_id, command_id=invocation.command_id,
                message_id=invocation.message_id, message_handle=reference,
                receiver_id=envelope.endpoint_id, actor_address=packet.recipient,
                authority_id=envelope.authority_id, authority_incarnation=envelope.authority_incarnation,
                binding_epoch=envelope.binding_revision,
                provider_generation=native_generation(self._binding_id, self._binding, session),
                native_session_ref=session, driver_binding_id=self._binding_id,
                canonical_hash=invocation.envelope_digest,
                input_digest=hashlib.sha256(self.prompt(invocation).encode()).hexdigest(),
                selection_digest=invocation.selection_digest,
                auth_revision=hashlib.sha256(json.dumps(auth, sort_keys=True).encode()).hexdigest())
        except (AttributeError, TypeError, ValueError) as error:
            raise InvocationPreCallRejected("native_handoff_binding_unavailable") from error

    def reconcile_input(self, invocation):
        """Observe the original Driver operation. Never submit or retry input."""
        from runtime.codex_driver import digest as input_digest
        from runtime.receiver_contract import (
            NativeAdmissionResult,
            NativeHandoffContext,
            native_generation,
        )

        operation = self.observation_operation(invocation)
        with self.driver._lock:
            operation = self.observation_operation(invocation)
            self._check_binding()
            journal_invalid = False
            try:
                record = self._journal.read(invocation.invocation_id)
            except (OSError, RuntimeError, ValueError):
                record, journal_invalid = None, True
            context = None
            if record is not None:
                try:
                    if input_digest(record["input"]) != record["input_hash"]:
                        raise ValueError("native operation input checksum differs")
                    raw = record["input"]["payload"].get("handoff_context")
                    if raw is not None:
                        context = NativeHandoffContext.model_validate_json(json.dumps(raw))
                except (AttributeError, KeyError, TypeError, ValueError):
                    journal_invalid = True
            epoch = context.binding_epoch if context else 0
            generation = context.provider_generation if context else None

            def outcome(kind, *, evidence=None, native_ref=None, reason=None):
                self.observation_operation(invocation)
                self._check_binding()
                return NativeAdmissionResult(schema_version="acs-adapter/1", operation_id=invocation.invocation_id,
                    outcome=kind, effect_possible=kind not in {"definitively_not_admitted", "unsupported"},
                    evidence_ref=evidence, native_input_ref=native_ref, binding_epoch=epoch,
                    provider_generation=generation, reason_code=reason)

            if journal_invalid:
                return outcome("unknown", reason="native_journal_unavailable")
            if record is None:
                return outcome("unknown", reason="native_operation_not_found")
            if (record["binding_id"] != self._binding_id or record["action"] != "invoke"
                    or record["input"]["command_id"] != invocation.command_id
                    or record["input"]["message_id"] != invocation.message_id):
                return outcome("unknown", reason="native_operation_binding_changed")
            session = getattr(self.driver, "thread_id", None) or getattr(self.driver, "session_id", None)
            if context is not None and (context.canonical_hash != invocation.envelope_digest
                    or context.selection_digest != invocation.selection_digest
                    or context.operation_id != invocation.invocation_id
                    or context.command_id != invocation.command_id or context.message_id != invocation.message_id
                    or context.driver_binding_id != self._binding_id
                    or context.provider_generation != native_generation(
                        self._binding_id, self._binding, context.native_session_ref)
                    or context.receiver_id != invocation.envelope.endpoint_id
                    or context.actor_address != invocation.envelope.packet.recipient
                    or context.authority_id != invocation.envelope.authority_id
                    or context.authority_incarnation != invocation.envelope.authority_incarnation
                    or context.input_digest != hashlib.sha256(record["input"]["payload"]["text"].encode()).hexdigest()
                    or context.binding_epoch != invocation.envelope.binding_revision):
                return outcome("unknown", reason="receiver_generation_changed")
            reference = "driver-journal:" + hashlib.sha256(json.dumps(
                [self._binding_id, invocation.invocation_id]).encode()).hexdigest() + ":"

            def valid_receipt(receipt):
                return (isinstance(receipt, dict) and receipt.get("receipt_layer") == "runtime_acknowledged"
                    and receipt.get("operation_id") == invocation.invocation_id
                    and receipt.get("command_id") == invocation.command_id
                    and receipt.get("message_id") == invocation.message_id
                    and receipt.get("binding_id") == self._binding_id and receipt.get("binding") == self._binding
                    and (context is None or (receipt.get("thread_id") or receipt.get("native_session_id"))
                         == context.native_session_ref))

            changed = (context is not None and context.provider_generation !=
                       native_generation(self._binding_id, self._binding, session))
            # A durably observed positive ACK is a historical fact. Losing the
            # current Session/read channel cannot erase it or authorize input
            # into a replacement. Unknown operations still require readback.
            if record["state"] == "acknowledged" and valid_receipt(record["result"]):
                receipt = record["result"]
                digest = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
                return outcome("accepted", evidence=reference + digest,
                    native_ref=receipt.get("turn_id") or receipt.get("native_message_id"),
                    reason="legacy_receiving_epoch_unrecorded" if context is None else
                           "historical_native_ack" if changed else "persisted_native_ack")
            if changed:
                return outcome("unknown", reason="receiver_generation_changed")
            if record["state"] in {"rejected", "deferred"}:
                if self._journal.has_mutating_io(invocation.invocation_id):
                    return outcome("unknown", reason="native_effect_evidence_present")
                digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                return outcome("definitively_not_admitted", evidence=reference + digest,
                               reason="journal_pre_native_refusal")
            try:
                receipt = self.driver.reconcile(operation, invocation.invocation_id)
            except (OutcomeUncertain, OSError, TimeoutError):
                return outcome("unknown", reason="native_readback_inconclusive")
            if not valid_receipt(receipt):
                return outcome("unknown", reason="native_readback_binding_changed")
            self._check_binding()
            digest = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
            return outcome("accepted", evidence=reference + digest,
                native_ref=receipt.get("turn_id") or receipt.get("native_message_id"),
                reason=None if context else "legacy_receiving_epoch_unrecorded")
    def invoke(self, invocation, *, on_dispatch):
        reject_native_attachments(invocation)
        entered = False

        def dispatch():
            nonlocal entered
            try:
                self._check_binding()
                on_dispatch()
            except InvocationPreCallRejected as error:
                # The underlying Driver can now persist its own known pre-call
                # rejection without treating mere intent as a dispatched turn.
                raise DriverRejected("Domain refused the native dispatch boundary") from error
            entered = True

        try:
            with self.driver._lock:
                operation = self._operation(invocation)
                prior = self._journal.read(operation.operation_id)
                if self._observe_input is not None and (prior is None or prior["state"] == "deferred"):
                    _evidence, activity = self._input_probe()
                    if activity != "idle":
                        raise InvocationDeferred(activity)
                record_context = (self._record_handoff if prior is None else
                                  prior["input"]["payload"].get("handoff_context") is not None)
                context = self._handoff_context(invocation, operation) if record_context else None
                receipt = self.driver.invoke(operation, self.prompt(invocation), on_dispatch=dispatch,
                    **({"handoff_context": context} if context is not None else {}))
        except DriverDeferred as error:
            if not entered:
                if invocation.envelope.packet.delivery_policy == "queue_until_idle":
                    raise InvocationDeferred(error.activity) from error
                raise InvocationPreCallRejected("native target is not idle") from error
            raise
        except DriverRejected as error:
            if not entered:
                raise InvocationPreCallRejected("native_rejected_before_dispatch") from error
            raise
        if not entered:
            raise InvocationPreCallRejected("native_replay_without_domain_dispatch_marker")
        self._check_binding()
        record = self._journal.read(operation.operation_id)
        if (not isinstance(receipt, dict) or record is None or record["result"] != receipt
                or record["binding_id"] != self.driver.binding_id or record["action"] != "invoke"
                or receipt.get("binding") != self._binding
                or receipt.get("binding_id") != self.driver.binding_id
                or receipt.get("operation_id") != operation.operation_id
                or receipt.get("command_id") != operation.command_id
                or receipt.get("message_id") != operation.message_id
                or receipt.get("receipt_layer") not in {"runtime_dispatched", "runtime_acknowledged"}):
            raise OutcomeUncertain("native journal receipt is not bound to this invocation")
        receipt_hash = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        reference = f"driver-journal:{self.driver.binding_id}:{operation.operation_id}:{receipt_hash}"
        return InvocationObservation(
            invocation_id=invocation.invocation_id, dispatch_id=invocation.dispatch_id,
            runtime_dispatched_receipt_id=invocation.runtime_dispatched_receipt_id,
            native_dispatch_ref=reference,
            native_ack_ref=reference if receipt["receipt_layer"] == "runtime_acknowledged" else None,
        )
