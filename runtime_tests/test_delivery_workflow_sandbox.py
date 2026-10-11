"""Real Temporal sandbox admission of public delivery Workflows."""
import asyncio

from temporalio import workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from runtime.delivery_temporal import CommittedDeliveryWorkflow, OwnerCommittedDeliveryWorkflow


def test_delivery_workflows_prepare_in_default_temporal_sandbox():
    async def prepare():
        runner = SandboxedWorkflowRunner()
        for candidate in (CommittedDeliveryWorkflow, OwnerCommittedDeliveryWorkflow):
            runner.prepare_workflow(workflow._Definition.must_from_class(candidate))
    asyncio.run(prepare())


def test_runtime_public_exports_keep_their_concrete_identity():
    from runtime import DomainAuthority, CommandEnvelope
    from runtime.domain import DomainAuthority as concrete_authority
    from runtime.models import CommandEnvelope as concrete_command
    assert DomainAuthority is concrete_authority
    assert CommandEnvelope is concrete_command
