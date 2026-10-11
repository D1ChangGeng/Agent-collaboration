"""Runtime public API; load concrete services when their exported names are used."""
from importlib import import_module

_EXPORTS = {'DomainAuthority': 'domain', 'HumanBridgeManualInbox': 'human_bridge_dispatch', 'HumanBridgeProviderDispatcher': 'human_bridge_dispatch', 'provision_local_provider': 'human_bridge_dispatch', 'AuthenticatedContext': 'models', 'CommandEnvelope': 'models', 'CommandResult': 'models', 'ExecutionStatus': 'models', 'WorkItemState': 'models', 'NodeResponseOutbox': 'recovery', 'PostgresDelayedResponseAuthority': 'recovery', 'RecoveryService': 'recovery_service', 'NativeResponseCollector': 'response_collector', 'SystemdUserSupervisor': 'systemd_supervisor'}
__all__ = sorted(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
